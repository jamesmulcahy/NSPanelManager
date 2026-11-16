#include "protobuf_nspanel.pb.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <ctime>
#include <mutex>
#include <nlohmann/json.hpp>
#include <optional>
#include <string>
#include <thread>
#include <vector>
#ifndef MQTT_MANAGER_ENERGY
#define MQTT_MANAGER_ENERGY

// MQTTManagerEnergy's types, outside the class: its static members are initialised with them, which
// a nested type's default member initialisers do not allow before the class ends.
enum class EnergyPowerSource { OFF, HOME_ASSISTANT_ENERGY, ENTITIES };
enum class EnergyPriceSource { OFF, HOME_ASSISTANT_ENERGY, ENTITY, FIXED };
enum class EnergyLightsSource { OFF, HOME_ASSISTANT, NSPANELMANAGER };

struct EnergySettings {
  EnergyPowerSource power_source = EnergyPowerSource::HOME_ASSISTANT_ENERGY;
  std::vector<std::string> power_entity_ids;
  EnergyPriceSource price_source = EnergyPriceSource::HOME_ASSISTANT_ENERGY;
  std::string price_entity_id;
  double price_per_kwh = 0;
  EnergyLightsSource lights_source = EnergyLightsSource::HOME_ASSISTANT;
  std::vector<std::string> exclude_labels;
  int alert_threshold = 15; // 0: never alert

  bool operator==(const EnergySettings &) const = default;
};

// Where the values come from, once the settings and Home Assistant's Energy settings are combined.
struct EnergySources {
  bool resolved = false;                   // False until the Energy settings needed have been read
  std::vector<std::string> power_entities; // Empty: power not configured
  std::string price_entity;                // A price entity, read by the energy template
  std::optional<double> fixed_price;       // Or a fixed price per kWh

  bool power_configured() const { return !power_entities.empty(); }
  bool price_configured() const { return !price_entity.empty() || fixed_price.has_value(); }
  bool operator==(const EnergySources &) const = default;
};

// The latest values. nullopt: unavailable.
struct EnergyReadings {
  std::optional<double> power_watts;
  std::optional<double> price_per_kwh; // From the price entity
  std::optional<int> lights_on;
};

// The house's power draw, what a day would cost at that draw, and the number of lights on, for the panels' screensaver
// energy card on nspanel/mqttmanager_<manager address>/status/energy.
//
// Home Assistant does the work: one render_template subscription sums the power sensors (and reads a price entity),
// another counts the lights that are on. Where the power sensors and price come from is read from Home Assistant's
// Energy settings (energy/get_prefs) unless the user picked them in the manager.
class MQTTManagerEnergy {
public:
  using PowerSource = EnergyPowerSource;
  using PriceSource = EnergyPriceSource;
  using LightsSource = EnergyLightsSource;
  using Settings = EnergySettings;
  using Sources = EnergySources;
  using Readings = EnergyReadings;

  /**
   * Load config and start the thread that keeps the sources up to date and publishes.
   */
  static void start();

  /**
   * Load new values from config and resolve the sources again.
   */
  static void reload_config();

  /**
   * Trigger for Home Assistant having (re)connected.
   */
  static void home_assistant_authenticated_callback();

  // The pure parts. Each depends on nothing but its arguments.

  static Settings settings_from_config();

  /**
   * Combine the settings with Home Assistant's Energy settings.
   *
   * @param energy_prefs The result of energy/get_prefs, or nullptr if they were not read (or not needed).
   */
  static Sources resolve(const Settings &settings, const nlohmann::json *energy_prefs);

  // True if resolve() needs energy/get_prefs.
  static bool needs_energy_prefs(const Settings &settings);

  /**
   * The template that sums the power sensors (in W, whatever unit each reports) and reads the price entity. It renders
   * to {"power_w": <int or null>, "price": <number or null>}; power_w is null if any sensor has no number.
   * Empty if there is nothing to read.
   */
  static std::string energy_template(const std::vector<std::string> &power_entities, const std::string &price_entity);

  /**
   * The template that counts the lights that are on: light.* entities, without groups (which would count their members
   * twice), hidden entities and entities with any of the labels.
   */
  static std::string lights_template(const std::vector<std::string> &exclude_labels);

  // "USD" -> "$". Empty for a code it does not know; the panel then shows the code.
  static std::string currency_symbol(const std::string &currency);

  /**
   * The update for the panels.
   *
   * @param ha_connected False marks every part that comes from Home Assistant as unavailable.
   */
  static NSPanelEnergyUpdate build_update(const Settings &settings, const Sources &sources, const Readings &readings, bool ha_connected, const std::string &currency, std::time_t now);

  // The value of a render_template event: its "result", parsed if Home Assistant sent it as text. Null on an error.
  static nlohmann::json template_result(const nlohmann::json &event);

  // Updates closer together than this are held back and sent as one.
  static constexpr std::chrono::seconds MIN_PUBLISH_INTERVAL{15};
  // How often the Energy settings are read again (they have no change event), and the lights template is
  // resubscribed so that label changes count.
  static constexpr std::chrono::minutes RESOLVE_INTERVAL{10};

#if defined(TEST_MODE) && TEST_MODE == 1
  // Resolve as the thread would: read config, ask Home Assistant, (re)subscribe.
  static void test_resolve() { MQTTManagerEnergy::_settings_changed(); MQTTManagerEnergy::_resolve(true); }

  // Publish whatever is pending now, without waiting for the rate limit.
  static void test_flush() {
    {
      std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
      MQTTManagerEnergy::_last_publish = {};
    }
    MQTTManagerEnergy::_publish_if_changed(std::time(nullptr));
  }

  static long test_power_subscription() { return MQTTManagerEnergy::_power_subscription; }
  static long test_lights_subscription() { return MQTTManagerEnergy::_lights_subscription; }

  // Forget everything: subscriptions, readings and what has been published.
  static void test_reset();
#endif

private:
  static inline std::thread _instance;
  static inline std::mutex _mutex;
  static inline std::condition_variable _cv;
  static inline bool _resolve_requested = false;
  static inline std::chrono::steady_clock::time_point _next_resolve;

  // Guarded by _mutex.
  static inline Settings _settings;
  static inline Sources _sources;
  static inline Readings _readings;
  static inline std::string _currency;
  static inline std::string _energy_template_text;
  static inline std::string _lights_template_text;
  static inline long _power_subscription = 0;
  static inline long _lights_subscription = 0;
  static inline std::string _last_published; // Without generated_at
  static inline std::chrono::steady_clock::time_point _last_publish;
  static inline bool _publish_pending = false;
  static inline bool _ha_connected = false;

  // True once the retained topic has been cleared, until something is published again.
  static inline std::atomic<bool> _topic_cleared = false;

  static void _run_thread();
  static void _request_resolve();
  static std::string _topic();

  static void _settings_changed();
  // Read the currency and (if needed) the Energy settings, then apply them. `refresh_lights`: resubscribe the lights
  // template even if its text is unchanged, so that label changes count.
  static void _resolve(bool refresh_lights);
  static void _apply_sources(const Sources &sources, bool refresh_lights);
  static void _count_nspanelmanager_lights();

  static void _on_energy_event(bool success, const nlohmann::json &event);
  static void _on_lights_event(bool success, const nlohmann::json &event);

  // Publish now, or mark it pending if the last publish was too recent.
  static void _publish_if_changed(std::time_t now);
};

#endif // !MQTT_MANAGER_ENERGY
