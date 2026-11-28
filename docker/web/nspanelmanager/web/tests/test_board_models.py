"""
The panel models (web/board_models.py): the page markers that hide what a board lacks, and the one list the
upload modals and the GitHub staging read.
"""

import hashlib
import tempfile

from django.urls import reverse

from web import board_models, github_firmware

from .harness import NSPMTestCase
from .test_files import FileTestCase, esp_image, md5


class BoardModelTests(NSPMTestCase):
    def test_every_model_has_a_distinct_chip_slot_and_label(self):
        self.assertEqual(board_models.MODEL_IDS, ("sonoff", "custom", "waveshare_p4"))
        self.assertEqual(board_models.CHIP_IDS, {"sonoff": 0x0000, "custom": 0x0009, "waveshare_p4": 0x0012})

    def test_only_built_boards_are_staged_from_github(self):
        # custom is the legacy ESP32-S3 slot: no release builds it any more. custom_pcb is the P4 board now.
        self.assertEqual(github_firmware.BOARDS, {"sonoff": "original_sonoff", "waveshare_p4": "custom_pcb"})

    def test_chip_names_are_in_the_message(self):
        header = bytearray(16)
        header[0] = 0xE9
        header[12:14] = (0x0009).to_bytes(2, "little")

        error = board_models.app_image_error("waveshare_p4", bytes(header))

        self.assertIn("ESP32-S3", error)
        self.assertIn("ESP32-P4", error)
        self.assertIsNone(board_models.app_image_error("custom", bytes(header)))

    def test_upload_modals_list_every_model(self):
        response = self.client.get(reverse("index"))

        for model in board_models.MODELS:
            self.assertContains(response, f'<option value="{model.id}">{model.label}</option>', count=2)


class SettingsPageFeatureTests(NSPMTestCase):
    def setUp(self):
        super().setUp()
        self.panel = self.make_panel(self.make_room())

    def test_settings_the_board_may_lack_are_marked_with_the_feature_that_hides_them(self):
        response = self.client.get(reverse("edit_nspanel", kwargs={"panel_id": self.panel.id}))

        for feature in ("no_buttons", "no_relays", "no_temperature"):
            self.assertContains(response, f'data-hidden-by-feature="{feature}"')
        # The thermostat limits, and the thermostat modes that need them, go with the temperature sensor.
        self.assertContains(response, 'id="button1_thermostat_mode_controls" class="hidden" data-hidden-by-feature="no_temperature"')
        self.assertContains(response, '<option data-hidden-by-feature="no_temperature" value="4"', count=2)


class StoredFeaturesTests(NSPMTestCase):
    def test_features_are_stored_on_the_panel_row_and_default_to_none(self):
        panel = self.make_panel(self.make_room())
        self.assertEqual(panel.features, "")

        panel.features = '["no_tft", "no_relays"]'
        panel.model = "waveshare_p4"
        panel.save()
        panel.refresh_from_db()

        self.assertEqual((panel.model, panel.features), ("waveshare_p4", '["no_tft", "no_relays"]'))


def esp_app_image(version="build-1a2b3c4d", chip_id=0x0000, hash_appended=True, body_size=1000):
    """A synthetic ESP-IDF app image: the header (magic, chip id at 12-13, hash_appended at 23), esp_app_desc_t at offset 32
    (version at +16, project name +48, time +80, date +96, IDF version +112, app_elf_sha256 +144), a body, and a trailing sha256."""
    header = bytearray(32)
    header[0] = 0xE9
    header[12:14] = chip_id.to_bytes(2, "little")
    header[23] = 1 if hash_appended else 0
    desc = bytearray(256)
    desc[0:4] = (0xABCD5432).to_bytes(4, "little")
    for offset, text in ((16, version), (48, "firmware_espidf"), (80, "07:08:09"), (96, "Nov 28 2026"), (112, "v5.5.0")):
        desc[offset : offset + len(text)] = text.encode()
    desc[144:176] = bytes(range(1, 33))
    image = bytes(header) + bytes(desc) + b"x" * body_size
    return image + hashlib.sha256(image).digest() if hash_appended else image


class AppImageInfoTests(NSPMTestCase):
    def parse(self, image):
        return board_models.parse_app_image(image[: board_models.APP_IMAGE_HEAD_SIZE], image[-32:])

    def test_the_identity_is_read_from_the_app_description_and_the_appended_hash(self):
        image = esp_app_image()

        info = self.parse(image)

        self.assertEqual(
            info.as_dict(),
            {
                "version": "build-1a2b3c4d",
                "project": "firmware_espidf",
                "build_date": "Nov 28 2026 07:08:09",
                "idf_version": "v5.5.0",
                "elf_sha256": bytes(range(1, 33)).hex(),
                "image_sha256": hashlib.sha256(image[:-32]).hexdigest(),
                "chip": "esp32",
            },
        )

    def test_the_chip_comes_from_the_header(self):
        self.assertEqual(self.parse(esp_app_image(chip_id=0x0009)).chip, "esp32s3")
        self.assertEqual(self.parse(esp_app_image(chip_id=0x0012)).chip, "esp32p4")

    def test_an_image_without_an_appended_hash_has_no_image_sha(self):
        info = self.parse(esp_app_image(hash_appended=False))

        self.assertEqual(info.image_sha256, "")
        self.assertEqual(info.version, "build-1a2b3c4d")

    def test_what_is_not_an_app_image_has_no_identity(self):
        self.assertIsNone(board_models.parse_app_image(b"", b""))
        self.assertIsNone(board_models.parse_app_image(b"\x00" * 300, b"\x00" * 32))
        self.assertIsNone(board_models.parse_app_image(b"\xe9" * 16, b"\x00" * 32))  # The header only, as the upload check sees it
        no_description = bytearray(esp_app_image())
        no_description[32:36] = b"\x00" * 4
        self.assertIsNone(self.parse(bytes(no_description)))

    def test_a_file_is_read_from_its_head_and_tail(self):
        with tempfile.NamedTemporaryFile() as image_file:
            image = esp_app_image()
            image_file.write(image)
            image_file.flush()

            info = board_models.read_app_image_info(image_file.name)

        self.assertEqual(info.image_sha256, hashlib.sha256(image[:-32]).hexdigest())
        self.assertIsNone(board_models.read_app_image_info("/nonexistent/firmware.bin"))


class FirmwareInfoEndpointTests(FileTestCase):
    def test_it_reports_the_staged_image_next_to_its_md5(self):
        image = esp_app_image()
        self.upload("save_new_firmware", "firmware", image, model="sonoff")

        body = self.client.get(reverse("firmware_info"), {"model": "sonoff"}).json()

        self.assertEqual(body["md5"], md5(image))
        self.assertEqual(body["size"], len(image))
        self.assertEqual(body["build"]["version"], "build-1a2b3c4d")
        self.assertEqual(body["build"]["image_sha256"], hashlib.sha256(image[:-32]).hexdigest())

    def test_the_md5_checksum_response_is_unchanged(self):
        image = esp_app_image()
        self.upload("save_new_firmware", "firmware", image, model="sonoff")

        response = self.client.get(reverse("checksum_firmware"))

        self.assertEqual(response.content.decode(), md5(image))
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")

    def test_an_image_that_is_not_an_esp_idf_app_has_a_null_build(self):
        # esp_image() in test_files has the header only: it passes the upload check but has no esp_app_desc_t.
        self.upload("save_new_firmware", "firmware", esp_image(0x0000), model="sonoff")

        body = self.client.get(reverse("firmware_info")).json()

        self.assertEqual(body["md5"], md5(esp_image(0x0000)))
        self.assertIsNone(body["build"])

    def test_nothing_staged_is_a_404(self):
        self.assertEqual(self.client.get(reverse("firmware_info"), {"model": "waveshare_p4"}).status_code, 404)

    def test_an_unknown_model_is_a_400(self):
        self.assertEqual(self.client.get(reverse("firmware_info"), {"model": "nope"}).status_code, 400)

    def test_the_models_are_separate(self):
        self.upload("save_new_firmware", "firmware", esp_app_image("build-sonoff"), model="sonoff")
        self.upload("save_new_firmware", "firmware", esp_app_image("build-p4", chip_id=0x0012), model="waveshare_p4")

        self.assertEqual(self.client.get(reverse("firmware_info"), {"model": "sonoff"}).json()["build"]["version"], "build-sonoff")
        self.assertEqual(self.client.get(reverse("firmware_info"), {"model": "waveshare_p4"}).json()["build"]["chip"], "esp32p4")


class StagedFirmwareStatusTests(FileTestCase):
    def test_the_rest_status_names_the_staged_version(self):
        image = esp_app_image("build-staged")
        self.upload("save_new_firmware", "firmware", image, model="sonoff")

        staged = self.client.get("/rest/v2/firmware").json()["staged"]

        self.assertEqual(staged["sonoff"]["version"], "build-staged")
        self.assertEqual(staged["sonoff"]["image_sha256"], hashlib.sha256(image[:-32]).hexdigest())
        self.assertEqual((staged["waveshare_p4"]["version"], staged["waveshare_p4"]["image_sha256"]), (None, None))
