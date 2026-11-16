// MQTTManagerEnergy: where the power, price and lights come from, the templates Home Assistant renders, and what is
// sent to the panels for the screensaver's energy card.

#include "test_helpers.hpp"
#include <energy/energy.hpp>
#include <gtest/gtest.h>
#include <home_assistant_manager/home_assistant_manager.hpp>
#include <protobuf_nspanel.pb.h>

namespace {

using Settings = MQTTManagerEnergy::Settings;
using Sources = MQTTManagerEnergy::Sources;
using Readings = MQTTManagerEnergy::Readings;

const std::time_t NOW = 1795334400;

// energy/get_prefs as Home Assistant 2026.11 returns it for a house with two Emporia mains panels and a flat price.
nlohmann::json two_panel_prefs() {
  return nlohmann::json::parse(R"({
    "energy_sources": [
      {"type": "grid", "name": "Redmond Panel #1", "stat_energy_from": "sensor.redmond_panel_1_energy_today",
       "number_energy_price": 0.1092, "power_config": {"stat_rate": "sensor.redmond_panel_1_power_minute_average"},
       "cost_adjustment_day": 0, "stat_energy_to": null, "stat_cost": null, "entity_energy_price": null,
       "stat_compensation": null, "entity_energy_price_export": null, "number_energy_price_export": null,
       "stat_rate": "sensor.redmond_panel_1_power_minute_average"},
      {"type": "grid", "name": "Redmond Panel #2", "stat_energy_from": "sensor.redmond_panel_2_energy_today",
       "number_energy_price": 0.1092, "power_config": {"stat_rate": "sensor.redmond_panel_2_power_minute_average"},
       "cost_adjustment_day": 0, "stat_energy_to": null, "stat_cost": null, "entity_energy_price": null,
       "stat_compensation": null, "entity_energy_price_export": null, "number_energy_price_export": null,
       "stat_rate": "sensor.redmond_panel_2_power_minute_average"},
      {"type": "solar", "stat_energy_from": "sensor.solar_energy", "stat_rate": "sensor.solar_power"}
    ],
    "device_consumption": [],
    "device_consumption_water": []
  })");
}

Sources full_sources() {
  Sources sources;
  sources.resolved = true;
  sources.power_entities = {"sensor.a_power", "sensor.b_power"};
  sources.fixed_price = 0.1092;
  return sources;
}

Readings full_readings() {
  Readings readings;
  readings.power_watts = 3577;
  readings.lights_on = 6;
  return readings;
}

NSPanelEnergyUpdate build(const Settings &settings = Settings{}, const Sources &sources = full_sources(), const Readings &readings = full_readings(), bool connected = true) {
  return MQTTManagerEnergy::build_update(settings, sources, readings, connected, "USD", NOW);
}

} // namespace

// Resolving the sources

TEST(EnergySources, energy_settings_give_every_grid_power_sensor_and_the_price) {
  nlohmann::json prefs = two_panel_prefs();

  Sources sources = MQTTManagerEnergy::resolve(Settings{}, &prefs);

  EXPECT_TRUE(sources.resolved);
  EXPECT_EQ(sources.power_entities, (std::vector<std::string>{"sensor.redmond_panel_1_power_minute_average", "sensor.redmond_panel_2_power_minute_average"}));
  ASSERT_TRUE(sources.fixed_price.has_value());
  EXPECT_DOUBLE_EQ(*sources.fixed_price, 0.1092);
  EXPECT_TRUE(sources.price_entity.empty());
}

TEST(EnergySources, a_price_entity_in_the_energy_settings_wins_over_nothing) {
  nlohmann::json prefs = two_panel_prefs();
  prefs["energy_sources"][0]["number_energy_price"] = nullptr;
  prefs["energy_sources"][0]["entity_energy_price"] = "sensor.electricity_price";

  Sources sources = MQTTManagerEnergy::resolve(Settings{}, &prefs);

  EXPECT_EQ(sources.price_entity, "sensor.electricity_price");
  EXPECT_FALSE(sources.fixed_price.has_value());
}

TEST(EnergySources, power_config_alone_is_read_when_stat_rate_is_missing) {
  nlohmann::json prefs = two_panel_prefs();
  prefs["energy_sources"][0].erase("stat_rate");

  Sources sources = MQTTManagerEnergy::resolve(Settings{}, &prefs);

  EXPECT_EQ(sources.power_entities.size(), 2u);
}

TEST(EnergySources, grids_without_a_power_sensor_leave_power_unconfigured) {
  nlohmann::json prefs = two_panel_prefs();
  for (auto &source : prefs["energy_sources"]) {
    source.erase("stat_rate");
    source.erase("power_config");
  }

  Sources sources = MQTTManagerEnergy::resolve(Settings{}, &prefs);

  EXPECT_TRUE(sources.resolved);
  EXPECT_FALSE(sources.power_configured());
  EXPECT_TRUE(sources.price_configured());
}

TEST(EnergySources, unresolved_until_the_energy_settings_are_read) {
  Sources sources = MQTTManagerEnergy::resolve(Settings{}, nullptr);

  EXPECT_FALSE(sources.resolved);
  EXPECT_TRUE(MQTTManagerEnergy::needs_energy_prefs(Settings{}));
}

TEST(EnergySources, picked_sensors_and_a_fixed_price_need_no_energy_settings) {
  Settings settings;
  settings.power_source = MQTTManagerEnergy::PowerSource::ENTITIES;
  settings.power_entity_ids = {"sensor.house_power"};
  settings.price_source = MQTTManagerEnergy::PriceSource::FIXED;
  settings.price_per_kwh = 0.25;
  nlohmann::json prefs = two_panel_prefs();

  EXPECT_FALSE(MQTTManagerEnergy::needs_energy_prefs(settings));
  Sources sources = MQTTManagerEnergy::resolve(settings, &prefs);

  EXPECT_TRUE(sources.resolved);
  EXPECT_EQ(sources.power_entities, (std::vector<std::string>{"sensor.house_power"}));
  EXPECT_DOUBLE_EQ(*sources.fixed_price, 0.25);
}

TEST(EnergySources, a_picked_price_entity) {
  Settings settings;
  settings.price_source = MQTTManagerEnergy::PriceSource::ENTITY;
  settings.price_entity_id = "input_number.electricity_price";
  nlohmann::json prefs = two_panel_prefs();

  Sources sources = MQTTManagerEnergy::resolve(settings, &prefs);

  EXPECT_EQ(sources.price_entity, "input_number.electricity_price");
  EXPECT_FALSE(sources.fixed_price.has_value());
}

// Templates

TEST(EnergyTemplates, the_energy_template_lists_the_sensors_and_reads_the_price_entity) {
  std::string text = MQTTManagerEnergy::energy_template({"sensor.a_power", "sensor.b_power"}, "sensor.price");

  EXPECT_NE(text.find(R"({%- set ids = ["sensor.a_power","sensor.b_power"] -%})"), std::string::npos) << text;
  EXPECT_NE(text.find(R"(states("sensor.price"))"), std::string::npos) << text;
  EXPECT_NE(text.find("'power_w'"), std::string::npos);
  EXPECT_NE(text.find("| to_json }}"), std::string::npos);
}

TEST(EnergyTemplates, no_price_entity_no_price_lookup) {
  std::string text = MQTTManagerEnergy::energy_template({"sensor.a_power"}, "");

  EXPECT_EQ(text.find("set p = states"), std::string::npos) << text;
  EXPECT_NE(text.find("{%- set price = none -%}"), std::string::npos);
}

TEST(EnergyTemplates, nothing_to_read_no_template) {
  EXPECT_EQ(MQTTManagerEnergy::energy_template({}, ""), "");
}

TEST(EnergyTemplates, ids_and_labels_cannot_break_out_of_their_strings) {
  std::string energy = MQTTManagerEnergy::energy_template({"sensor.a\"}} {{ 1"}, "");
  std::string lights = MQTTManagerEnergy::lights_template({"x'] }}{{ 2", "caf\xC3\xA9"});

  EXPECT_NE(energy.find(R"(["sensor.a\"}} {{ 1"])"), std::string::npos) << energy;
  EXPECT_NE(lights.find(R"(["x'] }}{{ 2","café"])"), std::string::npos) << lights;
}

TEST(EnergyTemplates, the_lights_template_skips_groups_hidden_lights_and_labels) {
  std::string text = MQTTManagerEnergy::lights_template({"exclude_from_whats_on", "seasonal_lights"});

  EXPECT_EQ(text.rfind(R"({%- set excluded = ["exclude_from_whats_on","seasonal_lights"] | map('label_entities') | sum(start=[]) -%})", 0), 0u) << text;
  for (const char *part : {"states.light", "selectattr('state', 'eq', 'on')", "rejectattr('attributes.entity_id', 'defined')", "rejectattr('attributes.is_hue_group', 'true')",
                           "rejectattr('entity_id', 'in', excluded)", "rejectattr('entity_id', 'is_hidden_entity')", "| list | count }}"}) {
    EXPECT_NE(text.find(part), std::string::npos) << part;
  }
  EXPECT_NE(MQTTManagerEnergy::lights_template({}).find("{%- set excluded = [] |"), std::string::npos);
}

TEST(EnergyTemplates, template_results_as_values_or_text) {
  EXPECT_EQ(MQTTManagerEnergy::template_result({{"result", 6}}), 6);
  EXPECT_EQ(MQTTManagerEnergy::template_result({{"result", {{"power_w", 3577}, {"price", nullptr}}}})["power_w"], 3577);
  // Home Assistant sends the rendered text when it does not turn it into a value, as with nulls.
  nlohmann::json from_text = MQTTManagerEnergy::template_result({{"result", R"({"power_w":null,"price":null})"}});
  ASSERT_TRUE(from_text.is_object());
  EXPECT_TRUE(from_text["power_w"].is_null());
  EXPECT_TRUE(MQTTManagerEnergy::template_result({{"error", "UndefinedError"}, {"level", "ERROR"}}).is_null());
  EXPECT_TRUE(MQTTManagerEnergy::template_result(nlohmann::json::object()).is_null());
}

TEST(EnergyTemplates, currency_symbols) {
  EXPECT_EQ(MQTTManagerEnergy::currency_symbol("USD"), "$");
  EXPECT_EQ(MQTTManagerEnergy::currency_symbol("eur"), "€");
  EXPECT_EQ(MQTTManagerEnergy::currency_symbol("GBP"), "£");
  EXPECT_EQ(MQTTManagerEnergy::currency_symbol("CHF"), "");
}

// The update

TEST(EnergyUpdate, everything_available) {
  NSPanelEnergyUpdate update = build();

  EXPECT_EQ(update.power(), NSPanelEnergyUpdate_Availability_AVAILABLE);
  EXPECT_EQ(update.power_watts(), 3580); // Rounded to 10 W
  EXPECT_EQ(update.cost(), NSPanelEnergyUpdate_Availability_AVAILABLE);
  EXPECT_DOUBLE_EQ(update.cost_per_day(), 9.38); // 3.58 kW x 24 h x 0.1092, in whole cents
  EXPECT_EQ(update.currency(), "USD");
  EXPECT_EQ(update.currency_symbol(), "$");
  EXPECT_EQ(update.lights(), NSPanelEnergyUpdate_Availability_AVAILABLE);
  EXPECT_EQ(update.lights_on(), 6);
  EXPECT_FALSE(update.lights_alert());
  EXPECT_EQ(update.generated_at(), NOW);
}

TEST(EnergyUpdate, exporting_is_a_negative_power_and_a_credit) {
  Readings readings = full_readings();
  readings.power_watts = -400;

  NSPanelEnergyUpdate update = build(Settings{}, full_sources(), readings);

  EXPECT_EQ(update.power_watts(), -400);
  EXPECT_DOUBLE_EQ(update.cost_per_day(), -1.05);
}

TEST(EnergyUpdate, the_price_entity_reading_is_used) {
  Sources sources = full_sources();
  sources.fixed_price.reset();
  sources.price_entity = "sensor.price";
  Readings readings = full_readings();
  readings.price_per_kwh = 0.2;

  EXPECT_DOUBLE_EQ(build(Settings{}, sources, readings).cost_per_day(), 17.18);

  readings.price_per_kwh.reset();
  NSPanelEnergyUpdate unavailable = build(Settings{}, sources, readings);
  EXPECT_EQ(unavailable.power(), NSPanelEnergyUpdate_Availability_AVAILABLE);
  EXPECT_EQ(unavailable.cost(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
}

TEST(EnergyUpdate, a_sensor_without_a_number_makes_power_and_cost_unavailable) {
  Readings readings = full_readings();
  readings.power_watts.reset();

  NSPanelEnergyUpdate update = build(Settings{}, full_sources(), readings);

  EXPECT_EQ(update.power(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  EXPECT_EQ(update.cost(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  EXPECT_EQ(update.lights(), NSPanelEnergyUpdate_Availability_AVAILABLE);
}

TEST(EnergyUpdate, home_assistant_disconnected_makes_its_parts_unavailable) {
  NSPanelEnergyUpdate update = build(Settings{}, full_sources(), full_readings(), false);

  EXPECT_EQ(update.power(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  EXPECT_EQ(update.cost(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  EXPECT_EQ(update.lights(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);

  Settings settings;
  settings.lights_source = MQTTManagerEnergy::LightsSource::NSPANELMANAGER;
  EXPECT_EQ(build(settings, full_sources(), full_readings(), false).lights(), NSPanelEnergyUpdate_Availability_AVAILABLE);
}

TEST(EnergyUpdate, before_the_energy_settings_are_read_power_and_cost_are_unavailable) {
  NSPanelEnergyUpdate update = build(Settings{}, Sources{}, full_readings());

  EXPECT_EQ(update.power(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  EXPECT_EQ(update.cost(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
}

TEST(EnergyUpdate, parts_that_are_off_or_missing_are_not_configured) {
  Settings settings;
  settings.price_source = MQTTManagerEnergy::PriceSource::OFF;
  settings.lights_source = MQTTManagerEnergy::LightsSource::OFF;
  NSPanelEnergyUpdate update = build(settings);
  EXPECT_EQ(update.power(), NSPanelEnergyUpdate_Availability_AVAILABLE);
  EXPECT_EQ(update.cost(), NSPanelEnergyUpdate_Availability_NOT_CONFIGURED);
  EXPECT_EQ(update.lights(), NSPanelEnergyUpdate_Availability_NOT_CONFIGURED);
  EXPECT_TRUE(update.currency().empty());

  Sources no_power = full_sources();
  no_power.power_entities.clear();
  NSPanelEnergyUpdate without_power = build(Settings{}, no_power);
  EXPECT_EQ(without_power.power(), NSPanelEnergyUpdate_Availability_NOT_CONFIGURED);
  EXPECT_EQ(without_power.cost(), NSPanelEnergyUpdate_Availability_NOT_CONFIGURED); // No cost without power

  Sources no_price = full_sources();
  no_price.fixed_price.reset();
  EXPECT_EQ(build(Settings{}, no_price).cost(), NSPanelEnergyUpdate_Availability_NOT_CONFIGURED);
}

TEST(EnergyUpdate, the_alert_starts_at_the_threshold_and_zero_turns_it_off) {
  Settings settings;
  settings.alert_threshold = 15;
  Readings readings = full_readings();

  readings.lights_on = 14;
  EXPECT_FALSE(build(settings, full_sources(), readings).lights_alert());
  readings.lights_on = 15;
  EXPECT_TRUE(build(settings, full_sources(), readings).lights_alert());

  settings.alert_threshold = 0;
  readings.lights_on = 60;
  EXPECT_FALSE(build(settings, full_sources(), readings).lights_alert());
}

TEST(EnergyUpdate, never_an_empty_payload) {
  Settings settings;
  settings.power_source = MQTTManagerEnergy::PowerSource::OFF;
  settings.lights_source = MQTTManagerEnergy::LightsSource::NSPANELMANAGER;
  Readings readings;
  readings.lights_on = 0;

  NSPanelEnergyUpdate update = MQTTManagerEnergy::build_update(settings, Sources{}, readings, true, "", 0);

  EXPECT_NE(update.generated_at(), 0);
  EXPECT_FALSE(update.SerializeAsString().empty());
}

// Running against Home Assistant

class EnergyPublishTest : public nspm_test::SendCaptureTest {
protected:
  void SetUp() override {
    SendCaptureTest::SetUp();
    MQTTManagerEnergy::test_reset();
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, "http://ha.invalid:8123");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_POWER_SOURCE, "home_assistant_energy");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_PRICE_SOURCE, "home_assistant_energy");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_SOURCE, "home_assistant");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_EXCLUDE_LABELS, "exclude_from_whats_on");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_ALERT_THRESHOLD, "15");
    HomeAssistantManager::test_set_authenticated(true);
    HomeAssistantManager::test_take_sent_messages();
    MQTT_Manager::test_take_published_messages();
  }

  void TearDown() override {
    MQTTManagerEnergy::test_reset();
    HomeAssistantManager::test_disconnect();
    HomeAssistantManager::test_set_authenticated(false);
    HomeAssistantManager::test_take_sent_messages();
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, "");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_EXCLUDE_LABELS, "");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_POWER_SOURCE, "home_assistant_energy");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_PRICE_SOURCE, "home_assistant_energy");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_SOURCE, "home_assistant");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_ALERT_THRESHOLD, "15");
  }

  // The id of the first sent message of `type`, or 0.
  static long sent_id(const std::vector<nlohmann::json> &sent, const std::string &type) {
    for (const auto &message : sent) {
      if (message.value("type", "").compare(type) == 0) {
        return message["id"].get<long>();
      }
    }
    return 0;
  }

  static std::vector<NSPanelEnergyUpdate> published() {
    std::vector<NSPanelEnergyUpdate> updates;
    for (auto &message : MQTT_Manager::test_take_published_messages()) {
      if (message.topic.ends_with("/status/energy")) {
        EXPECT_TRUE(message.retain);
        NSPanelEnergyUpdate update;
        EXPECT_TRUE(update.ParseFromString(message.payload));
        updates.push_back(update);
      }
    }
    return updates;
  }

  // Resolve, answer energy/get_prefs and get_config, and return the render_template commands sent.
  std::vector<nlohmann::json> resolve_with(const nlohmann::json &prefs) {
    MQTTManagerEnergy::test_resolve();
    auto sent = HomeAssistantManager::test_take_sent_messages();
    long prefs_id = sent_id(sent, "energy/get_prefs");
    long config_id = sent_id(sent, "get_config");
    EXPECT_NE(prefs_id, 0);
    EXPECT_NE(config_id, 0);
    HomeAssistantManager::test_deliver_result(config_id, {{"currency", "USD"}});
    HomeAssistantManager::test_deliver_result(prefs_id, prefs);
    std::vector<nlohmann::json> templates;
    for (auto &message : HomeAssistantManager::test_take_sent_messages()) {
      if (message.value("type", "").compare("render_template") == 0) {
        templates.push_back(message);
      }
    }
    return templates;
  }

  static void deliver_power(const nlohmann::json &result) {
    HomeAssistantManager::test_deliver_event(HomeAssistantManager::test_subscription_id(MQTTManagerEnergy::test_power_subscription()), {{"result", result}});
  }

  static void deliver_lights(const nlohmann::json &result) {
    HomeAssistantManager::test_deliver_event(HomeAssistantManager::test_subscription_id(MQTTManagerEnergy::test_lights_subscription()), {{"result", result}});
  }
};

TEST_F(EnergyPublishTest, subscribes_both_templates_and_publishes_what_they_render) {
  auto templates = resolve_with(two_panel_prefs());

  ASSERT_EQ(templates.size(), 2u);
  for (const auto &message : templates) {
    EXPECT_EQ(message["report_errors"], true);
  }
  EXPECT_NE(MQTTManagerEnergy::test_power_subscription(), 0);
  EXPECT_NE(MQTTManagerEnergy::test_lights_subscription(), 0);

  deliver_power({{"power_w", 3577}, {"price", nullptr}});
  deliver_lights(16);
  published();
  MQTTManagerEnergy::test_flush();

  auto updates = published();
  ASSERT_EQ(updates.size(), 1u);
  EXPECT_EQ(updates[0].power_watts(), 3580);
  EXPECT_DOUBLE_EQ(updates[0].cost_per_day(), 9.38);
  EXPECT_EQ(updates[0].currency_symbol(), "$");
  EXPECT_EQ(updates[0].lights_on(), 16);
  EXPECT_TRUE(updates[0].lights_alert());
}

TEST_F(EnergyPublishTest, an_unchanged_update_is_not_published_again) {
  resolve_with(two_panel_prefs());
  deliver_power({{"power_w", 3577}, {"price", nullptr}});
  deliver_lights(6);
  MQTTManagerEnergy::test_flush();
  published();

  deliver_power({{"power_w", 3581}, {"price", nullptr}}); // Still 3580 W
  MQTTManagerEnergy::test_flush();

  EXPECT_TRUE(published().empty());
}

TEST_F(EnergyPublishTest, changes_close_together_wait_for_the_rate_limit) {
  resolve_with(two_panel_prefs());
  deliver_lights(6);
  MQTTManagerEnergy::test_flush();
  published();

  deliver_lights(7);
  deliver_lights(8);
  EXPECT_TRUE(published().empty());

  MQTTManagerEnergy::test_flush();
  auto updates = published();
  ASSERT_EQ(updates.size(), 1u);
  EXPECT_EQ(updates[0].lights_on(), 8);
}

TEST_F(EnergyPublishTest, a_template_error_makes_its_part_unavailable) {
  resolve_with(two_panel_prefs());
  deliver_power({{"power_w", 3577}, {"price", nullptr}});
  deliver_lights(6);
  MQTTManagerEnergy::test_flush();
  published();

  HomeAssistantManager::test_deliver_event(HomeAssistantManager::test_subscription_id(MQTTManagerEnergy::test_lights_subscription()), {{"error", "UndefinedError: 'x' is undefined"}, {"level", "ERROR"}});
  MQTTManagerEnergy::test_flush();

  auto updates = published();
  ASSERT_EQ(updates.size(), 1u);
  EXPECT_EQ(updates[0].lights(), NSPanelEnergyUpdate_Availability_UNAVAILABLE);
  EXPECT_EQ(updates[0].power(), NSPanelEnergyUpdate_Availability_AVAILABLE);
}

TEST_F(EnergyPublishTest, resolving_again_keeps_the_power_subscription_and_refreshes_the_lights_one) {
  resolve_with(two_panel_prefs());
  long power = MQTTManagerEnergy::test_power_subscription();
  long lights = MQTTManagerEnergy::test_lights_subscription();

  auto templates = resolve_with(two_panel_prefs());

  EXPECT_EQ(MQTTManagerEnergy::test_power_subscription(), power);
  EXPECT_NE(MQTTManagerEnergy::test_lights_subscription(), lights); // Label changes have no event; resubscribing picks them up
  ASSERT_EQ(templates.size(), 1u);
  EXPECT_NE(templates[0]["template"].get<std::string>().find("states.light"), std::string::npos);
}

TEST_F(EnergyPublishTest, new_labels_change_the_lights_template) {
  resolve_with(two_panel_prefs());

  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_EXCLUDE_LABELS, "exclude_from_whats_on, seasonal_lights");
  auto templates = resolve_with(two_panel_prefs());

  ASSERT_EQ(templates.size(), 1u);
  EXPECT_NE(templates[0]["template"].get<std::string>().find(R"(["exclude_from_whats_on","seasonal_lights"])"), std::string::npos);
}

TEST_F(EnergyPublishTest, everything_off_publishes_nothing_and_subscribes_nothing) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_POWER_SOURCE, "off");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_PRICE_SOURCE, "off");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_SOURCE, "off");

  MQTTManagerEnergy::test_resolve();
  MQTTManagerEnergy::test_flush();

  for (const auto &message : HomeAssistantManager::test_take_sent_messages()) {
    EXPECT_NE(message.value("type", ""), "render_template");
    EXPECT_NE(message.value("type", ""), "energy/get_prefs");
  }
  EXPECT_TRUE(published().empty());
  EXPECT_EQ(MQTTManagerEnergy::test_power_subscription(), 0);
  EXPECT_EQ(MQTTManagerEnergy::test_lights_subscription(), 0);
}

TEST_F(EnergyPublishTest, without_home_assistant_only_nspanelmanager_lights_are_counted) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, "");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_SOURCE, "nspanelmanager");

  Settings settings = MQTTManagerEnergy::settings_from_config();

  EXPECT_EQ(settings.power_source, MQTTManagerEnergy::PowerSource::OFF);
  EXPECT_EQ(settings.lights_source, MQTTManagerEnergy::LightsSource::NSPANELMANAGER);

  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_SOURCE, "home_assistant");
  EXPECT_EQ(MQTTManagerEnergy::settings_from_config().lights_source, MQTTManagerEnergy::LightsSource::OFF);
}

TEST_F(EnergyPublishTest, settings_from_config) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_POWER_SOURCE, "Entities");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_POWER_ENTITY_IDS, "sensor.a, sensor.b,,sensor.a");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_PRICE_SOURCE, "fixed");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_PRICE_PER_KWH, "0.1092");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::LIGHTS_ON_ALERT_THRESHOLD, "-3");

  Settings settings = MQTTManagerEnergy::settings_from_config();

  EXPECT_EQ(settings.power_source, MQTTManagerEnergy::PowerSource::ENTITIES);
  EXPECT_EQ(settings.power_entity_ids, (std::vector<std::string>{"sensor.a", "sensor.b"}));
  EXPECT_EQ(settings.price_source, MQTTManagerEnergy::PriceSource::FIXED);
  EXPECT_DOUBLE_EQ(settings.price_per_kwh, 0.1092);
  EXPECT_EQ(settings.exclude_labels, (std::vector<std::string>{"exclude_from_whats_on"}));
  EXPECT_EQ(settings.alert_threshold, 0);

  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_POWER_ENTITY_IDS, "");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::ENERGY_PRICE_PER_KWH, "0");
}
