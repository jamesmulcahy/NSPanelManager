"""
Builders for the ``Entity.entity_data`` JSON of each entity type.

The PUT views in web.rest and the Home Assistant importer both go through these, so an
imported entity is stored exactly like one made in the add-entity form. The builders do
no validation and no request parsing: callers pass already-typed values.
"""


def build_light_entity_data(
    *,
    controller,
    home_assistant_name,
    can_dim,
    can_color_temperature,
    can_rgb,
    is_ceiling_light,
    controlled_by_nspanel_main_page,
    openhab_control_mode=None,
    openhab_item_dimmer="",
    openhab_item_switch="",
    openhab_item_color_temp="",
    openhab_item_rgb="",
):
    """openhab_control_mode defaults to "dimmer" when can_dim, else "switch"."""
    if openhab_control_mode is None:
        openhab_control_mode = "dimmer" if can_dim else "switch"
    return {
        "controller": controller,
        "home_assistant_name": home_assistant_name,
        "openhab_control_mode": openhab_control_mode,
        "openhab_item_dimmer": openhab_item_dimmer,
        "openhab_item_switch": openhab_item_switch,
        "openhab_item_color_temp": openhab_item_color_temp,
        "openhab_item_rgb": openhab_item_rgb,
        "can_dim": can_dim,
        "can_color_temperature": can_color_temperature,
        "can_rgb": can_rgb,
        "is_ceiling_light": is_ceiling_light,
        "controlled_by_nspanel_main_page": controlled_by_nspanel_main_page,
    }


def build_thermostat_entity_data(
    *,
    controller,
    home_assistant_name,
    step_size=1,
    use_current_temperature=True,
    fan_modes=None,
    hvac_modes=None,
    preset_modes=None,
    swing_modes=None,
    swingh_modes=None,
    openhab_fan_mode_item="",
    openhab_hvac_mode_item="",
    openhab_preset_mode_item="",
    openhab_swing_mode_item="",
    openhab_swingh_mode_item="",
    openhab_temperature_item="",
    openhab_current_temperature_item="",
):
    """Each mode list holds {"value", "label", "icon"} dicts. step_size is stored as a float."""
    return {
        "controller": controller,
        "fan_modes": [] if fan_modes is None else fan_modes,
        "hvac_modes": [] if hvac_modes is None else hvac_modes,
        "preset_modes": [] if preset_modes is None else preset_modes,
        "swing_modes": [] if swing_modes is None else swing_modes,
        "swingh_modes": [] if swingh_modes is None else swingh_modes,
        "use_current_temperature": use_current_temperature,
        "home_assistant_name": home_assistant_name,
        "openhab_fan_mode_item": openhab_fan_mode_item,
        "openhab_hvac_mode_item": openhab_hvac_mode_item,
        "openhab_preset_mode_item": openhab_preset_mode_item,
        "openhab_swing_mode_item": openhab_swing_mode_item,
        "openhab_swingh_mode_item": openhab_swingh_mode_item,
        "openhab_temperature_item": openhab_temperature_item,
        "openhab_current_temperature_item": openhab_current_temperature_item,
        "step_size": float(step_size),
    }


# Volume in % that one volume up/down press on the panel changes, unless set per media player.
MEDIA_PLAYER_DEFAULT_VOLUME_STEP = 5


def build_media_player_entity_data(
    *,
    controller,
    home_assistant_name,
    source_volume_strategy="none",
    source_entity_attribute="",
    source_volume_attribute="",
    volume_step=MEDIA_PLAYER_DEFAULT_VOLUME_STEP,
):
    return {
        "controller": controller,
        "home_assistant_name": home_assistant_name,
        "source_volume_strategy": source_volume_strategy,
        "source_entity_attribute": source_entity_attribute,
        "source_volume_attribute": source_volume_attribute,
        "volume_step": volume_step,
    }


def build_cover_entity_data(
    *,
    controller,
    home_assistant_name,
    invert_positions=False,
    position_preset1=0,
    position_preset2=0,
    position_preset3=0,
    tilt_preset1=0,
    tilt_preset2=0,
    tilt_preset3=0,
    openhab_item="",
    openhab_tilt_item="",
):
    return {
        "controller": controller,
        "home_assistant_name": home_assistant_name,
        "openhab_item": openhab_item,
        "openhab_tilt_item": openhab_tilt_item,
        "invert_positions": invert_positions,
        "position_preset1": int(position_preset1),
        "position_preset2": int(position_preset2),
        "position_preset3": int(position_preset3),
        "tilt_preset1": int(tilt_preset1),
        "tilt_preset2": int(tilt_preset2),
        "tilt_preset3": int(tilt_preset3),
    }


###############################
# Inference from Home Assistant
###############################
#
# These take an HA state dict ({"entity_id": ..., "state": ..., "attributes": {...}}) and return
# the inputs of the builders above for an entity imported rather than made in the add-entity form.

# HA domain -> NSPM entity type, for the domains the importer supports.
NSPM_TYPE_BY_HA_DOMAIN = {
    "light": "light",
    "climate": "thermostat",
    "media_player": "media_player",
    "cover": "cover",
}

_RGB_COLOR_MODES = ("hs", "xy", "rgb", "rgbw", "rgbww")

# Bits of a cover's supported_features that the NSPM cover form looks at.
COVER_SUPPORT_SET_POSITION = 4
COVER_SUPPORT_SET_TILT_POSITION = 128


def ha_domain(entity_id):
    return entity_id.split(".", 1)[0]


def nspm_type_for_entity_id(entity_id):
    """The NSPM entity type for an HA entity id ("light.x" -> "light", "climate.x" -> "thermostat"), or None if unsupported."""
    return NSPM_TYPE_BY_HA_DOMAIN.get(ha_domain(entity_id))


def is_light_group(state):
    """True for a light.* entity with an entity_id attribute (HA's light groups, which list their members there)."""
    return ha_domain(state["entity_id"]) == "light" and bool((state.get("attributes") or {}).get("entity_id"))


def _attributes(state):
    return state.get("attributes") or {}


def infer_light_inputs(state):
    """Keyword arguments for build_light_entity_data.

    can_dim: any supported_color_modes other than "onoff". can_color_temperature: "color_temp" in
    the modes. can_rgb: any of hs/xy/rgb/rgbw/rgbww. When supported_color_modes is missing or empty
    (old integrations, or a light that is unavailable), the light is treated as on/off, except that
    a non-null "brightness" attribute marks it dimmable.
    """
    attributes = _attributes(state)
    modes = list(attributes.get("supported_color_modes") or [])
    if not modes and attributes.get("brightness") is not None:
        modes = ["brightness"]
    return {
        "controller": "home_assistant",
        "home_assistant_name": state["entity_id"],
        "can_dim": any(mode != "onoff" for mode in modes),
        "can_color_temperature": "color_temp" in modes,
        "can_rgb": any(mode in _RGB_COLOR_MODES for mode in modes),
        "is_ceiling_light": False,
        "controlled_by_nspanel_main_page": True,
    }


def _mode_list(values):
    """HA mode names as the {value, label, icon} items the thermostat entity_data holds, like the add-entity form does."""
    return [{"icon": "", "label": mode, "value": mode} for mode in (values or [])]


def infer_thermostat_inputs(state):
    """Keyword arguments for build_thermostat_entity_data from a climate state."""
    attributes = _attributes(state)
    return {
        "controller": "home_assistant",
        "home_assistant_name": state["entity_id"],
        "fan_modes": _mode_list(attributes.get("fan_modes")),
        "hvac_modes": _mode_list(attributes.get("hvac_modes")),
        "preset_modes": _mode_list(attributes.get("preset_modes")),
        "swing_modes": _mode_list(attributes.get("swing_modes")),
        "swingh_modes": _mode_list(attributes.get("swing_horizontal_modes")),
        "step_size": attributes.get("target_temp_step") or 1,
        "use_current_temperature": True,
    }


def infer_media_player_inputs(state):
    """Keyword arguments for build_media_player_entity_data: no source volume, the default volume step."""
    return {
        "controller": "home_assistant",
        "home_assistant_name": state["entity_id"],
        "source_volume_strategy": "none",
        "volume_step": MEDIA_PLAYER_DEFAULT_VOLUME_STEP,
    }


def infer_cover_inputs(state):
    """Keyword arguments for build_cover_entity_data: presets 0, not inverted. Position and tilt support are read live from supported_features, not stored."""
    return {
        "controller": "home_assistant",
        "home_assistant_name": state["entity_id"],
        "invert_positions": False,
    }


_INFERENCE = {
    "light": (infer_light_inputs, build_light_entity_data),
    "thermostat": (infer_thermostat_inputs, build_thermostat_entity_data),
    "media_player": (infer_media_player_inputs, build_media_player_entity_data),
    "cover": (infer_cover_inputs, build_cover_entity_data),
}


def build_entity_data_from_state(entity_type, state):
    """entity_data for importing the HA entity in state as entity_type, identical to what the add-entity form stores for the same settings."""
    infer, build = _INFERENCE[entity_type]
    return build(**infer(state))
