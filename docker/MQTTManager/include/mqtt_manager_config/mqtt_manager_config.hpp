#ifndef MQTTMANAGER_CONFIG_HPP
#define MQTTMANAGER_CONFIG_HPP
#include "light/light.hpp"
#include "nspanel/firmware_build_info.hpp"
#include "nspanel/nspanel_model.hpp"
#include <boost/algorithm/string.hpp>
#include <boost/exception/diagnostic_information.hpp>
#include <boost/signals2.hpp>
#include <database_manager/database_manager.hpp>
#include <expected>
#include <mutex>
#include <optional>
#include <nlohmann/json.hpp>
#include <nlohmann/json_fwd.hpp>
#include <protobuf/protobuf_mqttmanager.pb.h>
#include <spdlog/spdlog.h>
#include <string>
#include <unordered_map>

#if defined(TEST_MODE) && TEST_MODE == 1
#include <gtest/gtest.h>
#endif

enum LightTurnOnBehaviour {
  COLOR_TEMPERATURE,
  RESTORE_PREVIOUS,
};

enum MQTT_MANAGER_SETTING {
  BUTTON_LONG_PRESS_TIME,
  CALENDAR_ENTITY_IDS,
  CALENDAR_LOOKAHEAD_HOURS,
  CALENDAR_MAX_EVENTS,
  CALENDAR_UPDATE_INTERVAL,
  CLOCK_US_STYLE,
  COLOR_TEMP_MAX,
  COLOR_TEMP_MIN,
  THEME,
  DATE_FORMAT,
  ENERGY_POWER_ENTITY_IDS,
  ENERGY_POWER_SOURCE,
  ENERGY_PRICE_ENTITY_ID,
  ENERGY_PRICE_PER_KWH,
  ENERGY_PRICE_SOURCE,
  LIGHTS_ON_ALERT_THRESHOLD,
  HOME_ASSISTANT_SYNC_EXCLUDE_LABELS,
  LIGHTS_ON_EXCLUDE_LABELS,
  LIGHTS_ON_SOURCE,
  IS_HOME_ASSISTANT_ADDON,
  HOME_ASSISTANT_ADDRESS,
  HOME_ASSISTANT_TOKEN,
  LOCATION_LATITUDE,
  LOCATION_LONGITUDE,
  MANAGER_ADDRESS,
  MANAGER_PORT,
  MAX_LIVE_LOG_MESSAGES,
  MAX_LOG_BUFFER_SIZE,
  MIN_BUTTON_PUSH_TIME,
  MQTTMANAGER_LOG_LEVEL,
  MQTT_PASSWORD,
  MQTT_PORT,
  MQTT_SERVER,
  MQTT_USERNAME,
  OPENHAB_ADDRESS,
  OPENHAB_TOKEN,
  OUTSIDE_TEMP_SENSOR_ENTITY_ID,
  OUTSIDE_TEMP_SENSOR_PROVIDER,
  WEATHER_PRECIPITATION_FORMAT,
  RAISE_TO_100_LIGHT_LEVEL,
  ROOM_STATUS_BACKOFF_TIME,
  ALL_ROOMS_STATUS_BACKOFF_TIME,
  REVERSE_COLOR_TEMP,
  SCREEN_DIM_LEVEL,
  SCREENSAVER_ACTIVATION_TIMEOUT,
  SCREENSAVER_BASE_CARD_SECONDS,
  SCREENSAVER_CARDS,
  SCREENSAVER_DIM_LEVEL,
  SCREENSAVER_MODE,
  SHOW_SCREENSAVER_INSIDE_TEMPERATURE,
  SHOW_SCREENSAVER_OUTSIDE_TEMPERATURE,
  SPECIAL_MODE_RELEASE_TIME,
  SPECIAL_MODE_TRIGGER_TIME,
  TURN_ON_BEHAVIOR,
  USE_FAHRENHEIT,
  WEATHER_UPDATE_INTERVAL,
  WEATHER_WIND_SPEED_FORMAT,
  MQTT_WAIT_TIME,
  OPTIMISTIC_MODE,
  LIGHT_TURN_ON_BRIGHTNESS,
  DEFAULT_NSPANEL_TYPE,
  BUZZER_SOUND_TOUCH,
  BUZZER_SOUND_SCENE_ACTIVATED,
  BUZZER_SOUND_SCENE_SAVED,
  BUZZER_SOUND_TIMER_FIRED,
  FIRMWARE_GITHUB_REPO,
  FIRMWARE_GITHUB_RELEASE,
  LAST, // Keep last as to be able to reference the last element in the list.
};

class MqttManagerConfig {
public:
  // Initialize this static library with settings and configuration options
  static void load();

  // Populate the database with default values in case they are not already set
  // and clean up any invalid or outdated settings.
  static void populate_default_and_clean();

  static inline std::string timezone;
  // POSIX TZ rule for timezone, read from its tzdata file. Empty if it could not be read.
  static inline std::string timezone_posix_rule;

  // Where Django keeps the terminal TFTs for panels in LVGL mode (settings.TERMINAL_TFT_ROOT): us/gui.tft and
  // eu/gui.tft. A variable so that tests can point it elsewhere.
  static inline std::string terminal_tft_directory = "/data/tft/terminal";
  // The terminal TFTs the image ships (HMI_files/terminal), used for a layout when nothing was uploaded. A variable
  // so that tests can point it elsewhere.
  static inline std::string bundled_terminal_tft_directory = "/usr/src/app/nspanelmanager/HMI_files/terminal";

  /**
   * Read the POSIX TZ rule from the end of a tzdata (TZif) file, ex. "CET-1CEST,M3.5.0,M10.5.0/3".
   * @param tzif_path: Path of the file, ex. /usr/share/zoneinfo/Europe/Stockholm.
   * @return The rule, or empty if the file is missing, not version 2 or later, or has no rule.
   */
  static std::string read_posix_tz_rule(const std::string &tzif_path);

  template <typename T>
  static T get_setting_with_default(MQTT_MANAGER_SETTING key);

  /**
   * Set the value of a setting key in the DB and update the in-memory cache.
   */
  static void set_setting_value(MQTT_MANAGER_SETTING key, std::string value);

  /**
   * Set a value for a NSPanel setting.
   */
  static void set_nspanel_setting_value(int32_t nspanel_id, std::string key, std::string default_value);

  /**
   * Check if we are running in Home Assistant addon mode. If so, return true.
   */
  static bool is_home_assistant_addon();

  /*
   * Get the light turn on behaviour.
   */
  static LightTurnOnBehaviour get_light_turn_on_behaviour();

  static void update_firmware_checksum();
  static void update_tft_checksums();

  // Where Django keeps the firmware slots (firmware/<model id>/firmware.bin, data_file.bin). A variable so that tests can
  // point it elsewhere.
  static inline std::string firmware_directory = "/usr/src/app/nspanelmanager/firmware/";

  /**
   * Read the build identity out of an ESP-IDF app image: the version, project, dates and ELF SHA-256 from esp_app_desc_t
   * (at offset 32), the chip from the header, and the image SHA-256 from the last 32 bytes when the header says one is
   * appended (hash_appended, byte 23).
   * @param head: At least the first 288 bytes of the image.
   * @param tail: The last 32 bytes of the image.
   * @return The identity, or empty if this is not an app image.
   */
  static std::optional<FirmwareBuildInfo> parse_app_image(const std::string &head, const std::string &tail);

  // The identity of the staged firmware.bin of a model's slot. Unexpected when none is staged or it is not an app image.
  static std::expected<FirmwareBuildInfo, bool> get_firmware_build_info(MQTT_MANAGER_NSPANEL_MODEL model);

  // The staged firmware.bin / data_file.bin of a model's slot. Unexpected when there is none.
  static std::expected<std::string, bool> get_firmware_checksum(MQTT_MANAGER_NSPANEL_MODEL model);
  static std::expected<std::string, bool> get_littlefs_checksum(MQTT_MANAGER_NSPANEL_MODEL model);
  // The terminal TFT for the US (portrait) or EU (landscape) LVGL layout. Unexpected when it has not been uploaded.
  static std::expected<std::string, bool> get_terminal_tft_checksum(bool us_layout);
  // Whether an md5 is one of the terminal TFTs the manager knows: the staged US or EU one, the ones the image ships,
  // or an earlier terminal upload (Django's TftUpload history).
  static bool is_known_terminal_tft_md5(const std::string &md5);

  /**
   * Attach a callback to be called when config has been fully loaded.
   */
  template <typename CALLBACK_BIND>
  static void attach_config_loaded_listener(CALLBACK_BIND callback) {
    MqttManagerConfig::_config_loaded_listeners.connect(callback);
  }

  /**
   * Detach a callback to be called when config has been fully loaded.
   */
  template <typename CALLBACK_BIND>
  static void dettach_config_loaded_listener(CALLBACK_BIND callback) {
    MqttManagerConfig::_config_loaded_listeners.disconnect(callback);
  }

private:
  // Mutex to make sure only one thread can load settings at the time
  static inline std::mutex _config_load_mutex;

  static inline std::mutex _database_access_mutex; // Mutex to only allow one thread to access the "get_setting_with_default" database function as the same time.

  static inline boost::signals2::signal<void()> _config_loaded_listeners;

  static inline std::mutex _settings_mutex;

  static inline LightTurnOnBehaviour _light_turn_on_behaviour = LightTurnOnBehaviour::COLOR_TEMPERATURE;

  static std::optional<std::string> _get_file_md5_checksum(std::string file_path);
  static std::optional<FirmwareBuildInfo> _read_firmware_build_info(const std::string &file_path);
  static inline std::mutex _md5_checksum_files_mutex;
  // Keyed by model id.
  static inline std::unordered_map<std::string, std::string> _md5_checksum_firmware;
  static inline std::unordered_map<std::string, std::string> _md5_checksum_littlefs;
  static inline std::unordered_map<std::string, FirmwareBuildInfo> _firmware_build_info;
  static inline std::string _md5_checksum_bundled_terminal_us;
  static inline std::string _md5_checksum_bundled_terminal_eu;
  static inline std::string _md5_checksum_terminal_us;
  static inline std::string _md5_checksum_terminal_eu;

  static inline std::unordered_map<MQTT_MANAGER_SETTING, std::string> _settings_values_cache;

  // Map of SETTING key that points to a pair of two strings. Pair.first is database key as string, Pair.second is default value.
  static inline std::unordered_map<MQTT_MANAGER_SETTING, std::pair<std::string, std::string>> _setting_key_map = {
      {MQTT_MANAGER_SETTING::IS_HOME_ASSISTANT_ADDON, {"is_home_assistant_addon", "false"}},
      {MQTT_MANAGER_SETTING::BUTTON_LONG_PRESS_TIME, {"button_long_press_time", "5000"}},
      {MQTT_MANAGER_SETTING::CALENDAR_ENTITY_IDS, {"calendar_entity_ids", ""}}, // Comma-separated calendar.* entity ids, "all" for every calendar, empty turns the calendar off
      {MQTT_MANAGER_SETTING::CALENDAR_LOOKAHEAD_HOURS, {"calendar_lookahead_hours", "48"}},
      {MQTT_MANAGER_SETTING::CALENDAR_MAX_EVENTS, {"calendar_max_events", "5"}},
      {MQTT_MANAGER_SETTING::CALENDAR_UPDATE_INTERVAL, {"calendar_update_interval", "5"}}, // Minutes
      {MQTT_MANAGER_SETTING::CLOCK_US_STYLE, {"clock_us_style", "False"}},
      {MQTT_MANAGER_SETTING::ENERGY_POWER_ENTITY_IDS, {"energy_power_entity_ids", ""}},                // Comma-separated power sensors, summed, for energy_power_source "entities"
      {MQTT_MANAGER_SETTING::ENERGY_POWER_SOURCE, {"energy_power_source", "home_assistant_energy"}},   // home_assistant_energy, entities or off
      {MQTT_MANAGER_SETTING::ENERGY_PRICE_ENTITY_ID, {"energy_price_entity_id", ""}},                  // For energy_price_source "entity"
      {MQTT_MANAGER_SETTING::ENERGY_PRICE_PER_KWH, {"energy_price_per_kwh", "0"}},                     // For energy_price_source "fixed"
      {MQTT_MANAGER_SETTING::ENERGY_PRICE_SOURCE, {"energy_price_source", "home_assistant_energy"}},   // home_assistant_energy, entity, fixed or off
      {MQTT_MANAGER_SETTING::LIGHTS_ON_ALERT_THRESHOLD, {"lights_on_alert_threshold", "15"}},          // 0: never alert
      {MQTT_MANAGER_SETTING::HOME_ASSISTANT_SYNC_EXCLUDE_LABELS, {"home_assistant_sync_exclude_labels", ""}}, // Comma-separated Home Assistant label ids left out of the entity sync (web only)
      {MQTT_MANAGER_SETTING::LIGHTS_ON_EXCLUDE_LABELS, {"lights_on_exclude_labels", ""}},              // Comma-separated Home Assistant label ids
      {MQTT_MANAGER_SETTING::LIGHTS_ON_SOURCE, {"lights_on_source", "home_assistant"}},                // home_assistant, nspanelmanager or off
      {MQTT_MANAGER_SETTING::COLOR_TEMP_MAX, {"color_temp_max", "6000"}},
      {MQTT_MANAGER_SETTING::COLOR_TEMP_MIN, {"color_temp_min", "2000"}},
      {MQTT_MANAGER_SETTING::THEME, {"theme", "default"}},
      {MQTT_MANAGER_SETTING::DATE_FORMAT, {"date_format", "%a %d/%m %Y"}},
      {MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, {"home_assistant_address", ""}},
      {MQTT_MANAGER_SETTING::HOME_ASSISTANT_TOKEN, {"home_assistant_token", ""}},
      {MQTT_MANAGER_SETTING::LOCATION_LATITUDE, {"location_latitude", ""}},
      {MQTT_MANAGER_SETTING::LOCATION_LONGITUDE, {"location_longitude", ""}},
      {MQTT_MANAGER_SETTING::MANAGER_ADDRESS, {"manager_address", ""}},
      {MQTT_MANAGER_SETTING::MANAGER_PORT, {"manager_port", ""}},
      {MQTT_MANAGER_SETTING::MAX_LIVE_LOG_MESSAGES, {"max_live_log_messages", "10"}},
      {MQTT_MANAGER_SETTING::MAX_LOG_BUFFER_SIZE, {"max_log_buffer_size", "10"}},
      {MQTT_MANAGER_SETTING::MIN_BUTTON_PUSH_TIME, {"min_button_push_time", "50"}},
      {MQTT_MANAGER_SETTING::MQTTMANAGER_LOG_LEVEL, {"mqttmanager_log_level", "debug"}},
      {MQTT_MANAGER_SETTING::MQTT_PASSWORD, {"mqtt_password", ""}},
      {MQTT_MANAGER_SETTING::MQTT_PORT, {"mqtt_port", "1883"}},
      {MQTT_MANAGER_SETTING::MQTT_SERVER, {"mqtt_server", ""}},
      {MQTT_MANAGER_SETTING::MQTT_USERNAME, {"mqtt_username", ""}},
      {MQTT_MANAGER_SETTING::OPENHAB_ADDRESS, {"openhab_address", ""}},
      {MQTT_MANAGER_SETTING::OPENHAB_TOKEN, {"openhab_token", ""}},
      {MQTT_MANAGER_SETTING::OUTSIDE_TEMP_SENSOR_ENTITY_ID, {"outside_temp_sensor_entity_id", ""}},
      {MQTT_MANAGER_SETTING::OUTSIDE_TEMP_SENSOR_PROVIDER, {"outside_temp_sensor_provider", ""}},
      {MQTT_MANAGER_SETTING::WEATHER_PRECIPITATION_FORMAT, {"weather_precipitation_format", "mm"}},
      {MQTT_MANAGER_SETTING::RAISE_TO_100_LIGHT_LEVEL, {"raise_to_100_light_level", "95"}},
      {MQTT_MANAGER_SETTING::ROOM_STATUS_BACKOFF_TIME, {"room_status_backoff_time", "100"}},
      {MQTT_MANAGER_SETTING::ALL_ROOMS_STATUS_BACKOFF_TIME, {"all_rooms_status_backoff_time", "250"}},
      {MQTT_MANAGER_SETTING::REVERSE_COLOR_TEMP, {"reverse_color_temp", "False"}},
      {MQTT_MANAGER_SETTING::SCREEN_DIM_LEVEL, {"screen_dim_level", "100"}},
      {MQTT_MANAGER_SETTING::SCREENSAVER_ACTIVATION_TIMEOUT, {"screensaver_activation_timeout", "30000"}},
      {MQTT_MANAGER_SETTING::SCREENSAVER_BASE_CARD_SECONDS, {"screensaver_base_card_seconds", "10"}},
      {MQTT_MANAGER_SETTING::SCREENSAVER_CARDS, {"screensaver_cards", ""}}, // Comma-separated type:seconds, for example "calendar:10"
      {MQTT_MANAGER_SETTING::SCREENSAVER_DIM_LEVEL, {"screensaver_dim_level", "1"}},
      {MQTT_MANAGER_SETTING::SCREENSAVER_MODE, {"screensaver_mode", "with_background"}},
      {MQTT_MANAGER_SETTING::SHOW_SCREENSAVER_INSIDE_TEMPERATURE, {"show_screensaver_inside_temperature", "True"}},
      {MQTT_MANAGER_SETTING::SHOW_SCREENSAVER_OUTSIDE_TEMPERATURE, {"show_screensaver_outside_temperature", "True"}},
      {MQTT_MANAGER_SETTING::SPECIAL_MODE_RELEASE_TIME, {"special_mode_release_time", "5000"}},
      {MQTT_MANAGER_SETTING::SPECIAL_MODE_TRIGGER_TIME, {"special_mode_trigger_time", "300"}},
      {MQTT_MANAGER_SETTING::TURN_ON_BEHAVIOR, {"turn_on_behavior", "color_temp"}},
      {MQTT_MANAGER_SETTING::USE_FAHRENHEIT, {"use_fahrenheit", "False"}},
      {MQTT_MANAGER_SETTING::WEATHER_UPDATE_INTERVAL, {"weather_update_interval", "10"}},
      {MQTT_MANAGER_SETTING::WEATHER_WIND_SPEED_FORMAT, {"weather_wind_speed_format", "kmh"}},
      {MQTT_MANAGER_SETTING::MQTT_WAIT_TIME, {"mqtt_wait_time", "1000"}},
      {MQTT_MANAGER_SETTING::OPTIMISTIC_MODE, {"optimistic_mode", "True"}},
      {MQTT_MANAGER_SETTING::LIGHT_TURN_ON_BRIGHTNESS, {"light_turn_on_brightness", "50"}},
      {MQTT_MANAGER_SETTING::DEFAULT_NSPANEL_TYPE, {"default_nspanel_type", "eu"}},
      {MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, {"buzzer_sound_touch", ""}}, // RTTTL, empty for no sound
      {MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_ACTIVATED, {"buzzer_sound_scene_activated", ""}},
      {MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_SAVED, {"buzzer_sound_scene_saved", ""}},
      // Unlike the other sounds this one is not empty: a timer without a sound would be useless. Keep in sync with
      // BUZZER_SOUND_TIMER_FIRED_DEFAULT in rest_v2/global_settings.py. Empty still means silent.
      {MQTT_MANAGER_SETTING::BUZZER_SOUND_TIMER_FIRED, {"buzzer_sound_timer_fired", "timer:d=8,o=6,b=200:c7,p,c7,p,c7,p,c7"}},
      // Where the web interface fetches firmware from. MQTTManager does not read these; the keys are here so that it
      // keeps the rows. Keep in sync with FIRMWARE_GITHUB_*_DEFAULT in rest_v2/global_settings.py.
      {MQTT_MANAGER_SETTING::FIRMWARE_GITHUB_REPO, {"firmware_github_repo", "jamesmulcahy/NSPanelManager-firmware"}},
      {MQTT_MANAGER_SETTING::FIRMWARE_GITHUB_RELEASE, {"firmware_github_release", "latest"}},
#if defined(TEST_MODE) && TEST_MODE == 1
      {MQTT_MANAGER_SETTING::LAST, {"last", "last_value"}},
#endif
  };

#if defined(TEST_MODE) && TEST_MODE == 1
  FRIEND_TEST(MqttManagerConfigTest, verify_all_settings_exists_and_have_db_key);
  FRIEND_TEST(MqttManagerConfigTest, verify_settings_cache_is_used);
#endif
};

template <>
inline std::string MqttManagerConfig::get_setting_with_default(MQTT_MANAGER_SETTING key) {
  std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_database_access_mutex);
  if (MqttManagerConfig::_settings_values_cache.contains(key)) {
    return MqttManagerConfig::_settings_values_cache[key];
  }

  std::string setting_db_key = MqttManagerConfig::_setting_key_map[key].first;
  try {
    auto result = database_manager::database.get_all<database_manager::SettingHolder>(sqlite_orm::where(sqlite_orm::c(&database_manager::SettingHolder::name) == setting_db_key));
    if (result.size() > 0) [[likely]] {
      SPDLOG_TRACE("Found setting {} with value {}", setting_db_key, result[0].value);
      MqttManagerConfig::_settings_values_cache[key] = result[0].value;
      return result[0].value;
    } else {
      SPDLOG_TRACE("Did not find setting {} in database. Looking for default value.", setting_db_key);

      if (MqttManagerConfig::_setting_key_map.contains(key)) {
        std::string value = MqttManagerConfig::_setting_key_map[key].second;
        SPDLOG_TRACE("Returning default value '{}' for setting '{}'", value, setting_db_key);
        MqttManagerConfig::_settings_values_cache[key] = value;
        return value;
      } else {
        SPDLOG_ERROR("Did not find default setting value for key '{}'. Returning empty string.", setting_db_key);
        return "";
      }
    }
  } catch (std::exception &ex) {
    SPDLOG_ERROR("Caught exception while trying to access database to retrieve setting {}. Exception: {}", setting_db_key, boost::diagnostic_information(ex));
  }
  SPDLOG_TRACE("Did not find setting {}. Returning empty string.", setting_db_key);
  return "";
}

template <>
inline bool MqttManagerConfig::get_setting_with_default(MQTT_MANAGER_SETTING key) {
  std::string value = MqttManagerConfig::get_setting_with_default<std::string>(key);
  boost::to_lower(value);
  return value.compare("true") == 0;
}

template <>
inline int32_t MqttManagerConfig::get_setting_with_default(MQTT_MANAGER_SETTING key) {
  std::string value = MqttManagerConfig::get_setting_with_default<std::string>(key);
  try {
    return std::stoi(value);
  } catch (std::invalid_argument &ex) {
    SPDLOG_ERROR("Caught exception while trying to convert string to integer. Returning 0. Key: {}, Exception: {}", MqttManagerConfig::_setting_key_map[key].first, boost::diagnostic_information(ex));
    return 0;
  } catch (std::out_of_range &ex) {
    SPDLOG_ERROR("Caught exception while trying to convert string to integer. Returning 0. Key: {}, Exception: {}", MqttManagerConfig::_setting_key_map[key].first, boost::diagnostic_information(ex));
    return 0;
  }
}

template <>
inline uint32_t MqttManagerConfig::get_setting_with_default(MQTT_MANAGER_SETTING key) {
  std::string value = MqttManagerConfig::get_setting_with_default<std::string>(key);
  try {
    return std::stoul(value);
  } catch (std::invalid_argument &ex) {
    SPDLOG_ERROR("Caught exception while trying to convert string to unsigned integer. Key: {}, Returning 0. Exception: {}", MqttManagerConfig::_setting_key_map[key].first, boost::diagnostic_information(ex));
    return 0;
  } catch (std::out_of_range &ex) {
    SPDLOG_ERROR("Caught exception while trying to convert string to unsigned integer. Key: {}, Returning 0. Exception: {}", MqttManagerConfig::_setting_key_map[key].first, boost::diagnostic_information(ex));
    return 0;
  }
}

template <>
inline float MqttManagerConfig::get_setting_with_default(MQTT_MANAGER_SETTING key) {
  std::string value = MqttManagerConfig::get_setting_with_default<std::string>(key);
  try {
    return std::stof(value);
  } catch (std::invalid_argument &ex) {
    SPDLOG_ERROR("Caught exception while trying to convert string to float. Returning 0.0f. Key: {}, Exception: {}", MqttManagerConfig::_setting_key_map[key].first, boost::diagnostic_information(ex));
    return 0.0f;
  } catch (std::out_of_range &ex) {
    SPDLOG_ERROR("Caught exception while trying to convert string to float. Returning 0.0f. Key: {}, Exception: {}", MqttManagerConfig::_setting_key_map[key].first, boost::diagnostic_information(ex));
    return 0.0f;
  }
}

#endif // !MQTTMANAGER_CONFIG_HPP
