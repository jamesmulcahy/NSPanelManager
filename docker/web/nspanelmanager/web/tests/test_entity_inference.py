"""Inferring entity_data for imported Home Assistant entities, from recorded HA states (tests/fixtures/ha_states.json).

The "live" fixtures were captured from a running Home Assistant. That instance has no
color_temp/hs lights, light groups, covers with tilt or climates with swing modes, so the
"synthetic" fixtures follow the shape HA reports for those.
"""

import json
from pathlib import Path

from django.test import SimpleTestCase

from web.entity_data import (
    build_entity_data_from_state,
    infer_light_inputs,
    infer_thermostat_inputs,
    is_light_group,
    nspm_type_for_entity_id,
)

_FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "ha_states.json").read_text())
STATES = {**_FIXTURES["live"], **_FIXTURES["synthetic"]}


def mode(value):
    return {"value": value, "label": value, "icon": ""}


class LightInferenceTests(SimpleTestCase):
    def flags(self, entity_id):
        data = infer_light_inputs(STATES[entity_id])
        return data["can_dim"], data["can_color_temperature"], data["can_rgb"]

    def test_flags_per_color_mode(self):
        cases = {
            "light.garage_main_lights": (False, False, False),  # onoff
            "light.kitchen_main_lights": (True, False, False),  # brightness
            "light.tree": (True, False, True),  # rgbw
            "light.hue_white_ambiance": (True, True, False),  # color_temp
            "light.hue_color_lamp": (True, True, True),  # color_temp + xy
            "light.hs_lamp": (True, False, True),
            "light.rgb_bulb": (True, False, True),
            "light.rgbww_strip": (True, True, True),
        }
        for entity_id, expected in cases.items():
            with self.subTest(entity_id):
                self.assertEqual(self.flags(entity_id), expected)

    def test_fixed_fields(self):
        data = infer_light_inputs(STATES["light.tree"])
        self.assertEqual((data["controller"], data["home_assistant_name"]), ("home_assistant", "light.tree"))
        self.assertIs(data["is_ceiling_light"], False)
        self.assertIs(data["controlled_by_nspanel_main_page"], True)

    def test_missing_color_modes_is_on_off(self):
        self.assertEqual(self.flags("light.no_modes"), (False, False, False))

    def test_missing_color_modes_with_brightness_attribute_is_dimmable(self):
        state = {"entity_id": "light.old", "attributes": {"brightness": 10}}
        self.assertEqual(infer_light_inputs(state)["can_dim"], True)

    def test_missing_attributes(self):
        self.assertEqual(infer_light_inputs({"entity_id": "light.x"})["can_dim"], False)

    def test_full_entity_data(self):
        self.assertEqual(
            build_entity_data_from_state("light", STATES["light.hue_color_lamp"]),
            {
                "controller": "home_assistant",
                "home_assistant_name": "light.hue_color_lamp",
                "openhab_control_mode": "dimmer",
                "openhab_item_dimmer": "",
                "openhab_item_switch": "",
                "openhab_item_color_temp": "",
                "openhab_item_rgb": "",
                "can_dim": True,
                "can_color_temperature": True,
                "can_rgb": True,
                "is_ceiling_light": False,
                "controlled_by_nspanel_main_page": True,
            },
        )

    def test_onoff_light_uses_switch_control_mode(self):
        self.assertEqual(build_entity_data_from_state("light", STATES["light.garage_main_lights"])["openhab_control_mode"], "switch")


class LightGroupTests(SimpleTestCase):
    def test_group_has_entity_id_attribute(self):
        self.assertTrue(is_light_group(STATES["light.kitchen_all_lights"]))

    def test_plain_lights_are_not_groups(self):
        for entity_id in ("light.kitchen_main_lights", "light.tree", "light.no_modes"):
            self.assertFalse(is_light_group(STATES[entity_id]))

    def test_empty_member_list_is_not_a_group(self):
        self.assertFalse(is_light_group({"entity_id": "light.x", "attributes": {"entity_id": []}}))

    def test_other_domains_are_never_groups(self):
        self.assertFalse(is_light_group({"entity_id": "media_player.x", "attributes": {"entity_id": ["a"]}}))

    def test_no_attributes(self):
        self.assertFalse(is_light_group({"entity_id": "light.x"}))
        self.assertFalse(is_light_group({"entity_id": "light.x", "attributes": None}))


class ThermostatInferenceTests(SimpleTestCase):
    def test_live_climate(self):
        data = build_entity_data_from_state("thermostat", STATES["climate.upstairs"])
        self.assertEqual(data["hvac_modes"], [mode(m) for m in ("heat_cool", "heat", "cool", "off")])
        self.assertEqual(data["fan_modes"], [mode("auto"), mode("on")])
        self.assertEqual(data["preset_modes"], [mode(m) for m in ("away", "home", "sleep", "away_indefinitely")])
        self.assertEqual((data["swing_modes"], data["swingh_modes"]), ([], []))
        self.assertEqual(data["step_size"], 0.5)
        self.assertIs(data["use_current_temperature"], True)
        self.assertEqual((data["controller"], data["home_assistant_name"]), ("home_assistant", "climate.upstairs"))

    def test_second_live_climate(self):
        self.assertEqual(build_entity_data_from_state("thermostat", STATES["climate.downstairs"])["home_assistant_name"], "climate.downstairs")

    def test_swing_modes_and_null_preset_modes(self):
        data = build_entity_data_from_state("thermostat", STATES["climate.mini_split"])
        self.assertEqual(data["swing_modes"], [mode("off"), mode("vertical")])
        self.assertEqual(data["swingh_modes"], [mode("off"), mode("on")])
        self.assertEqual(data["preset_modes"], [])
        self.assertEqual(data["step_size"], 1.0)  # no target_temp_step

    def test_step_size_defaults_to_one(self):
        self.assertEqual(infer_thermostat_inputs({"entity_id": "climate.x", "attributes": {"target_temp_step": None}})["step_size"], 1)


class MediaPlayerAndCoverInferenceTests(SimpleTestCase):
    def test_media_player(self):
        for entity_id in ("media_player.acmax24_gym", "media_player.panasonic_blu_ray"):
            with self.subTest(entity_id):
                self.assertEqual(
                    build_entity_data_from_state("media_player", STATES[entity_id]),
                    {
                        "controller": "home_assistant",
                        "home_assistant_name": entity_id,
                        "source_volume_strategy": "none",
                        "source_entity_attribute": "",
                        "source_volume_attribute": "",
                        "volume_step": 5,
                    },
                )

    def test_cover_with_and_without_tilt_is_identical(self):
        for entity_id in ("cover.living_room_blinds_5", "cover.double_door", "cover.tilt_blind"):
            with self.subTest(entity_id):
                self.assertEqual(
                    build_entity_data_from_state("cover", STATES[entity_id]),
                    {
                        "controller": "home_assistant",
                        "home_assistant_name": entity_id,
                        "openhab_item": "",
                        "openhab_tilt_item": "",
                        "invert_positions": False,
                        "position_preset1": 0,
                        "position_preset2": 0,
                        "position_preset3": 0,
                        "tilt_preset1": 0,
                        "tilt_preset2": 0,
                        "tilt_preset3": 0,
                    },
                )


class TypeMapTests(SimpleTestCase):
    def test_supported_domains(self):
        self.assertEqual(nspm_type_for_entity_id("light.a"), "light")
        self.assertEqual(nspm_type_for_entity_id("climate.a"), "thermostat")
        self.assertEqual(nspm_type_for_entity_id("media_player.a"), "media_player")
        self.assertEqual(nspm_type_for_entity_id("cover.a"), "cover")

    def test_unsupported_domains(self):
        for entity_id in ("switch.a", "scene.a", "sensor.a", "button.a", "lightx.a"):
            self.assertIsNone(nspm_type_for_entity_id(entity_id))
