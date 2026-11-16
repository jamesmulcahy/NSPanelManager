#include "energy.hpp"
#include "entity_manager/entity_manager.hpp"
#include "home_assistant_manager/home_assistant_manager.hpp"
#include "light/light.hpp"
#include "mqtt_manager/mqtt_manager.hpp"
#include "mqtt_manager_config/mqtt_manager_config.hpp"
#include <algorithm>
#include <boost/algorithm/string.hpp>
#include <cmath>
#include <cstdlib>
#include <fmt/core.h>
#include <protobuf_nspanel.pb.h>
#include <spdlog/spdlog.h>
#include <unordered_map>
#include <utility>

namespace {

std::vector<std::string> split_list(const std::string &setting) {
  std::vector<std::string> parts;
  boost::algorithm::split(parts, setting, boost::algorithm::is_any_of(","));
  std::vector<std::string> items;
  for (std::string &part : parts) {
    boost::algorithm::trim(part);
    if (!part.empty() && std::find(items.begin(), items.end(), part) == items.end()) {
      items.push_back(part);
    }
  }
  return items;
}

std::string setting(MQTT_MANAGER_SETTING key) {
  std::string value = MqttManagerConfig::get_setting_with_default<std::string>(key);
  boost::algorithm::trim(value);
  boost::algorithm::to_lower(value);
  return value;
}

// A list of strings as a Jinja list literal. JSON strings are valid Jinja strings; ASCII-only so nothing is mangled.
std::string jinja_list(const std::vector<std::string> &items) {
  return nlohmann::json(items).dump(-1, ' ', true);
}

std::string jinja_string(const std::string &text) {
  return nlohmann::json(text).dump(-1, ' ', true);
}

// A JSON number from a template result, or nullopt.
std::optional<double> number(const nlohmann::json &value) {
  if (value.is_number()) {
    double result = value.get<double>();
    if (std::isfinite(result)) {
      return result;
    }
  }
  return std::nullopt;
}

} // namespace

MQTTManagerEnergy::Settings MQTTManagerEnergy::settings_from_config() {
  Settings settings;
  bool home_assistant = !MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS).empty();

  std::string power = setting(MQTT_MANAGER_SETTING::ENERGY_POWER_SOURCE);
  if (!home_assistant || power.compare("off") == 0) {
    settings.power_source = PowerSource::OFF;
  } else if (power.compare("entities") == 0) {
    settings.power_source = PowerSource::ENTITIES;
  } else {
    settings.power_source = PowerSource::HOME_ASSISTANT_ENERGY;
  }
  settings.power_entity_ids = split_list(MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::ENERGY_POWER_ENTITY_IDS));

  std::string price = setting(MQTT_MANAGER_SETTING::ENERGY_PRICE_SOURCE);
  if (price.compare("off") == 0) {
    settings.price_source = PriceSource::OFF;
  } else if (price.compare("entity") == 0) {
    settings.price_source = PriceSource::ENTITY;
  } else if (price.compare("fixed") == 0) {
    settings.price_source = PriceSource::FIXED;
  } else {
    settings.price_source = PriceSource::HOME_ASSISTANT_ENERGY;
  }
  settings.price_entity_id = MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::ENERGY_PRICE_ENTITY_ID);
  boost::algorithm::trim(settings.price_entity_id);
  std::string price_per_kwh = MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::ENERGY_PRICE_PER_KWH);
  char *end = nullptr;
  double parsed = std::strtod(price_per_kwh.c_str(), &end);
  settings.price_per_kwh = (end != price_per_kwh.c_str() && std::isfinite(parsed) && parsed > 0) ? parsed : 0;

  std::string lights = setting(MQTT_MANAGER_SETTING::LIGHTS_ON_SOURCE);
  if (lights.compare("off") == 0) {
    settings.lights_source = LightsSource::OFF;
  } else if (lights.compare("nspanelmanager") == 0) {
    settings.lights_source = LightsSource::NSPANELMANAGER;
  } else {
    settings.lights_source = home_assistant ? LightsSource::HOME_ASSISTANT : LightsSource::OFF;
  }
  settings.exclude_labels = split_list(MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::LIGHTS_ON_EXCLUDE_LABELS));
  settings.alert_threshold = std::max<int32_t>(0, MqttManagerConfig::get_setting_with_default<int32_t>(MQTT_MANAGER_SETTING::LIGHTS_ON_ALERT_THRESHOLD));
  return settings;
}

bool MQTTManagerEnergy::needs_energy_prefs(const Settings &settings) {
  return settings.power_source == PowerSource::HOME_ASSISTANT_ENERGY || settings.price_source == PriceSource::HOME_ASSISTANT_ENERGY;
}

MQTTManagerEnergy::Sources MQTTManagerEnergy::resolve(const Settings &settings, const nlohmann::json *energy_prefs) {
  Sources sources;
  sources.resolved = !MQTTManagerEnergy::needs_energy_prefs(settings) || energy_prefs != nullptr;

  // The grid sources of the Energy settings, in order.
  std::vector<nlohmann::json> grids;
  if (energy_prefs != nullptr && energy_prefs->is_object() && energy_prefs->contains("energy_sources") && (*energy_prefs)["energy_sources"].is_array()) {
    for (const nlohmann::json &source : (*energy_prefs)["energy_sources"]) {
      if (source.is_object() && source.value("type", "").compare("grid") == 0) {
        grids.push_back(source);
      }
    }
  }

  if (settings.power_source == PowerSource::ENTITIES) {
    sources.power_entities = settings.power_entity_ids;
  } else if (settings.power_source == PowerSource::HOME_ASSISTANT_ENERGY) {
    for (const nlohmann::json &grid : grids) {
      // Home Assistant copies power_config.stat_rate to stat_rate. A grid with separate import and export sensors
      // (stat_rate_from/stat_rate_to) or an inverted sensor has no single net sensor to sum.
      std::string rate;
      if (grid.contains("stat_rate") && grid["stat_rate"].is_string()) {
        rate = grid["stat_rate"].get<std::string>();
      } else if (grid.contains("power_config") && grid["power_config"].is_object() && grid["power_config"].contains("stat_rate") && grid["power_config"]["stat_rate"].is_string()) {
        rate = grid["power_config"]["stat_rate"].get<std::string>();
      }
      if (rate.empty()) {
        SPDLOG_DEBUG("Energy: grid source '{}' has no power sensor in Home Assistant's Energy settings.", grid.value("name", grid.value("stat_energy_from", "")));
      } else if (std::find(sources.power_entities.begin(), sources.power_entities.end(), rate) == sources.power_entities.end()) {
        sources.power_entities.push_back(rate);
      }
    }
  }

  if (settings.price_source == PriceSource::ENTITY) {
    sources.price_entity = settings.price_entity_id;
  } else if (settings.price_source == PriceSource::FIXED) {
    if (settings.price_per_kwh > 0) {
      sources.fixed_price = settings.price_per_kwh;
    }
  } else if (settings.price_source == PriceSource::HOME_ASSISTANT_ENERGY) {
    for (const nlohmann::json &grid : grids) {
      if (grid.contains("entity_energy_price") && grid["entity_energy_price"].is_string() && !grid["entity_energy_price"].get<std::string>().empty()) {
        sources.price_entity = grid["entity_energy_price"].get<std::string>();
        break;
      }
      if (grid.contains("number_energy_price") && grid["number_energy_price"].is_number()) {
        sources.fixed_price = grid["number_energy_price"].get<double>();
        break;
      }
    }
  }
  return sources;
}

std::string MQTTManagerEnergy::energy_template(const std::vector<std::string> &power_entities, const std::string &price_entity) {
  if (power_entities.empty() && price_entity.empty()) {
    return "";
  }
  std::string text = fmt::format("{{%- set ids = {} -%}}\n", jinja_list(power_entities));
  text.append("{%- set scale = {'mW': 0.001, 'W': 1, 'kW': 1000, 'MW': 1000000, 'GW': 1000000000} -%}\n"
              "{%- set ns = namespace(w=0, ok=true) -%}\n"
              "{%- for id in ids -%}\n"
              "  {%- set v = states(id) -%}\n"
              "  {%- set u = state_attr(id, 'unit_of_measurement') -%}\n"
              "  {%- if is_number(v) and u in scale -%}\n"
              "    {%- set ns.w = ns.w + (v | float) * scale[u] -%}\n"
              "  {%- else -%}\n"
              "    {%- set ns.ok = false -%}\n"
              "  {%- endif -%}\n"
              "{%- endfor -%}\n"
              "{%- set price = none -%}\n");
  if (!price_entity.empty()) {
    std::string id = jinja_string(price_entity);
    text.append(fmt::format("{{%- set p = states({0}) -%}}\n"
                            "{{%- if is_number(p) -%}}\n"
                            "  {{%- set price = p | float -%}}\n"
                            "  {{%- if (state_attr({0}, 'unit_of_measurement') or '') is search('/MWh$') -%}}\n"
                            "    {{%- set price = price / 1000 -%}}\n"
                            "  {{%- endif -%}}\n"
                            "{{%- endif -%}}\n",
                            id));
  }
  text.append("{{ {'power_w': (ns.w | round(0) | int) if (ns.ok and ids | count > 0) else none, 'price': price} | to_json }}");
  return text;
}

std::string MQTTManagerEnergy::lights_template(const std::vector<std::string> &exclude_labels) {
  return fmt::format("{{%- set excluded = {} | map('label_entities') | sum(start=[]) -%}}\n"
                     "{{{{ states.light\n"
                     "   | selectattr('state', 'eq', 'on')\n"
                     "   | rejectattr('attributes.entity_id', 'defined')\n"
                     "   | rejectattr('attributes.is_hue_group', 'true')\n"
                     "   | rejectattr('entity_id', 'in', excluded)\n"
                     "   | rejectattr('entity_id', 'is_hidden_entity')\n"
                     "   | list | count }}}}",
                     jinja_list(exclude_labels));
}

std::string MQTTManagerEnergy::currency_symbol(const std::string &currency) {
  static const std::unordered_map<std::string, std::string> symbols = {
      {"USD", "$"}, {"CAD", "$"}, {"AUD", "$"}, {"NZD", "$"}, {"MXN", "$"}, {"SGD", "$"}, {"HKD", "$"},
      {"EUR", "€"}, {"GBP", "£"}, {"JPY", "¥"}, {"CNY", "¥"}, {"INR", "₹"},
  };
  std::string code = boost::algorithm::to_upper_copy(currency);
  auto it = symbols.find(code);
  return it == symbols.end() ? "" : it->second;
}

NSPanelEnergyUpdate MQTTManagerEnergy::build_update(const Settings &settings, const Sources &sources, const Readings &readings, bool ha_connected, const std::string &currency, std::time_t now) {
  NSPanelEnergyUpdate update;
  update.set_generated_at(now > 0 ? now : 1); // Never 0, so that an update never serialises to an empty payload.

  // Power
  std::optional<int> watts;
  if (settings.power_source == PowerSource::OFF || (sources.resolved && !sources.power_configured())) {
    update.set_power(NSPanelEnergyUpdate_Availability_NOT_CONFIGURED);
  } else if (!sources.resolved || !ha_connected || !readings.power_watts.has_value()) {
    update.set_power(NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  } else {
    watts = static_cast<int>(std::lround(*readings.power_watts / 10.0) * 10);
    update.set_power(NSPanelEnergyUpdate_Availability_AVAILABLE);
    update.set_power_watts(*watts);
  }

  // Cost
  if (update.power() == NSPanelEnergyUpdate_Availability_NOT_CONFIGURED || settings.price_source == PriceSource::OFF || (sources.resolved && !sources.price_configured())) {
    update.set_cost(NSPanelEnergyUpdate_Availability_NOT_CONFIGURED);
  } else {
    std::optional<double> price = sources.fixed_price;
    if (!sources.price_entity.empty()) {
      price = ha_connected ? readings.price_per_kwh : std::nullopt;
    }
    if (watts.has_value() && price.has_value()) {
      double cost = *watts / 1000.0 * *price * 24.0;
      update.set_cost(NSPanelEnergyUpdate_Availability_AVAILABLE);
      update.set_cost_per_day(std::round(cost * 100.0) / 100.0); // Whole cents: finer changes are not worth sending
    } else {
      update.set_cost(NSPanelEnergyUpdate_Availability_UNAVAILABLE);
    }
    update.set_currency(currency);
    update.set_currency_symbol(MQTTManagerEnergy::currency_symbol(currency));
  }

  // Lights
  if (settings.lights_source == LightsSource::OFF) {
    update.set_lights(NSPanelEnergyUpdate_Availability_NOT_CONFIGURED);
  } else if ((settings.lights_source == LightsSource::HOME_ASSISTANT && !ha_connected) || !readings.lights_on.has_value()) {
    update.set_lights(NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  } else {
    update.set_lights(NSPanelEnergyUpdate_Availability_AVAILABLE);
    update.set_lights_on(*readings.lights_on);
    update.set_lights_alert(settings.alert_threshold > 0 && *readings.lights_on >= settings.alert_threshold);
  }
  return update;
}

nlohmann::json MQTTManagerEnergy::template_result(const nlohmann::json &event) {
  if (!event.is_object() || event.contains("error") || !event.contains("result")) {
    return nullptr;
  }
  const nlohmann::json &result = event["result"];
  if (result.is_string()) {
    nlohmann::json parsed = nlohmann::json::parse(result.get<std::string>(), nullptr, false);
    return parsed.is_discarded() ? result : parsed;
  }
  return result;
}

// The running part.

std::string MQTTManagerEnergy::_topic() {
  return fmt::format("nspanel/mqttmanager_{}/status/energy", MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::MANAGER_ADDRESS));
}

void MQTTManagerEnergy::start() {
  HomeAssistantManager::attach_authenticated_observer(&MQTTManagerEnergy::home_assistant_authenticated_callback);
  MQTTManagerEnergy::reload_config();
  if (!MQTTManagerEnergy::_instance.joinable()) {
    SPDLOG_INFO("No running instance of energy manager found. Will start new thread.");
    MQTTManagerEnergy::_instance = std::thread(MQTTManagerEnergy::_run_thread);
  } else {
    SPDLOG_INFO("Energy manager already running.");
  }
}

void MQTTManagerEnergy::reload_config() {
  MQTTManagerEnergy::_request_resolve();
}

void MQTTManagerEnergy::home_assistant_authenticated_callback() {
  MQTTManagerEnergy::_request_resolve();
}

void MQTTManagerEnergy::_request_resolve() {
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    MQTTManagerEnergy::_resolve_requested = true;
  }
  MQTTManagerEnergy::_cv.notify_all();
}

void MQTTManagerEnergy::_run_thread() {
  // Woken by resolve requests; otherwise every few seconds, to notice a lost connection, count NSPanel Manager's lights
  // and send what the rate limit held back.
  constexpr std::chrono::seconds TICK{5};
  while (true) {
    bool resolve = false;
    bool periodic = false;
    {
      std::unique_lock<std::mutex> lock(MQTTManagerEnergy::_mutex);
      MQTTManagerEnergy::_cv.wait_for(lock, TICK, [] { return MQTTManagerEnergy::_resolve_requested; });
      auto now = std::chrono::steady_clock::now();
      periodic = now >= MQTTManagerEnergy::_next_resolve;
      resolve = MQTTManagerEnergy::_resolve_requested || periodic;
      MQTTManagerEnergy::_resolve_requested = false;
      if (resolve) {
        MQTTManagerEnergy::_next_resolve = now + RESOLVE_INTERVAL;
      }
    }
    try {
      if (resolve) {
        MQTTManagerEnergy::_settings_changed();
        MQTTManagerEnergy::_resolve(periodic);
      }
      {
        std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
        MQTTManagerEnergy::_ha_connected = HomeAssistantManager::is_authenticated();
      }
      MQTTManagerEnergy::_count_nspanelmanager_lights();
      MQTTManagerEnergy::_publish_if_changed(std::time(nullptr));
    } catch (const std::exception &e) {
      SPDLOG_ERROR("Energy: caught exception: {}", e.what());
    }
  }
}

void MQTTManagerEnergy::_settings_changed() {
  Settings settings = MQTTManagerEnergy::settings_from_config();
  std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
  if (!(settings == MQTTManagerEnergy::_settings)) {
    MQTTManagerEnergy::_settings = settings;
    MQTTManagerEnergy::_sources = Sources{}; // Unknown until resolved again
  }
}

void MQTTManagerEnergy::_resolve(bool refresh_lights) {
  Settings settings;
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    settings = MQTTManagerEnergy::_settings;
    MQTTManagerEnergy::_ha_connected = HomeAssistantManager::is_authenticated();
  }

  if (!MQTTManagerEnergy::needs_energy_prefs(settings)) {
    // Nothing to ask Home Assistant: the subscriptions are sent as soon as it connects.
    MQTTManagerEnergy::_apply_sources(MQTTManagerEnergy::resolve(settings, nullptr), refresh_lights);
  } else if (HomeAssistantManager::is_authenticated()) {
    HomeAssistantManager::send_command_with_response({{"type", "energy/get_prefs"}}, [settings, refresh_lights](bool success, const nlohmann::json &prefs) {
      if (!success) {
        SPDLOG_WARN("Energy: reading Home Assistant's Energy settings failed: {}", prefs.dump());
        return; // Keep the sources there are.
      }
      Sources sources = MQTTManagerEnergy::resolve(settings, &prefs);
      SPDLOG_INFO("Energy: {} power sensor(s) and {} from Home Assistant's Energy settings.", sources.power_entities.size(),
                  !sources.price_entity.empty() ? fmt::format("the price from {}", sources.price_entity) : (sources.fixed_price.has_value() ? fmt::format("a price of {}/kWh", *sources.fixed_price) : std::string("no price")));
      MQTTManagerEnergy::_apply_sources(sources, refresh_lights);
    });
  } else {
    // Resolved again once Home Assistant connects. The lights template does not depend on the Energy settings.
    Sources sources;
    {
      std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
      sources = MQTTManagerEnergy::_sources;
    }
    MQTTManagerEnergy::_apply_sources(sources, refresh_lights);
  }

  if (HomeAssistantManager::is_authenticated()) {
    HomeAssistantManager::send_command_with_response({{"type", "get_config"}}, [](bool success, const nlohmann::json &config) {
      if (success && config.is_object() && config.contains("currency") && config["currency"].is_string()) {
        std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
        MQTTManagerEnergy::_currency = config["currency"].get<std::string>();
      }
    });
  }
}

void MQTTManagerEnergy::_apply_sources(const Sources &sources, bool refresh_lights) {
  long old_power = 0;
  long old_lights = 0;
  std::string energy_text;
  std::string lights_text;
  bool resubscribe_power = false;
  bool resubscribe_lights = false;
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    MQTTManagerEnergy::_sources = sources;
    energy_text = MQTTManagerEnergy::energy_template(sources.power_entities, sources.price_entity);
    lights_text = MQTTManagerEnergy::_settings.lights_source == LightsSource::HOME_ASSISTANT ? MQTTManagerEnergy::lights_template(MQTTManagerEnergy::_settings.exclude_labels) : "";

    if (energy_text.compare(MQTTManagerEnergy::_energy_template_text) != 0) {
      resubscribe_power = true;
      old_power = std::exchange(MQTTManagerEnergy::_power_subscription, 0);
      MQTTManagerEnergy::_energy_template_text = energy_text;
      MQTTManagerEnergy::_readings.power_watts.reset();
      MQTTManagerEnergy::_readings.price_per_kwh.reset();
    }
    if (lights_text.compare(MQTTManagerEnergy::_lights_template_text) != 0 || (refresh_lights && !lights_text.empty())) {
      resubscribe_lights = true;
      old_lights = std::exchange(MQTTManagerEnergy::_lights_subscription, 0);
      if (lights_text.compare(MQTTManagerEnergy::_lights_template_text) != 0 && MQTTManagerEnergy::_settings.lights_source != LightsSource::NSPANELMANAGER) {
        MQTTManagerEnergy::_readings.lights_on.reset();
      }
      MQTTManagerEnergy::_lights_template_text = lights_text;
    }
  }

  // Outside the lock: subscribing sends at once, and events come back on the websocket thread.
  if (resubscribe_power) {
    HomeAssistantManager::unsubscribe(old_power);
    if (!energy_text.empty()) {
      long handle = HomeAssistantManager::subscribe({{"type", "render_template"}, {"template", energy_text}, {"report_errors", true}}, &MQTTManagerEnergy::_on_energy_event);
      std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
      MQTTManagerEnergy::_power_subscription = handle;
    }
  }
  if (resubscribe_lights) {
    HomeAssistantManager::unsubscribe(old_lights);
    if (!lights_text.empty()) {
      long handle = HomeAssistantManager::subscribe({{"type", "render_template"}, {"template", lights_text}, {"report_errors", true}}, &MQTTManagerEnergy::_on_lights_event);
      std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
      MQTTManagerEnergy::_lights_subscription = handle;
    }
  }
  MQTTManagerEnergy::_publish_if_changed(std::time(nullptr));
}

void MQTTManagerEnergy::_count_nspanelmanager_lights() {
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    if (MQTTManagerEnergy::_settings.lights_source != LightsSource::NSPANELMANAGER) {
      return;
    }
  }
  int count = 0;
  auto lights = EntityManager::get_all_entities_by_type<Light>(MQTT_MANAGER_ENTITY_TYPE::LIGHT);
  if (lights) {
    for (const auto &light : *lights) {
      if (light->get_state()) {
        count++;
      }
    }
  }
  std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
  MQTTManagerEnergy::_readings.lights_on = count;
}

void MQTTManagerEnergy::_on_energy_event(bool success, const nlohmann::json &event) {
  nlohmann::json result = success ? MQTTManagerEnergy::template_result(event) : nlohmann::json();
  if (!result.is_object()) {
    SPDLOG_WARN("Energy: the power template failed: {}", event.dump());
  }
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    MQTTManagerEnergy::_readings.power_watts = result.is_object() && result.contains("power_w") ? number(result["power_w"]) : std::nullopt;
    MQTTManagerEnergy::_readings.price_per_kwh = result.is_object() && result.contains("price") ? number(result["price"]) : std::nullopt;
  }
  MQTTManagerEnergy::_publish_if_changed(std::time(nullptr));
}

void MQTTManagerEnergy::_on_lights_event(bool success, const nlohmann::json &event) {
  nlohmann::json result = success ? MQTTManagerEnergy::template_result(event) : nlohmann::json();
  std::optional<double> count = number(result);
  if (!count.has_value()) {
    SPDLOG_WARN("Energy: the lights template failed: {}", event.dump());
  }
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    MQTTManagerEnergy::_readings.lights_on = count.has_value() ? std::optional<int>(static_cast<int>(*count)) : std::nullopt;
  }
  MQTTManagerEnergy::_publish_if_changed(std::time(nullptr));
}

void MQTTManagerEnergy::_publish_if_changed(std::time_t now) {
  std::string bytes;
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    NSPanelEnergyUpdate update = MQTTManagerEnergy::build_update(MQTTManagerEnergy::_settings, MQTTManagerEnergy::_sources, MQTTManagerEnergy::_readings,
                                                                 MQTTManagerEnergy::_ha_connected, MQTTManagerEnergy::_currency, now);
    if (update.power() == NSPanelEnergyUpdate_Availability_NOT_CONFIGURED && update.cost() == NSPanelEnergyUpdate_Availability_NOT_CONFIGURED &&
        update.lights() == NSPanelEnergyUpdate_Availability_NOT_CONFIGURED) {
      // Feature off. Remove what an earlier run (or setting) left on the broker, once, so that the panels stop showing it.
      MQTTManagerEnergy::_publish_pending = false;
      MQTTManagerEnergy::_last_published.clear();
      if (!MQTTManagerEnergy::_topic_cleared.exchange(true)) {
        SPDLOG_INFO("Energy card is not in use, will clear retained energy topic.");
        MQTT_Manager::clear_retain(MQTTManagerEnergy::_topic());
      }
      return;
    }

    // Compare without the time of generation, which differs every time.
    NSPanelEnergyUpdate comparable = update;
    comparable.set_generated_at(0);
    std::string comparable_bytes;
    if (!comparable.SerializeToString(&comparable_bytes) || !update.SerializeToString(&bytes)) {
      SPDLOG_ERROR("Failed to serialize energy update.");
      return;
    }
    if (comparable_bytes.compare(MQTTManagerEnergy::_last_published) == 0) {
      MQTTManagerEnergy::_publish_pending = false;
      return;
    }
    auto steady_now = std::chrono::steady_clock::now();
    if (steady_now - MQTTManagerEnergy::_last_publish < MIN_PUBLISH_INTERVAL) {
      MQTTManagerEnergy::_publish_pending = true; // The thread's next tick tries again.
      return;
    }
    MQTTManagerEnergy::_last_published = comparable_bytes;
    MQTTManagerEnergy::_last_publish = steady_now;
    MQTTManagerEnergy::_publish_pending = false;
    SPDLOG_DEBUG("Energy: power {} ({} W), cost {} ({:.2f}/day), lights {} ({}, alert {}).", NSPanelEnergyUpdate_Availability_Name(update.power()), update.power_watts(),
                 NSPanelEnergyUpdate_Availability_Name(update.cost()), update.cost_per_day(), NSPanelEnergyUpdate_Availability_Name(update.lights()), update.lights_on(), update.lights_alert());
  }
  MQTTManagerEnergy::_topic_cleared = false;
  MQTT_Manager::publish(MQTTManagerEnergy::_topic(), bytes, true);
}

#if defined(TEST_MODE) && TEST_MODE == 1
void MQTTManagerEnergy::test_reset() {
  long power = 0;
  long lights = 0;
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerEnergy::_mutex);
    power = std::exchange(MQTTManagerEnergy::_power_subscription, 0);
    lights = std::exchange(MQTTManagerEnergy::_lights_subscription, 0);
    MQTTManagerEnergy::_settings = Settings{};
    MQTTManagerEnergy::_sources = Sources{};
    MQTTManagerEnergy::_readings = Readings{};
    MQTTManagerEnergy::_currency.clear();
    MQTTManagerEnergy::_energy_template_text.clear();
    MQTTManagerEnergy::_lights_template_text.clear();
    MQTTManagerEnergy::_last_published.clear();
    MQTTManagerEnergy::_last_publish = {};
    MQTTManagerEnergy::_publish_pending = false;
    MQTTManagerEnergy::_ha_connected = false;
  }
  MQTTManagerEnergy::_topic_cleared = false;
  HomeAssistantManager::unsubscribe(power);
  HomeAssistantManager::unsubscribe(lights);
}
#endif
