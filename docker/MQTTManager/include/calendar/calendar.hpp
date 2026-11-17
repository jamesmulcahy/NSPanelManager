#include "protobuf_nspanel.pb.h"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <ctime>
#include <mutex>
#include <nlohmann/json.hpp>
#include <string>
#include <thread>
#include <vector>
#ifndef MQTT_MANAGER_CALENDAR
#define MQTT_MANAGER_CALENDAR

// Fetches upcoming events from Home Assistant calendars and publishes them, merged into one list, for the panels'
// screensaver calendar card on nspanel/mqttmanager_<manager address>/status/calendar.
//
// The calendar_entity_ids setting is "" (off), "all" (every calendar in Home Assistant) or a comma separated list of entity ids.
class MQTTManagerCalendar {
public:
  /**
   * Load config and start the thread that fetches events.
   */
  static void start();

  /**
   * Load new values from config and fetch again.
   */
  static void reload_config();

  /**
   * Trigger for state changes of the configured calendar entities in Home Assistant.
   */
  static void home_assistant_event_callback(nlohmann::json event_data);

  /**
   * Trigger for Home Assistant having (re)connected.
   */
  static void home_assistant_authenticated_callback();

  /**
   * Turn the reply to a calendar.get_events call into the update for the panels. Pure: depends on nothing but its arguments.
   *
   * @param result The "result" of the call: {"response": {"calendar.x": {"events": [{start, end, summary, ...}]}}}.
   * @param now Current time, Unix seconds. Events that ended before it are dropped.
   * @param timezone TZ name or POSIX rule. All-day events are bare dates and start at local midnight in it.
   * @param max_events At most this many events are kept.
   * @param lookahead_hours Sent to the panels as the window the list covers.
   * @param clock_us_style 12 hour "3:00 PM" when true, otherwise 24 hour "15:00".
   */
  static NSPanelCalendarUpdate process_events(const nlohmann::json &result, std::time_t now, const std::string &timezone, int max_events, int lookahead_hours, bool clock_us_style);

  static constexpr size_t MAX_SUMMARY_BYTES = 64;
  static constexpr size_t MAX_PAYLOAD_BYTES = 3500;

#if defined(TEST_MODE) && TEST_MODE == 1
  // Handle the reply to a fetch as if it had just arrived.
  static void test_handle_result(bool success, const nlohmann::json &result, std::time_t now) { MQTTManagerCalendar::_handle_result(success, result, now); }

  // Fetch now, without waiting for the thread, ignoring the debounce.
  static void test_fetch() { MQTTManagerCalendar::_fetch(); }

  // Forget what has been published or cleared.
  static void test_reset() {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerCalendar::_mutex);
    MQTTManagerCalendar::_last_published.clear();
    MQTTManagerCalendar::_topic_cleared = false;
  }

  // Entities that have a state change observer attached right now.
  static std::vector<std::string> test_observed_entities() {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerCalendar::_mutex);
    return MQTTManagerCalendar::_observed_entities;
  }

  // Detach all observers and forget them.
  static void test_detach_observers() { MQTTManagerCalendar::_set_observed_entities({}); }
#endif

private:
  static inline std::thread _instance;
  static inline std::mutex _mutex;
  static inline std::condition_variable _cv;
  static inline bool _fetch_requested = false;
  static inline std::vector<std::string> _observed_entities;
  static inline std::chrono::steady_clock::time_point _last_fetch;

  // Last payload published, to avoid sending the same list again. The time it was generated at is not part of it.
  static inline std::string _last_published;
  // True once the retained topic has been cleared, until something is published again.
  static inline std::atomic<bool> _topic_cleared = false;

  static void _run_thread();
  static void _request_fetch();
  static std::string _topic();

  // Ask Home Assistant for the events (or clear the topic when the feature is off).
  static void _fetch();
  static void _handle_result(bool success, const nlohmann::json &result, std::time_t now);
  static void _publish(NSPanelCalendarUpdate &update);

  // The configured calendars. Empty for "all" as well as when the feature is off, see _all_calendars().
  static std::vector<std::string> _configured_entities();

  // True when the setting is the reserved value "all": every calendar in Home Assistant, including ones added later.
  static bool _all_calendars();

  // Make these the entities with a state change observer, attaching and detaching the difference.
  static void _set_observed_entities(std::vector<std::string> entities);
  static std::string _cut_utf8(const std::string &text, size_t max_bytes);
};

#endif // !MQTT_MANAGER_CALENDAR
