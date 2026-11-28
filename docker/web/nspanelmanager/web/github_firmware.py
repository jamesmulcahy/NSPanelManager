"""
Fetching panel firmware from a GitHub release, and staging it as the firmware the manager serves.

The release layout is the one the firmware repo's build workflow publishes (FIRMWARE_GITHUB_PLAN.md, C1): a
tag per build, with the app images firmware-original_sonoff.bin and firmware-custom_pcb.bin (the Waveshare ESP32-P4 board) and a build.json
that records each image's size, md5 and sha256.

This decides what gets flashed onto panels, so nothing is staged until both boards' images have been
downloaded and have passed every check in verify_image(). Nothing here uses a token: only anonymous
requests to GitHub, over HTTPS, and a redirect is followed only to a known GitHub host.
"""

import fcntl
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from django.core.files.storage import FileSystemStorage
from django.db import transaction

from . import board_models
from .apps import send_mqttmanager_reload_command
from .models import FirmwareUpload

logger = logging.getLogger(__name__)

# firmware_espidf/partitions.csv in the firmware repo: the ota_0/ota_1 app slots and the
# spiffs partition that holds LittleFS.
APP_SLOT_BYTES = 0x1B0000
LITTLEFS_PARTITION_BYTES = 0x8F000

# The models, the chip each one's image is for (esp_image_header_t.chip_id) and each one's board in the release:
# board_models.py.
ESP_IMAGE_MAGIC = board_models.ESP_IMAGE_MAGIC
CHIP_IDS = board_models.CHIP_IDS
BOARDS = board_models.BOARDS

API_HOST = "api.github.com"
# Where a download may redirect to: release assets are served from GitHub's own domains.
DOWNLOAD_HOSTS = frozenset({"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"})

API_CACHE_SECONDS = 300
# uwsgi kills a request after 20 s (--harakiri in run_uwsgi.sh), and a kill skips every cleanup below. So a
# whole request, API calls and both downloads, shares one deadline well inside that. Harakiri stays the final
# backstop: a blocked syscall cannot be interrupted by the deadline checks between chunks.
OVERALL_DEADLINE_SECONDS = 15
REQUEST_TIMEOUT = (10, 15)  # Connect, read: each is further limited to the time left on the deadline.
CHUNK_BYTES = 8192
MAX_REDIRECTS = 5
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_BUILD_JSON_BYTES = 64 * 1024
RELEASE_LIST_SIZE = 20
USER_AGENT = "nspanel-manager"

_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_BUILD_TAG = re.compile(r"build-([0-9a-f]{8})")

LOCK_NAME = ".stage.lock"
LOCK_POLL_SECONDS = 0.1
STALE_PATTERN = ".firmware-*"

_cache = {}
_cache_lock = threading.Lock()


class FirmwareError(Exception):
    """A failure with the code the REST API reports (rest_v2/firmware.py maps codes to HTTP statuses)."""

    def __init__(self, code, message, board=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.board = board


@dataclass
class ImageInfo:
    model: str
    asset_name: str
    url: str
    size: int
    md5: str
    sha256: str
    digest_sha256: str | None  # GitHub's digest of the asset, when it gives one


@dataclass
class ResolvedRelease:
    repo: str
    tag: str
    commit: str
    built_at: str
    run_url: str
    html_url: str
    images: dict  # model -> ImageInfo


# ------------------------------------------------------------------ HTTP


def _session():
    """A session that ignores the environment: no .netrc credentials and no HTTP(S)_PROXY."""
    session = requests.Session()
    session.trust_env = False
    return session


def _check_url(url, allowed_hosts):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "https" or host not in allowed_hosts or port not in (None, 443) or parts.username or parts.password:
        raise ValueError(f"Refusing to fetch {parts.scheme}://{host}: only HTTPS to {', '.join(sorted(allowed_hosts))} is allowed")


def _rate_limited(response):
    if response.status_code not in (403, 429):
        return False
    headers = response.headers
    return headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers or response.status_code == 429


def _open(url, allowed_hosts, failure_code, accept, deadline):
    """GET url with a streamed body, following redirects by hand so that every hop's host is checked.

    The returned response is open: the caller reads it and closes it. Raises FirmwareError otherwise.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    session = _session()
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            _check_url(url, allowed_hosts)
        except ValueError as error:
            raise FirmwareError(failure_code, str(error)) from None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FirmwareError(failure_code, "Timed out")
        timeout = (min(REQUEST_TIMEOUT[0], remaining), min(REQUEST_TIMEOUT[1], remaining))
        try:
            response = session.get(url, headers=headers, stream=True, allow_redirects=False, timeout=timeout)
        except requests.RequestException as error:
            raise FirmwareError(failure_code, f"Could not reach GitHub: {type(error).__name__}") from None

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            response.close()
            if not location:
                raise FirmwareError(failure_code, "GitHub sent a redirect without a location")
            url = requests.compat.urljoin(url, location)
            continue
        if response.status_code == 200:
            return response
        status = response.status_code
        limited = _rate_limited(response)
        response.close()
        if limited:
            raise FirmwareError("rate_limited", "GitHub's rate limit has been reached. Try again later.")
        if status == 404:
            raise FirmwareError("not_found", "GitHub has no such release or file.")
        raise FirmwareError(failure_code, f"GitHub answered HTTP {status}")
    raise FirmwareError(failure_code, "Too many redirects")


def _read_limited(response, limit, too_big_code, transport_code, deadline):
    """The whole body, which must not exceed limit bytes. A body that is too big is too_big_code; a transport
    error or running out of time is transport_code."""
    chunks, total = [], 0
    try:
        for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
            total += len(chunk)
            if total > limit:
                raise FirmwareError(too_big_code, "The response from GitHub is larger than expected")
            if time.monotonic() > deadline:
                raise FirmwareError(transport_code, "Timed out")
            chunks.append(chunk)
    except requests.RequestException as error:
        raise FirmwareError(transport_code, f"Could not read from GitHub: {type(error).__name__}") from None
    finally:
        response.close()
    return b"".join(chunks)


def _cached(key, fetch, fresh):
    now = time.monotonic()
    if not fresh:
        with _cache_lock:
            hit = _cache.get(key)
            if hit and now - hit[0] < API_CACHE_SECONDS:
                return hit[1]
    value = fetch()
    with _cache_lock:
        _cache[key] = (time.monotonic(), value)
        for stale in [k for k, (at, _) in _cache.items() if time.monotonic() - at >= API_CACHE_SECONDS]:
            del _cache[stale]
    return value


def clear_cache():
    with _cache_lock:
        _cache.clear()


def _api_json(path, deadline):
    response = _open(f"https://{API_HOST}{path}", {API_HOST}, "unreachable", "application/vnd.github+json", deadline)
    body = _read_limited(response, MAX_JSON_BYTES, "bad_release", "unreachable", deadline)
    try:
        return json.loads(body)
    except ValueError:
        raise FirmwareError("bad_release", "GitHub's answer was not valid JSON") from None


def _download_small(url, deadline):
    response = _open(url, DOWNLOAD_HOSTS, "unreachable", "application/octet-stream", deadline)
    return _read_limited(response, MAX_BUILD_JSON_BYTES, "bad_release", "unreachable", deadline)


def new_deadline():
    return time.monotonic() + OVERALL_DEADLINE_SECONDS


# ------------------------------------------------------------------ Releases


def _release_path(repo, release):
    if release == "latest":
        return f"/repos/{repo}/releases/latest"
    return f"/repos/{repo}/releases/tags/{release}"


def resolve_release(repo, release, fresh=False, deadline=None):
    """The release (a tag, or "latest") with its build.json read and checked. Cached for 5 minutes unless fresh."""
    return _cached(("release", repo, release), lambda: _resolve_release(repo, release, deadline or new_deadline()), fresh)


def _resolve_release(repo, release, deadline):
    data = _api_json(_release_path(repo, release), deadline)
    if not isinstance(data, dict) or not isinstance(data.get("tag_name"), str) or data.get("draft"):
        raise FirmwareError("bad_release", "GitHub's release record is not usable")
    if data.get("prerelease"):
        # The firmware CI's test builds (test-<sha>) are prereleases and must never be staged for the fleet.
        raise FirmwareError("not_found", f"{data['tag_name']} is a prerelease")
    assets = {}
    for asset in data.get("assets") or []:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str) and isinstance(asset.get("browser_download_url"), str):
            assets[asset["name"]] = asset

    build_asset = assets.get("build.json")
    if build_asset is None:
        raise FirmwareError("not_found", "The release has no build.json")
    try:
        build = json.loads(_download_small(build_asset["browser_download_url"], deadline))
    except ValueError:
        raise FirmwareError("bad_release", "build.json is not valid JSON") from None
    return _parse_build(repo, data, build, assets)


def _parse_build(repo, release_data, build, assets):
    def bad(message):
        return FirmwareError("bad_release", f"build.json: {message}")

    if not isinstance(build, dict) or build.get("schema") != 1:
        raise bad("unsupported schema")
    commit = build.get("commit")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise bad("commit is not a 40-character sha")
    images_json = build.get("images")
    if not isinstance(images_json, dict):
        raise bad("no images")

    images = {}
    for model, board in BOARDS.items():
        entry = images_json.get(board)
        if not isinstance(entry, dict):
            raise bad(f"no image for {board}")
        expected_asset = f"firmware-{board}.bin"
        size, md5, sha256 = entry.get("size"), entry.get("md5"), entry.get("sha256")
        if entry.get("asset") != expected_asset:
            raise bad(f"{board} should be the asset {expected_asset}")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise bad(f"{board} has no valid size")
        if not isinstance(md5, str) or not _HEX32.fullmatch(md5) or not isinstance(sha256, str) or not _HEX64.fullmatch(sha256):
            raise bad(f"{board} has no valid md5 and sha256 (lower-case hex)")
        asset = assets.get(expected_asset)
        if asset is None:
            raise FirmwareError("not_found", f"The release has no {expected_asset}")
        digest = asset.get("digest")
        digest_sha256 = None
        if isinstance(digest, str) and digest.lower().startswith("sha256:"):
            digest_sha256 = digest[len("sha256:") :].lower()
        images[model] = ImageInfo(model, expected_asset, asset["browser_download_url"], size, md5, sha256, digest_sha256)

    tag = release_data["tag_name"]
    return ResolvedRelease(
        repo=repo,
        tag=tag,
        commit=commit,
        built_at=str(build.get("built_at") or ""),
        run_url=str(build.get("run_url") or ""),
        html_url=str(release_data.get("html_url") or ""),
        images=images,
    )


def list_releases(repo, fresh=False, deadline=None):
    """The newest 20 releases (drafts left out), newest first, as [{"tag", "commit", "built_at"}]."""
    return _cached(("releases", repo), lambda: _list_releases(repo, deadline or new_deadline()), fresh)


def _list_releases(repo, deadline):
    data = _api_json(f"/repos/{repo}/releases?per_page={RELEASE_LIST_SIZE}", deadline)
    if not isinstance(data, list):
        raise FirmwareError("bad_release", "GitHub's release list is not usable")
    releases = []
    for item in data:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease") or not isinstance(item.get("tag_name"), str):
            continue
        # The commit is the release's target when that is a sha, else the sha in a build-<sha> tag's name.
        target = item.get("target_commitish")
        tagged = _BUILD_TAG.fullmatch(item["tag_name"])
        commit = target if isinstance(target, str) and _COMMIT.fullmatch(target) else (tagged.group(1) if tagged else None)
        releases.append({"tag": item["tag_name"], "commit": commit, "built_at": item.get("published_at") or item.get("created_at")})
        if len(releases) == RELEASE_LIST_SIZE:
            break
    return releases


# ------------------------------------------------------------------ Verification


def verify_image(model, path, info):
    """Raises FirmwareError("verification_failed", board=model) unless the file at path is the image build.json
    describes and is an OTA app image for this board. Checks, in order: size, ESP image magic byte, chip id,
    sha256 (build.json and GitHub's digest), md5."""

    def fail(message):
        raise FirmwareError("verification_failed", f"{model}: {message}", board=model)

    size = os.path.getsize(path)
    if size != info.size:
        fail(f"size is {size} bytes, build.json says {info.size}")
    if size > APP_SLOT_BYTES:
        fail(f"{size} bytes does not fit an app slot ({APP_SLOT_BYTES} bytes)")
    with open(path, "rb") as image:
        header = image.read(16)
        if len(header) < 16 or header[0] != ESP_IMAGE_MAGIC:
            fail("not an ESP app image (first byte is not 0xE9)")
        chip_id = int.from_bytes(header[12:14], "little")
        if chip_id != CHIP_IDS[model]:
            fail(f"image is for chip id {chip_id:#06x}, expected {CHIP_IDS[model]:#06x}")
        image.seek(0)
        sha256, md5 = hashlib.sha256(), hashlib.md5()
        while chunk := image.read(65536):
            sha256.update(chunk)
            md5.update(chunk)
    if sha256.hexdigest() != info.sha256:
        fail("sha256 does not match build.json")
    if info.digest_sha256 is not None and sha256.hexdigest() != info.digest_sha256:
        fail("sha256 does not match the digest GitHub reports for the asset")
    if md5.hexdigest() != info.md5:
        fail("md5 does not match build.json")


def _download_image(info, target_dir, deadline):
    """Download an image into a new temp file in target_dir, which is returned. The download is capped at the
    app slot size plus one byte, and at the request's deadline."""
    fd, temp_path = tempfile.mkstemp(dir=target_dir, prefix=".firmware-", suffix=".tmp")
    try:
        response = _open(info.url, DOWNLOAD_HOSTS, "download_failed", "application/octet-stream", deadline)
        with os.fdopen(fd, "wb") as out:
            total = 0
            try:
                for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                    total += len(chunk)
                    if total > APP_SLOT_BYTES + 1:
                        break
                    if time.monotonic() > deadline:
                        raise FirmwareError("download_failed", f"{info.model}: download timed out")
                    out.write(chunk)
            except requests.RequestException as error:
                raise FirmwareError("download_failed", f"{info.model}: download failed ({type(error).__name__})") from None
            finally:
                response.close()
        if total > APP_SLOT_BYTES:
            raise FirmwareError("verification_failed", f"{info.model}: the image is larger than an app slot ({APP_SLOT_BYTES} bytes)", board=info.model)
        os.chmod(temp_path, 0o644)
        return temp_path
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass  # Already closed by the with block
        _remove(temp_path)
        raise


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Could not remove %s", path)


# ------------------------------------------------------------------ Staging


def firmware_path(model):
    """Where the manager serves model's firmware from (the same place the manual upload writes)."""
    return FileSystemStorage().path(f"firmware/{model}/firmware.bin")


def file_md5(path):
    try:
        with open(path, "rb") as image:
            digest = hashlib.md5()
            while chunk := image.read(65536):
                digest.update(chunk)
            return digest.hexdigest()
    except FileNotFoundError:
        return None


def _sweep_stale(directory):
    """Delete temp and backup files an earlier stage left behind (it was killed before it could clean up)."""
    for path in glob.glob(os.path.join(glob.escape(directory), STALE_PATTERN)):
        _remove(path)


class StageLock:
    """An exclusive lock across every worker process, on firmware/.stage.lock. The kernel drops it if the holder
    dies, so a killed request cannot leave it held. Waiting for it is bounded by deadline (a monotonic time):
    a request that waits must not outlive uwsgi's harakiri, so it gives up and touches nothing."""

    def __init__(self, deadline):
        self.deadline = deadline

    def __enter__(self):
        path = FileSystemStorage().path(f"firmware/{LOCK_NAME}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            while True:
                try:
                    fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except BlockingIOError:
                    if time.monotonic() >= self.deadline:
                        raise FirmwareError("unreachable", "Another firmware stage is in progress; try again") from None
                    time.sleep(LOCK_POLL_SECONDS)
        except BaseException:
            os.close(self._fd)
            raise

    def __exit__(self, *exc):
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)


def stage_release(repo, release):
    """Resolve release (fresh, never from the cache) and stage both of its boards, all or nothing.

    Both images are downloaded and verified before the staged files are touched. Then every changed file is
    replaced (put back if anything fails, including the database write), and only after that is MQTTManager
    told to reload. One deadline covers the lot. Returns
    {"tag", "commit", "boards": {model: {"before_md5", "after_md5", "changed"}}, "changed": bool}.
    """
    deadline = new_deadline()  # From the start of the request, so waiting for the lock counts
    with StageLock(deadline):
        targets = {model: firmware_path(model) for model in BOARDS}
        for target in targets.values():
            _sweep_stale(os.path.dirname(target))
        release_data = resolve_release(repo, release, fresh=True, deadline=deadline)
        temps, backups = {}, []
        try:
            for model, info in release_data.images.items():
                directory = os.path.dirname(targets[model])
                os.makedirs(directory, exist_ok=True)
                temps[model] = _download_image(info, directory, deadline)
                verify_image(model, temps[model], info)

            before = {model: file_md5(targets[model]) for model in BOARDS}
            changed = [model for model, info in release_data.images.items() if before[model] != info.md5]
            replaced = []
            try:
                with transaction.atomic():
                    for model in changed:
                        backup = None
                        if os.path.exists(targets[model]):
                            backup_fd, backup = tempfile.mkstemp(dir=os.path.dirname(targets[model]), prefix=".firmware-", suffix=".bak")
                            os.close(backup_fd)
                            backups.append(backup)
                            shutil.copy2(targets[model], backup)  # Keeps the mode, for a rollback
                        os.replace(temps[model], targets[model])
                        replaced.append((model, backup))
                    for model in changed:
                        FirmwareUpload.objects.create(
                            md5=release_data.images[model].md5,
                            model=model,
                            source=FirmwareUpload.Source.GITHUB,
                            repo=release_data.repo,
                            tag=release_data.tag,
                            commit=release_data.commit,
                            run_url=release_data.run_url,
                        )
            except BaseException:
                for model, backup in reversed(replaced):
                    try:
                        if backup:
                            os.replace(backup, targets[model])
                        else:
                            os.remove(targets[model])
                    except OSError:
                        logger.exception("Could not put back the previous %s firmware", model)
                raise
        except FirmwareError:
            raise
        except OSError as error:
            raise FirmwareError("download_failed", f"Could not write the firmware files: {error.strerror or type(error).__name__}") from None
        finally:
            for path in [*temps.values(), *backups]:
                _remove(path)

    # The files are staged for good. A reload that fails is logged, not an error: the manager picks the change up
    # on its next reload, and the caller must not think nothing was staged.
    if changed:
        logger.info("Staged firmware %s (%s) for %s", release_data.tag, release_data.commit, ", ".join(changed))
        try:
            send_mqttmanager_reload_command()
        except Exception:
            logger.exception("Staged the firmware, but could not tell MQTTManager to reload")
    return {
        "tag": release_data.tag,
        "commit": release_data.commit,
        "boards": {model: {"before_md5": before[model], "after_md5": release_data.images[model].md5, "changed": model in changed} for model in BOARDS},
        "changed": bool(changed),
    }
