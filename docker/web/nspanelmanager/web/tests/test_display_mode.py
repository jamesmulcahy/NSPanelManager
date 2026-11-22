"""
LVGL panel mode (docs/LVGL_PANEL_MODE.md): terminal TFT uploads, which TFT a panel is served in each display mode,
naming the TFT a panel runs, and the Display section of the panel settings form.
"""

import shutil
import tempfile

from django.db.migrations import RunPython
from django.test import override_settings
from django.urls import reverse

from web import display_mode
from web.models import NSPanelSettings, TftUpload
from web.settings_helper import get_nspanel_setting_with_default, set_nspanel_setting_value

from .test_files import FileTestCase, md5
from .test_panels import PANEL_FORM

US_TERMINAL = b"terminal tft for us panels"
EU_TERMINAL = b"terminal tft for eu panels"


class DisplayModeTestCase(FileTestCase):
    def setUp(self):
        super().setUp()
        terminal_root = tempfile.mkdtemp(prefix="nspm-terminal-")
        self.addCleanup(shutil.rmtree, terminal_root, ignore_errors=True)
        override = override_settings(TERMINAL_TFT_ROOT=terminal_root)
        override.enable()
        self.addCleanup(override.disable)
        self.terminal_root = terminal_root
        self.room = self.make_room()
        self.panel = self.make_panel(self.room, accepted=True)

    def upload_tft(self, tft_file_type, data):
        return self.upload("save_new_tft_file", "tft_file", data, tft_file_type=tft_file_type)

    def configure_panel(self, mode=None, is_us_panel="False", orientation=None, tft="tft1"):
        set_nspanel_setting_value(self.panel.id, "is_us_panel", is_us_panel)
        set_nspanel_setting_value(self.panel.id, "selected_tft", tft)
        if orientation:
            set_nspanel_setting_value(self.panel.id, "us_panel_orientation", orientation)
        if mode:
            set_nspanel_setting_value(self.panel.id, "display_mode", mode)

    def served(self):
        """(status, body) of download_tft and the body of checksum_tft_file for the panel."""
        download = self.client.get(reverse("download_tft", kwargs={"panel_id": self.panel.id}))
        checksum = self.client.get(reverse("checksum_tft_file", kwargs={"panel_id": self.panel.id}))
        return download.status_code, download.content, checksum.status_code, checksum.content.decode()


class TerminalTftTests(DisplayModeTestCase):
    def test_terminal_upload_is_kept_in_the_data_directory(self):
        response = self.upload_tft("terminal_us", US_TERMINAL)

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        with open(f"{self.terminal_root}/us/gui.tft", "rb") as file:
            self.assertEqual(file.read(), US_TERMINAL)
        self.assertManagerReloaded(times=1)

    def test_every_upload_is_recorded(self):
        self.upload_tft("terminal_eu", EU_TERMINAL)
        self.upload_tft("us4", b"nspm us 4")

        uploads = list(TftUpload.objects.order_by("id").values_list("md5", "kind", "target"))
        self.assertEqual(uploads, [(md5(EU_TERMINAL), "terminal", "terminal_eu"), (md5(b"nspm us 4"), "nextion", "us4")])

    def test_lvgl_panels_get_the_terminal_tft_for_their_layout(self):
        self.upload_tft("terminal_us", US_TERMINAL)
        self.upload_tft("terminal_eu", EU_TERMINAL)
        self.upload_tft("eu1", b"eu1")

        cases = [
            ({"is_us_panel": "False"}, EU_TERMINAL),
            ({"is_us_panel": "True", "orientation": "vertical"}, US_TERMINAL),
            # The firmware lays LVGL out by is_us_panel alone, so horizontal US panels get the US terminal TFT too.
            ({"is_us_panel": "True", "orientation": "horizontal"}, US_TERMINAL),
            ({"is_us_panel": "True", "orientation": "horizontal_mirrored"}, US_TERMINAL),
        ]
        for config, expected in cases:
            with self.subTest(config=config):
                self.configure_panel(mode="lvgl", **config)
                self.assertEqual(self.served(), (200, expected, 200, md5(expected)))

    def test_terminal_tft_range_download(self):
        self.upload_tft("terminal_eu", EU_TERMINAL)
        self.configure_panel(mode="lvgl")

        response = self.client.get(reverse("download_tft", kwargs={"panel_id": self.panel.id}), HTTP_RANGE="bytes=2-8")

        self.assertEqual(response.content, EU_TERMINAL[2:8])

    def test_a_leftover_nextion_row_serves_the_selected_slot(self):
        self.upload_tft("terminal_us", US_TERMINAL)
        self.upload_tft("us3", b"us3")
        self.configure_panel(mode="lvgl", is_us_panel="True", orientation="vertical", tft="tft3")
        self.assertEqual(self.served()[1], US_TERMINAL)

        set_nspanel_setting_value(self.panel.id, "display_mode", "nextion")

        self.assertEqual(self.served(), (200, b"us3", 200, md5(b"us3")))

    def test_lvgl_panel_without_a_terminal_tft_gets_not_found(self):
        # The panel must not be told a checksum it would then try to download.
        self.upload_tft("eu1", b"eu1")
        self.configure_panel(mode="lvgl")

        self.assertEqual(self.served(), (404, b"", 404, ""))

    def test_unknown_display_mode_is_lvgl(self):
        self.upload_tft("eu1", b"eu1")
        self.upload_tft("terminal_eu", EU_TERMINAL)
        self.configure_panel(mode="something else")

        self.assertEqual(self.served()[1], EU_TERMINAL)

    def test_a_panel_without_a_display_mode_is_lvgl(self):
        self.upload_tft("eu1", b"eu1")
        self.upload_tft("terminal_eu", EU_TERMINAL)

        self.assertEqual(display_mode.get_display_mode(self.panel.id), "lvgl")
        self.assertEqual(self.served()[1], EU_TERMINAL)


class DisplayModeMigrationTests(DisplayModeTestCase):
    """Migration 0076 writes display_mode=lvgl for every panel."""

    def migrate(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module("web.migrations.0076_display_mode_lvgl")
        migration.set_every_panel_to_lvgl(apps, None)

    def test_panels_on_nextion_or_without_a_row_become_lvgl(self):
        on_nextion = self.make_panel(self.room, accepted=True)
        set_nspanel_setting_value(on_nextion.id, "display_mode", "nextion")
        already_lvgl = self.make_panel(self.room, accepted=True)
        set_nspanel_setting_value(already_lvgl.id, "display_mode", "lvgl")
        set_nspanel_setting_value(already_lvgl.id, "lvgl_theme", "dusk")

        self.migrate()

        for panel in (self.panel, on_nextion, already_lvgl):
            self.assertEqual(NSPanelSettings.objects.get(nspanel=panel, name="display_mode").value, "lvgl")
        # Nothing else is touched, and no row is added twice.
        self.assertEqual(NSPanelSettings.objects.filter(name="display_mode").count(), 3)
        self.assertEqual(get_nspanel_setting_with_default(already_lvgl.id, "lvgl_theme", None), "dusk")

    def test_migration_is_repeatable_and_reverses_to_a_no_op(self):
        import importlib

        self.migrate()
        self.migrate()
        self.assertEqual(NSPanelSettings.objects.filter(name="display_mode").count(), 1)
        migration = importlib.import_module("web.migrations.0076_display_mode_lvgl")
        self.assertIs(migration.Migration.operations[0].reverse_code, RunPython.noop)


class DescribeTftTests(DisplayModeTestCase):
    def test_staged_terminal_tft(self):
        self.upload_tft("terminal_us", US_TERMINAL)

        self.assertEqual(display_mode.describe_tft_md5(md5(US_TERMINAL)), {"kind": "terminal", "label": "Terminal TFT (US)", "current": True})

    def test_staged_slot(self):
        self.upload_tft("us4_horizontal_mirrored", b"mirrored 4")

        self.assertEqual(display_mode.describe_tft_md5(md5(b"mirrored 4")), {"kind": "nextion", "label": "NSPM TFT slot 4 (US, landscape mirrored)", "current": True})

    def test_replaced_upload_is_still_named(self):
        # The way the terminal TFT was installed by hand before: uploaded over a background slot, then replaced.
        self.upload_tft("us4", US_TERMINAL)
        self.upload_tft("us4", b"nspm us 4")
        TftUpload.objects.filter(md5=md5(US_TERMINAL)).update(kind=TftUpload.Kind.TERMINAL)

        self.assertEqual(display_mode.describe_tft_md5(md5(US_TERMINAL)), {"kind": "terminal", "label": "NSPM TFT slot 4 (US), an older upload", "current": False})

    def test_unknown_and_missing(self):
        self.assertEqual(display_mode.describe_tft_md5("0123456789abcdef0123456789abcdef")["kind"], "unknown")
        self.assertEqual(display_mode.describe_tft_md5("")["label"], "Not reported yet")

    def test_checksum_follows_a_replaced_file(self):
        self.upload_tft("terminal_eu", EU_TERMINAL)
        self.configure_panel(mode="lvgl")
        self.assertEqual(self.served()[3], md5(EU_TERMINAL))

        self.upload_tft("terminal_eu", b"a newer terminal tft, of another size")

        self.assertEqual(self.served()[3], md5(b"a newer terminal tft, of another size"))


class DisplaySettingsFormTests(DisplayModeTestCase):
    def save(self, **overrides):
        return self.client.post(reverse("save_panel_settings", kwargs={"panel_id": self.panel.id}), PANEL_FORM | {"room_id": self.room.id} | overrides)

    def setting(self, name):
        return get_nspanel_setting_with_default(self.panel.id, name, None)

    def test_display_settings_are_stored(self):
        self.save(display_mode="lvgl", lvgl_theme="ocean", lvgl_background="peaks")

        self.assertEqual((self.setting("display_mode"), self.setting("lvgl_theme"), self.setting("lvgl_background")), ("lvgl", "ocean", "peaks"))
        # The slot is kept for switching back.
        self.assertEqual(self.setting("selected_tft"), "tft1")
        self.assertManagerReloaded(times=1)

    def test_empty_look_is_no_longer_managed(self):
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "dusk")
        set_nspanel_setting_value(self.panel.id, "lvgl_background", "dusk")

        self.save(display_mode="lvgl", lvgl_theme="", lvgl_background="")

        self.assertIsNone(self.setting("lvgl_theme"))
        self.assertIsNone(self.setting("lvgl_background"))

    def test_nextion_can_no_longer_be_chosen(self):
        self.save(display_mode="nextion")

        self.assertIsNone(self.setting("display_mode"))

    def test_settings_page_offers_only_lvgl(self):
        response = self.client.get(reverse("edit_nspanel", kwargs={"panel_id": self.panel.id}))

        self.assertContains(response, 'name="display_mode" id="display_mode" value="lvgl"')
        self.assertNotContains(response, 'value="nextion"')

    def test_unknown_values_are_ignored(self):
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "grey")

        self.save(display_mode="vga", lvgl_theme="light", lvgl_background="photo")

        self.assertIsNone(self.setting("display_mode"))
        self.assertEqual(self.setting("lvgl_theme"), "grey")
        self.assertIsNone(self.setting("lvgl_background"))

    def test_a_form_without_the_display_fields_leaves_them_alone(self):
        set_nspanel_setting_value(self.panel.id, "display_mode", "lvgl")
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "aurora")

        self.save()

        self.assertEqual((self.setting("display_mode"), self.setting("lvgl_theme")), ("lvgl", "aurora"))

    def test_settings_page_shows_the_display_section(self):
        self.upload_tft("terminal_us", US_TERMINAL)
        self.configure_panel(mode="lvgl", is_us_panel="True", orientation="vertical")
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "peaks")
        self.panel.md5_tft_file = md5(US_TERMINAL)
        self.panel.save()

        response = self.client.get(reverse("edit_nspanel", kwargs={"panel_id": self.panel.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="lvgl_settings" class=""')
        self.assertContains(response, '<option value="peaks" selected>Peaks</option>', html=False)
        self.assertContains(response, 'Running now: <span id="display_running">Terminal TFT (US)</span>')
        self.assertNotContains(response, "has been uploaded yet")

    def test_settings_page_shows_a_look_chosen_on_the_panel(self):
        # As MQTTManager stores a look the panel reports (NSPanel::_handle_lvgl_look_report): plain name/value rows.
        self.configure_panel(mode="lvgl", is_us_panel="True", orientation="vertical")
        set_nspanel_setting_value(self.panel.id, "lvgl_theme", "auto")
        set_nspanel_setting_value(self.panel.id, "lvgl_background", "ocean")

        response = self.client.get(reverse("edit_nspanel", kwargs={"panel_id": self.panel.id}))

        self.assertContains(response, '<option value="auto" selected>', html=False)
        self.assertContains(response, '<option value="ocean" selected>Ocean</option>', html=False)
        self.assertContains(response, 'A look chosen on the panel itself')

    def test_every_look_the_panel_offers_can_be_shown_and_saved(self):
        # The firmware's look picker (LookView.cpp, Looks::ALL) and what MQTTManager accepts in a report.
        for theme, background in (("auto", "ocean"), ("auto", "dusk"), ("auto", "aurora"), ("auto", "peaks"), ("dark", "none"), ("grey", "none")):
            self.assertIn(theme, display_mode.LVGL_THEMES)
            self.assertIn(background, display_mode.LVGL_BACKGROUNDS)
            self.save(display_mode="lvgl", lvgl_theme=theme, lvgl_background=background)
            self.assertEqual((self.setting("lvgl_theme"), self.setting("lvgl_background")), (theme, background))

    def test_settings_page_warns_when_the_terminal_tft_is_missing(self):
        self.configure_panel(mode="lvgl")

        response = self.client.get(reverse("edit_nspanel", kwargs={"panel_id": self.panel.id}))

        self.assertContains(response, "No Terminal TFT (EU) has been uploaded yet")


US_BUNDLED = b"bundled terminal tft for us panels"


class BundledTerminalTftTests(DisplayModeTestCase):
    """The terminal TFTs the image ships (HMI_files/terminal), served when nothing was uploaded."""

    def bundle(self, layout, data):
        from django.conf import settings
        import os

        path = os.path.join(settings.MEDIA_ROOT, "HMI_files", "terminal", layout, "gui.tft")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as file:
            file.write(data)

    def test_lvgl_panel_gets_the_bundled_tft_without_an_upload(self):
        self.bundle("us", US_BUNDLED)
        self.configure_panel(mode="lvgl", is_us_panel="True", orientation="vertical")

        self.assertEqual(self.served(), (200, US_BUNDLED, 200, md5(US_BUNDLED)))

    def test_upload_replaces_the_bundled_tft(self):
        self.bundle("us", US_BUNDLED)
        self.upload_tft("terminal_us", US_TERMINAL)
        self.configure_panel(mode="lvgl", is_us_panel="True", orientation="vertical")

        self.assertEqual(self.served(), (200, US_TERMINAL, 200, md5(US_TERMINAL)))

    def test_each_layout_falls_back_on_its_own(self):
        # An upload for one layout leaves the other on its bundled file.
        self.bundle("eu", EU_TERMINAL)
        self.upload_tft("terminal_us", US_TERMINAL)
        self.configure_panel(mode="lvgl")

        self.assertEqual(self.served()[1], EU_TERMINAL)

    def test_bundled_tft_is_named_as_bundled(self):
        self.bundle("us", US_BUNDLED)

        self.assertEqual(display_mode.describe_tft_md5(md5(US_BUNDLED)), {"kind": "terminal", "label": "Terminal TFT (US), bundled", "current": True})

    def test_the_image_ships_both_terminal_tfts(self):
        # The files themselves, as docker/HMI_files/terminal/README.md lists them: a replacement must update both.
        import hashlib
        import os

        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "..", "..", "..", "..", "HMI_files", "terminal"),  # the repository: docker/web/nspanelmanager/web/tests
            os.path.join(here, "..", "..", "HMI_files", "terminal"),  # the image: /usr/src/app/nspanelmanager/web/tests
        ]
        root = next((path for path in candidates if os.path.isdir(path)), None)
        self.assertIsNotNone(root, "HMI_files/terminal not found")
        expected = {"us": "ee73878729a0757704a86d136ddcdf33", "eu": "c873a214b53a10269138c6c81b9ee57e"}
        for layout, checksum in expected.items():
            with open(os.path.join(root, layout, "gui.tft"), "rb") as file:
                self.assertEqual(hashlib.md5(file.read()).hexdigest(), checksum, layout)
