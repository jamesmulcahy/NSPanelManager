"""
Staging firmware from a GitHub release (web/github_firmware.py, /rest/v2/firmware). GitHub is faked at
requests.get; no test touches the network.

What matters is what must never happen: a bad image reaching firmware/<model>/firmware.bin, or only one board
being updated. So most tests check that the staged files are exactly as they were.
"""

import hashlib
import json
import os
import shutil
import tempfile
from unittest import mock

import requests
from django.test import override_settings

from web import github_firmware
from web.github_firmware import APP_SLOT_BYTES, CHIP_IDS
from web.models import FirmwareUpload
from web.rest_v2.global_settings import FIRMWARE_GITHUB_REPO_DEFAULT
from web.settings_helper import set_setting_value

from .harness import NSPMTestCase

REPO = FIRMWARE_GITHUB_REPO_DEFAULT
TAG = "build-545a9e4d"
COMMIT = "545a9e4d" + "0" * 32
BOARDS = {"sonoff": "original_sonoff", "custom": "custom_pcb"}
GET_URL = "/rest/v2/firmware"
STAGE_URL = "/rest/v2/firmware/stage"


def make_image(model, fill, size=4096, chip_id=None):
    header = bytearray(16)
    header[0] = 0xE9
    header[12:14] = (CHIP_IDS[model] if chip_id is None else chip_id).to_bytes(2, "little")
    return bytes(header) + bytes([fill]) * (size - 16)


def md5(data):
    return hashlib.md5(data).hexdigest()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class FakeResponse:
    def __init__(self, status=200, body=b"", headers=None, fail_after=None):
        self.status_code = status
        self.body = body
        self.headers = headers or {}
        self.fail_after = fail_after
        self.closed = False

    def iter_content(self, chunk_size=1):
        step = 1000
        for start in range(0, len(self.body), step):
            if self.fail_after is not None and start >= self.fail_after:
                raise requests.ConnectionError("connection reset")
            yield self.body[start : start + step]
        if self.fail_after is not None and self.fail_after >= len(self.body):
            raise requests.ConnectionError("connection reset")

    def close(self):
        self.closed = True


class FakeGitHub:
    """Routes by exact URL; unknown URLs fail the test."""

    def __init__(self):
        self.routes = {}
        self.requested = []

    def __call__(self, url, **kwargs):
        assert kwargs.get("allow_redirects") is False, "redirects must be followed by hand"
        assert "Authorization" not in kwargs.get("headers", {}), "no token is ever sent"
        self.requested.append(url)
        if url not in self.routes:
            raise AssertionError(f"Unexpected request to {url}")
        route = self.routes[url]
        if isinstance(route, Exception):
            raise route
        return route() if callable(route) else route

    def add_release(self, tag=TAG, images=None, build_overrides=None, digests=None, asset_overrides=None, latest=True, repo=REPO):
        """Serve release `tag`: images is {model: bytes}. Returns the images."""
        images = images or {"sonoff": make_image("sonoff", 1), "custom": make_image("custom", 2)}
        build = {
            "schema": 1,
            "commit": COMMIT,
            "branch": "fork",
            "run_id": 1,
            "run_url": "https://github.com/x/y/actions/runs/1",
            "built_at": "2026-11-19T12:00:00Z",
            "images": {BOARDS[m]: {"asset": f"firmware-{BOARDS[m]}.bin", "size": len(data), "md5": md5(data), "sha256": sha256(data)} for m, data in images.items()},
        }
        build.update(build_overrides or {})
        assets = []
        files = {"build.json": json.dumps(build).encode()}
        for m, data in images.items():
            files[f"firmware-{BOARDS[m]}.bin"] = data
        for name, data in files.items():
            download = f"https://github.com/{repo}/releases/download/{tag}/{name}"
            asset = {"name": name, "browser_download_url": download, "size": len(data), "digest": f"sha256:{sha256(data)}"}
            if digests and name in digests:
                asset["digest"] = digests[name]
            asset.update((asset_overrides or {}).get(name, {}))
            assets.append(asset)
            cdn = f"https://release-assets.githubusercontent.com/{tag}/{name}"
            self.routes[download] = FakeResponse(302, headers={"location": cdn})
            self.routes[cdn] = lambda body=data: FakeResponse(200, body)
        release = {"tag_name": tag, "draft": False, "html_url": f"https://github.com/{repo}/releases/tag/{tag}", "assets": assets}
        self.routes[f"https://api.github.com/repos/{repo}/releases/tags/{tag}"] = FakeResponse(200, json.dumps(release).encode())
        if latest:
            self.routes[f"https://api.github.com/repos/{repo}/releases/latest"] = FakeResponse(200, json.dumps(release).encode())
        return images


class FirmwareGithubTestCase(NSPMTestCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix="nspm-fw-test-")
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        github_firmware.clear_cache()
        self.addCleanup(github_firmware.clear_cache)

        self.github = FakeGitHub()
        self._patch("requests.get", side_effect=self.github)

        self.old = {"sonoff": make_image("sonoff", 0xA1), "custom": make_image("custom", 0xA2)}
        for model, data in self.old.items():
            os.makedirs(os.path.join(self.media, "firmware", model))
            with open(self.path(model), "wb") as f:
                f.write(data)

    def path(self, model):
        return os.path.join(self.media, "firmware", model, "firmware.bin")

    def staged(self, model):
        with open(self.path(model), "rb") as f:
            return f.read()

    def assertUntouched(self):
        for model, data in self.old.items():
            self.assertEqual(self.staged(model), data, f"{model} firmware was modified")
        for model in self.old:
            self.assertEqual(os.listdir(os.path.dirname(self.path(model))), ["firmware.bin"], "temp files left behind")
        self.assertEqual(FirmwareUpload.objects.count(), 0)
        self.assertManagerNotReloaded()

    def stage(self, **body):
        return self.post_json(STAGE_URL, body)

    def error_of(self, response):
        return response.json()["error"]


class StageTests(FirmwareGithubTestCase):
    def test_stages_both_boards(self):
        images = self.github.add_release()
        response = self.stage()
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["tag"], TAG)
        self.assertEqual(body["commit"], COMMIT)
        for model in images:
            self.assertEqual(self.staged(model), images[model])
            self.assertEqual(body["boards"][model], {"before_md5": md5(self.old[model]), "after_md5": md5(images[model]), "changed": True})
            row = FirmwareUpload.objects.get(model=model)
            self.assertEqual((row.md5, row.source, row.repo, row.tag, row.commit), (md5(images[model]), "github", REPO, TAG, COMMIT))
            self.assertEqual(row.run_url, "https://github.com/x/y/actions/runs/1")
        self.assertManagerReloaded(times=1)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path("sonoff")))), ["firmware.bin"])
        self.assertEqual(oct(os.stat(self.path("sonoff")).st_mode & 0o777), "0o644")

    def test_stages_when_nothing_was_staged_before(self):
        for model in self.old:
            os.remove(self.path(model))
        images = self.github.add_release()
        body = self.stage().json()
        self.assertIsNone(body["boards"]["sonoff"]["before_md5"])
        self.assertEqual(self.staged("custom"), images["custom"])

    def test_same_release_again_changes_nothing(self):
        images = self.github.add_release()
        self.assertEqual(self.stage().status_code, 200)
        self.mqttmanager.reset()
        rows = FirmwareUpload.objects.count()
        before = {m: os.stat(self.path(m)).st_mtime_ns for m in images}

        body = self.stage().json()
        for model in images:
            self.assertEqual(body["boards"][model], {"before_md5": md5(images[model]), "after_md5": md5(images[model]), "changed": False})
            self.assertEqual(os.stat(self.path(model)).st_mtime_ns, before[model])
        self.assertEqual(FirmwareUpload.objects.count(), rows)
        self.assertManagerNotReloaded()

    def test_only_the_changed_board_is_replaced(self):
        images = self.github.add_release()
        with open(self.path("custom"), "wb") as f:
            f.write(images["custom"])
        body = self.stage().json()
        self.assertFalse(body["boards"]["custom"]["changed"])
        self.assertTrue(body["boards"]["sonoff"]["changed"])
        self.assertEqual(FirmwareUpload.objects.filter(model="custom").count(), 0)
        self.assertManagerReloaded(times=1)

    def test_explicit_tag(self):
        self.github.add_release(tag="build-11111111", latest=False)
        response = self.stage(release="build-11111111")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tag"], "build-11111111")

    def test_release_setting_is_the_default(self):
        self.github.add_release(tag="build-22222222", latest=False)
        set_setting_value("firmware_github_release", "build-22222222")
        self.assertEqual(self.stage().json()["tag"], "build-22222222")

    def test_stage_never_uses_the_cache(self):
        self.github.add_release()
        self.client.get(GET_URL)
        self.github.requested.clear()
        self.stage()
        self.assertIn(f"https://api.github.com/repos/{REPO}/releases/latest", self.github.requested)


class RejectionTests(FirmwareGithubTestCase):
    def assertRejected422(self, response, board, fragment):
        self.assertEqual(response.status_code, 422, response.content)
        error = self.error_of(response)
        self.assertEqual((error["code"], error["board"]), ("verification_failed", board))
        self.assertIn(fragment, error["message"])
        self.assertUntouched()

    def test_wrong_chip_id_for_a_board(self):
        # The custom board's image is fine; the Sonoff one is an ESP32-S3 image. Neither may be staged.
        self.github.add_release(images={"sonoff": make_image("sonoff", 1, chip_id=0x0009), "custom": make_image("custom", 2)})
        self.assertRejected422(self.stage(), "sonoff", "chip id")

    def test_wrong_chip_id_on_the_second_board_leaves_the_first_untouched(self):
        self.github.add_release(images={"sonoff": make_image("sonoff", 1), "custom": make_image("custom", 2, chip_id=0x0000)})
        self.assertRejected422(self.stage(), "custom", "chip id")

    def test_not_an_esp_image(self):
        bad = bytearray(make_image("sonoff", 1))
        bad[0] = 0x7F
        self.github.add_release(images={"sonoff": bytes(bad), "custom": make_image("custom", 2)})
        self.assertRejected422(self.stage(), "sonoff", "0xE9")

    def test_oversized_image(self):
        big = make_image("sonoff", 1, size=APP_SLOT_BYTES + 1)
        self.github.add_release(images={"sonoff": big, "custom": make_image("custom", 2)})
        self.assertRejected422(self.stage(), "sonoff", "app slot")

    def test_oversized_image_is_not_read_beyond_the_cap(self):
        # build.json claims a plausible size but the server keeps sending: the download stops at the slot size + 1.
        images = self.github.add_release()
        url = f"https://release-assets.githubusercontent.com/{TAG}/firmware-original_sonoff.bin"
        sent = []

        class Endless(FakeResponse):
            def iter_content(self, chunk_size=1):
                for _ in range(10_000):
                    sent.append(1)
                    yield b"\xe9" * 65536

        self.github.routes[url] = lambda: Endless(200)
        response = self.stage()
        self.assertEqual(response.status_code, 422)
        self.assertLess(len(sent), 100)
        self.assertUntouched()
        del images

    def test_size_mismatch(self):
        images = self.github.add_release()
        self.github.add_release(images={"sonoff": images["sonoff"] + b"\x00", "custom": images["custom"]}, build_overrides=None)
        # build.json now describes the longer image; serve the original (shorter) one instead.
        cdn = f"https://release-assets.githubusercontent.com/{TAG}/firmware-original_sonoff.bin"
        self.github.routes[cdn] = lambda: FakeResponse(200, images["sonoff"])
        self.assertRejected422(self.stage(), "sonoff", "size")

    def test_sha256_mismatch_with_build_json(self):
        images = self.github.add_release()
        tampered = bytearray(images["sonoff"])
        tampered[100] ^= 0xFF
        cdn = f"https://release-assets.githubusercontent.com/{TAG}/firmware-original_sonoff.bin"
        self.github.routes[cdn] = lambda: FakeResponse(200, bytes(tampered))
        self.assertRejected422(self.stage(), "sonoff", "sha256")

    def test_sha256_mismatch_with_github_digest(self):
        self.github.add_release(digests={"firmware-custom_pcb.bin": "sha256:" + "0" * 64})
        self.assertRejected422(self.stage(), "custom", "digest")

    def test_missing_digest_is_fine(self):
        self.github.add_release(digests={"firmware-custom_pcb.bin": None})
        # A digest of None is skipped, as for a release GitHub gave no digest for.
        self.assertEqual(self.stage().status_code, 200)

    def test_md5_mismatch(self):
        images = {"sonoff": make_image("sonoff", 1), "custom": make_image("custom", 2)}
        entry = {"asset": "firmware-custom_pcb.bin", "size": len(images["custom"]), "md5": "0" * 32, "sha256": sha256(images["custom"])}
        sonoff = {"asset": "firmware-original_sonoff.bin", "size": len(images["sonoff"]), "md5": md5(images["sonoff"]), "sha256": sha256(images["sonoff"])}
        self.github.add_release(images=images, build_overrides={"images": {"original_sonoff": sonoff, "custom_pcb": entry}})
        self.assertRejected422(self.stage(), "custom", "md5")


class ReleaseErrorTests(FirmwareGithubTestCase):
    def test_invalid_tag(self):
        for tag in ("../etc", "a b", "x" * 101, "", "a/b"):
            with self.subTest(tag=tag):
                response = self.stage(release=tag)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.error_of(response)["code"], "bad_release")
        self.assertEqual(self.stage(release=5).status_code, 400)
        self.assertEqual(self.client.get(GET_URL, {"release": "a/b"}).status_code, 400)
        self.assertEqual(self.github.requested, [])
        self.assertUntouched()

    def test_nonexistent_tag(self):
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases/tags/nope"] = FakeResponse(404, b"{}")
        response = self.stage(release="nope")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.error_of(response)["code"], "not_found")
        self.assertUntouched()

    def test_rate_limited_on_post(self):
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"] = FakeResponse(403, b"{}", {"x-ratelimit-remaining": "0"})
        response = self.stage()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(self.error_of(response)["code"], "rate_limited")
        self.assertUntouched()

    def test_rate_limited_on_get_is_200_with_error(self):
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"] = FakeResponse(429, b"{}", {"retry-after": "60"})
        response = self.client.get(GET_URL)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["error"]["code"], "rate_limited")
        self.assertIsNone(body["resolved"])
        self.assertIsNone(body["up_to_date"])
        self.assertEqual(body["staged"]["sonoff"]["md5"], md5(self.old["sonoff"]))

    def test_unreachable(self):
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"] = requests.ConnectTimeout("slow")
        response = self.stage()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.error_of(response)["code"], "unreachable")
        body = self.client.get(GET_URL).json()
        self.assertEqual(body["error"]["code"], "unreachable")
        self.assertUntouched()

    def test_malformed_build_json(self):
        self.github.add_release()
        self.github.routes[f"https://release-assets.githubusercontent.com/{TAG}/build.json"] = lambda: FakeResponse(200, b"{not json")
        response = self.stage()
        self.assertEqual((response.status_code, self.error_of(response)["code"]), (400, "bad_release"))
        self.assertUntouched()

    def test_build_json_missing_a_board(self):
        self.github.add_release(images={"sonoff": make_image("sonoff", 1)})
        response = self.stage()
        self.assertEqual(self.error_of(response)["code"], "bad_release")
        self.assertUntouched()

    def test_release_missing_an_asset(self):
        self.github.add_release()
        route = self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"]
        release = json.loads(route.body)
        release["assets"] = [a for a in release["assets"] if a["name"] != "firmware-custom_pcb.bin"]
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"] = FakeResponse(200, json.dumps(release).encode())
        response = self.stage()
        self.assertEqual((response.status_code, self.error_of(response)["code"]), (404, "not_found"))
        self.assertUntouched()

    def test_draft_release_is_refused(self):
        self.github.add_release()
        route = self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"]
        release = json.loads(route.body)
        release["draft"] = True
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"] = FakeResponse(200, json.dumps(release).encode())
        self.assertEqual(self.stage().status_code, 400)
        self.assertUntouched()

    def test_http_500_from_github(self):
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases/latest"] = FakeResponse(500, b"")
        self.assertEqual(self.stage().status_code, 502)


class DownloadSafetyTests(FirmwareGithubTestCase):
    def test_redirect_to_a_disallowed_host_is_rejected(self):
        self.github.add_release()
        evil = "https://evil.example.com/firmware.bin"
        self.github.routes[f"https://github.com/{REPO}/releases/download/{TAG}/firmware-custom_pcb.bin"] = FakeResponse(302, headers={"location": evil})
        response = self.stage()
        self.assertEqual((response.status_code, self.error_of(response)["code"]), (502, "download_failed"))
        self.assertNotIn(evil, self.github.requested)
        self.assertUntouched()

    def test_redirect_to_http_is_rejected(self):
        self.github.add_release()
        self.github.routes[f"https://github.com/{REPO}/releases/download/{TAG}/firmware-custom_pcb.bin"] = FakeResponse(302, headers={"location": "http://objects.githubusercontent.com/x"})
        self.assertEqual(self.stage().status_code, 502)
        self.assertNotIn("http://objects.githubusercontent.com/x", self.github.requested)
        self.assertUntouched()

    def test_lookalike_hosts_are_rejected(self):
        for host in ("objects.githubusercontent.com.evil.example", "evilgithub.com", "github.com@evil.example", "github.com:8443"):
            with self.subTest(host=host):
                self.github.add_release()
                url = f"https://{host}/x"
                self.github.routes[f"https://github.com/{REPO}/releases/download/{TAG}/firmware-original_sonoff.bin"] = FakeResponse(302, headers={"location": url})
                self.assertEqual(self.stage().status_code, 502)
                self.assertNotIn(url, self.github.requested)
                self.assertUntouched()

    def test_redirect_loop_is_cut(self):
        self.github.add_release()
        a = f"https://github.com/{REPO}/releases/download/{TAG}/firmware-original_sonoff.bin"
        self.github.routes[a] = FakeResponse(302, headers={"location": a})
        self.assertEqual(self.stage().status_code, 502)
        self.assertUntouched()

    def test_asset_url_pointing_off_github_is_rejected(self):
        self.github.add_release(asset_overrides={"firmware-custom_pcb.bin": {"browser_download_url": "https://evil.example.com/f.bin"}})
        response = self.stage()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("https://evil.example.com/f.bin", self.github.requested)
        self.assertUntouched()

    def test_download_failing_midway_leaves_old_files_and_no_temp_files(self):
        images = self.github.add_release()
        cdn = f"https://release-assets.githubusercontent.com/{TAG}/firmware-custom_pcb.bin"
        self.github.routes[cdn] = lambda: FakeResponse(200, images["custom"], fail_after=2000)
        response = self.stage()
        self.assertEqual((response.status_code, self.error_of(response)["code"]), (502, "download_failed"))
        self.assertUntouched()

    def test_connection_error_during_download(self):
        self.github.add_release()
        self.github.routes[f"https://github.com/{REPO}/releases/download/{TAG}/firmware-custom_pcb.bin"] = requests.ConnectionError("down")
        self.assertEqual(self.error_of(self.stage())["code"], "download_failed")
        self.assertUntouched()

    def test_slow_download_times_out(self):
        self.github.add_release()
        clock = iter(range(0, 10_000, 30))
        with mock.patch("web.github_firmware.time.monotonic", side_effect=lambda: next(clock)):
            response = self.stage()
        self.assertEqual(response.status_code, 502)
        self.assertUntouched()

    def test_failed_second_replace_puts_the_first_file_back(self):
        images = self.github.add_release()
        real_replace = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_replace(src, dst)

        with mock.patch("web.github_firmware.os.replace", side_effect=flaky):
            response = self.stage()
        self.assertEqual(response.status_code, 502)
        self.assertUntouched()
        del images

    def test_no_token_or_identifying_headers(self):
        self.github.add_release()
        seen = []
        real = self.github.__call__

        def spy(url, **kwargs):
            seen.append(kwargs["headers"])
            return real(url, **kwargs)

        self._patch("requests.get", side_effect=spy)
        self.stage()
        self.assertTrue(seen)
        for headers in seen:
            self.assertEqual(set(headers), {"User-Agent", "Accept"})
            self.assertEqual(headers["User-Agent"], "nspanel-manager")


class StatusTests(FirmwareGithubTestCase):
    def test_get_latest(self):
        images = self.github.add_release()
        body = self.client.get(GET_URL).json()
        self.assertEqual(body["repo"], REPO)
        self.assertEqual(body["release"], "latest")
        self.assertIsNone(body["error"])
        self.assertNotIn("releases", body)
        resolved = body["resolved"]
        self.assertEqual((resolved["tag"], resolved["commit"], resolved["built_at"]), (TAG, COMMIT, "2026-11-19T12:00:00Z"))
        self.assertEqual(resolved["html_url"], f"https://github.com/{REPO}/releases/tag/{TAG}")
        self.assertEqual(resolved["boards"]["custom"], {"md5": md5(images["custom"]), "size": len(images["custom"])})
        self.assertEqual(body["up_to_date"], {"sonoff": False, "custom": False})
        self.assertEqual(body["staged"]["sonoff"], {"md5": md5(self.old["sonoff"]), "source": None, "tag": None, "commit": None, "staged_at": None})

    def test_up_to_date_after_staging(self):
        self.github.add_release()
        self.stage()
        body = self.client.get(GET_URL).json()
        self.assertEqual(body["up_to_date"], {"sonoff": True, "custom": True})
        staged = body["staged"]["sonoff"]
        self.assertEqual((staged["source"], staged["tag"], staged["commit"]), ("github", TAG, COMMIT))
        self.assertIsNotNone(staged["staged_at"])

    def test_staged_with_no_file(self):
        os.remove(self.path("custom"))
        self.github.add_release()
        self.assertIsNone(self.client.get(GET_URL).json()["staged"]["custom"]["md5"])

    def test_get_with_release_param_echoes_it(self):
        self.github.add_release(tag="build-33333333", latest=False)
        body = self.client.get(GET_URL, {"release": "build-33333333"}).json()
        self.assertEqual(body["release"], "build-33333333")
        self.assertEqual(body["resolved"]["tag"], "build-33333333")

    def test_get_with_latest_param(self):
        self.github.add_release()
        set_setting_value("firmware_github_release", "build-33333333")
        self.assertEqual(self.client.get(GET_URL, {"release": "latest"}).json()["resolved"]["tag"], TAG)

    def test_get_uses_the_settings(self):
        self.github.add_release(repo="someone/else-firmware")
        set_setting_value("firmware_github_repo", "someone/else-firmware")
        body = self.client.get(GET_URL).json()
        self.assertEqual(body["repo"], "someone/else-firmware")
        self.assertEqual(body["resolved"]["tag"], TAG)

    def test_get_lists_releases(self):
        self.github.add_release()
        releases = [{"tag_name": f"build-{i:08x}", "draft": False, "target_commitish": "fork", "published_at": f"2026-11-{i + 1:02d}T00:00:00Z"} for i in range(25)]
        releases.insert(0, {"tag_name": "build-deadbeef", "draft": True})
        releases[2]["target_commitish"] = "a" * 40
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases?per_page=20"] = FakeResponse(200, json.dumps(releases).encode())
        body = self.client.get(GET_URL, {"releases": "1"}).json()
        self.assertEqual(len(body["releases"]), 20)
        self.assertEqual(body["releases"][0], {"tag": "build-00000000", "commit": "00000000", "built_at": "2026-11-01T00:00:00Z"})
        self.assertEqual(body["releases"][1]["commit"], "a" * 40)
        self.assertNotIn("build-deadbeef", [r["tag"] for r in body["releases"]])
        self.assertEqual(body["resolved"]["tag"], TAG)

    def test_release_list_failure(self):
        self.github.add_release()
        self.github.routes[f"https://api.github.com/repos/{REPO}/releases?per_page=20"] = FakeResponse(403, b"{}", {"x-ratelimit-remaining": "0"})
        body = self.client.get(GET_URL, {"releases": "1"}).json()
        self.assertEqual(body["releases"], [])
        self.assertEqual(body["error"]["code"], "rate_limited")

    def test_api_answers_are_cached_for_five_minutes(self):
        self.github.add_release()
        self.client.get(GET_URL)
        self.client.get(GET_URL)
        api = [u for u in self.github.requested if u.startswith("https://api.github.com")]
        self.assertEqual(len(api), 1)
        now = github_firmware.time.monotonic()
        with mock.patch("web.github_firmware.time.monotonic", return_value=now + 301):
            self.client.get(GET_URL)
        api = [u for u in self.github.requested if u.startswith("https://api.github.com")]
        self.assertEqual(len(api), 2)

    def test_errors_are_not_cached(self):
        url = f"https://api.github.com/repos/{REPO}/releases/latest"
        self.github.routes[url] = FakeResponse(500, b"")
        self.assertEqual(self.client.get(GET_URL).json()["error"]["code"], "unreachable")
        self.github.add_release()
        self.assertEqual(self.client.get(GET_URL).json()["error"], None)

    def test_binaries_are_not_cached(self):
        self.github.add_release()
        self.stage()
        self.stage()
        downloads = [u for u in self.github.requested if u.endswith("firmware-custom_pcb.bin")]
        self.assertEqual(len(downloads), 4)  # Two requests (the redirect and the file) per stage


class ManualUploadTests(FirmwareGithubTestCase):
    def test_manual_upload_writes_a_row(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.github.add_release()
        data = make_image("custom", 7)
        response = self.client.post("/save_new_firmware", {"model": "custom", "firmware": SimpleUploadedFile("firmware.bin", data)})
        self.assertEqual(response.status_code, 302)
        row = FirmwareUpload.objects.get()
        self.assertEqual((row.md5, row.model, row.source, row.tag), (md5(data), "custom", "upload", ""))
        self.assertManagerReloaded(times=1)
        staged = self.client.get(GET_URL).json()["staged"]["custom"]
        self.assertEqual((staged["md5"], staged["source"], staged["tag"]), (md5(data), "upload", None))
