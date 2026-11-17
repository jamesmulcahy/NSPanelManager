"""
Pins the exact entity_data the PUT endpoints store for each entity type, so the
builders in web.entity_data can be shared with the Home Assistant importer without
changing what hand-made entities look like.
"""

from django.urls import reverse

from web.models import Entity

from .harness import NSPMTestCase


class EntityDataCharacterizationTests(NSPMTestCase):
    def setUp(self):
        super().setUp()
        self.room = self.make_room("Kitchen")
        self.page = self.entities_page(self.room)

    def place(self, slot=0):
        return {"room_id": self.room.id, "entities_page_id": self.page.id, "room_view_position": slot}

    def stored(self):
        return Entity.objects.get().entity_data

    def test_light_entity_data(self):
        values = {
            **self.place(),
            "controller": "home_assistant",
            "type": "light",
            "friendly_name": "Ceiling",
            "can_color_temperature": True,
            "can_dim": True,
            "can_rgb": False,
            "controlled_by_nspanel_main_page": True,
            "home_assistant_name": "light.kitchen_ceiling",
            "is_ceiling_light": False,
            "openhab_item_color_temp": "ct",
            "openhab_item_dimmer": "dim",
            "openhab_item_switch": "sw",
            "openhab_item_rgb": "rgb",
        }
        self.assertEqual(self.put_json(reverse("rest_entities_lights"), {"values": values}).status_code, 200)
        self.assertEqual(
            self.stored(),
            {
                "controller": "home_assistant",
                "home_assistant_name": "light.kitchen_ceiling",
                "openhab_control_mode": "dimmer",
                "openhab_item_dimmer": "dim",
                "openhab_item_switch": "sw",
                "openhab_item_color_temp": "ct",
                "openhab_item_rgb": "rgb",
                "can_dim": True,
                "can_color_temperature": True,
                "can_rgb": False,
                "is_ceiling_light": False,
                "controlled_by_nspanel_main_page": True,
            },
        )

    def test_light_entity_data_string_flags_and_switch_mode(self):
        values = {
            **self.place(),
            "controller": "openhab",
            "type": "light",
            "friendly_name": "Lamp",
            "can_color_temperature": "false",
            "can_dim": "False",
            "can_rgb": "TRUE",
            "controlled_by_nspanel_main_page": "true",
            "home_assistant_name": "",
            "is_ceiling_light": "true",
            "openhab_item_color_temp": "",
            "openhab_item_dimmer": "",
            "openhab_item_switch": "Lamp",
            "openhab_item_rgb": "",
        }
        self.put_json(reverse("rest_entities_lights"), {"values": values})
        data = self.stored()
        # Quirk kept as is: the control mode follows the truthiness of the raw can_dim, so the string "False" is dimmer.
        self.assertEqual(data["openhab_control_mode"], "dimmer")
        self.assertEqual((data["can_dim"], data["can_color_temperature"], data["can_rgb"]), (False, False, True))
        self.assertEqual((data["is_ceiling_light"], data["controlled_by_nspanel_main_page"]), (True, True))
        self.assertEqual(set(data), {"controller", "home_assistant_name", "openhab_control_mode", "openhab_item_dimmer", "openhab_item_switch", "openhab_item_color_temp", "openhab_item_rgb", "can_dim", "can_color_temperature", "can_rgb", "is_ceiling_light", "controlled_by_nspanel_main_page"})

    def test_light_switch_control_mode_for_boolean_false(self):
        values = {
            **self.place(),
            "controller": "openhab",
            "type": "light",
            "friendly_name": "Lamp",
            "can_color_temperature": False,
            "can_dim": False,
            "can_rgb": False,
            "controlled_by_nspanel_main_page": False,
            "home_assistant_name": "",
            "is_ceiling_light": False,
            "openhab_item_color_temp": "",
            "openhab_item_dimmer": "",
            "openhab_item_switch": "Lamp",
            "openhab_item_rgb": "",
        }
        self.put_json(reverse("rest_entities_lights"), {"values": values})
        self.assertEqual(self.stored()["openhab_control_mode"], "switch")

    def test_thermostat_entity_data(self):
        modes = [{"value": "heat", "label": "heat", "icon": ""}]
        payload = {
            **self.place(),
            "controller": "home_assistant",
            "type": "thermostat",
            "friendly_name": "Heat pump",
            "step_size": "0.5",
            "use_current_temperature": "True",
            "home_assistant_name": "climate.kitchen",
            "openhab_fan_mode_item": "a",
            "openhab_hvac_mode_item": "b",
            "openhab_preset_mode_item": "c",
            "openhab_swing_mode_item": "d",
            "openhab_swingh_mode_item": "e",
            "openhab_temperature_item": "f",
            "openhab_current_temperature_item": "g",
            "fan_modes": modes,
            "hvac_modes": modes,
            "preset_modes": [],
            "swing_modes": [],
            "swingh_modes": modes,
        }
        self.assertEqual(self.put_json(reverse("rest_entities_thermostats"), payload).status_code, 200)
        self.assertEqual(
            self.stored(),
            {
                "controller": "home_assistant",
                "fan_modes": modes,
                "hvac_modes": modes,
                "preset_modes": [],
                "swing_modes": [],
                "swingh_modes": modes,
                "use_current_temperature": True,
                "home_assistant_name": "climate.kitchen",
                "openhab_fan_mode_item": "a",
                "openhab_hvac_mode_item": "b",
                "openhab_preset_mode_item": "c",
                "openhab_swing_mode_item": "d",
                "openhab_swingh_mode_item": "e",
                "openhab_temperature_item": "f",
                "openhab_current_temperature_item": "g",
                "step_size": 0.5,
            },
        )

    def test_thermostat_use_current_temperature_false_and_default_current_item(self):
        payload = {
            **self.place(),
            "controller": "home_assistant",
            "type": "thermostat",
            "friendly_name": "Heat pump",
            "step_size": 1,
            "use_current_temperature": "False",
            "home_assistant_name": "climate.kitchen",
            "openhab_fan_mode_item": "",
            "openhab_hvac_mode_item": "",
            "openhab_preset_mode_item": "",
            "openhab_swing_mode_item": "",
            "openhab_swingh_mode_item": "",
            "openhab_temperature_item": "",
            "fan_modes": [],
            "hvac_modes": [],
            "preset_modes": [],
            "swing_modes": [],
            "swingh_modes": [],
        }
        self.put_json(reverse("rest_entities_thermostats"), payload)
        data = self.stored()
        self.assertIs(data["use_current_temperature"], False)
        self.assertEqual(data["openhab_current_temperature_item"], "")
        self.assertEqual(data["step_size"], 1.0)

    def test_media_player_entity_data(self):
        payload = {
            **self.place(),
            "controller": "home_assistant",
            "friendly_name": "Speakers",
            "home_assistant_name": "media_player.kitchen",
            "volume_step": 10,
            "source_volume_strategy": "player_attributes",
            "source_entity_attribute": " source ",
            "source_volume_attribute": "vol ",
        }
        self.assertEqual(self.put_json(reverse("rest_entities_media_players"), payload).status_code, 200)
        self.assertEqual(
            self.stored(),
            {
                "controller": "home_assistant",
                "home_assistant_name": "media_player.kitchen",
                "source_volume_strategy": "player_attributes",
                "source_entity_attribute": "source",
                "source_volume_attribute": "vol",
                "volume_step": 10,
            },
        )

    def test_media_player_defaults(self):
        payload = {**self.place(), "controller": "home_assistant", "friendly_name": "Speakers", "home_assistant_name": "media_player.kitchen"}
        self.put_json(reverse("rest_entities_media_players"), payload)
        self.assertEqual(
            self.stored(),
            {"controller": "home_assistant", "home_assistant_name": "media_player.kitchen", "source_volume_strategy": "none", "source_entity_attribute": "", "source_volume_attribute": "", "volume_step": 5},
        )

    def test_cover_entity_data(self):
        payload = {
            **self.place(),
            "controller": "home_assistant",
            "friendly_name": "  Blind ",
            "home_assistant_name": " cover.blind ",
            "openhab_item": " oh ",
            "openhab_tilt_item": "tilt",
            "invert_positions": True,
            "position_preset1": 1,
            "position_preset2": "2",
            "position_preset3": 3,
            "tilt_preset1": 4,
            "tilt_preset2": 5,
            "tilt_preset3": 6,
        }
        self.assertEqual(self.put_json(reverse("rest_entities_covers"), payload).status_code, 200)
        self.assertEqual(
            self.stored(),
            {
                "controller": "home_assistant",
                "home_assistant_name": "cover.blind",
                "openhab_item": "oh",
                "openhab_tilt_item": "tilt",
                "invert_positions": True,
                "position_preset1": 1,
                "position_preset2": 2,
                "position_preset3": 3,
                "tilt_preset1": 4,
                "tilt_preset2": 5,
                "tilt_preset3": 6,
            },
        )
        self.assertEqual(Entity.objects.get().friendly_name, "Blind")
