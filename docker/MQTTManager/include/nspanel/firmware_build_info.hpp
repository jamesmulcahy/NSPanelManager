#ifndef MQTT_MANAGER_FIRMWARE_BUILD_INFO
#define MQTT_MANAGER_FIRMWARE_BUILD_INFO
#include <nlohmann/json.hpp>
#include <string>

/**
 * Which firmware build a panel runs, or a staged firmware.bin is. Panels report it in register_request ("build") and in
 * the status report (BuildInfo); for a staged image it is read from the image itself. Every field is empty when unknown.
 */
struct FirmwareBuildInfo {
  std::string version;       // esp_app_desc_t.version
  std::string project;       // esp_app_desc_t.project_name
  std::string build_date;    // esp_app_desc_t.date + " " + time
  std::string idf_version;   // esp_app_desc_t.idf_ver
  std::string elf_sha256;    // 64 lowercase hex characters
  std::string image_sha256;  // The image's appended SHA-256, 64 lowercase hex characters
  std::string chip;          // "esp32", "esp32s3" or "esp32p4"
  std::string ota_partition; // Panels only: the running partition's label

  bool operator==(const FirmwareBuildInfo &other) const = default;
  nlohmann::json to_json() const {
    return nlohmann::json{
        {"version", this->version},
        {"project", this->project},
        {"build_date", this->build_date},
        {"idf_version", this->idf_version},
        {"elf_sha256", this->elf_sha256},
        {"image_sha256", this->image_sha256},
        {"chip", this->chip},
        {"ota_partition", this->ota_partition},
    };
  }
};

#endif
