"""
/rest/v2/nspanels/<id>/settings (web/rest_v2/nspanel_settings.py): for now only the LVGL panel mode
settings, stored in the same NSPanelSettings rows the panel settings form writes and MQTTManager reads.
"""

from web.models import NSPanelSettings
from web.settings_helper import get_nspanel_setting_with_default, set_nspanel_setting_value

from .harness import NSPMTestCase


class NSPanelSettingsTests(NSPMTestCase):
    def setUp(self):
        super().setUp()
        self.panel = self.make_panel(self.make_room())
        self.url = f"/rest/v2/nspanels/{self.panel.id}/settings"

    def rows(self):
        return dict(NSPanelSettings.objects.filter(nspanel=self.panel).values_list("name", "value"))

    def test_get_defaults(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"display_mode": "nextion", "lvgl_theme": None, "lvgl_background": None})

    def test_get_reads_the_rows_the_form_writes(self):
        set_nspanel_setting_value(self.panel.id, "display_mode", "lvgl")
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "dusk")
        set_nspanel_setting_value(self.panel.id, "lvgl_background", "peaks")

        self.assertEqual(self.client.get(self.url).json(), {"display_mode": "lvgl", "lvgl_theme": "dusk", "lvgl_background": "peaks"})

    def test_patch_display_mode_alone(self):
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "ocean")

        response = self.patch_json(self.url, {"display_mode": "lvgl"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"display_mode": "lvgl", "lvgl_theme": "ocean", "lvgl_background": None})
        self.assertEqual(self.rows(), {"display_mode": "lvgl", "lvgl_theme": "ocean"})
        self.assertManagerReloaded(times=1)

    def test_patch_look(self):
        response = self.patch_json(self.url, {"lvgl_theme": "auto", "lvgl_background": "aurora"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_nspanel_setting_with_default(self.panel.id, "lvgl_theme", None), "auto")
        self.assertEqual(get_nspanel_setting_with_default(self.panel.id, "lvgl_background", None), "aurora")
        self.assertManagerReloaded(times=1)

    def test_null_stops_managing_that_part_of_the_look(self):
        # As the form's empty choice: no row, so the manager never sends it.
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "dusk")
        set_nspanel_setting_value(self.panel.id, "lvgl_background", "dusk")

        response = self.patch_json(self.url, {"lvgl_theme": None})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rows(), {"lvgl_background": "dusk"})
        self.assertManagerReloaded(times=1)

    def test_unchanged_values_write_nothing_and_do_not_reload(self):
        set_nspanel_setting_value(self.panel.id, "display_mode", "lvgl")
        current = self.client.get(self.url).json()

        response = self.patch_json(self.url, current)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.rows(), {"display_mode": "lvgl"})  # No rows created for the nulls.
        self.assertManagerNotReloaded()

    def test_unknown_values_are_rejected(self):
        for body in ({"display_mode": "terminal"}, {"lvgl_theme": "light"}, {"lvgl_background": "space"}, {"display_mode": None}, {"lvgl_theme": 1}):
            with self.subTest(body=body):
                response = self.patch_json(self.url, body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["status"], "error")
        self.assertEqual(self.rows(), {})
        self.assertManagerNotReloaded()

    def test_unknown_fields_are_rejected(self):
        response = self.patch_json(self.url, {"display_mode": "lvgl", "selected_tft": "tft2"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("selected_tft", response.json()["message"])
        self.assertEqual(self.rows(), {})
        self.assertManagerNotReloaded()

    def test_missing_panel_is_not_found(self):
        self.assertEqual(self.client.get("/rest/v2/nspanels/999/settings").status_code, 404)
        self.assertEqual(self.patch_json("/rest/v2/nspanels/999/settings", {"display_mode": "lvgl"}).status_code, 404)

    def test_other_panels_are_untouched(self):
        other = self.make_panel(self.panel.room, name="Other", mac="11:22:33:44:55:66")

        self.patch_json(self.url, {"display_mode": "lvgl", "lvgl_theme": "grey"})

        self.assertFalse(NSPanelSettings.objects.filter(nspanel=other).exists())
