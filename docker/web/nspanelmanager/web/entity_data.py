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
