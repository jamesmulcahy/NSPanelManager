// Which of the home page's light controls a room (or "All rooms") needs, as the room status tells
// the panel: num_ceiling_lights and num_table_lights for the two light groups, and
// num_color_temperature_lights, with color_temperature_lights_known, for the colour-temperature
// slider. Only lights controlled from the main page count.

#include "test_helpers.hpp"

#include <algorithm>
#include <chrono>
#include <fmt/format.h>
#include <gtest/gtest.h>
#include <mutex>
#include <optional>
#include <protobuf/protobuf_nspanel.pb.h>
#include <room/room.hpp>
#include <string>
#include <thread>

using nspm_test::django_light_data;
using nspm_test::ScopedEntity;

namespace {

nlohmann::json light(bool ceiling, bool color_temperature, bool main_page = true) {
  nlohmann::json data = django_light_data();
  data["is_ceiling_light"] = ceiling;
  data["can_color_temperature"] = color_temperature;
  data["controlled_by_nspanel_main_page"] = main_page;
  return data;
}

// The last status published on a topic since the last call, if any.
std::optional<NSPanelRoomStatus> last_status(const std::string &topic) {
  auto messages = nspm_test::mqtt_published_to(topic);
  if (messages.empty()) {
    return std::nullopt;
  }
  NSPanelRoomStatus status;
  if (!status.ParseFromString(messages.back().payload)) {
    return std::nullopt;
  }
  return status;
}

} // namespace

class RoomLightCapabilitiesTest : public nspm_test::SendCaptureTest {
protected:
  void SetUp() override {
    nspm_test::SendCaptureTest::SetUp();
    // A room of its own per test: a room only publishes a status that differs from its last one.
    const auto *test = ::testing::UnitTest::GetInstance()->current_test_info();
    room_id = nspm_test::create_room(fmt::format("Light capabilities {}", test->name()));
    database_manager::RoomEntitiesPage page;
    page.room_id = room_id;
    page.page_type = 4;
    page.is_scenes_page = false;
    page_id = database_manager::database.insert(page);
  }

  void TearDown() override {
    // The tests' light rows are gone by now; unload them, and the page.
    database_manager::database.remove<database_manager::RoomEntitiesPage>(page_id);
    load_lights_and_rooms();
  }

  static void load_lights_and_rooms() {
    EntityManager::load_lights();
    EntityManager::load_rooms();
  }

  std::unique_ptr<ScopedEntity> add_light(const std::string &name, const nlohmann::json &data, int slot) {
    return std::make_unique<ScopedEntity>("light", name, data, room_id, page_id, slot);
  }

  // Loads the lights added, and returns the room's status once it has sent one.
  std::optional<NSPanelRoomStatus> room_status() {
    load_lights_and_rooms();
    auto room = EntityManager::get_room(room_id);
    if (!room) {
      return std::nullopt;
    }
    (*room)->page_changed_callback(nullptr);
    std::this_thread::sleep_for(backoff_time() * 4);
    return last_status(fmt::format("nspanel/mqttmanager_{}/room/{}/state", manager_address(), room_id));
  }

  static std::string manager_address() {
    return MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::MANAGER_ADDRESS);
  }

  static std::chrono::milliseconds backoff_time() {
    return std::chrono::milliseconds(MqttManagerConfig::get_setting_with_default<uint32_t>(MQTT_MANAGER_SETTING::ROOM_STATUS_BACKOFF_TIME));
  }

  int room_id = 0;
  int page_id = 0;
};

TEST_F(RoomLightCapabilitiesTest, counts_each_group_and_the_colour_temperature_lights) {
  auto ceiling = add_light("Ceiling", light(true, true), 0);
  auto lamp = add_light("Lamp", light(false, false), 1);
  auto spot = add_light("Spot", light(true, false), 2);

  auto status = room_status();

  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(status->num_ceiling_lights(), 2);
  EXPECT_EQ(status->num_table_lights(), 1);
  EXPECT_EQ(status->num_color_temperature_lights(), 1);
  EXPECT_TRUE(status->color_temperature_lights_known());
}

// F1: a room of dimmer-only lights. average_color_temperature is 0 here, as it is for a room turned
// fully warm, so only the count tells the panel to hide the slider.
TEST_F(RoomLightCapabilitiesTest, dimmer_only_room_has_no_colour_temperature_lights_and_says_so) {
  auto ceiling = add_light("Ceiling", light(true, false), 0);
  auto lamp = add_light("Lamp", light(false, false), 1);

  auto status = room_status();

  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(status->num_color_temperature_lights(), 0);
  EXPECT_TRUE(status->color_temperature_lights_known());
  EXPECT_EQ(status->average_color_temperature(), 0);
}

// The panel shows a control whether the lights are on or off: the count doesn't follow the state.
TEST_F(RoomLightCapabilitiesTest, lights_that_are_off_still_count) {
  auto lamp = add_light("Lamp", light(false, true), 0);

  auto status = room_status();

  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(status->num_table_lights_on(), 0);
  EXPECT_EQ(status->num_table_lights(), 1);
  EXPECT_EQ(status->num_color_temperature_lights(), 1);
}

TEST_F(RoomLightCapabilitiesTest, lights_not_controlled_from_the_main_page_do_not_count) {
  auto ceiling = add_light("Ceiling", light(true, true, /*main_page=*/false), 0);
  auto lamp = add_light("Lamp", light(false, false), 1);

  auto status = room_status();

  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(status->num_ceiling_lights(), 0);
  EXPECT_EQ(status->num_table_lights(), 1);
  EXPECT_EQ(status->num_color_temperature_lights(), 0);
  EXPECT_TRUE(status->color_temperature_lights_known());
}

TEST_F(RoomLightCapabilitiesTest, room_without_lights_says_it_has_none) {
  auto status = room_status();

  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(status->num_ceiling_lights(), 0);
  EXPECT_EQ(status->num_table_lights(), 0);
  EXPECT_EQ(status->num_color_temperature_lights(), 0);
  // Sent even though every count is 0: "known" is what tells "none" from "an older manager".
  EXPECT_TRUE(status->color_temperature_lights_known());
}

// "All rooms" counts every room's main-page lights. Its thread is started by EntityManager::init(),
// which the tests don't run, so this starts it (once; like the manager's, it never stops).
TEST_F(RoomLightCapabilitiesTest, all_rooms_counts_every_rooms_lights) {
  static std::once_flag started;
  std::call_once(started, [] { std::thread(EntityManager::update_all_rooms_status).detach(); });
  const std::string topic = fmt::format("nspanel/mqttmanager_{}/all_rooms_status", manager_address());
  // Every other test's lights are unloaded (TearDown), so these are the only ones loaded.
  auto ceiling = add_light("Ceiling", light(true, false), 0);
  auto lamp = add_light("Lamp", light(false, true), 1);
  auto hidden = add_light("Hidden", light(false, true, /*main_page=*/false), 2);

  load_lights_and_rooms();
  auto room = EntityManager::get_room(room_id);
  ASSERT_TRUE(room.has_value());
  (*room)->page_changed_callback(nullptr); // A room changing wakes the all-rooms thread.
  auto backoff = std::chrono::milliseconds(MqttManagerConfig::get_setting_with_default<uint32_t>(MQTT_MANAGER_SETTING::ALL_ROOMS_STATUS_BACKOFF_TIME));
  std::this_thread::sleep_for(std::max(backoff, backoff_time()) * 4);
  auto status = last_status(topic);

  ASSERT_TRUE(status.has_value());
  EXPECT_EQ(status->num_ceiling_lights(), 1);
  EXPECT_EQ(status->num_table_lights(), 1);
  EXPECT_EQ(status->num_color_temperature_lights(), 1);
  EXPECT_TRUE(status->color_temperature_lights_known());
}
