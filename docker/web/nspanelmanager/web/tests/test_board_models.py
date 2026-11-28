"""
The panel models (web/board_models.py): the page markers that hide what a board lacks, and the one list the
upload modals and the GitHub staging read.
"""

from django.urls import reverse

from web import board_models, github_firmware

from .harness import NSPMTestCase


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
