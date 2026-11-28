#include "mqtt_manager_config.hpp"
#include "light/light.hpp"
#include "openssl/evp.h"
#include "web_helper/WebHelper.hpp"
#include <boost/algorithm/string/case_conv.hpp>
#include <boost/algorithm/string/classification.hpp>
#include <boost/algorithm/string/trim.hpp>
#include <boost/exception/diagnostic_information.hpp>
#include <boost/smart_ptr/shared_ptr.hpp>
#include <boost/stacktrace/stacktrace_fwd.hpp>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <curl/curl.h>
#include <curl/easy.h>
#include <database_manager/database_manager.hpp>
#include <exception>
#include <fmt/core.h>
#include <fstream>
#include <iterator>
#include <mutex>
#include <nlohmann/detail/conversions/to_json.hpp>
#include <nlohmann/detail/exceptions.hpp>
#include <nlohmann/json.hpp>
#include <nlohmann/json_fwd.hpp>
#include <optional>
#include <protobuf/protobuf_mqttmanager.pb.h>
#include <protobuf_general.pb.h>
#include <spdlog/common.h>
#include <spdlog/spdlog.h>
#include <sqlite_orm/sqlite_orm.h>
#include <string>
#include <websocket_server/websocket_server.hpp>

void MqttManagerConfig::load() {
  SPDLOG_TRACE("Loading timezone from /etc/timezone.");
  // Begin by loading timezone
  std::ifstream f("/etc/timezone", std::ios::in | std::ios::binary);
  const size_t file_size = std::filesystem::file_size("/etc/timezone");
  std::string timezone_str(file_size, '\0');
  f.read(timezone_str.data(), file_size);
  f.close();
  boost::algorithm::trim(timezone_str);
  MqttManagerConfig::timezone = timezone_str;
  SPDLOG_INFO("Read timezone {} from /etc/timezone.", timezone_str);
  MqttManagerConfig::timezone_posix_rule = MqttManagerConfig::read_posix_tz_rule(fmt::format("/usr/share/zoneinfo/{}", timezone_str));
  if (MqttManagerConfig::timezone_posix_rule.empty()) {
    SPDLOG_WARN("Could not read a POSIX TZ rule for timezone {}. NSPanels will show the time sent by the manager.", timezone_str);
  } else {
    SPDLOG_INFO("Using POSIX TZ rule {} for timezone {}.", MqttManagerConfig::timezone_posix_rule, timezone_str);
  }

  SPDLOG_DEBUG("Clearing config values cache.");
  MqttManagerConfig::_settings_values_cache.clear();

  {
    SPDLOG_INFO("Loading MQTT Manager settings.");
    std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_settings_mutex);

    const char *is_home_assistant_addon = std::getenv("IS_HOME_ASSISTANT_ADDON");
    if (is_home_assistant_addon != nullptr) {
      if (std::string(is_home_assistant_addon).compare("true") == 0) {
        MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::IS_HOME_ASSISTANT_ADDON, "true");
      } else {
        MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::IS_HOME_ASSISTANT_ADDON, "false");
      }
    } else {
      MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::IS_HOME_ASSISTANT_ADDON, "false");
    }

    std::string turn_on_bevaiour = MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::TURN_ON_BEHAVIOR);
    if (turn_on_bevaiour.compare("color_temp") == 0) {
      MqttManagerConfig::_light_turn_on_behaviour = LightTurnOnBehaviour::COLOR_TEMPERATURE;
    } else if (turn_on_bevaiour.compare("restore") == 0) {
      MqttManagerConfig::_light_turn_on_behaviour = LightTurnOnBehaviour::RESTORE_PREVIOUS;
    } else {
      SPDLOG_WARN("Failed to determine turn on bevaiour for lights, assuming color temp. Value set: {}", turn_on_bevaiour);
      MqttManagerConfig::_light_turn_on_behaviour = LightTurnOnBehaviour::COLOR_TEMPERATURE;
    }
  }

  MqttManagerConfig::update_firmware_checksum();
  MqttManagerConfig::update_tft_checksums();

  MqttManagerConfig::populate_default_and_clean();

  // Notify all listeners that the config has been loaded
  MqttManagerConfig::_config_loaded_listeners();
}

void MqttManagerConfig::populate_default_and_clean() {
  auto settings = database_manager::database.get_all<database_manager::SettingHolder>();
  // Check for set settings that are invalid/unused.
  for (const auto &setting : settings) {
    bool found = false;
    for (const auto &setting_pair : MqttManagerConfig::_setting_key_map) {
      if (setting_pair.second.first == setting.name) {
        found = true;
        break;
      }
    }
    // Cleanup old setting.
    if (!found) {
      SPDLOG_WARN("Removing invalid setting {} from DB.", setting.name);
      database_manager::database.remove<database_manager::SettingHolder>(setting.id);
    }
  }

  // Check if all default settings are set.
  for (const auto &setting : MqttManagerConfig::_setting_key_map) {
    bool found = false;
    for (const auto &setting_pair : settings) {
      if (setting_pair.name == setting.second.first) {
        found = true;
        break;
      }
    }
    if (!found) {
      SPDLOG_INFO("Setting {} not found in DB. Setting default value: '{}'.", setting.second.first, setting.second.second);
      database_manager::SettingHolder new_setting;
      new_setting.name = setting.second.first;
      new_setting.value = setting.second.second;
      database_manager::database.insert(new_setting);
    }
  }
}

void MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING key, std::string value) {
  std::string setting_db_key = MqttManagerConfig::_setting_key_map[key].first;
  SPDLOG_DEBUG("Setting '{}' to value '{}'", setting_db_key, value);

  auto result = database_manager::database.get_all<database_manager::SettingHolder>(sqlite_orm::where(sqlite_orm::c(&database_manager::SettingHolder::name) == setting_db_key));
  if (!result.empty()) {
    result[0].value = value;
    SPDLOG_DEBUG("Set settings key '{}' to value '{}'", setting_db_key, value);
    while (true) {
      try {
        database_manager::database.update(result[0]);
        break;
      } catch (std::exception &ex) {
        SPDLOG_WARN("Caught exception while trying to update setting '{}'. Retrying...", setting_db_key);
        std::this_thread::sleep_for(std::chrono::seconds(1));
      }
    }
  } else {
    SPDLOG_ERROR("Failed to find existing setting for key '{}'. Will create a new key.", setting_db_key);
    database_manager::SettingHolder setting;
    setting.name = setting_db_key;
    setting.value = value;
    while (true) {
      try {
        database_manager::database.insert(setting);
        break;
      } catch (std::exception &ex) {
        SPDLOG_WARN("Caught exception while trying to insert setting '{}'. Retrying...", setting_db_key);
        std::this_thread::sleep_for(std::chrono::seconds(1));
      }
    }
  }

  MqttManagerConfig::_settings_values_cache[key] = value;
}

void MqttManagerConfig::set_nspanel_setting_value(int32_t nspanel_id, std::string key, std::string value) {
  using namespace sqlite_orm;
  SPDLOG_DEBUG("Setting '{}' to value '{}' for NSPanel with ID {}", key, value, nspanel_id);

  auto result = database_manager::database.get_all<database_manager::NSPanelSettingHolder>(sqlite_orm::where(sqlite_orm::c(&database_manager::NSPanelSettingHolder::name) = key) and sqlite_orm::c(&database_manager::NSPanelSettingHolder::nspanel_id) == nspanel_id);
  if (!result.empty()) {
    result[0].value = value;
    database_manager::database.update(result[0]);
  } else {
    database_manager::NSPanelSettingHolder setting;
    setting.nspanel_id = nspanel_id;
    setting.name = key;
    setting.value = value;
    database_manager::database.insert(setting);
  }
}

bool MqttManagerConfig::is_home_assistant_addon() {
  return MqttManagerConfig::get_setting_with_default<bool>(MQTT_MANAGER_SETTING::IS_HOME_ASSISTANT_ADDON);
}

LightTurnOnBehaviour MqttManagerConfig::get_light_turn_on_behaviour() {
  return MqttManagerConfig::_light_turn_on_behaviour;
}

void MqttManagerConfig::update_firmware_checksum() {
  std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_md5_checksum_files_mutex);
  SPDLOG_INFO("Updating/calculating MD5 checksums for all firmware files.");

  for (const NSPanelModelInfo &info : NSPANEL_MODELS) {
    const std::string id(info.id);
    const std::string slot = fmt::format("{}{}/", MqttManagerConfig::firmware_directory, id);

    // Update firmware checksum
    const std::string firmware_warning = fmt::format("MD5 checksum for {} firmware was not able to be calculated.", id);
    auto firmware_checksum = MqttManagerConfig::_get_file_md5_checksum(slot + "firmware.bin");
    if (firmware_checksum.has_value()) {
      MqttManagerConfig::_md5_checksum_firmware[id] = firmware_checksum.value();
      WebsocketServer::remove_warning(firmware_warning);
      SPDLOG_INFO("Firmware checksum for {}: {}", id, firmware_checksum.value());
      auto build_info = MqttManagerConfig::_read_firmware_build_info(slot + "firmware.bin");
      if (build_info) {
        SPDLOG_INFO("Firmware build for {}: version {}, image sha256 {}", id, build_info->version, build_info->image_sha256);
        MqttManagerConfig::_firmware_build_info[id] = *build_info;
      } else {
        MqttManagerConfig::_firmware_build_info.erase(id);
      }
    } else {
      MqttManagerConfig::_md5_checksum_firmware.erase(id);
      MqttManagerConfig::_firmware_build_info.erase(id);
      if (info.firmware_bundled) {
        WebsocketServer::register_warning(WebsocketServer::ActiveWarningLevel::ERROR, firmware_warning);
        SPDLOG_ERROR("Failed to calculate checksum for {} firmware!", id);
      } else {
        SPDLOG_INFO("No {} firmware staged.", id);
      }
    }

    // Update LittleFS checksum
    const std::string littlefs_warning = fmt::format("MD5 checksum for {} littlefs/data file was not able to be calculated.", id);
    auto littlefs_checksum = MqttManagerConfig::_get_file_md5_checksum(slot + "data_file.bin");
    if (littlefs_checksum.has_value()) {
      MqttManagerConfig::_md5_checksum_littlefs[id] = littlefs_checksum.value();
      WebsocketServer::remove_warning(littlefs_warning);
      SPDLOG_INFO("LittleFS checksum for {}: {}", id, littlefs_checksum.value());
    } else {
      MqttManagerConfig::_md5_checksum_littlefs.erase(id);
      if (info.firmware_bundled) {
        WebsocketServer::register_warning(WebsocketServer::ActiveWarningLevel::ERROR, littlefs_warning);
        SPDLOG_ERROR("Failed to calculate checksum for {} LittleFS!", id);
      } else {
        SPDLOG_INFO("No {} LittleFS image staged.", id);
      }
    }
  }
}

void MqttManagerConfig::update_tft_checksums() {
  std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_md5_checksum_files_mutex);
  SPDLOG_INFO("Updating/calculating MD5 checksums for the terminal .tft GUI files.");

  // The terminal TFTs, which every panel runs: an uploaded one if there is one, else the one the image ships
  // (as Django's display_mode.staged_terminal_tft_file() picks). A panel with neither gets "no checksum"
  // from the web server and is not offered a GUI update.
  for (bool us_layout : {true, false}) {
    std::string layout = us_layout ? "us" : "eu";
    std::string &checksum = us_layout ? MqttManagerConfig::_md5_checksum_terminal_us : MqttManagerConfig::_md5_checksum_terminal_eu;
    std::string uploaded = fmt::format("{}/{}/gui.tft", MqttManagerConfig::terminal_tft_directory, layout);
    std::string bundled = fmt::format("{}/{}/gui.tft", MqttManagerConfig::bundled_terminal_tft_directory, layout);
    std::string path = uploaded;
    auto file_checksum = MqttManagerConfig::_get_file_md5_checksum(uploaded);
    if (!file_checksum.has_value()) {
      path = bundled;
      file_checksum = MqttManagerConfig::_get_file_md5_checksum(bundled);
    }
    checksum = file_checksum.value_or("");
    (us_layout ? MqttManagerConfig::_md5_checksum_bundled_terminal_us : MqttManagerConfig::_md5_checksum_bundled_terminal_eu) = MqttManagerConfig::_get_file_md5_checksum(bundled).value_or("");
    if (file_checksum.has_value()) {
      SPDLOG_INFO("{} terminal TFT checksum: {} ({})", us_layout ? "US" : "EU", *file_checksum, path == uploaded ? "uploaded" : "bundled");
    } else {
      SPDLOG_INFO("No {} terminal TFT at {} or {}.", us_layout ? "US" : "EU", uploaded, bundled);
    }
  }
}

std::expected<std::string, bool> MqttManagerConfig::get_terminal_tft_checksum(bool us_layout) {
  std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_md5_checksum_files_mutex);
  const std::string &checksum = us_layout ? MqttManagerConfig::_md5_checksum_terminal_us : MqttManagerConfig::_md5_checksum_terminal_eu;
  if (checksum.empty()) {
    return std::unexpected(false);
  }
  return checksum;
}

bool MqttManagerConfig::is_known_terminal_tft_md5(const std::string &md5) {
  if (md5.empty()) {
    return false;
  }
  {
    std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_md5_checksum_files_mutex);
    for (const std::string *known : {&MqttManagerConfig::_md5_checksum_terminal_us, &MqttManagerConfig::_md5_checksum_terminal_eu, &MqttManagerConfig::_md5_checksum_bundled_terminal_us, &MqttManagerConfig::_md5_checksum_bundled_terminal_eu}) {
      if (!known->empty() && *known == md5) {
        return true;
      }
    }
  }
  try {
    return !database_manager::database
                .get_all<database_manager::TftUpload>(sqlite_orm::where(sqlite_orm::c(&database_manager::TftUpload::md5) == md5 && sqlite_orm::c(&database_manager::TftUpload::kind) == std::string("terminal")), sqlite_orm::limit(1))
                .empty();
  } catch (const std::exception &e) {
    SPDLOG_WARN("Failed to look up TFT upload history for {}: {}", md5, e.what());
    return false;
  }
}

std::optional<std::string> MqttManagerConfig::_get_file_md5_checksum(std::string file_path) {
  std::ifstream file(file_path, std::ifstream::binary);
  if (!file) {
    return std::nullopt;
  }

  EVP_MD_CTX *mdctx;
  unsigned char *md5_digest;
  unsigned int md5_digest_len = EVP_MD_size(EVP_md5());

  // MD5_Init
  mdctx = EVP_MD_CTX_new();
  EVP_DigestInit_ex(mdctx, EVP_md5(), NULL);

  // MD5_Update
  // char buffer[1024];
  // while (file.read(buffer, 1024)) {
  //   EVP_DigestUpdate(mdctx, buffer, file.gcount());
  // }

  unsigned char buffer[8192];
  while (file.read(reinterpret_cast<char *>(buffer), sizeof(buffer)) || file.gcount() > 0) {
    if (EVP_DigestUpdate(mdctx, buffer, file.gcount()) != 1) {
      EVP_MD_CTX_free(mdctx);
      return "";
    }
  }

  // MD5_Final
  md5_digest = (unsigned char *)OPENSSL_malloc(md5_digest_len);
  EVP_DigestFinal_ex(mdctx, md5_digest, &md5_digest_len);
  EVP_MD_CTX_free(mdctx);

  // char tmp[3] = {0};
  // std::string return_string;
  // for (int i = 0; i < md5_digest_len; i++) {
  //   sprintf(tmp, "%02x", md5_digest[i]);
  //   return_string.append(tmp);
  // }

  std::stringstream ss;
  ss << std::hex << std::uppercase << std::setfill('0');
  for (int i = 0; i < EVP_MD_size(EVP_md5()); i++) {
    ss << std::setw(2) << (int)md5_digest[i];
  }

  EVP_cleanup();
  return boost::algorithm::to_lower_copy(ss.str()); // Convert to lowercase as the md5 checksum calculated in Django is calculated with lower case latters.
}

std::expected<std::string, bool> MqttManagerConfig::get_firmware_checksum(MQTT_MANAGER_NSPANEL_MODEL model) {
  std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_md5_checksum_files_mutex);
  auto checksum = MqttManagerConfig::_md5_checksum_firmware.find(std::string(nspanel_model_id(model)));
  if (checksum == MqttManagerConfig::_md5_checksum_firmware.end() || checksum->second.empty()) {
    return std::unexpected(false);
  }
  return checksum->second;
}

namespace {
// esp_app_desc_t sits at offset 32 of an app image (after the 24-byte header and the 8-byte first segment header).
constexpr size_t APP_DESC_OFFSET = 32;
constexpr uint32_t APP_DESC_MAGIC = 0xABCD5432;
constexpr size_t APP_DESC_SIZE = 256;
constexpr size_t SHA256_SIZE = 32;

// A NUL-padded fixed-size C string field.
std::string fixed_string(const std::string &data, size_t offset, size_t size) {
  std::string value = data.substr(offset, size);
  value.resize(strnlen(value.c_str(), value.size()));
  return value;
}

std::string hex_string(const std::string &data, size_t offset, size_t size) {
  static const char *digits = "0123456789abcdef";
  std::string hex;
  for (size_t i = offset; i < offset + size; i++) {
    const unsigned char byte = static_cast<unsigned char>(data[i]);
    hex.push_back(digits[byte >> 4]);
    hex.push_back(digits[byte & 0x0f]);
  }
  return hex;
}

const char *chip_name_from_id(uint16_t chip_id) {
  switch (chip_id) {
  case 0x0000:
    return "esp32";
  case 0x0009:
    return "esp32s3";
  case 0x0012:
    return "esp32p4";
  default:
    return "";
  }
}
} // namespace

std::optional<FirmwareBuildInfo> MqttManagerConfig::parse_app_image(const std::string &head, const std::string &tail) {
  if (head.size() < APP_DESC_OFFSET + APP_DESC_SIZE || static_cast<unsigned char>(head[0]) != 0xE9) {
    return std::nullopt;
  }
  uint32_t magic = 0;
  std::memcpy(&magic, head.data() + APP_DESC_OFFSET, sizeof(magic));
  if (magic != APP_DESC_MAGIC) {
    return std::nullopt;
  }

  FirmwareBuildInfo info;
  const size_t desc = APP_DESC_OFFSET;
  info.version = fixed_string(head, desc + 16, 32);
  info.project = fixed_string(head, desc + 48, 32);
  const std::string time = fixed_string(head, desc + 80, 16);
  const std::string date = fixed_string(head, desc + 96, 16);
  info.build_date = date + " " + time;
  info.idf_version = fixed_string(head, desc + 112, 32);
  info.elf_sha256 = hex_string(head, desc + 144, SHA256_SIZE);
  const uint16_t chip_id = static_cast<uint16_t>(static_cast<unsigned char>(head[12]) | (static_cast<unsigned char>(head[13]) << 8));
  info.chip = chip_name_from_id(chip_id);
  const bool hash_appended = head[23] != 0;
  if (hash_appended && tail.size() == SHA256_SIZE) {
    info.image_sha256 = hex_string(tail, 0, SHA256_SIZE);
  }
  return info;
}

std::optional<FirmwareBuildInfo> MqttManagerConfig::_read_firmware_build_info(const std::string &file_path) {
  std::ifstream file(file_path, std::ifstream::binary | std::ifstream::ate);
  if (!file) {
    return std::nullopt;
  }
  const std::streamoff size = file.tellg();
  if (size < static_cast<std::streamoff>(APP_DESC_OFFSET + APP_DESC_SIZE + SHA256_SIZE)) {
    return std::nullopt;
  }
  std::string head(APP_DESC_OFFSET + APP_DESC_SIZE, '\0');
  std::string tail(SHA256_SIZE, '\0');
  file.seekg(0);
  file.read(head.data(), head.size());
  file.seekg(size - static_cast<std::streamoff>(SHA256_SIZE));
  file.read(tail.data(), tail.size());
  if (!file) {
    return std::nullopt;
  }
  return MqttManagerConfig::parse_app_image(head, tail);
}

std::expected<FirmwareBuildInfo, bool> MqttManagerConfig::get_firmware_build_info(MQTT_MANAGER_NSPANEL_MODEL model) {
  std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_md5_checksum_files_mutex);
  auto info = MqttManagerConfig::_firmware_build_info.find(std::string(nspanel_model_id(model)));
  if (info == MqttManagerConfig::_firmware_build_info.end()) {
    return std::unexpected(false);
  }
  return info->second;
}

std::expected<std::string, bool> MqttManagerConfig::get_littlefs_checksum(MQTT_MANAGER_NSPANEL_MODEL model) {
  std::lock_guard<std::mutex> lock_guard(MqttManagerConfig::_md5_checksum_files_mutex);
  auto checksum = MqttManagerConfig::_md5_checksum_littlefs.find(std::string(nspanel_model_id(model)));
  if (checksum == MqttManagerConfig::_md5_checksum_littlefs.end() || checksum->second.empty()) {
    return std::unexpected(false);
  }
  return checksum->second;
}

std::string MqttManagerConfig::read_posix_tz_rule(const std::string &tzif_path) {
  try {
    std::ifstream file(tzif_path, std::ios::in | std::ios::binary);
    if (!file) {
      return "";
    }
    std::string content((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());

    // Version 2 and later files end with the rule between two newlines (RFC 8536, section 3.3).
    // Version 1 files have a zero version byte and no rule.
    if (content.size() < 5 || content.compare(0, 4, "TZif") != 0 || content[4] < '2' || content.back() != '\n') {
      return "";
    }
    size_t rule_start = content.rfind('\n', content.size() - 2);
    if (rule_start == std::string::npos) {
      return "";
    }
    return content.substr(rule_start + 1, content.size() - rule_start - 2);
  } catch (std::exception &ex) {
    SPDLOG_WARN("Caught exception while reading POSIX TZ rule from '{}': {}", tzif_path, ex.what());
    return "";
  }
}

// TESTING
#if defined(TEST_MODE) && TEST_MODE == 1
#include <gtest/gtest.h>

TEST(MqttManagerConfigTest, verify_all_settings_exists_and_have_db_key) {
  for (int i = 0; i < static_cast<int>(MQTT_MANAGER_SETTING::LAST); i++) {
    MQTT_MANAGER_SETTING setting = static_cast<MQTT_MANAGER_SETTING>(i);
    bool found = MqttManagerConfig::_setting_key_map.contains(setting);
    EXPECT_TRUE(found) << "Setting (enum value) " << i << " not found in the settings list. Cannot test if it has a setting key.";
    if (found) {
      EXPECT_TRUE(!MqttManagerConfig::_setting_key_map[setting].first.empty()) << "Setting (enum value) " << i << " does not name a DB key.";
    }
  }
}

TEST(MqttManagerConfigTest, verify_settings_cache_is_used) {
  bool value = MqttManagerConfig::get_setting_with_default<bool>(MQTT_MANAGER_SETTING::CLOCK_US_STYLE);
  EXPECT_TRUE(MqttManagerConfig::_settings_values_cache.contains(MQTT_MANAGER_SETTING::CLOCK_US_STYLE));
}

#endif
