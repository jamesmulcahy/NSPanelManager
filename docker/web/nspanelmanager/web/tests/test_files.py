"""
Firmware, LittleFS and TFT images: uploading from the UI, and the checksum and download
endpoints panels use to decide whether to update and to fetch the image.
"""

import hashlib
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from web.settings_helper import set_nspanel_setting_value

from .harness import NSPMTestCase


def esp_image(chip_id, size=1024):
    """An app image as far as the upload checks go: the 0xE9 magic and the chip id (bytes 12-13), then a recognisable pattern."""
    header = bytearray(16)
    header[0] = 0xE9
    header[12:14] = chip_id.to_bytes(2, "little")
    return bytes(header) + (bytes(range(256)) * (size // 256 + 1))[: size - 16]


FIRMWARE = esp_image(0x0000)  # A Sonoff (ESP32) image, 1 KiB


def md5(data):
    return hashlib.md5(data).hexdigest()


class FileTestCase(NSPMTestCase):
    def setUp(self):
        super().setUp()
        media_root = tempfile.mkdtemp(prefix="nspm-media-")
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media_root)
        override.enable()
        self.addCleanup(override.disable)

    def upload(self, url_name, field, data, **form):
        return self.client.post(reverse(url_name), {field: SimpleUploadedFile("upload.bin", data), **form})


class FirmwareTests(FileTestCase):
    def test_upload_then_checksum_and_download(self):
        response = self.upload("save_new_firmware", "firmware", FIRMWARE, model="sonoff")

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("checksum_firmware")).content.decode(), md5(FIRMWARE))
        self.assertEqual(self.client.get(reverse("download_firmware")).content, FIRMWARE)
        self.assertManagerReloaded(times=1)

    def test_models_are_stored_separately(self):
        sonoff, custom, p4 = esp_image(0x0000, 64), esp_image(0x0009, 64), esp_image(0x0012, 64)
        self.upload("save_new_firmware", "firmware", sonoff, model="sonoff")
        self.upload("save_new_firmware", "firmware", custom, model="custom")
        self.upload("save_new_firmware", "firmware", p4, model="waveshare_p4")

        self.assertEqual(self.client.get(reverse("download_firmware"), {"model": "custom"}).content, custom)
        self.assertEqual(self.client.get(reverse("download_firmware"), {"model": "sonoff"}).content, sonoff)
        self.assertEqual(self.client.get(reverse("download_firmware"), {"model": "waveshare_p4"}).content, p4)
        self.assertEqual(self.client.get(reverse("checksum_firmware"), {"model": "custom"}).content.decode(), md5(custom))
        self.assertEqual(self.client.get(reverse("checksum_firmware"), {"model": "waveshare_p4"}).content.decode(), md5(p4))

    def test_upload_replaces_previous_image(self):
        self.upload("save_new_firmware", "firmware", esp_image(0x0000, 64), model="sonoff")
        self.upload("save_new_firmware", "firmware", esp_image(0x0000, 128), model="sonoff")

        self.assertEqual(self.client.get(reverse("download_firmware")).content, esp_image(0x0000, 128))

    def test_upload_without_model_is_ignored(self):
        self.upload("save_new_firmware", "firmware", FIRMWARE)

        self.assertManagerNotReloaded()
        self.assertRejected(self.client.get(reverse("download_firmware")))

    def test_upload_for_the_matching_chip_is_accepted(self):
        for model, chip_id in (("sonoff", 0x0000), ("custom", 0x0009), ("waveshare_p4", 0x0012)):
            with self.subTest(model=model):
                image = esp_image(chip_id)
                response = self.upload("save_new_firmware", "firmware", image, model=model)

                self.assertRedirects(response, "/", fetch_redirect_response=False)
                self.assertEqual(self.client.get(reverse("download_firmware"), {"model": model}).content, image)

    def test_upload_for_another_chip_is_rejected_naming_both(self):
        self.upload("save_new_firmware", "firmware", esp_image(0x0012, 64), model="waveshare_p4")
        self.assertManagerReloaded(times=1)

        # What the staged custom slot holds today: an ESP32-S3 image, sent to the Waveshare P4 slot.
        response = self.upload("save_new_firmware", "firmware", esp_image(0x0009, 128), model="waveshare_p4")

        self.assertEqual(response.status_code, 400)
        body = response.content.decode()
        self.assertIn("ESP32-S3", body)
        self.assertIn("ESP32-P4", body)
        self.assertIn("0x0009", body)
        self.assertIn("0x0012", body)
        self.assertIn("waveshare_p4", body)
        # The staged image is untouched and the manager was not told to reload.
        self.assertEqual(self.client.get(reverse("download_firmware"), {"model": "waveshare_p4"}).content, esp_image(0x0012, 64))
        self.assertManagerReloaded(times=1)

    def test_sonoff_slot_rejects_an_esp32_s3_image(self):
        response = self.upload("save_new_firmware", "firmware", esp_image(0x0009), model="sonoff")

        self.assertEqual(response.status_code, 400)
        self.assertRejected(self.client.get(reverse("download_firmware")))

    def test_upload_that_is_not_an_esp_image_is_rejected(self):
        for name, data in (("wrong magic", b"\x00" * 64), ("too short", b"\xe9\x00"), ("empty", b"")):
            with self.subTest(name=name):
                response = self.upload("save_new_firmware", "firmware", data, model="sonoff")

                self.assertEqual(response.status_code, 400)
                self.assertIn("0xE9", response.content.decode())
        self.assertManagerNotReloaded()

    def test_upload_for_an_unknown_model_is_rejected(self):
        for url_name, field in (("save_new_firmware", "firmware"), ("save_new_data_file", "data_file"), ("save_new_merged_flash", "bin")):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.upload(url_name, field, FIRMWARE, model="../../etc").status_code, 400)
        self.assertManagerNotReloaded()

    def test_merged_flash_is_not_checked_for_a_chip(self):
        response = self.upload("save_new_merged_flash", "bin", b"\x00" * 64, model="waveshare_p4")

        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_unknown_model_is_rejected(self):
        for url_name in ("download_firmware", "checksum_firmware", "download_data_file", "checksum_data_file"):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name), {"model": "../../etc"}).status_code, 400)

    def test_range_requests_use_an_exclusive_end(self):
        # CONTRACT with the panel firmware (NSPanelManager-firmware, UpdateManager.cpp): the
        # "bytes=start-end" end is treated as EXCLUSIVE (Python slice), not inclusive as RFC 7233
        # says. The firmware deliberately sends ranges in the same convention. Changing either
        # side alone corrupts OTA updates.
        self.upload("save_new_firmware", "firmware", FIRMWARE, model="sonoff")

        response = self.client.get(reverse("download_firmware"), HTTP_RANGE="bytes=100-200")

        self.assertEqual(response.content, FIRMWARE[100:200])
        self.assertEqual(len(response.content), 100)

    def test_open_ended_range(self):
        self.upload("save_new_firmware", "firmware", FIRMWARE, model="sonoff")

        self.assertEqual(self.client.get(reverse("download_firmware"), HTTP_RANGE="bytes=1000-").content, FIRMWARE[1000:])

    def test_merged_flash_upload_does_not_reload_manager(self):
        # MQTTManager does not track the merged image's checksum, so there is nothing to reload.
        self.upload("save_new_merged_flash", "bin", FIRMWARE, model="sonoff")

        self.assertManagerNotReloaded()

    def test_checksum_of_missing_image_is_not_found(self):
        panel = self.make_panel(self.make_room())
        for url in (reverse("checksum_firmware"), reverse("checksum_data_file"), reverse("checksum_tft_file", kwargs={"panel_id": panel.id})):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.content, b"")


class DataFileTests(FileTestCase):
    def test_upload_then_checksum_and_download(self):
        self.upload("save_new_data_file", "data_file", FIRMWARE, model="sonoff")

        self.assertEqual(self.client.get(reverse("checksum_data_file")).content.decode(), md5(FIRMWARE))
        self.assertEqual(self.client.get(reverse("download_data_file")).content, FIRMWARE)
        self.assertEqual(self.client.get(reverse("download_data_file"), HTTP_RANGE="bytes=0-16").content, FIRMWARE[:16])
        self.assertManagerReloaded(times=1)


class TFTTests(FileTestCase):
    def setUp(self):
        super().setUp()
        self.room = self.make_room()
        self.panel = self.make_panel(self.room)

    def upload_tft(self, tft_file_type, data):
        return self.upload("save_new_tft_file", "tft_file", data, tft_file_type=tft_file_type)

    def panel_tft(self, **headers):
        return self.client.get(reverse("download_tft", kwargs={"panel_id": self.panel.id}), **headers).content

    def configure_panel(self, is_us_panel="False", orientation=None):
        set_nspanel_setting_value(self.panel.id, "is_us_panel", is_us_panel)
        if orientation:
            set_nspanel_setting_value(self.panel.id, "us_panel_orientation", orientation)

    def test_each_panel_gets_the_terminal_tft_for_its_layout(self):
        for tft_file_type in ("terminal_eu", "terminal_us"):
            self.upload_tft(tft_file_type, tft_file_type.encode())

        cases = [
            ({}, b"terminal_eu"),  # defaults: EU panel
            ({"is_us_panel": "True", "orientation": "vertical"}, b"terminal_us"),
            # A US panel mounted sideways draws the landscape layout, as an EU panel does.
            ({"is_us_panel": "True", "orientation": "horizontal"}, b"terminal_eu"),
        ]
        for config, expected in cases:
            with self.subTest(config=config):
                self.configure_panel(**config)
                self.assertEqual(self.panel_tft(), expected)
                self.assertEqual(self.client.get(reverse("checksum_tft_file", kwargs={"panel_id": self.panel.id})).content.decode(), md5(expected))

    def test_tft_range_download(self):
        self.upload_tft("terminal_eu", FIRMWARE)
        self.configure_panel()

        self.assertEqual(self.panel_tft(HTTP_RANGE="bytes=10-20"), FIRMWARE[10:20])

    def test_upload_reloads_manager(self):
        self.upload_tft("terminal_eu", FIRMWARE)

        self.assertManagerReloaded(times=1)

    def test_unknown_tft_type_is_rejected(self):
        self.assertEqual(self.upload_tft("eu1", FIRMWARE).status_code, 400)
        self.assertManagerNotReloaded()
