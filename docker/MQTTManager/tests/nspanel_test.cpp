#include "test_helpers.hpp"
#include <algorithm>
#include <command_manager/command_manager.hpp>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <iterator>
#include <optional>
#include <gtest/gtest.h>
#include <media_player/media_player.hpp>
#include <metrics/metrics.hpp>
#include <metrics/panel_metrics_collector.hpp>
#include <metrics/prometheus_targets.hpp>
#include <nspanel/nspanel.hpp>
#include <protobuf_nspanel.pb.h>
#include <room/room.hpp>
#include <room/room_entities_page.hpp>
#include <unistd.h>
#include <vector>

using nspm_test::django_media_player_data;
using nspm_test::django_switch_data;
using nspm_test::home_assistant_service_calls;
using nspm_test::ScopedEntity;
using nspm_test::ScopedErrorLog;
using nspm_test::ScopedNSPanel;
using nspm_test::ScopedScene;

namespace {

const std::string PANEL_MAC = "C0:49:EF:00:01:01";
const std::string PANEL_NAME = "Hall panel";

// Button modes as Django stores them in NSPanel.button1_mode/button2_mode.
enum DjangoButtonMode {
  DIRECT = 0,
  DETACHED = 1,
  MQTT_PAYLOAD = 2,
  FOLLOW = 3,
  THERMOSTAT_HEATING = 4,
  THERMOSTAT_COOLING = 5,
  OPEN_MEDIA_PLAYER = 6,
};

// Rooms shared by every test here (rooms are never removed, see create_room). The first has one
// entities page and one scenes page, the sensor room has a Home Assistant temperature sensor.
struct PanelRooms {
  int room_id;
  int other_room_id;
  int sensor_room_id;
  int entities_page_id;
  int scenes_page_id;
};

const PanelRooms &panel_rooms() {
  static PanelRooms rooms = [] {
    PanelRooms rooms;
    rooms.room_id = nspm_test::create_room("Panel config room");
    rooms.other_room_id = nspm_test::create_room("Panel config other room");
    database_manager::Room sensor_room;
    sensor_room.friendly_name = "Panel config sensor room";
    sensor_room.room_temp_provider = "home_assistant";
    sensor_room.room_temp_sensor = "sensor.panel_config_temperature";
    rooms.sensor_room_id = database_manager::database.insert(sensor_room);
    database_manager::RoomEntitiesPage page;
    page.room_id = rooms.room_id;
    page.page_type = 4;
    page.is_scenes_page = false;
    rooms.entities_page_id = database_manager::database.insert(page);
    page.is_scenes_page = true;
    rooms.scenes_page_id = database_manager::database.insert(page);
    EntityManager::load_rooms();
    return rooms;
  }();
  return rooms;
}

// Runs a function when it goes out of scope.
struct OnExit {
  std::function<void()> function;
  ~OnExit() {
    function();
  }
};

} // namespace

class NSPanelTest : public nspm_test::SendCaptureTest {
protected:
  void SetUp() override {
    nspm_test::SendCaptureTest::SetUp();
    row = std::make_unique<ScopedNSPanel>(PANEL_NAME, PANEL_MAC, panel_rooms().room_id);
  }

  void TearDown() override {
    panel.reset();
    for (int id : setting_ids) {
      database_manager::database.remove<database_manager::NSPanelSettingHolder>(id);
    }
    // And any the panel object wrote itself (an LVGL look reported by the panel).
    database_manager::database.remove_all<database_manager::NSPanelSettingHolder>(
        sqlite_orm::where(sqlite_orm::c(&database_manager::NSPanelSettingHolder::nspanel_id) == row->id));
    for (int id : relay_group_binding_ids) {
      database_manager::database.remove<database_manager::NSPanelRelayGroupBinding>(id);
    }
    row.reset();
  }

  // Change a setting added with set_panel_setting, or add it.
  void change_panel_setting(const std::string &name, const std::string &value) {
    for (int id : setting_ids) {
      auto setting = database_manager::database.get<database_manager::NSPanelSettingHolder>(id);
      if (setting.name == name) {
        setting.value = value;
        database_manager::database.update(setting);
        return;
      }
    }
    set_panel_setting(name, value);
  }

  // The JSON commands published on the panel's MAC command topic since the last call to it or to last_published_config.
  std::vector<nlohmann::json> commands_sent() {
    std::vector<nlohmann::json> commands;
    for (auto &message : nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/command")) {
      commands.push_back(nlohmann::json::parse(message.payload));
    }
    return commands;
  }

  // The LVGL look commands among commands_sent().
  std::vector<nlohmann::json> lvgl_commands_sent() {
    std::vector<nlohmann::json> commands;
    for (auto &command : commands_sent()) {
      if (command["command"] == "lvgl_theme" || command["command"] == "lvgl_background") {
        commands.push_back(command);
      }
    }
    return commands;
  }

  bool register_panel(nlohmann::json features = nullptr) {
    nlohmann::json request = {{"mac_origin", PANEL_MAC}, {"friendly_name", PANEL_NAME}, {"model", "sonoff"}, {"version", "1.0"}, {"md5_firmware", "f"}, {"md5_data_file", "d"}, {"md5_tft_file", "t"}};
    if (!features.is_null()) {
      request["features"] = features;
    }
    return panel->register_to_manager(request);
  }

  // The panel's settings rows named `name`, as Django and MQTTManager read them.
  std::vector<std::string> panel_setting_values(const std::string &name) {
    std::vector<std::string> values;
    for (auto &setting : database_manager::database.get_all<database_manager::NSPanelSettingHolder>(
             sqlite_orm::where(sqlite_orm::c(&database_manager::NSPanelSettingHolder::name) == name and
                               sqlite_orm::c(&database_manager::NSPanelSettingHolder::nspanel_id) == row->id))) {
      values.push_back(setting.value);
    }
    return values;
  }

  // Both the LVGL look commands and the last config published since the last take (the capture is shared, so taking
  // one with commands_sent() or last_published_config() would drop the other).
  struct Published {
    std::vector<nlohmann::json> lvgl_commands;
    std::optional<NSPanelConfig> config;
  };
  Published take_published() {
    Published published;
    for (auto &message : MQTT_Manager::test_take_published_messages()) {
      if (message.topic == "nspanel/" + PANEL_MAC + "/command") {
        auto command = nlohmann::json::parse(message.payload);
        if (command["command"] == "lvgl_theme" || command["command"] == "lvgl_background") {
          published.lvgl_commands.push_back(command);
        }
      } else if (message.topic == "nspanel/" + PANEL_MAC + "/config") {
        published.config.emplace();
        EXPECT_TRUE(published.config->ParseFromString(message.payload));
      }
    }
    return published;
  }

  // The panel reports a look chosen on it (firmware LvglLook), as CommandManager hands every panel a command.
  void report_look(const std::string &theme, const std::string &background, std::optional<int> nspanel_id = std::nullopt) {
    NSPanelMQTTManagerCommand command;
    command.set_nspanel_id(nspanel_id.value_or(row->id));
    command.mutable_lvgl_look()->set_theme(theme);
    command.mutable_lvgl_look()->set_background(background);
    panel->command_callback(command);
  }

  // A setting as web/settings_helper.py set_nspanel_setting_value() stores it.
  void set_panel_setting(const std::string &name, const std::string &value) {
    database_manager::NSPanelSettingHolder setting;
    setting.nspanel_id = row->id;
    setting.name = name;
    setting.value = value;
    setting_ids.push_back(database_manager::database.insert(setting));
  }

  void bind_relay_group(int relay_num, int relay_group_id, int nspanel_id) {
    database_manager::NSPanelRelayGroupBinding binding;
    binding.relay_num = relay_num;
    binding.relay_group_id = relay_group_id;
    binding.nspanel_id = nspanel_id;
    relay_group_binding_ids.push_back(database_manager::database.insert(binding));
  }

  void update_row(const std::function<void(database_manager::NSPanel &)> &change) {
    auto settings = database_manager::database.get<database_manager::NSPanel>(row->id);
    change(settings);
    database_manager::database.update(settings);
  }

  void load_panel() {
    panel = std::make_unique<NSPanel>(row->id);
  }

  // The last config published to the panel since the previous call.
  std::optional<NSPanelConfig> last_published_config() {
    auto messages = nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/config");
    if (messages.empty()) {
      return std::nullopt;
    }
    EXPECT_TRUE(messages.back().retain);
    NSPanelConfig config;
    EXPECT_TRUE(config.ParseFromString(messages.back().payload));
    return config;
  }

  void press_button(int button_id, int nspanel_id) {
    NSPanelMQTTManagerCommand command;
    command.set_nspanel_id(nspanel_id);
    command.mutable_button_pressed()->set_button_id(button_id);
    panel->command_callback(command);
  }

  std::unique_ptr<ScopedNSPanel> row;
  std::unique_ptr<NSPanel> panel;
  std::vector<int> setting_ids;
  std::vector<int> relay_group_binding_ids;
};

TEST_F(NSPanelTest, loading_sends_a_retained_config) {
  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->nspanel_id(), row->id);
  EXPECT_EQ(config->name(), PANEL_NAME);
  EXPECT_EQ(config->default_room(), panel_rooms().room_id);
}

TEST_F(NSPanelTest, config_defaults_without_panel_settings) {
  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->default_page(), NSPanelConfig_NSPanelDefaultPage_HOME);
  EXPECT_FALSE(config->is_us_panel());
  EXPECT_FALSE(config->reverse_relays());
  EXPECT_FALSE(config->relay1_default_mode());
  EXPECT_FALSE(config->relay2_default_mode());
  EXPECT_EQ(config->temperature_calibration(), 0);
  EXPECT_FALSE(config->locked_to_default_room());
  EXPECT_EQ(config->button1_mode(), NSPanelConfig_NSPanelButtonMode_DIRECT);
  EXPECT_EQ(config->button2_mode(), NSPanelConfig_NSPanelButtonMode_DIRECT);
  EXPECT_EQ(config->screen_dim_level(), std::stoi(MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::SCREEN_DIM_LEVEL)));
  EXPECT_EQ(config->screensaver_activation_timeout(), std::stoi(MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::SCREENSAVER_ACTIVATION_TIMEOUT)));
  EXPECT_TRUE(config->relay1_relay_group().empty());
  EXPECT_TRUE(config->relay2_relay_group().empty());
  EXPECT_TRUE(config->inside_temperature_sensor_mqtt_topic().empty());
}

TEST_F(NSPanelTest, panel_settings_are_sent_in_the_config) {
  set_panel_setting("default_page", "2");
  set_panel_setting("is_us_panel", "True");
  set_panel_setting("reverse_relays", "True");
  set_panel_setting("relay1_default_mode", "True");
  set_panel_setting("relay2_default_mode", "False");
  set_panel_setting("screen_dim_level", "80");
  set_panel_setting("screensaver_dim_level", "5");
  set_panel_setting("screensaver_activation_timeout", "120");
  set_panel_setting("screensaver_mode", "datetime_without_background");
  set_panel_setting("show_screensaver_inside_temperature", "True");
  set_panel_setting("show_screensaver_outside_temperature", "False");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->default_page(), NSPanelConfig_NSPanelDefaultPage_ENTITIES);
  EXPECT_TRUE(config->is_us_panel());
  EXPECT_TRUE(config->reverse_relays());
  EXPECT_TRUE(config->relay1_default_mode());
  EXPECT_FALSE(config->relay2_default_mode());
  EXPECT_EQ(config->screen_dim_level(), 80);
  EXPECT_EQ(config->screensaver_dim_level(), 5);
  EXPECT_EQ(config->screensaver_activation_timeout(), 120);
  EXPECT_EQ(config->screensaver_mode(), NSPanelConfig_NSPanelScreensaverMode_DATETIME_WITHOUT_BACKGROUND);
  EXPECT_TRUE(config->show_screensaver_inside_temperature());
  EXPECT_FALSE(config->show_screensaver_outside_temperature());
}

// The global screensaver card settings apply to a panel without its own.
TEST_F(NSPanelTest, screensaver_cards_come_from_the_global_settings) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_CARDS, "calendar:12");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_BASE_CARD_SECONDS, "30");
  OnExit restore{[] {
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_CARDS, "");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_BASE_CARD_SECONDS, "10");
  }};

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  ASSERT_EQ(config->screensaver_cards_size(), 1);
  EXPECT_EQ(config->screensaver_cards(0).type(), NSPanelConfig_NSPanelScreensaverCardType_SCREENSAVER_CARD_CALENDAR);
  EXPECT_EQ(config->screensaver_cards(0).seconds(), 12);
  EXPECT_EQ(config->screensaver_base_card_seconds(), 30);
}

TEST_F(NSPanelTest, panel_screensaver_cards_override_the_global_ones) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_CARDS, "calendar:12");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_BASE_CARD_SECONDS, "30");
  OnExit restore{[] {
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_CARDS, "");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::SCREENSAVER_BASE_CARD_SECONDS, "10");
  }};
  set_panel_setting("screensaver_cards", "doorbell:5,calendar:bad");
  set_panel_setting("screensaver_base_card_seconds", "45");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  ASSERT_EQ(config->screensaver_cards_size(), 1); // doorbell is not known and is skipped
  EXPECT_EQ(config->screensaver_cards(0).seconds(), 10);
  EXPECT_EQ(config->screensaver_base_card_seconds(), 45);
}

TEST_F(NSPanelTest, no_screensaver_cards_by_default) {
  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->screensaver_cards_size(), 0);
  EXPECT_EQ(config->screensaver_base_card_seconds(), 10);
}

TEST_F(NSPanelTest, timezone_rule_is_sent_in_the_config) {
  std::string previous_rule = MqttManagerConfig::timezone_posix_rule;
  OnExit restore_rule{[&] { MqttManagerConfig::timezone_posix_rule = previous_rule; }};
  MqttManagerConfig::timezone_posix_rule = "CET-1CEST,M3.5.0,M10.5.0/3";

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->tz_posix(), "CET-1CEST,M3.5.0,M10.5.0/3");
}

TEST_F(NSPanelTest, unknown_timezone_rule_is_sent_empty) {
  std::string previous_rule = MqttManagerConfig::timezone_posix_rule;
  OnExit restore_rule{[&] { MqttManagerConfig::timezone_posix_rule = previous_rule; }};
  MqttManagerConfig::timezone_posix_rule = "";

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->tz_posix(), "");
}

TEST_F(NSPanelTest, temperature_calibration_is_sent_in_tenths_of_a_degree) {
  set_panel_setting("temperature_calibration", "-1.5"); // Django stores str(float(...)).

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->temperature_calibration(), -15);
}

TEST_F(NSPanelTest, room_temperature_sensor_topic_is_sent_in_the_config) {
  update_row([](auto &settings) {
    settings.room_id = panel_rooms().sensor_room_id;
  });

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  auto room = EntityManager::get_room(panel_rooms().sensor_room_id);
  ASSERT_TRUE(room.has_value());
  EXPECT_FALSE(config->inside_temperature_sensor_mqtt_topic().empty());
  EXPECT_EQ(config->inside_temperature_sensor_mqtt_topic(), (*room)->get_temperature_sensor_mqtt_topic());
}

TEST_F(NSPanelTest, a_shown_screensaver_is_never_fully_dimmed) {
  set_panel_setting("screensaver_mode", "with_background");
  set_panel_setting("screensaver_dim_level", "0");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->screensaver_mode(), NSPanelConfig_NSPanelScreensaverMode_WEATHER_WITH_BACKGROUND);
  EXPECT_EQ(config->screensaver_dim_level(), 10);
}

TEST_F(NSPanelTest, unknown_screensaver_mode_falls_back_to_weather_with_background) {
  set_panel_setting("screensaver_mode", "fireworks");
  ScopedErrorLog log;

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->screensaver_mode(), NSPanelConfig_NSPanelScreensaverMode_WEATHER_WITH_BACKGROUND);
  auto errors = log.errors();
  EXPECT_TRUE(std::any_of(errors.begin(), errors.end(), [](auto &error) { return error.find("Unknown screensaver mode 'fireworks'") != std::string::npos; }));
}

TEST_F(NSPanelTest, manager_handled_button_modes_are_sent_as_notify_manager) {
  update_row([](auto &settings) {
    settings.button1_mode = DETACHED;
    settings.button2_mode = MQTT_PAYLOAD;
  });

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_mode(), NSPanelConfig_NSPanelButtonMode_NOTIFY_MANAGER);
  EXPECT_EQ(config->button2_mode(), NSPanelConfig_NSPanelButtonMode_NOTIFY_MANAGER);
}

// Media players are attached to their room when the rooms load, so load both, and again once the rows are removed.
void load_media_players_and_rooms() {
  EntityManager::load_media_players();
  EntityManager::load_rooms();
}

TEST_F(NSPanelTest, open_media_player_button_opens_the_first_media_player_in_the_panels_room) {
  OnExit unload{[] { load_media_players_and_rooms(); }}; // Runs after the rows are removed.
  ScopedEntity second("media_player", "Kitchen speaker", django_media_player_data("media_player.kitchen"), panel_rooms().room_id, panel_rooms().entities_page_id, 2);
  ScopedEntity first("media_player", "Hall speaker", django_media_player_data("media_player.hall"), panel_rooms().room_id, panel_rooms().entities_page_id, 1);
  load_media_players_and_rooms();
  update_row([](auto &settings) {
    settings.button1_mode = OPEN_MEDIA_PLAYER;
    settings.button2_mode = OPEN_MEDIA_PLAYER;
  });

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  auto player = EntityManager::get_entity_by_id<MediaPlayerEntity>(MQTT_MANAGER_ENTITY_TYPE::MEDIA_PLAYER, first.id);
  ASSERT_TRUE(player);
  EXPECT_EQ(config->button1_mode(), NSPanelConfig_NSPanelButtonMode_OPEN_ENTITY_PAGE);
  EXPECT_EQ(config->button1_entity_page_topic(), (*player)->get_mqtt_state_topic());
  EXPECT_EQ(config->button2_mode(), NSPanelConfig_NSPanelButtonMode_OPEN_ENTITY_PAGE);
  EXPECT_EQ(config->button2_entity_page_topic(), (*player)->get_mqtt_state_topic());
}

TEST_F(NSPanelTest, open_media_player_button_ignores_media_players_in_other_rooms) {
  database_manager::RoomEntitiesPage page;
  page.room_id = panel_rooms().other_room_id;
  page.page_type = 4;
  page.is_scenes_page = false;
  int other_page_id = database_manager::database.insert(page);
  OnExit unload{[other_page_id] {
    database_manager::database.remove<database_manager::RoomEntitiesPage>(other_page_id);
    load_media_players_and_rooms();
  }};
  ScopedEntity elsewhere("media_player", "Lounge speaker", django_media_player_data("media_player.lounge"), panel_rooms().other_room_id, other_page_id, 0);
  load_media_players_and_rooms();
  update_row([](auto &settings) { settings.button1_mode = OPEN_MEDIA_PLAYER; });
  ScopedErrorLog log(spdlog::level::warn);

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_mode(), NSPanelConfig_NSPanelButtonMode_NOTIFY_MANAGER);
  EXPECT_EQ(config->button1_entity_page_topic(), "");
  auto errors = log.errors();
  EXPECT_TRUE(std::any_of(errors.begin(), errors.end(), [](auto &error) { return error.find("has no media player") != std::string::npos; }));
}

TEST_F(NSPanelTest, open_media_player_button_falls_back_when_its_media_player_is_removed) {
  OnExit unload{[] { load_media_players_and_rooms(); }}; // Runs after the row is removed.
  auto speaker = std::make_unique<ScopedEntity>("media_player", "Hall speaker", django_media_player_data("media_player.hall"), panel_rooms().room_id, panel_rooms().entities_page_id, 0);
  load_media_players_and_rooms();
  update_row([](auto &settings) { settings.button1_mode = OPEN_MEDIA_PLAYER; });
  load_panel();
  ASSERT_EQ(last_published_config()->button1_mode(), NSPanelConfig_NSPanelButtonMode_OPEN_ENTITY_PAGE);

  // What EntityManager::load_entities() does when Django signals that the player was deleted.
  speaker.reset();
  load_media_players_and_rooms();
  panel->reload_config();
  panel->send_config();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_mode(), NSPanelConfig_NSPanelButtonMode_NOTIFY_MANAGER);
  EXPECT_EQ(config->button1_entity_page_topic(), "");
}

TEST_F(NSPanelTest, other_button_modes_send_no_entity_page_topic) {
  update_row([](auto &settings) {
    settings.button1_mode = DIRECT;
    settings.button2_mode = DETACHED;
  });

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_entity_page_topic(), "");
  EXPECT_EQ(config->button2_entity_page_topic(), "");
}

TEST_F(NSPanelTest, thermostat_button_modes_send_their_temperature_limits) {
  update_row([](auto &settings) {
    settings.button1_mode = THERMOSTAT_HEATING;
    settings.button2_mode = THERMOSTAT_COOLING;
  });
  set_panel_setting("button1_relay_lower_temperature", "18");
  set_panel_setting("button1_relay_upper_temperature", "21");
  set_panel_setting("button2_relay_lower_temperature", "24");
  set_panel_setting("button2_relay_upper_temperature", "27");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_mode(), NSPanelConfig_NSPanelButtonMode_THERMOSTAT_HEAT);
  EXPECT_EQ(config->button1_lower_temperature(), 18);
  EXPECT_EQ(config->button1_upper_temperature(), 21);
  EXPECT_EQ(config->button2_mode(), NSPanelConfig_NSPanelButtonMode_THERMOSTAT_COOL);
  EXPECT_EQ(config->button2_lower_temperature(), 24);
  EXPECT_EQ(config->button2_upper_temperature(), 27);
}

TEST_F(NSPanelTest, invalid_temperature_limit_is_sent_as_zero) {
  update_row([](auto &settings) {
    settings.button1_mode = THERMOSTAT_HEATING;
    settings.button2_mode = THERMOSTAT_COOLING;
  });
  set_panel_setting("button1_relay_lower_temperature", "eighteen");
  set_panel_setting("button1_relay_upper_temperature", "21");
  set_panel_setting("button2_relay_lower_temperature", "21abc"); // std::stoi would have read 21.
  set_panel_setting("button2_relay_upper_temperature", "21,5");
  ScopedErrorLog log;

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_lower_temperature(), 0);
  EXPECT_EQ(config->button1_upper_temperature(), 21);
  EXPECT_EQ(config->button2_lower_temperature(), 0);
  EXPECT_EQ(config->button2_upper_temperature(), 0);
  auto errors = log.errors();
  for (auto value : {"'eighteen'", "'21abc'", "'21,5'"}) {
    SCOPED_TRACE(value);
    EXPECT_TRUE(std::any_of(errors.begin(), errors.end(), [&value](auto &error) { return error.find(value) != std::string::npos && error.find("not a number") != std::string::npos; }));
  }
}

// Issue #336: saving the settings page stored blank temperature limits, and std::stoi("") then took the manager
// down while sending the config. Databases saved before d8220f68 still hold those blank rows.
TEST_F(NSPanelTest, blank_temperature_limits_do_not_stop_the_config_being_sent) {
  update_row([](auto &settings) {
    settings.button1_mode = THERMOSTAT_HEATING;
    settings.button2_mode = THERMOSTAT_COOLING;
  });
  set_panel_setting("temperature_calibration", "-3.4");
  set_panel_setting("button1_relay_lower_temperature", "");
  set_panel_setting("button1_relay_upper_temperature", "");
  set_panel_setting("button2_relay_lower_temperature", "");
  set_panel_setting("button2_relay_upper_temperature", "");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->temperature_calibration(), -34);
  EXPECT_EQ(config->button1_lower_temperature(), 0);
  EXPECT_EQ(config->button1_upper_temperature(), 0);
  EXPECT_EQ(config->button2_lower_temperature(), 0);
  EXPECT_EQ(config->button2_upper_temperature(), 0);
}

TEST_F(NSPanelTest, blank_temperature_limits_are_ignored_outside_thermostat_modes) {
  set_panel_setting("temperature_calibration", "-3.4");
  set_panel_setting("button1_relay_lower_temperature", "");
  set_panel_setting("button1_relay_upper_temperature", "");
  set_panel_setting("button2_relay_lower_temperature", "");
  set_panel_setting("button2_relay_upper_temperature", "");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->temperature_calibration(), -34);
}

TEST_F(NSPanelTest, out_of_range_temperature_limit_is_sent_as_zero) {
  update_row([](auto &settings) {
    settings.button1_mode = THERMOSTAT_HEATING;
  });
  set_panel_setting("button1_relay_lower_temperature", "1e20");
  ScopedErrorLog log;

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_lower_temperature(), 0);
  auto errors = log.errors();
  EXPECT_TRUE(std::any_of(errors.begin(), errors.end(), [](auto &error) { return error.find("is 1e20, which is out of range") != std::string::npos; }));
}

// NSPanelConfig only holds whole degrees.
TEST_F(NSPanelTest, decimal_temperature_limit_is_rounded) {
  update_row([](auto &settings) {
    settings.button2_mode = THERMOSTAT_COOLING;
  });
  set_panel_setting("button2_relay_lower_temperature", "21.5");
  set_panel_setting("button2_relay_upper_temperature", "24.4");
  ScopedErrorLog log(spdlog::level::warn);

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button2_lower_temperature(), 22);
  EXPECT_EQ(config->button2_upper_temperature(), 24);
  auto warnings = log.errors();
  EXPECT_TRUE(std::any_of(warnings.begin(), warnings.end(), [](auto &warning) { return warning.find("is 21.5, but panels only take whole degrees. Will send 22.") != std::string::npos; }));
}

TEST_F(NSPanelTest, temperature_limits_are_only_sent_in_thermostat_modes) {
  update_row([](auto &settings) {
    settings.button1_mode = FOLLOW;
  });
  set_panel_setting("button1_relay_lower_temperature", "18");
  set_panel_setting("button1_relay_upper_temperature", "21");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->button1_mode(), NSPanelConfig_NSPanelButtonMode_FOLLOW);
  EXPECT_EQ(config->button1_lower_temperature(), 0);
  EXPECT_EQ(config->button1_upper_temperature(), 0);
}

TEST_F(NSPanelTest, relay_group_bindings_are_sent_per_relay) {
  bind_relay_group(1, 7, row->id);
  bind_relay_group(1, 9, row->id);
  bind_relay_group(2, 11, row->id);
  bind_relay_group(1, 13, row->id + 1000); // Another panel's binding.

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(std::vector<int>(config->relay1_relay_group().begin(), config->relay1_relay_group().end()), std::vector<int>({7, 9}));
  EXPECT_EQ(std::vector<int>(config->relay2_relay_group().begin(), config->relay2_relay_group().end()), std::vector<int>({11}));
}

TEST_F(NSPanelTest, unlocked_panel_gets_every_room_with_its_pages) {
  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->room_infos_size(), static_cast<int>(EntityManager::get_all_rooms()->size()));
  auto room = std::find_if(config->room_infos().begin(), config->room_infos().end(), [](auto &info) { return info.room_id() == panel_rooms().room_id; });
  ASSERT_NE(room, config->room_infos().end());
  EXPECT_EQ(std::vector<int>(room->entity_page_ids().begin(), room->entity_page_ids().end()), std::vector<int>({panel_rooms().entities_page_id}));
  EXPECT_EQ(std::vector<int>(room->scene_page_ids().begin(), room->scene_page_ids().end()), std::vector<int>({panel_rooms().scenes_page_id}));
  EXPECT_TRUE(std::any_of(config->room_infos().begin(), config->room_infos().end(), [](auto &info) { return info.room_id() == panel_rooms().other_room_id; }));
}

TEST_F(NSPanelTest, panel_locked_to_its_room_only_gets_that_room) {
  set_panel_setting("lock_to_default_room", "True");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_TRUE(config->locked_to_default_room());
  ASSERT_EQ(config->room_infos_size(), 1);
  EXPECT_EQ(config->room_infos(0).room_id(), panel_rooms().room_id);
  EXPECT_EQ(std::vector<int>(config->room_infos(0).entity_page_ids().begin(), config->room_infos(0).entity_page_ids().end()), std::vector<int>({panel_rooms().entities_page_id}));
}

TEST_F(NSPanelTest, config_only_has_the_default_timer_sound_without_buzzer_settings) {
  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  ASSERT_EQ(config->sounds_size(), 1);
  EXPECT_EQ(config->sounds(0).event(), NSPanelConfig_NSPanelSoundEvent_TIMER_FIRED);
  EXPECT_EQ(config->sounds(0).rtttl(), "timer:d=8,o=6,b=200:c7,p,c7,p,c7,p,c7");
}

TEST_F(NSPanelTest, an_empty_timer_sound_is_not_sent) {
  OnExit reset{[] {
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TIMER_FIRED, "timer:d=8,o=6,b=200:c7,p,c7,p,c7,p,c7");
  }};
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TIMER_FIRED, "");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->sounds_size(), 0);
}

TEST_F(NSPanelTest, global_buzzer_sounds_are_sent_per_event) {
  OnExit reset{[] {
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_ACTIVATED, "");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_SAVED, "");
  }};
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "touch:d=32,o=6,b=190:g6");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_ACTIVATED, "activated:d=16,o=6,b=180:c,e,g");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_SAVED, "saved:d=8,o=5,b=120:c6");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  ASSERT_EQ(config->sounds_size(), 4);
  EXPECT_EQ(config->sounds(0).event(), NSPanelConfig_NSPanelSoundEvent_TOUCH);
  EXPECT_EQ(config->sounds(0).rtttl(), "touch:d=32,o=6,b=190:g6");
  EXPECT_EQ(config->sounds(1).event(), NSPanelConfig_NSPanelSoundEvent_SCENE_ACTIVATED);
  EXPECT_EQ(config->sounds(1).rtttl(), "activated:d=16,o=6,b=180:c,e,g");
  EXPECT_EQ(config->sounds(2).event(), NSPanelConfig_NSPanelSoundEvent_SCENE_SAVED);
  EXPECT_EQ(config->sounds(2).rtttl(), "saved:d=8,o=5,b=120:c6");
  EXPECT_EQ(config->sounds(3).event(), NSPanelConfig_NSPanelSoundEvent_TIMER_FIRED);
  EXPECT_EQ(config->sounds(3).rtttl(), "timer:d=8,o=6,b=200:c7,p,c7,p,c7,p,c7");
}

TEST_F(NSPanelTest, panel_buzzer_settings_override_the_global_sounds) {
  OnExit reset{[] {
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_ACTIVATED, "");
  }};
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "global_touch:d=32,o=6,b=190:g6");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_SCENE_ACTIVATED, "global_activated:d=16,o=6,b=180:c");
  set_panel_setting("buzzer_sound_touch", "panel_touch:d=32,o=7,b=200:c");
  set_panel_setting("buzzer_sound_scene_activated", ""); // Silences the event on this panel only.
  set_panel_setting("buzzer_sound_scene_saved", "panel_saved:d=8,o=5,b=120:e");
  set_panel_setting("buzzer_sound_timer_fired", ""); // The timer default is silenced on this panel only.

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  ASSERT_EQ(config->sounds_size(), 2);
  EXPECT_EQ(config->sounds(0).event(), NSPanelConfig_NSPanelSoundEvent_TOUCH);
  EXPECT_EQ(config->sounds(0).rtttl(), "panel_touch:d=32,o=7,b=200:c");
  EXPECT_EQ(config->sounds(1).event(), NSPanelConfig_NSPanelSoundEvent_SCENE_SAVED);
  EXPECT_EQ(config->sounds(1).rtttl(), "panel_saved:d=8,o=5,b=120:e");
}

TEST_F(NSPanelTest, muting_the_buzzer_sends_no_sounds_until_unmuted) {
  OnExit reset{[] {
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "");
  }};
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "touch:d=32,o=6,b=190:g6");
  load_panel();
  last_published_config();

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/buzzer_mute_cmd", "1");

  auto messages = MQTT_Manager::test_take_published_messages();
  auto state = std::find_if(messages.begin(), messages.end(), [](auto &message) { return message.topic == "nspanel/" + PANEL_MAC + "/buzzer_mute_state"; });
  ASSERT_NE(state, messages.end());
  EXPECT_EQ(state->payload, "1");
  EXPECT_TRUE(state->retain);
  auto config = std::find_if(messages.begin(), messages.end(), [](auto &message) { return message.topic == "nspanel/" + PANEL_MAC + "/config"; });
  ASSERT_NE(config, messages.end());
  NSPanelConfig muted_config;
  ASSERT_TRUE(muted_config.ParseFromString(config->payload));
  EXPECT_EQ(muted_config.sounds_size(), 0);

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/buzzer_mute_cmd", "0");

  auto unmuted_config = last_published_config();
  ASSERT_TRUE(unmuted_config.has_value());
  ASSERT_EQ(unmuted_config->sounds_size(), 2); // The touch sound and the default timer sound.
  EXPECT_EQ(unmuted_config->sounds(0).rtttl(), "touch:d=32,o=6,b=190:g6");
}

TEST_F(NSPanelTest, buzzer_mute_is_kept_across_config_reloads) {
  OnExit reset{[] {
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "");
  }};
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::BUZZER_SOUND_TOUCH, "touch:d=32,o=6,b=190:g6");
  load_panel();
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/buzzer_mute_cmd", "1");
  last_published_config();

  panel->reload_config();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->sounds_size(), 0);
}

TEST_F(NSPanelTest, unchanged_buzzer_mute_does_not_resend_the_config) {
  load_panel();
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/buzzer_mute_cmd", "1");
  last_published_config();

  // The broker replays the retained command on every resubscribe.
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/buzzer_mute_cmd", "1");

  EXPECT_FALSE(last_published_config().has_value());
}

TEST_F(NSPanelTest, unknown_buzzer_mute_command_is_ignored) {
  load_panel();
  last_published_config();
  ScopedErrorLog log;

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/buzzer_mute_cmd", "ON");

  EXPECT_FALSE(last_published_config().has_value());
  auto errors = log.errors();
  EXPECT_TRUE(std::any_of(errors.begin(), errors.end(), [](auto &error) { return error.find("buzzer mute") != std::string::npos; }));
}

TEST_F(NSPanelTest, sonoff_panel_registers_a_retained_buzzer_mute_switch) {
  load_panel();

  auto messages = nspm_test::mqtt_published_to("homeassistant/switch/nspanelmanager/c0_49_ef_00_01_01_buzzer_mute/config");
  ASSERT_FALSE(messages.empty());
  auto discovery = nlohmann::json::parse(messages.back().payload);
  EXPECT_EQ(discovery["command_topic"], "nspanel/" + PANEL_MAC + "/buzzer_mute_cmd");
  EXPECT_EQ(discovery["state_topic"], "nspanel/" + PANEL_MAC + "/buzzer_mute_state");
  EXPECT_EQ(discovery["retain"], true);
}

TEST_F(NSPanelTest, custom_panel_does_not_register_a_buzzer_mute_switch) {
  update_row([](auto &settings) {
    settings.model = "custom";
  });

  load_panel();

  EXPECT_TRUE(nspm_test::mqtt_published_to("homeassistant/switch/nspanelmanager/c0_49_ef_00_01_01_buzzer_mute/config").empty());
}

TEST_F(NSPanelTest, reload_config_sends_changed_settings) {
  load_panel();
  last_published_config();

  set_panel_setting("screen_dim_level", "42");
  update_row([](auto &settings) {
    settings.friendly_name = "Renamed hall panel";
  });
  panel->reload_config();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->screen_dim_level(), 42);
  EXPECT_EQ(config->name(), "Renamed hall panel");
  EXPECT_EQ(panel->get_name(), "Renamed hall panel");
}

TEST_F(NSPanelTest, panel_in_an_unknown_room_is_not_sent_a_config) {
  update_row([](auto &settings) {
    settings.room_id = 999999;
  });
  ScopedErrorLog log;

  load_panel();

  EXPECT_FALSE(last_published_config().has_value());
  auto errors = log.errors();
  EXPECT_TRUE(std::any_of(errors.begin(), errors.end(), [](auto &error) { return error.find("default room") != std::string::npos; }));
}

TEST_F(NSPanelTest, denied_panel_is_not_sent_a_config) {
  update_row([](auto &settings) {
    settings.accepted = false;
    settings.denied = true;
  });

  load_panel();

  EXPECT_EQ(panel->get_state(), MQTT_MANAGER_NSPANEL_STATE::DENIED);
  EXPECT_FALSE(last_published_config().has_value());
}

TEST_F(NSPanelTest, panel_not_yet_accepted_is_awaiting_accept) {
  update_row([](auto &settings) {
    settings.accepted = false;
    settings.denied = false;
  });

  load_panel();

  EXPECT_EQ(panel->get_state(), MQTT_MANAGER_NSPANEL_STATE::AWAITING_ACCEPT);
}

TEST_F(NSPanelTest, accepted_panel_is_loaded_as_waiting) {
  load_panel();

  EXPECT_EQ(panel->get_state(), MQTT_MANAGER_NSPANEL_STATE::WAITING);
}

// Accepting in the web interface sets accepted and reloads the manager. The panel must leave
// AWAITING_ACCEPT/DENIED, as register requests from panels in those states are ignored.
TEST_F(NSPanelTest, accepting_a_pending_panel_moves_it_to_waiting) {
  update_row([](auto &settings) {
    settings.accepted = false;
    settings.denied = false;
  });
  load_panel();

  update_row([](auto &settings) {
    settings.accepted = true;
  });
  panel->reload_config();

  EXPECT_EQ(panel->get_state(), MQTT_MANAGER_NSPANEL_STATE::WAITING);
}

TEST_F(NSPanelTest, accepting_a_denied_panel_moves_it_to_waiting) {
  update_row([](auto &settings) {
    settings.accepted = false;
    settings.denied = true;
  });
  load_panel();

  update_row([](auto &settings) {
    settings.accepted = true;
    settings.denied = false;
  });
  panel->reload_config();

  EXPECT_EQ(panel->get_state(), MQTT_MANAGER_NSPANEL_STATE::WAITING);
}

TEST_F(NSPanelTest, denying_a_pending_panel_marks_it_denied) {
  update_row([](auto &settings) {
    settings.accepted = false;
    settings.denied = false;
  });
  load_panel();

  update_row([](auto &settings) {
    settings.denied = true;
  });
  panel->reload_config();

  EXPECT_EQ(panel->get_state(), MQTT_MANAGER_NSPANEL_STATE::DENIED);
}

TEST_F(NSPanelTest, commands_go_to_the_mac_and_legacy_name_topics) {
  load_panel();
  MQTT_Manager::test_take_published_messages();

  panel->reboot();

  auto published = MQTT_Manager::test_take_published_messages();
  for (auto topic : {"nspanel/" + PANEL_MAC + "/command", "nspanel/" + PANEL_NAME + "/command"}) {
    SCOPED_TRACE(topic);
    std::vector<MQTT_Manager::TestPublishedMessage> messages;
    std::copy_if(published.begin(), published.end(), std::back_inserter(messages), [&topic](auto &message) { return message.topic == topic; });
    ASSERT_EQ(messages.size(), 1);
    EXPECT_EQ(nlohmann::json::parse(messages[0].payload), nlohmann::json({{"command", "reboot"}}));
  }
  EXPECT_EQ(panel->get_state(), MQTT_MANAGER_NSPANEL_STATE::WAITING);
}

TEST_F(NSPanelTest, panel_coming_online_is_sent_the_time) {
  load_panel();
  nspm_test::ScopedBrokerConnected connected;

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status", R"({"state": "online"})");

  auto messages = nspm_test::mqtt_sent_to(nspm_test::epoch_topic());
  ASSERT_EQ(messages.size(), 1);
  EXPECT_FALSE(messages[0].retain);
}

TEST_F(NSPanelTest, panel_going_offline_is_not_sent_the_time) {
  load_panel();
  nspm_test::ScopedBrokerConnected connected;

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status", R"({"state": "offline"})");

  EXPECT_TRUE(nspm_test::mqtt_sent_to(nspm_test::epoch_topic()).empty());
}

TEST_F(NSPanelTest, mqtt_payload_button_publishes_the_configured_message) {
  update_row([](auto &settings) {
    settings.button2_mode = MQTT_PAYLOAD;
  });
  set_panel_setting("button2_mqtt_topic", "hall/doorbell");
  set_panel_setting("button2_mqtt_payload", "ring");
  load_panel();
  MQTT_Manager::test_take_published_messages();

  press_button(2, row->id);

  auto messages = nspm_test::mqtt_published_to("hall/doorbell");
  ASSERT_EQ(messages.size(), 1);
  EXPECT_EQ(messages[0].payload, "ring");
  EXPECT_FALSE(messages[0].retain);
}

TEST_F(NSPanelTest, button_presses_from_other_panels_are_ignored) {
  update_row([](auto &settings) {
    settings.button1_mode = MQTT_PAYLOAD;
  });
  set_panel_setting("button1_mqtt_topic", "hall/doorbell");
  set_panel_setting("button1_mqtt_payload", "ring");
  load_panel();
  MQTT_Manager::test_take_published_messages();

  press_button(1, row->id + 1000);

  EXPECT_TRUE(nspm_test::mqtt_published_to("hall/doorbell").empty());
}

// The panel only notifies the manager in this mode when the room had no media player.
TEST_F(NSPanelTest, open_media_player_button_press_without_a_media_player_is_only_logged) {
  update_row([](auto &settings) { settings.button1_mode = OPEN_MEDIA_PLAYER; });
  load_panel();
  home_assistant_service_calls();
  ScopedErrorLog log(spdlog::level::warn);

  press_button(1, row->id);

  EXPECT_TRUE(home_assistant_service_calls().empty());
  auto errors = log.errors();
  EXPECT_TRUE(std::any_of(errors.begin(), errors.end(), [](auto &error) { return error.find("no media player in its room") != std::string::npos; }));
  EXPECT_TRUE(std::none_of(errors.begin(), errors.end(), [](auto &error) { return error.find("Unknown button mode") != std::string::npos; }));
}

TEST_F(NSPanelTest, detached_button_toggles_its_entity) {
  OnExit unload_switch{[] { EntityManager::load_switches(); }}; // Runs after the row is removed.
  ScopedEntity fan("switch", "Hall fan", django_switch_data("home_assistant", "switch.hall_fan"));
  EntityManager::load_switches();
  update_row([&](auto &settings) {
    settings.button1_mode = DETACHED;
    settings.button1_detached_mode_entity_id = fan.id;
  });
  load_panel();
  home_assistant_service_calls();

  press_button(1, row->id);

  auto calls = home_assistant_service_calls();
  ASSERT_EQ(calls.size(), 1);
  EXPECT_EQ(calls[0]["domain"], "switch");
  EXPECT_EQ(calls[0]["target"], nlohmann::json({{"entity_id", "switch.hall_fan"}}));
}

TEST_F(NSPanelTest, detached_button_activates_a_scene_in_the_panels_room) {
  OnExit unload_scene{[] { EntityManager::load_scenes(); }}; // Runs after the row is removed.
  ScopedScene script("home_assistant", "Movie night", "script.movie_night", std::nullopt);
  EntityManager::load_scenes();
  update_row([&](auto &settings) {
    settings.button2_mode = DETACHED;
    settings.button2_detached_mode_entity_id = script.id;
  });
  load_panel();
  home_assistant_service_calls();

  press_button(2, row->id);

  auto calls = home_assistant_service_calls();
  ASSERT_EQ(calls.size(), 1);
  EXPECT_EQ(calls[0]["service_data"]["variables"]["nspanelmanager"]["triggering_room_id"], panel_rooms().room_id);
}

TEST_F(NSPanelTest, detached_button_runs_a_script_with_the_panels_room_and_the_scripts_room) {
  OnExit unload_scene{[] { EntityManager::load_scenes(); }}; // Runs after the row is removed.
  ScopedScene script("home_assistant", "Lights out", "script.lights_out", panel_rooms().other_room_id);
  EntityManager::load_scenes();
  update_row([&](auto &settings) {
    settings.button1_mode = DETACHED;
    settings.button1_detached_mode_entity_id = script.id;
  });
  load_panel();
  home_assistant_service_calls();

  press_button(1, row->id);

  auto calls = home_assistant_service_calls();
  ASSERT_EQ(calls.size(), 1);
  EXPECT_EQ(calls[0]["domain"], "script");
  EXPECT_EQ(calls[0]["service"], "turn_on");
  EXPECT_EQ(calls[0]["target"]["entity_id"], "script.lights_out");
  EXPECT_EQ(calls[0]["service_data"]["variables"]["nspanelmanager"], nlohmann::json({
                                                                         {"scene_name", "Lights out"},
                                                                         {"scene_id", script.id},
                                                                         {"triggering_room_id", panel_rooms().room_id},
                                                                         {"triggering_room_name", "Panel config room"},
                                                                         {"scene_room_id", panel_rooms().other_room_id},
                                                                         {"scene_room_name", "Panel config other room"},
                                                                     }));
}

TEST_F(NSPanelTest, detached_button_turns_on_a_scene) {
  OnExit unload_scene{[] { EntityManager::load_scenes(); }}; // Runs after the row is removed.
  ScopedScene scene("home_assistant", "Movie time", "scene.movie_time", std::nullopt);
  EntityManager::load_scenes();
  update_row([&](auto &settings) {
    settings.button1_mode = DETACHED;
    settings.button1_detached_mode_entity_id = scene.id;
  });
  load_panel();
  home_assistant_service_calls();

  press_button(1, row->id);

  auto calls = home_assistant_service_calls();
  ASSERT_EQ(calls.size(), 1);
  EXPECT_EQ(calls[0], nlohmann::json({{"type", "call_service"}, {"domain", "scene"}, {"service", "turn_on"}, {"target", {{"entity_id", "scene.movie_time"}}}}));
}

// A callback left behind would call into the destroyed NSPanel on the next button press from any
// panel, or the next message on one of the deleted panel's topics.
TEST_F(NSPanelTest, destroyed_panel_leaves_no_callbacks_behind) {
  size_t command_callbacks = CommandManager::test_callback_count();
  load_panel();

  panel.reset();

  EXPECT_EQ(CommandManager::test_callback_count(), command_callbacks);
  for (auto topic : {"nspanel/" + PANEL_MAC + "/log", "nspanel/" + PANEL_NAME + "/status", "nspanel/" + PANEL_NAME + "/status_report", "nspanel/" + PANEL_MAC + "/status"}) {
    SCOPED_TRACE(topic);
    EXPECT_EQ(MQTT_Manager::test_callback_count(topic), 0);
  }
}

TEST_F(NSPanelTest, renamed_panel_moves_its_legacy_subscriptions_to_the_new_name) {
  load_panel();

  update_row([](auto &settings) {
    settings.friendly_name = "Renamed hall panel";
  });
  panel->reload_config();

  for (auto suffix : {"/status", "/status_report", "/log"}) {
    SCOPED_TRACE(suffix);
    EXPECT_EQ(MQTT_Manager::test_callback_count("nspanel/" + PANEL_NAME + suffix), 0);
    EXPECT_EQ(MQTT_Manager::test_callback_count("nspanel/Renamed hall panel" + std::string(suffix)), 1);
  }
}

// LVGL mode, docs/LVGL_PANEL_MODE.md.

namespace {
nlohmann::json theme_command(const std::string &theme) {
  return nlohmann::json{{"command", "lvgl_theme"}, {"theme", theme}};
}
nlohmann::json background_command(const std::string &preset) {
  return nlohmann::json{{"command", "lvgl_background"}, {"preset", preset}};
}
} // namespace

TEST_F(NSPanelTest, lvgl_look_is_empty_in_the_config_when_not_managed) {
  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->lvgl_theme(), "");
  EXPECT_EQ(config->lvgl_background(), "");
}

TEST_F(NSPanelTest, lvgl_look_is_sent_in_the_config) {
  set_panel_setting("lvgl_theme", "ocean");
  set_panel_setting("lvgl_background", "peaks");

  load_panel();

  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->lvgl_theme(), "ocean");
  EXPECT_EQ(config->lvgl_background(), "peaks");
}

TEST_F(NSPanelTest, loading_a_panel_sends_no_lvgl_commands) {
  // The manager starting is not a reason to repaint every panel; the panel gets its look when it registers.
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_theme", "dusk");

  load_panel();

  EXPECT_TRUE(lvgl_commands_sent().empty());
  EXPECT_TRUE(panel->is_lvgl_mode());
}

TEST_F(NSPanelTest, changed_lvgl_theme_is_sent_to_a_panel_in_lvgl_mode) {
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_theme", "dusk");
  set_panel_setting("lvgl_background", "dusk");
  load_panel();
  commands_sent();

  change_panel_setting("lvgl_theme", "grey");
  panel->reload_config();

  EXPECT_EQ(lvgl_commands_sent(), (std::vector<nlohmann::json>{theme_command("grey")}));
}

TEST_F(NSPanelTest, changed_lvgl_background_is_sent_to_a_panel_in_lvgl_mode) {
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_background", "none");
  load_panel();
  commands_sent();

  change_panel_setting("lvgl_background", "aurora");
  panel->reload_config();

  EXPECT_EQ(lvgl_commands_sent(), (std::vector<nlohmann::json>{background_command("aurora")}));
}

TEST_F(NSPanelTest, unchanged_lvgl_look_is_not_sent_again_on_reload) {
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_theme", "dusk");
  load_panel();
  commands_sent();

  change_panel_setting("screen_dim_level", "42");
  panel->reload_config();

  EXPECT_TRUE(lvgl_commands_sent().empty());
}

TEST_F(NSPanelTest, panel_in_nextion_mode_is_sent_no_lvgl_commands) {
  set_panel_setting("lvgl_theme", "dusk");
  load_panel();
  commands_sent();

  change_panel_setting("lvgl_theme", "ocean");
  panel->reload_config();
  register_panel();

  EXPECT_TRUE(lvgl_commands_sent().empty());
  EXPECT_FALSE(panel->is_lvgl_mode());
}

TEST_F(NSPanelTest, moving_a_panel_to_lvgl_sends_its_whole_look) {
  set_panel_setting("display_mode", "nextion");
  set_panel_setting("lvgl_theme", "peaks");
  set_panel_setting("lvgl_background", "peaks");
  load_panel();
  commands_sent();

  change_panel_setting("display_mode", "lvgl");
  panel->reload_config();

  EXPECT_EQ(lvgl_commands_sent(), (std::vector<nlohmann::json>{theme_command("peaks"), background_command("peaks")}));
}

TEST_F(NSPanelTest, unmanaged_lvgl_look_is_never_sent) {
  set_panel_setting("display_mode", "nextion");
  set_panel_setting("lvgl_background", "ocean");
  load_panel();
  commands_sent();

  change_panel_setting("display_mode", "lvgl");
  panel->reload_config();
  register_panel();

  // Only the background is managed; the panel keeps its own theme.
  EXPECT_EQ(lvgl_commands_sent(), (std::vector<nlohmann::json>{background_command("ocean")}));
}

TEST_F(NSPanelTest, lvgl_look_is_sent_after_the_first_registration_only) {
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_theme", "aurora");
  load_panel();
  commands_sent();

  register_panel();
  auto first = commands_sent();
  register_panel();
  auto second = commands_sent();

  // register_accept first, then the look.
  ASSERT_EQ(first.size(), 2);
  EXPECT_EQ(first[0]["command"], "register_accept");
  EXPECT_EQ(first[1], theme_command("aurora"));
  ASSERT_EQ(second.size(), 1);
  EXPECT_EQ(second[0]["command"], "register_accept");
}

TEST_F(NSPanelTest, panel_in_lvgl_mode_is_compared_with_the_terminal_tft_for_its_layout) {
  auto directory = std::filesystem::temp_directory_path() / fmt::format("nspm-terminal-tft-{}", ::getpid());
  std::filesystem::create_directories(directory / "us");
  std::filesystem::create_directories(directory / "eu");
  std::ofstream(directory / "us" / "gui.tft") << "us terminal tft";
  std::ofstream(directory / "eu" / "gui.tft") << "eu terminal tft";
  std::string previous_directory = MqttManagerConfig::terminal_tft_directory;
  OnExit restore{[&] {
    MqttManagerConfig::terminal_tft_directory = previous_directory;
    MqttManagerConfig::update_tft_checksums();
    std::filesystem::remove_all(directory);
  }};
  MqttManagerConfig::terminal_tft_directory = directory.string();
  MqttManagerConfig::update_tft_checksums();
  auto us_checksum = MqttManagerConfig::get_terminal_tft_checksum(true);
  auto eu_checksum = MqttManagerConfig::get_terminal_tft_checksum(false);
  ASSERT_TRUE(us_checksum.has_value());
  ASSERT_TRUE(eu_checksum.has_value());
  EXPECT_NE(*us_checksum, *eu_checksum);

  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("is_us_panel", "True");
  load_panel();
  auto report_tft = [&](const std::string &md5) {
    NSPanelStatusReport report;
    report.set_md5_tft_gui(md5);
    panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", report.SerializeAsString());
  };

  report_tft(*eu_checksum);
  EXPECT_TRUE(panel->has_tft_update());
  report_tft(*us_checksum);
  EXPECT_FALSE(panel->has_tft_update());
}

TEST_F(NSPanelTest, panel_in_lvgl_mode_without_a_terminal_tft_has_no_update) {
  std::string previous_directory = MqttManagerConfig::terminal_tft_directory;
  OnExit restore{[&] {
    MqttManagerConfig::terminal_tft_directory = previous_directory;
    MqttManagerConfig::update_tft_checksums();
  }};
  MqttManagerConfig::terminal_tft_directory = "/nonexistent/nspm-terminal-tft";
  MqttManagerConfig::update_tft_checksums();
  set_panel_setting("display_mode", "lvgl");
  load_panel();

  NSPanelStatusReport report;
  report.set_md5_tft_gui("0123456789abcdef0123456789abcdef");
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", report.SerializeAsString());

  EXPECT_FALSE(panel->has_tft_update());
}

// Panels whose web UI is embedded in the firmware have no LittleFS image to update.
TEST_F(NSPanelTest, panel_with_an_embedded_web_ui_has_no_littlefs_update) {
  load_panel();
  NSPanelStatusReport report;
  report.set_md5_littlefs(NSPM_WEB_UI_EMBEDDED);
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", report.SerializeAsString());

  EXPECT_FALSE(panel->has_littlefs_update());
}

// A look chosen on the panel, docs/LVGL_PANEL_MODE.md.

TEST_F(NSPanelTest, look_chosen_on_the_panel_is_saved_and_confirmed_by_the_config) {
  load_panel();
  last_published_config();

  report_look("auto", "ocean");

  EXPECT_EQ(panel_setting_values("lvgl_theme"), std::vector<std::string>{"auto"});
  EXPECT_EQ(panel_setting_values("lvgl_background"), std::vector<std::string>{"ocean"});
  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->lvgl_theme(), "auto");
  EXPECT_EQ(config->lvgl_background(), "ocean");
}

TEST_F(NSPanelTest, look_chosen_on_the_panel_replaces_the_managed_look) {
  set_panel_setting("lvgl_theme", "dusk");
  set_panel_setting("lvgl_background", "dusk");
  load_panel();
  last_published_config();

  report_look("grey", "none");

  // The same rows, changed: Django reads the first row of a name.
  EXPECT_EQ(panel_setting_values("lvgl_theme"), std::vector<std::string>{"grey"});
  EXPECT_EQ(panel_setting_values("lvgl_background"), std::vector<std::string>{"none"});
  auto config = last_published_config();
  ASSERT_TRUE(config.has_value());
  EXPECT_EQ(config->lvgl_theme(), "grey");
  EXPECT_EQ(config->lvgl_background(), "none");
}

TEST_F(NSPanelTest, look_chosen_on_the_panel_is_not_sent_back_as_commands) {
  // Even to a panel whose firmware takes commands only: the report proves the panel has the look already.
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_theme", "dusk");
  set_panel_setting("lvgl_background", "dusk");
  load_panel();
  register_panel();
  commands_sent();

  report_look("auto", "peaks");
  // And a later reload (a save in the web interface) finds nothing changed.
  panel->reload_config();

  auto published = take_published();
  EXPECT_TRUE(published.lvgl_commands.empty());
  ASSERT_TRUE(published.config.has_value());
  EXPECT_EQ(published.config->lvgl_background(), "peaks");
}

TEST_F(NSPanelTest, unknown_look_report_is_ignored) {
  load_panel();
  last_published_config();

  report_look("pink", "ocean");
  report_look("dark", "space");
  report_look("dark", "");
  report_look("", "");

  EXPECT_TRUE(panel_setting_values("lvgl_theme").empty());
  EXPECT_TRUE(panel_setting_values("lvgl_background").empty());
  // No config either: nothing for the panel to take as a confirmation, or to answer.
  EXPECT_FALSE(last_published_config().has_value());
}

TEST_F(NSPanelTest, look_reported_for_another_panel_is_ignored) {
  load_panel();
  last_published_config();

  report_look("auto", "ocean", row->id + 1);

  EXPECT_TRUE(panel_setting_values("lvgl_theme").empty());
  EXPECT_FALSE(last_published_config().has_value());
}

TEST_F(NSPanelTest, panel_that_reports_its_look_is_sent_no_lvgl_commands) {
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_theme", "aurora");
  set_panel_setting("lvgl_background", "aurora");
  load_panel();
  commands_sent();

  register_panel(nlohmann::json::array({"lvgl_look"}));
  auto after_register = commands_sent();
  change_panel_setting("lvgl_theme", "grey");
  panel->reload_config();

  // register_accept only; the look travels in the config.
  ASSERT_EQ(after_register.size(), 1);
  EXPECT_EQ(after_register[0]["command"], "register_accept");
  auto published = take_published();
  EXPECT_TRUE(published.lvgl_commands.empty());
  ASSERT_TRUE(published.config.has_value());
  EXPECT_EQ(published.config->lvgl_theme(), "grey");
}

TEST_F(NSPanelTest, panel_that_stops_listing_the_feature_is_sent_commands_again) {
  // Firmware rolled back to a build that only knows the commands.
  set_panel_setting("display_mode", "lvgl");
  set_panel_setting("lvgl_theme", "aurora");
  load_panel();
  register_panel(nlohmann::json::array({"lvgl_look"}));
  commands_sent();

  register_panel(nlohmann::json::array({"something_else"}));
  commands_sent();
  change_panel_setting("lvgl_theme", "peaks");
  panel->reload_config();

  EXPECT_EQ(lvgl_commands_sent(), (std::vector<nlohmann::json>{theme_command("peaks")}));
}

namespace {

std::string status_report_payload(int32_t metrics_port = 0) {
  NSPanelStatusReport report;
  report.set_metrics_port(metrics_port);
  report.set_nspanel_state(NSPanelStatusReport_state_ONLINE);
  report.set_rssi(-61);
  report.set_heap_used_pct(42);
  report.set_temperature(71.5);
  report.set_ip_address("10.8.0.79");
  report.set_md5_firmware("d7a9ecce");
  report.set_md5_littlefs("706c2b5f");
  report.set_md5_tft_gui("13bf1937");
  report.set_has_humidity(true);
  report.set_humidity(40);
  return report.SerializeAsString();
}

// The labels every per-panel series of the test panel carries, as serialized.
std::string panel_series(const std::string &name, int nspm_id) {
  return name + "{mac=\"" + PANEL_MAC + "\",nspm_id=\"" + std::to_string(nspm_id) + "\",panel=\"" + PANEL_NAME + "\"}";
}

nlohmann::json register_request(std::optional<nlohmann::json> metrics_port) {
  nlohmann::json request = {
      {"command", "register_request"},
      {"mac", PANEL_MAC},
      {"friendly_name", PANEL_NAME},
      {"model", "sonoff"},
      {"version", "1.0"},
      {"md5_firmware", "d7a9ecce"},
      {"md5_data_file", "706c2b5f"},
      {"md5_tft_file", "13bf1937"},
  };
  if (metrics_port) {
    request["metrics_port"] = *metrics_port;
  }
  return request;
}

} // namespace

TEST_F(NSPanelTest, panel_with_an_embedded_web_ui_has_no_littlefs_update_from_its_register_request) {
  auto request = register_request(std::nullopt);
  request["md5_data_file"] = NSPM_WEB_UI_EMBEDDED;
  load_panel();
  panel->register_to_manager(request);

  EXPECT_FALSE(panel->has_littlefs_update());
}

namespace {

std::string temperature_report(std::optional<float> temperature, bool has_temperature) {
  NSPanelStatusReport report;
  report.set_nspanel_state(NSPanelStatusReport_state_ONLINE);
  if (temperature) {
    report.set_temperature(*temperature);
  }
  report.set_has_temperature(has_temperature);
  return report.SerializeAsString();
}

} // namespace

TEST_F(NSPanelTest, status_report_without_a_temperature_publishes_and_records_nothing) {
  load_panel();
  nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/temperature"); // Drop what loading published.

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", temperature_report(std::nullopt, false));

  EXPECT_TRUE(nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/temperature").empty());
  EXPECT_FALSE(panel->get_metrics_snapshot().temperature.has_value());
}

TEST_F(NSPanelTest, status_report_with_a_temperature_publishes_it_and_keeps_it_when_the_next_has_none) {
  load_panel();
  nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/temperature");

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", temperature_report(0.0, true));
  auto published = nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/temperature");
  ASSERT_EQ(published.size(), 1u);
  EXPECT_EQ(published[0].payload, "0.0");
  ASSERT_TRUE(panel->get_metrics_snapshot().temperature.has_value());

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", temperature_report(69.8, true));
  nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/temperature");
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", temperature_report(std::nullopt, false));

  EXPECT_TRUE(nspm_test::mqtt_published_to("nspanel/" + PANEL_MAC + "/temperature").empty());
  ASSERT_TRUE(panel->get_metrics_snapshot().temperature.has_value());
  EXPECT_FLOAT_EQ(*panel->get_metrics_snapshot().temperature, 69.8f);
}

TEST_F(NSPanelTest, status_report_from_firmware_without_the_flag_counts_a_non_zero_temperature_as_present) {
  load_panel();

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", temperature_report(71.5, false));
  ASSERT_TRUE(panel->get_metrics_snapshot().temperature.has_value());
  EXPECT_FLOAT_EQ(*panel->get_metrics_snapshot().temperature, 71.5f);
}

TEST_F(NSPanelTest, metrics_snapshot_has_the_latest_status_report) {
  load_panel();
  NSPanelMetricsSnapshot before = panel->get_metrics_snapshot();
  EXPECT_FALSE(before.status_report_received);
  EXPECT_FALSE(before.humidity.has_value());

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload());
  NSPanelMetricsSnapshot snapshot = panel->get_metrics_snapshot();
  EXPECT_TRUE(snapshot.status_report_received);
  EXPECT_EQ(snapshot.state, MQTT_MANAGER_NSPANEL_STATE::ONLINE);
  EXPECT_EQ(snapshot.ip_address, "10.8.0.79");
  EXPECT_EQ(snapshot.rssi, -61);
  EXPECT_EQ(snapshot.heap_used_pct, 42);
  ASSERT_TRUE(snapshot.temperature.has_value());
  EXPECT_FLOAT_EQ(*snapshot.temperature, 71.5);
  ASSERT_TRUE(snapshot.humidity.has_value());
  EXPECT_FLOAT_EQ(*snapshot.humidity, 40);
  EXPECT_FALSE(snapshot.pressure.has_value());
  EXPECT_EQ(snapshot.md5_firmware, "d7a9ecce");
  EXPECT_EQ(snapshot.model, "sonoff");
  EXPECT_TRUE(PanelMetricsCollector::is_accepted(snapshot));
  EXPECT_TRUE(PanelMetricsCollector::is_up(snapshot));

  std::string text = Metrics::serialize();
  EXPECT_NE(text.find(panel_series("nspm_panel_status_reports_total", row->id)), std::string::npos) << text;
  EXPECT_NE(text.find(panel_series("nspm_panel_last_status_report_timestamp_seconds", row->id)), std::string::npos) << text;
}

TEST_F(NSPanelTest, panel_is_a_target_once_it_advertises_metrics_port) {
  load_panel();
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload());
  EXPECT_TRUE(PrometheusTargets::select_panel_targets({panel->get_metrics_snapshot()}).empty()) << "no metrics_port yet";

  panel->register_to_manager(register_request(80));
  auto targets = PrometheusTargets::select_panel_targets({panel->get_metrics_snapshot()});
  ASSERT_EQ(targets.size(), 1u);
  EXPECT_EQ(targets[0].ip_address, "10.8.0.79");
  EXPECT_EQ(targets[0].metrics_port, 80);
  EXPECT_EQ(targets[0].nspm_id, static_cast<uint32_t>(row->id));
  EXPECT_EQ(targets[0].mac, PANEL_MAC);

  std::string text = Metrics::serialize();
  EXPECT_NE(text.find(panel_series("nspm_panel_register_requests_total", row->id)), std::string::npos) << text;

  // Sample output for review.
  std::cout << "--- sample /prometheus/targets ---\n"
            << PrometheusTargets::build_json("nspm.manque.net", targets) << "\n--- end ---" << std::endl;

  // Re-registering without it (firmware downgraded) drops the panel again.
  panel->register_to_manager(register_request(std::nullopt));
  EXPECT_TRUE(PrometheusTargets::select_panel_targets({panel->get_metrics_snapshot()}).empty());
}

TEST_F(NSPanelTest, invalid_metrics_port_is_ignored) {
  load_panel();
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload());
  for (nlohmann::json port : {nlohmann::json(0), nlohmann::json(70000), nlohmann::json(-1), nlohmann::json("80"), nlohmann::json(80.5)}) {
    panel->register_to_manager(register_request(port));
    EXPECT_EQ(panel->get_metrics_snapshot().metrics_port, 0) << port.dump();
  }
}

TEST_F(NSPanelTest, status_report_metrics_port_makes_panel_a_target) {
  // A restarted manager never sees the register_request; the next status report must be enough.
  load_panel();
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload());
  EXPECT_TRUE(PrometheusTargets::select_panel_targets({panel->get_metrics_snapshot()}).empty()) << "no metrics_port yet";

  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload(80));
  auto targets = PrometheusTargets::select_panel_targets({panel->get_metrics_snapshot()});
  ASSERT_EQ(targets.size(), 1u);
  EXPECT_EQ(targets[0].ip_address, "10.8.0.79");
  EXPECT_EQ(targets[0].metrics_port, 80);
}

TEST_F(NSPanelTest, status_report_without_metrics_port_keeps_registered_port) {
  // Firmware that predates the field sends 0 in every report.
  load_panel();
  panel->register_to_manager(register_request(80));
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload(0));
  EXPECT_EQ(panel->get_metrics_snapshot().metrics_port, 80);
  EXPECT_EQ(PrometheusTargets::select_panel_targets({panel->get_metrics_snapshot()}).size(), 1u);

  for (int32_t port : {-1, 70000}) {
    panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload(port));
    EXPECT_EQ(panel->get_metrics_snapshot().metrics_port, 80) << port;
  }
}

TEST_F(NSPanelTest, status_report_metrics_port_overrides_registered_port) {
  load_panel();
  panel->register_to_manager(register_request(80));
  panel->mqtt_callback("nspanel/" + PANEL_MAC + "/status_report", status_report_payload(9100));
  auto targets = PrometheusTargets::select_panel_targets({panel->get_metrics_snapshot()});
  ASSERT_EQ(targets.size(), 1u);
  EXPECT_EQ(targets[0].metrics_port, 9100);
}

TEST_F(NSPanelTest, sent_configs_are_counted) {
  load_panel();
  std::string name = "nspm_panel_configs_sent_total{mac=\"" + PANEL_MAC + "\",nspm_id=\"" + std::to_string(row->id) + "\",panel=\"" + PANEL_NAME + "\",reason=\"buzzer_mute\"} ";
  auto count = [&name]() {
    std::string text = Metrics::serialize();
    size_t start = text.find(name);
    return start == std::string::npos ? 0.0 : std::stod(text.substr(start + name.size()));
  };
  double before = count();
  panel->send_config("buzzer_mute");
  EXPECT_EQ(count(), before + 1);
  EXPECT_NE(Metrics::serialize().find(panel_series("nspm_panel_config_bytes_total", row->id)), std::string::npos);
}

TEST(MetricsSampleOutput, print_metrics) {
  // Not a check: prints what /prometheus/metrics serves after the other tests, for review.
  std::cout << "--- sample /prometheus/metrics ---\n"
            << Metrics::serialize() << "--- end ---" << std::endl;
}
