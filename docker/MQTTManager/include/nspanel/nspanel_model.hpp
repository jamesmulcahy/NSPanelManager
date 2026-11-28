#pragma once

#include <array>
#include <optional>
#include <string_view>

enum MQTT_MANAGER_NSPANEL_MODEL {
  SONOFF,
  CUSTOM,
  WAVESHARE_P4,
};

/**
 * The model selects the firmware/data file slot (firmware/<id>/ in Django). What a board has or lacks is a feature
 * (see NSPanel::register_to_manager), never a model check. Adding a board is one line in NSPANEL_MODELS (and the enum).
 */
struct NSPanelModelInfo {
  MQTT_MANAGER_NSPANEL_MODEL model;
  std::string_view id;
  // The manager image ships firmware for this model, so a missing/unreadable file is reported as an error.
  bool firmware_bundled;
};

inline constexpr std::array<NSPanelModelInfo, 3> NSPANEL_MODELS = {{
    {MQTT_MANAGER_NSPANEL_MODEL::SONOFF, "sonoff", true},
    {MQTT_MANAGER_NSPANEL_MODEL::CUSTOM, "custom", true}, // The legacy ESP32-S3 custom PCB, kept so existing panels and DB rows work.
    {MQTT_MANAGER_NSPANEL_MODEL::WAVESHARE_P4, "waveshare_p4", false},
}};

// The model with this id, or nullopt for an unknown one.
inline std::optional<MQTT_MANAGER_NSPANEL_MODEL> nspanel_model_from_id(std::string_view id) {
  for (const NSPanelModelInfo &info : NSPANEL_MODELS) {
    if (info.id == id) {
      return info.model;
    }
  }
  return std::nullopt;
}

inline std::string_view nspanel_model_id(MQTT_MANAGER_NSPANEL_MODEL model) {
  for (const NSPanelModelInfo &info : NSPANEL_MODELS) {
    if (info.model == model) {
      return info.id;
    }
  }
  return "sonoff";
}
