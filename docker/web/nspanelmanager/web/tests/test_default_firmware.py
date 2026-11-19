"""
The firmware the image ships by default (firmware/<model>/), which panels download until someone
uploads their own: the files are the ones firmware/PROVENANCE.md records, fit the panel's flash
layout, and are what the checksum and download views serve.

docker/fetch_fork_firmware.sh writes both the files and PROVENANCE.md.
"""

import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from web.github_firmware import APP_SLOT_BYTES, CHIP_IDS, LITTLEFS_PARTITION_BYTES

from .harness import NSPMTestCase

FIRMWARE_DIR = Path(settings.BASE_DIR) / "firmware"
PROVENANCE = FIRMWARE_DIR / "PROVENANCE.md"


def recorded_md5s():
    """{"sonoff/firmware.bin": md5, ...} from PROVENANCE.md's md5sum block."""
    block = re.search(r"```md5\n(.*?)```", PROVENANCE.read_text(), re.S)
    assert block, "PROVENANCE.md has no ```md5 block"
    return {path: md5 for md5, path in (line.split() for line in block.group(1).splitlines() if line.strip())}


class DefaultFirmwareTests(NSPMTestCase):
    def test_every_shipped_file_matches_provenance(self):
        md5s = recorded_md5s()

        expected = {f"{model}/{name}" for model in CHIP_IDS for name in ("firmware.bin", "data_file.bin", "merged_flash.bin")}
        self.assertEqual(set(md5s), expected)
        for path, md5 in md5s.items():
            with self.subTest(path=path):
                self.assertEqual(hashlib.md5((FIRMWARE_DIR / path).read_bytes()).hexdigest(), md5)

    def test_images_fit_the_partition_table(self):
        for model in CHIP_IDS:
            with self.subTest(model=model):
                self.assertLessEqual((FIRMWARE_DIR / model / "firmware.bin").stat().st_size, APP_SLOT_BYTES)
                self.assertLessEqual((FIRMWARE_DIR / model / "data_file.bin").stat().st_size, LITTLEFS_PARTITION_BYTES)

    def test_each_model_ships_an_image_for_its_chip(self):
        for model, chip_id in CHIP_IDS.items():
            with self.subTest(model=model):
                header = (FIRMWARE_DIR / model / "firmware.bin").read_bytes()[:16]
                self.assertEqual(header[0], 0xE9, "not an ESP app image")
                self.assertEqual(int.from_bytes(header[12:14], "little"), chip_id)

    # Production leaves MEDIA_ROOT unset, so FileSystemStorage resolves firmware/ against uwsgi's
    # --chdir, which is BASE_DIR.
    @override_settings(MEDIA_ROOT=settings.BASE_DIR)
    def test_views_serve_the_shipped_files(self):
        md5s = recorded_md5s()
        for model in CHIP_IDS:
            with self.subTest(model=model):
                firmware = self.client.get(reverse("checksum_firmware"), {"model": model})
                data_file = self.client.get(reverse("checksum_data_file"), {"model": model})
                self.assertEqual(firmware.content.decode(), md5s[f"{model}/firmware.bin"])
                self.assertEqual(data_file.content.decode(), md5s[f"{model}/data_file.bin"])

                download = self.client.get(reverse("download_firmware"), {"model": model})
                self.assertEqual(hashlib.md5(download.content).hexdigest(), md5s[f"{model}/firmware.bin"])

        # A panel that doesn't name its model is an original Sonoff one.
        self.assertEqual(self.client.get(reverse("checksum_firmware")).content.decode(), md5s["sonoff/firmware.bin"])
