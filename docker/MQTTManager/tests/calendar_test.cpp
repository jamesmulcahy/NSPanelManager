// What MQTTManagerCalendar sends to the panels after a calendar.get_events reply from Home Assistant.

#include "test_helpers.hpp"
#include <calendar/calendar.hpp>
#include <ctime>
#include <map>
#include <gtest/gtest.h>
#include <protobuf_nspanel.pb.h>

namespace {

// A POSIX rule rather than "America/Los_Angeles", so the tests do not depend on tzdata being installed. US Pacific time.
const std::string PACIFIC = "PST8PDT,M3.2.0,M11.1.0";

std::time_t utc(int year, int month, int day, int hour = 0, int minute = 0) {
  std::tm tm = {};
  tm.tm_year = year - 1900;
  tm.tm_mon = month - 1;
  tm.tm_mday = day;
  tm.tm_hour = hour;
  tm.tm_min = minute;
  return timegm(&tm);
}

// Sunday 2026-11-15 12:00 in Pacific time (UTC-8).
const std::time_t NOW = utc(2026, 11, 15, 20, 0);

nlohmann::json event(const std::string &summary, const std::string &start, const std::string &end) {
  return {{"summary", summary}, {"start", start}, {"end", end}};
}

// The "result" of a calendar.get_events call with return_response.
nlohmann::json reply(const std::map<std::string, std::vector<nlohmann::json>> &calendars) {
  nlohmann::json response = nlohmann::json::object();
  for (const auto &[entity, events] : calendars) {
    response[entity] = {{"events", events}};
  }
  return {{"response", response}};
}

NSPanelCalendarUpdate process(const nlohmann::json &result, int max_events = 5, bool us_style = true, std::time_t now = NOW) {
  return MQTTManagerCalendar::process_events(result, now, PACIFIC, max_events, 48, us_style);
}

std::vector<std::string> summaries(const NSPanelCalendarUpdate &update) {
  std::vector<std::string> names;
  for (const auto &item : update.events()) {
    names.push_back(item.summary());
  }
  return names;
}

bool valid_utf8(const std::string &text) {
  size_t i = 0;
  while (i < text.size()) {
    unsigned char lead = text[i];
    size_t length = lead < 0x80 ? 1 : (lead >> 5) == 0x6 ? 2 : (lead >> 4) == 0xE ? 3 : (lead >> 3) == 0x1E ? 4 : 0;
    if (length == 0 || i + length > text.size()) {
      return false;
    }
    for (size_t j = 1; j < length; j++) {
      if ((static_cast<unsigned char>(text[i + j]) & 0xC0) != 0x80) {
        return false;
      }
    }
    i += length;
  }
  return true;
}

std::string repeat(const std::string &text, int times) {
  std::string out;
  for (int i = 0; i < times; i++) {
    out += text;
  }
  return out;
}

} // namespace

TEST(CalendarProcessing, timed_events_use_their_offset_and_get_a_when_string) {
  auto update = process(reply({{"calendar.family", {
                                                       event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00"),
                                                       event("Soccer", "2026-11-16T09:00:00-08:00", "2026-11-16T10:30:00-08:00"),
                                                       event("Brunch", "2026-11-21T09:00:00-08:00", "2026-11-21T11:00:00-08:00"),
                                                   }}}));

  ASSERT_EQ(update.events_size(), 3);
  EXPECT_EQ(update.events(0).summary(), "Dentist");
  EXPECT_EQ(update.events(0).start(), utc(2026, 11, 15, 23, 0));
  EXPECT_EQ(update.events(0).end(), utc(2026, 11, 16, 0, 0));
  EXPECT_FALSE(update.events(0).all_day());
  EXPECT_EQ(update.events(0).when_string(), "Today 3:00 PM");
  EXPECT_EQ(update.events(1).when_string(), "Tomorrow 9:00 AM");
  EXPECT_EQ(update.events(2).when_string(), "Sat 9:00 AM");
}

TEST(CalendarProcessing, offsets_of_other_zones_and_utc_are_honoured) {
  auto update = process(reply({{"calendar.x", {
                                                  event("Utc", "2026-11-15T23:00:00Z", "2026-11-16T00:00:00Z"),
                                                  event("Berlin", "2026-11-16T10:00:00+01:00", "2026-11-16T11:00:00+01:00"),
                                              }}}));

  ASSERT_EQ(update.events_size(), 2);
  EXPECT_EQ(update.events(0).start(), utc(2026, 11, 15, 23, 0));
  EXPECT_EQ(update.events(1).start(), utc(2026, 11, 16, 9, 0));
  EXPECT_EQ(update.events(0).when_string(), "Today 3:00 PM");
}

TEST(CalendarProcessing, twenty_four_hour_clock_when_not_us_style) {
  auto update = process(reply({{"calendar.x", {event("Dentist", "2026-11-15T15:05:00-08:00", "2026-11-15T16:00:00-08:00"),
                                               event("Early", "2026-11-16T00:30:00-08:00", "2026-11-16T01:00:00-08:00")}}}),
                        5, false);

  ASSERT_EQ(update.events_size(), 2);
  EXPECT_EQ(update.events(0).when_string(), "Today 15:05");
  EXPECT_EQ(update.events(1).when_string(), "Tomorrow 00:30");
}

TEST(CalendarProcessing, us_clock_shows_midnight_and_noon_as_twelve) {
  auto update = process(reply({{"calendar.x", {event("Noon", "2026-11-16T12:00:00-08:00", "2026-11-16T13:00:00-08:00"),
                                               event("Midnight", "2026-11-16T00:00:00-08:00", "2026-11-16T00:30:00-08:00")}}}));

  ASSERT_EQ(update.events_size(), 2);
  EXPECT_EQ(update.events(0).when_string(), "Tomorrow 12:00 AM");
  EXPECT_EQ(update.events(1).when_string(), "Tomorrow 12:00 PM");
}

TEST(CalendarProcessing, all_day_events_are_local_midnight_with_an_exclusive_end) {
  auto update = process(reply({{"calendar.x", {
                                                  event("Bin day", "2026-11-16", "2026-11-17"),
                                                  event("Birthday", "2026-11-21", "2026-11-22"),
                                              }}}));

  ASSERT_EQ(update.events_size(), 2);
  EXPECT_TRUE(update.events(0).all_day());
  EXPECT_EQ(update.events(0).start(), utc(2026, 11, 16, 8, 0)); // Midnight Pacific
  EXPECT_EQ(update.events(0).end(), utc(2026, 11, 17, 8, 0));
  EXPECT_EQ(update.events(0).when_string(), "Tomorrow");
  EXPECT_EQ(update.events(1).when_string(), "Sat");
}

TEST(CalendarProcessing, all_day_event_today_says_today) {
  auto update = process(reply({{"calendar.x", {event("Holiday", "2026-11-15", "2026-11-16")}}}));

  ASSERT_EQ(update.events_size(), 1);
  EXPECT_EQ(update.events(0).when_string(), "Today");
}

TEST(CalendarProcessing, multi_day_all_day_event_runs_to_the_end_date) {
  auto update = process(reply({{"calendar.x", {event("Trip", "2026-11-16", "2026-11-19")}}}));

  ASSERT_EQ(update.events_size(), 1);
  EXPECT_EQ(update.events(0).start(), utc(2026, 11, 16, 8, 0));
  EXPECT_EQ(update.events(0).end(), utc(2026, 11, 19, 8, 0));
}

TEST(CalendarProcessing, multi_day_all_day_event_in_progress_says_today) {
  auto update = process(reply({{"calendar.x", {event("Trip", "2026-11-13", "2026-11-17")}}}));

  ASSERT_EQ(update.events_size(), 1);
  EXPECT_EQ(update.events(0).when_string(), "Today");
}

TEST(CalendarProcessing, all_day_events_come_first_among_events_starting_together) {
  auto update = process(reply({{"calendar.x", {event("Meeting", "2026-11-16T00:00:00-08:00", "2026-11-16T01:00:00-08:00"),
                                               event("Bin day", "2026-11-16", "2026-11-17")}}}));

  EXPECT_EQ(summaries(update), (std::vector<std::string>{"Bin day", "Meeting"}));
}

TEST(CalendarProcessing, in_progress_events_are_kept_and_ended_ones_dropped) {
  auto update = process(reply({{"calendar.x", {
                                                  event("Over", "2026-11-15T09:00:00-08:00", "2026-11-15T10:00:00-08:00"),
                                                  event("Yesterday", "2026-11-14", "2026-11-15"),
                                                  event("Lunch", "2026-11-15T11:00:00-08:00", "2026-11-15T13:00:00-08:00"),
                                                  event("Ends right now", "2026-11-15T11:00:00-08:00", "2026-11-15T12:00:00-08:00"),
                                              }}}));

  EXPECT_EQ(summaries(update), (std::vector<std::string>{"Lunch"}));
  EXPECT_EQ(update.events(0).when_string(), "Now");
}

TEST(CalendarProcessing, calendars_are_merged_sorted_and_duplicates_dropped) {
  auto update = process(reply({
      {"calendar.family", {event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00"), event("Soccer", "2026-11-16T09:00:00-08:00", "2026-11-16T10:00:00-08:00")}},
      {"calendar.work", {event("Standup", "2026-11-15T13:00:00-08:00", "2026-11-15T13:15:00-08:00"), event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00")}},
  }));

  EXPECT_EQ(summaries(update), (std::vector<std::string>{"Standup", "Dentist", "Soccer"}));
}

TEST(CalendarProcessing, same_summary_at_a_different_time_is_not_a_duplicate) {
  auto update = process(reply({{"calendar.x", {event("Gym", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00"),
                                               event("Gym", "2026-11-15T18:00:00-08:00", "2026-11-15T19:00:00-08:00")}}}));

  EXPECT_EQ(update.events_size(), 2);
}

TEST(CalendarProcessing, only_the_first_max_events_are_kept) {
  std::vector<nlohmann::json> events;
  for (int i = 8; i >= 1; i--) { // Out of order on purpose
    events.push_back(event("Event " + std::to_string(i), fmt::format("2026-11-15T{:02d}:00:00-08:00", 12 + i), fmt::format("2026-11-15T{:02d}:30:00-08:00", 12 + i)));
  }

  auto update = process(reply({{"calendar.x", events}}), 3);

  EXPECT_EQ(summaries(update), (std::vector<std::string>{"Event 1", "Event 2", "Event 3"}));
}

TEST(CalendarProcessing, summary_is_cut_at_64_bytes_on_a_character_boundary) {
  std::string emoji = "\xF0\x9F\x8E\x89";     // 4 bytes
  std::string cjk = "\xE6\x97\xA5";           // 3 bytes
  std::string long_ascii(100, 'a');
  auto update = process(reply({{"calendar.x", {
                                                  event(repeat(emoji, 30), "2026-11-15T13:00:00-08:00", "2026-11-15T14:00:00-08:00"),
                                                  event(repeat(cjk, 30), "2026-11-15T14:00:00-08:00", "2026-11-15T15:00:00-08:00"),
                                                  event("ab" + repeat(emoji, 30), "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00"),
                                                  event(long_ascii, "2026-11-15T16:00:00-08:00", "2026-11-15T17:00:00-08:00"),
                                                  event("Short", "2026-11-15T17:00:00-08:00", "2026-11-15T18:00:00-08:00"),
                                              }}}),
                        10);

  ASSERT_EQ(update.events_size(), 5);
  EXPECT_EQ(update.events(0).summary(), repeat(emoji, 16)); // 64 bytes exactly
  EXPECT_EQ(update.events(1).summary(), repeat(cjk, 21));   // 63 bytes, 64 would split a character
  EXPECT_EQ(update.events(2).summary(), "ab" + repeat(emoji, 15)); // 62 bytes
  EXPECT_EQ(update.events(3).summary(), std::string(64, 'a'));
  EXPECT_EQ(update.events(4).summary(), "Short");
  for (const auto &item : update.events()) {
    EXPECT_LE(item.summary().size(), 64u);
    EXPECT_TRUE(valid_utf8(item.summary()));
  }
}

TEST(CalendarProcessing, description_and_location_are_not_sent) {
  nlohmann::json detailed = event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00");
  detailed["description"] = "Bring the insurance card DESCRIPTION-MARKER";
  detailed["location"] = "12 Main Street LOCATION-MARKER";

  auto update = process(reply({{"calendar.x", {detailed}}}));

  ASSERT_EQ(update.events_size(), 1);
  std::string bytes;
  ASSERT_TRUE(update.SerializeToString(&bytes));
  EXPECT_EQ(bytes.find("DESCRIPTION-MARKER"), std::string::npos);
  EXPECT_EQ(bytes.find("LOCATION-MARKER"), std::string::npos);
}

TEST(CalendarProcessing, an_empty_reply_is_still_a_non_empty_payload_with_the_window) {
  auto update = process(reply({{"calendar.x", {}}}));

  EXPECT_EQ(update.events_size(), 0);
  EXPECT_EQ(update.lookahead_hours(), 48);
  EXPECT_EQ(update.generated_at(), NOW);
  std::string bytes;
  ASSERT_TRUE(update.SerializeToString(&bytes));
  EXPECT_FALSE(bytes.empty());
}

TEST(CalendarProcessing, a_reply_without_calendars_is_also_non_empty) {
  auto update = process(nlohmann::json::object());

  EXPECT_EQ(update.events_size(), 0);
  EXPECT_NE(update.generated_at(), 0);
}

TEST(CalendarProcessing, malformed_events_are_ignored) {
  auto update = process(reply({{"calendar.x", {
                                                  nlohmann::json{{"summary", "No start"}},
                                                  event("Bad start", "tomorrow-ish", "2026-11-16"),
                                                  event("Fine", "2026-11-16T09:00:00-08:00", "2026-11-16T10:00:00-08:00"),
                                              }}}));

  EXPECT_EQ(summaries(update), (std::vector<std::string>{"Fine"}));
}

TEST(CalendarProcessing, the_payload_is_kept_under_the_panels_buffer) {
  std::vector<nlohmann::json> events;
  for (int i = 0; i < 100; i++) {
    events.push_back(event(std::string(60, 'a' + i % 26), fmt::format("2026-11-16T{:02d}:{:02d}:00-08:00", i / 60, i % 60), fmt::format("2026-11-16T{:02d}:{:02d}:00-08:00", 5 + i / 60, i % 60)));
  }

  auto update = process(reply({{"calendar.x", events}}), 1000);

  EXPECT_GT(update.events_size(), 10);
  EXPECT_LT(update.events_size(), 100);
  EXPECT_LE(update.ByteSizeLong(), 3500u);
  EXPECT_EQ(update.events(0).start(), utc(2026, 11, 16, 8, 0)); // The first ones are the ones kept
}

// An all-day event across the end of daylight saving time (2026-11-01): its midnights are 73 hours apart.
TEST(CalendarProcessing, all_day_event_across_a_dst_change_uses_local_midnights) {
  auto update = process(reply({{"calendar.x", {event("Long weekend", "2026-10-31", "2026-11-03")}}}), 5, true, utc(2026, 10, 30, 19, 0));

  ASSERT_EQ(update.events_size(), 1);
  EXPECT_EQ(update.events(0).start(), utc(2026, 10, 31, 7, 0)); // Midnight PDT (UTC-7)
  EXPECT_EQ(update.events(0).end(), utc(2026, 11, 3, 8, 0));    // Midnight PST (UTC-8)
  EXPECT_EQ(update.events(0).end() - update.events(0).start(), 73 * 3600);
  EXPECT_EQ(update.events(0).when_string(), "Tomorrow");
}

TEST(CalendarProcessing, processing_does_not_change_the_process_timezone) {
  setenv("TZ", "UTC", 1);
  tzset();

  process(reply({{"calendar.x", {event("Bin day", "2026-11-16", "2026-11-17")}}}));

  EXPECT_STREQ(std::getenv("TZ"), "UTC");
}

// Publishing

class CalendarPublishTest : public nspm_test::SendCaptureTest {
protected:
  void SetUp() override {
    SendCaptureTest::SetUp();
    MQTTManagerCalendar::test_reset();
    _saved_timezone = MqttManagerConfig::timezone;
    MqttManagerConfig::timezone = PACIFIC;
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CLOCK_US_STYLE, "True");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CALENDAR_MAX_EVENTS, "5");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CALENDAR_LOOKAHEAD_HOURS, "48");
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CALENDAR_ENTITY_IDS, "");
  }

  void TearDown() override {
    MqttManagerConfig::timezone = _saved_timezone;
    MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CLOCK_US_STYLE, "False");
    HomeAssistantManager::test_set_authenticated(false);
    MQTTManagerCalendar::test_reset();
  }

  static std::vector<NSPanelCalendarUpdate> published() {
    std::vector<NSPanelCalendarUpdate> updates;
    for (auto &message : MQTT_Manager::test_take_published_messages()) {
      if (message.topic.ends_with("/status/calendar")) {
        EXPECT_TRUE(message.retain);
        NSPanelCalendarUpdate update;
        EXPECT_TRUE(update.ParseFromString(message.payload));
        updates.push_back(update);
      }
    }
    return updates;
  }

private:
  std::string _saved_timezone;
};

TEST_F(CalendarPublishTest, a_reply_is_published_retained) {
  auto result = reply({{"calendar.x", {event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00")}}});

  MQTTManagerCalendar::test_handle_result(true, result, NOW);

  auto updates = published();
  ASSERT_EQ(updates.size(), 1u);
  EXPECT_EQ(summaries(updates[0]), (std::vector<std::string>{"Dentist"}));
  EXPECT_EQ(updates[0].generated_at(), NOW);
}

TEST_F(CalendarPublishTest, an_unchanged_list_is_not_published_again) {
  auto result = reply({{"calendar.x", {event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00")}}});
  MQTTManagerCalendar::test_handle_result(true, result, NOW);
  published();

  MQTTManagerCalendar::test_handle_result(true, result, NOW + 300);
  EXPECT_TRUE(published().empty());

  auto changed = reply({{"calendar.x", {event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00"), event("Soccer", "2026-11-16T09:00:00-08:00", "2026-11-16T10:00:00-08:00")}}});
  MQTTManagerCalendar::test_handle_result(true, changed, NOW + 600);
  EXPECT_EQ(published().size(), 1u);
}

TEST_F(CalendarPublishTest, a_failed_fetch_publishes_nothing) {
  MQTTManagerCalendar::test_handle_result(false, nlohmann::json{{"code", "unknown_error"}}, NOW);

  EXPECT_TRUE(published().empty());
}

TEST_F(CalendarPublishTest, the_settings_limit_the_list) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CALENDAR_MAX_EVENTS, "1");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CALENDAR_LOOKAHEAD_HOURS, "72");
  auto result = reply({{"calendar.x", {event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00"), event("Soccer", "2026-11-16T09:00:00-08:00", "2026-11-16T10:00:00-08:00")}}});

  MQTTManagerCalendar::test_handle_result(true, result, NOW);

  auto updates = published();
  ASSERT_EQ(updates.size(), 1u);
  EXPECT_EQ(updates[0].events_size(), 1);
  EXPECT_EQ(updates[0].lookahead_hours(), 72);
}

TEST_F(CalendarPublishTest, a_fetch_asks_home_assistant_for_all_calendars_at_once) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, "http://ha.invalid:8123");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CALENDAR_ENTITY_IDS, "calendar.family, calendar.work,,calendar.family");
  HomeAssistantManager::test_set_authenticated(true);
  HomeAssistantManager::test_take_sent_messages();

  MQTTManagerCalendar::test_fetch();

  auto sent = HomeAssistantManager::test_take_sent_messages();
  ASSERT_EQ(sent.size(), 1u);
  EXPECT_EQ(sent[0]["type"], "call_service");
  EXPECT_EQ(sent[0]["domain"], "calendar");
  EXPECT_EQ(sent[0]["service"], "get_events");
  EXPECT_EQ(sent[0]["return_response"], true);
  EXPECT_EQ(sent[0]["target"]["entity_id"], (nlohmann::json{"calendar.family", "calendar.work"}));
  EXPECT_EQ(sent[0]["service_data"]["duration"]["hours"], 48);

  // The reply publishes the list.
  nlohmann::json result = reply({{"calendar.family", {event("Dentist", "2026-11-15T15:00:00-08:00", "2026-11-15T16:00:00-08:00")}}});
  result["response"]["calendar.family"]["events"][0]["start"] = "2099-01-01T10:00:00-08:00";
  result["response"]["calendar.family"]["events"][0]["end"] = "2099-01-01T11:00:00-08:00";
  HomeAssistantManager::test_deliver_result(sent[0]["id"].get<long>(), result);
  auto updates = published();
  ASSERT_EQ(updates.size(), 1u);
  EXPECT_EQ(summaries(updates[0]), (std::vector<std::string>{"Dentist"}));

  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, "");
}

TEST_F(CalendarPublishTest, nothing_is_fetched_or_published_while_home_assistant_is_disconnected) {
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, "http://ha.invalid:8123");
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::CALENDAR_ENTITY_IDS, "calendar.family");
  HomeAssistantManager::test_set_authenticated(false);
  HomeAssistantManager::test_take_sent_messages();

  MQTTManagerCalendar::test_fetch();

  EXPECT_TRUE(HomeAssistantManager::test_take_sent_messages().empty());
  EXPECT_TRUE(published().empty());
  MqttManagerConfig::set_setting_value(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS, "");
}

TEST_F(CalendarPublishTest, turning_the_feature_off_clears_the_retained_topic_once) {
  size_t before = MQTT_Manager::test_buffered_message_count();

  MQTTManagerCalendar::test_fetch();
  size_t after_first = MQTT_Manager::test_buffered_message_count();
  MQTTManagerCalendar::test_fetch();
  size_t after_second = MQTT_Manager::test_buffered_message_count();

  EXPECT_EQ(after_first, before + 1);
  EXPECT_EQ(after_second, after_first);
  EXPECT_TRUE(published().empty());
}
