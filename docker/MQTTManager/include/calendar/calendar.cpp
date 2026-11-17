#include "calendar.hpp"
#include "home_assistant_manager/home_assistant_manager.hpp"
#include "mqtt_manager/mqtt_manager.hpp"
#include "mqtt_manager_config/mqtt_manager_config.hpp"
#include <algorithm>
#include <boost/algorithm/string.hpp>
#include <cstdio>
#include <cstdlib>
#include <fmt/core.h>
#include <optional>
#include <protobuf_nspanel.pb.h>
#include <set>
#include <spdlog/spdlog.h>
#include <tuple>
#include <utility>

namespace {

// Wait at least this long between two fetches, however many state changes Home Assistant reports.
constexpr std::chrono::seconds FETCH_DEBOUNCE{10};

// Local time conversions use the process-wide TZ variable. This sets it for a scope and puts the old value back.
class ScopedTimezone {
public:
  explicit ScopedTimezone(const std::string &timezone) : _lock(mutex()) {
    const char *old = std::getenv("TZ");
    _had_old = old != nullptr;
    if (_had_old) {
      _old = old;
    }
    setenv("TZ", timezone.c_str(), 1);
    tzset();
  }

  ~ScopedTimezone() {
    if (_had_old) {
      setenv("TZ", _old.c_str(), 1);
    } else {
      unsetenv("TZ");
    }
    tzset();
  }

  ScopedTimezone(const ScopedTimezone &) = delete;
  ScopedTimezone &operator=(const ScopedTimezone &) = delete;

private:
  static std::mutex &mutex() {
    static std::mutex m;
    return m;
  }
  std::lock_guard<std::mutex> _lock;
  bool _had_old = false;
  std::string _old;
};

struct ParsedTime {
  std::time_t time;
  bool all_day;
};

// Parses what Home Assistant sends: "2026-11-15" (all-day, local midnight), or "2026-11-15T15:00:00-08:00" (offset used as is).
// A time without an offset is read as local time. Must be called with a ScopedTimezone active.
std::optional<ParsedTime> parse_time(const std::string &text) {
  int year = 0, month = 0, day = 0, consumed = 0;
  if (std::sscanf(text.c_str(), "%4d-%2d-%2d%n", &year, &month, &day, &consumed) < 3 || consumed == 0) {
    return std::nullopt;
  }
  if (month < 1 || month > 12 || day < 1 || day > 31) {
    return std::nullopt;
  }

  std::tm tm = {};
  tm.tm_year = year - 1900;
  tm.tm_mon = month - 1;
  tm.tm_mday = day;
  tm.tm_isdst = -1;

  const char *rest = text.c_str() + consumed;
  if (*rest == '\0') {
    return ParsedTime{std::mktime(&tm), true};
  }
  if (*rest != 'T' && *rest != ' ') {
    return std::nullopt;
  }
  rest++;

  int hour = 0, minute = 0, second = 0;
  consumed = 0;
  int fields = std::sscanf(rest, "%2d:%2d:%2d%n", &hour, &minute, &second, &consumed);
  if (fields < 3) {
    second = 0;
    consumed = 0;
    if (std::sscanf(rest, "%2d:%2d%n", &hour, &minute, &consumed) < 2) {
      return std::nullopt;
    }
  }
  if (hour > 24 || minute > 59 || second > 60) {
    return std::nullopt;
  }
  rest += consumed;
  if (*rest == '.') { // Fractions of a second
    rest++;
    while (*rest >= '0' && *rest <= '9') {
      rest++;
    }
  }
  tm.tm_hour = hour;
  tm.tm_min = minute;
  tm.tm_sec = second;

  if (*rest == '\0') {
    return ParsedTime{std::mktime(&tm), false};
  }
  if (*rest == '+' || *rest == '-') {
    int sign = (*rest == '+') ? 1 : -1;
    int offset_hours = 0, offset_minutes = 0;
    if (std::sscanf(rest + 1, "%2d:%2d", &offset_hours, &offset_minutes) < 2 && std::sscanf(rest + 1, "%2d%2d", &offset_hours, &offset_minutes) < 1) {
      return std::nullopt;
    }
    tm.tm_isdst = 0;
    return ParsedTime{timegm(&tm) - sign * (offset_hours * 3600 + offset_minutes * 60), false};
  } else if (*rest != 'Z' && *rest != 'z') {
    return std::nullopt;
  }
  tm.tm_isdst = 0;
  return ParsedTime{timegm(&tm), false}; // UTC
}

// Number of the local calendar day, only for comparing days.
long local_day_number(std::time_t time) {
  std::tm local = {};
  localtime_r(&time, &local);
  std::tm midnight_utc = {};
  midnight_utc.tm_year = local.tm_year;
  midnight_utc.tm_mon = local.tm_mon;
  midnight_utc.tm_mday = local.tm_mday;
  return static_cast<long>(timegm(&midnight_utc) / 86400);
}

const char *const WEEKDAYS[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
const char *const MONTHS[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};

std::string day_label(std::time_t time, long today) {
  long difference = local_day_number(time) - today;
  if (difference <= 0) {
    return "Today";
  } else if (difference == 1) {
    return "Tomorrow";
  }
  std::tm local = {};
  localtime_r(&time, &local);
  if (difference < 7) {
    return WEEKDAYS[local.tm_wday];
  }
  return fmt::format("{} {} {}", WEEKDAYS[local.tm_wday], local.tm_mday, MONTHS[local.tm_mon]);
}

std::string clock_string(std::time_t time, bool us_style) {
  std::tm local = {};
  localtime_r(&time, &local);
  if (us_style) {
    int hour12 = local.tm_hour % 12 == 0 ? 12 : local.tm_hour % 12;
    return fmt::format("{}:{:02d} {}", hour12, local.tm_min, local.tm_hour < 12 ? "AM" : "PM");
  }
  return fmt::format("{:02d}:{:02d}", local.tm_hour, local.tm_min);
}

struct Event {
  std::string summary;
  std::time_t start;
  std::time_t end;
  bool all_day;
};

} // namespace

std::string MQTTManagerCalendar::_cut_utf8(const std::string &text, size_t max_bytes) {
  if (text.size() <= max_bytes) {
    return text;
  }
  size_t cut = max_bytes;
  // text[cut] is the first byte that is left out. If it continues a character, that character started earlier and goes as well.
  while (cut > 0 && (static_cast<unsigned char>(text[cut]) & 0xC0) == 0x80) {
    cut--;
  }
  return text.substr(0, cut);
}

NSPanelCalendarUpdate MQTTManagerCalendar::process_events(const nlohmann::json &result, std::time_t now, const std::string &timezone, int max_events, int lookahead_hours, bool clock_us_style) {
  ScopedTimezone scoped_timezone(timezone);
  std::vector<Event> events;

  const nlohmann::json *calendars = &result;
  if (result.is_object() && result.contains("response") && result["response"].is_object()) {
    calendars = &result["response"];
  }

  if (calendars->is_object()) {
    for (const auto &calendar : calendars->items()) {
      if (!calendar.value().is_object() || !calendar.value().contains("events") || !calendar.value()["events"].is_array()) {
        continue;
      }
      for (const nlohmann::json &item : calendar.value()["events"]) {
        if (!item.is_object() || !item.contains("start") || !item["start"].is_string()) {
          continue;
        }
        auto start = parse_time(item["start"].get<std::string>());
        if (!start) {
          SPDLOG_WARN("Ignoring calendar event with unparseable start '{}'.", item["start"].get<std::string>());
          continue;
        }
        // The end is exclusive in Home Assistant's replies, also for all-day events. Without one the event takes no time (timed) or the day (all-day).
        std::time_t end = start->time;
        if (item.contains("end") && item["end"].is_string()) {
          if (auto parsed_end = parse_time(item["end"].get<std::string>())) {
            end = parsed_end->time;
          }
        } else if (start->all_day) {
          end = start->time + 24 * 3600;
        }
        if (end < start->time) {
          end = start->time;
        }
        if (end <= now) {
          continue; // Already over
        }
        std::string summary = item.contains("summary") && item["summary"].is_string() ? item["summary"].get<std::string>() : "";
        if (summary.empty()) {
          summary = "(No title)";
        }
        events.push_back({_cut_utf8(summary, MAX_SUMMARY_BYTES), start->time, end, start->all_day});
      }
    }
  }

  // Sorted by start, all-day events first among events that start together.
  std::sort(events.begin(), events.end(), [](const Event &a, const Event &b) {
    if (a.start != b.start) {
      return a.start < b.start;
    }
    if (a.all_day != b.all_day) {
      return a.all_day;
    }
    if (a.end != b.end) {
      return a.end < b.end;
    }
    return a.summary < b.summary;
  });

  // The same event invited to two calendars.
  std::set<std::tuple<std::string, std::time_t, std::time_t>> seen;
  std::vector<Event> unique_events;
  for (Event &event : events) {
    if (seen.insert({event.summary, event.start, event.end}).second) {
      unique_events.push_back(std::move(event));
    }
  }

  const size_t keep = static_cast<size_t>(std::max(max_events, 0));
  if (unique_events.size() > keep) {
    unique_events.resize(keep);
  }

  NSPanelCalendarUpdate update;
  const long today = local_day_number(now);
  for (const Event &event : unique_events) {
    NSPanelCalendarUpdate_Event *out = update.add_events();
    out->set_summary(event.summary);
    out->set_start(event.start);
    out->set_end(event.end);
    out->set_all_day(event.all_day);
    if (event.all_day) {
      out->set_when_string(day_label(event.start, today));
    } else if (event.start <= now) {
      out->set_when_string("Now");
    } else {
      out->set_when_string(fmt::format("{} {}", day_label(event.start, today), clock_string(event.start, clock_us_style)));
    }
  }
  update.set_lookahead_hours(lookahead_hours);
  update.set_generated_at(now > 0 ? now : 1); // Never 0, so that an empty list is not an empty (and so ignored) payload.

  // The panels drop anything larger than their MQTT buffer.
  while (update.events_size() > 0 && update.ByteSizeLong() > MAX_PAYLOAD_BYTES) {
    update.mutable_events()->RemoveLast();
  }
  return update;
}

std::string MQTTManagerCalendar::_topic() {
  return fmt::format("nspanel/mqttmanager_{}/status/calendar", MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::MANAGER_ADDRESS));
}

bool MQTTManagerCalendar::_all_calendars() {
  std::string value = MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::CALENDAR_ENTITY_IDS);
  boost::algorithm::trim(value);
  return boost::algorithm::iequals(value, "all");
}

void MQTTManagerCalendar::_set_observed_entities(std::vector<std::string> entities) {
  std::vector<std::string> old_entities;
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerCalendar::_mutex);
    old_entities = std::exchange(MQTTManagerCalendar::_observed_entities, entities);
  }
  for (const std::string &entity : old_entities) {
    if (std::find(entities.begin(), entities.end(), entity) == entities.end()) {
      HomeAssistantManager::detach_event_observer(entity, &MQTTManagerCalendar::home_assistant_event_callback);
    }
  }
  for (const std::string &entity : entities) {
    if (std::find(old_entities.begin(), old_entities.end(), entity) == old_entities.end()) {
      HomeAssistantManager::attach_event_observer(entity, &MQTTManagerCalendar::home_assistant_event_callback);
    }
  }
}

std::vector<std::string> MQTTManagerCalendar::_configured_entities() {
  if (MQTTManagerCalendar::_all_calendars()) {
    return {};
  }
  std::vector<std::string> parts;
  boost::algorithm::split(parts, MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::CALENDAR_ENTITY_IDS), boost::algorithm::is_any_of(","));
  std::vector<std::string> entities;
  for (std::string &part : parts) {
    boost::algorithm::trim(part);
    if (!part.empty() && std::find(entities.begin(), entities.end(), part) == entities.end()) {
      entities.push_back(part);
    }
  }
  return entities;
}

void MQTTManagerCalendar::start() {
  MQTTManagerCalendar::reload_config();
  HomeAssistantManager::attach_authenticated_observer(&MQTTManagerCalendar::home_assistant_authenticated_callback);
  if (!MQTTManagerCalendar::_instance.joinable()) {
    SPDLOG_INFO("No running instance of calendar manager found. Will start new thread.");
    MQTTManagerCalendar::_instance = std::thread(MQTTManagerCalendar::_run_thread);
  } else {
    SPDLOG_INFO("Calendar manager already running.");
  }
}

void MQTTManagerCalendar::reload_config() {
  // With "all" the calendars are not known until a fetch has answered, which then attaches the observers (see _handle_result).
  // Until then, and when the feature is off, there are none.
  std::vector<std::string> entities = MQTTManagerCalendar::_configured_entities();
  MQTTManagerCalendar::_set_observed_entities(entities);
  if (MQTTManagerCalendar::_all_calendars()) {
    SPDLOG_INFO("Calendar: all calendars configured.");
  } else {
    SPDLOG_INFO("Calendar: {} calendar(s) configured.", entities.size());
  }
  MQTTManagerCalendar::_request_fetch();
}

void MQTTManagerCalendar::_request_fetch() {
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerCalendar::_mutex);
    MQTTManagerCalendar::_fetch_requested = true;
  }
  MQTTManagerCalendar::_cv.notify_all();
}

void MQTTManagerCalendar::home_assistant_event_callback(nlohmann::json event_data) {
  // A calendar entity changes state when an event starts or ends and when the next event changes.
  MQTTManagerCalendar::_request_fetch();
}

void MQTTManagerCalendar::home_assistant_authenticated_callback() {
  MQTTManagerCalendar::_request_fetch();
}

void MQTTManagerCalendar::_run_thread() {
  while (true) {
    auto interval = std::chrono::minutes(std::max<uint32_t>(1, MqttManagerConfig::get_setting_with_default<uint32_t>(MQTT_MANAGER_SETTING::CALENDAR_UPDATE_INTERVAL)));
    {
      std::unique_lock<std::mutex> lock(MQTTManagerCalendar::_mutex);
      MQTTManagerCalendar::_cv.wait_for(lock, interval, [] { return MQTTManagerCalendar::_fetch_requested; });
      // Requests that arrive during the wait are served by the fetch that follows it.
      auto since_last_fetch = std::chrono::steady_clock::now() - MQTTManagerCalendar::_last_fetch;
      if (since_last_fetch < FETCH_DEBOUNCE) {
        auto remaining = FETCH_DEBOUNCE - since_last_fetch;
        MQTTManagerCalendar::_cv.wait_for(lock, remaining, [] { return false; });
      }
      MQTTManagerCalendar::_fetch_requested = false;
    }
    try {
      MQTTManagerCalendar::_fetch();
    } catch (const std::exception &e) {
      SPDLOG_ERROR("Calendar: caught exception while fetching events: {}", e.what());
    }
  }
}

void MQTTManagerCalendar::_fetch() {
  std::vector<std::string> entities = MQTTManagerCalendar::_configured_entities();
  bool home_assistant_configured = !MqttManagerConfig::get_setting_with_default<std::string>(MQTT_MANAGER_SETTING::HOME_ASSISTANT_ADDRESS).empty();

  bool all_calendars = MQTTManagerCalendar::_all_calendars();

  if ((entities.empty() && !all_calendars) || !home_assistant_configured) {
    // Feature off. Remove what an earlier run (or setting) left on the broker, once, so that the panels stop showing it.
    if (!MQTTManagerCalendar::_topic_cleared.exchange(true)) {
      SPDLOG_INFO("Calendar is not in use, will clear retained calendar topic.");
      MQTT_Manager::clear_retain(MQTTManagerCalendar::_topic());
      std::lock_guard<std::mutex> lock_guard(MQTTManagerCalendar::_mutex);
      MQTTManagerCalendar::_last_published.clear();
    }
    return;
  }
  if (!HomeAssistantManager::is_authenticated()) {
    SPDLOG_DEBUG("Calendar: Home Assistant not connected, will not fetch events.");
    return; // Publish nothing, the last retained list stays.
  }

  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerCalendar::_mutex);
    MQTTManagerCalendar::_last_fetch = std::chrono::steady_clock::now();
  }
  int hours = std::clamp<int>(MqttManagerConfig::get_setting_with_default<int32_t>(MQTT_MANAGER_SETTING::CALENDAR_LOOKAHEAD_HOURS), 1, 336);
  // Home Assistant answers "all" with every calendar, keyed by entity id. Without a target it answers 400.
  nlohmann::json target = all_calendars ? nlohmann::json{{"entity_id", "all"}} : nlohmann::json{{"entity_id", entities}};
  nlohmann::json service_data = {{"duration", {{"hours", hours}}}};
  HomeAssistantManager::call_service_with_response("calendar", "get_events", target, service_data, [](bool success, const nlohmann::json &result) {
    MQTTManagerCalendar::_handle_result(success, result, std::time(nullptr));
  });
}

void MQTTManagerCalendar::_handle_result(bool success, const nlohmann::json &result, std::time_t now) {
  if (!success) {
    SPDLOG_WARN("Calendar: fetching events from Home Assistant failed: {}", result.dump());
    return; // Publish nothing, the last retained list stays.
  }
  if (MQTTManagerCalendar::_all_calendars()) {
    // The calendars are whatever Home Assistant answered with. Follow their state changes from now on.
    std::vector<std::string> entities;
    const nlohmann::json *calendars = result.is_object() && result.contains("response") ? &result["response"] : &result;
    if (calendars->is_object()) {
      for (const auto &calendar : calendars->items()) {
        entities.push_back(calendar.key());
      }
    }
    std::sort(entities.begin(), entities.end());
    MQTTManagerCalendar::_set_observed_entities(std::move(entities));
  }

  int max_events = std::clamp<int>(MqttManagerConfig::get_setting_with_default<int32_t>(MQTT_MANAGER_SETTING::CALENDAR_MAX_EVENTS), 1, 10);
  int hours = std::clamp<int>(MqttManagerConfig::get_setting_with_default<int32_t>(MQTT_MANAGER_SETTING::CALENDAR_LOOKAHEAD_HOURS), 1, 336);
  bool us_style = MqttManagerConfig::get_setting_with_default<bool>(MQTT_MANAGER_SETTING::CLOCK_US_STYLE);

  NSPanelCalendarUpdate update = MQTTManagerCalendar::process_events(result, now, MqttManagerConfig::timezone, max_events, hours, us_style);
  MQTTManagerCalendar::_publish(update);
}

void MQTTManagerCalendar::_publish(NSPanelCalendarUpdate &update) {
  // Compare without the time of generation, which differs on every fetch.
  NSPanelCalendarUpdate comparable = update;
  comparable.set_generated_at(0);
  std::string comparable_bytes;
  std::string bytes;
  if (!comparable.SerializeToString(&comparable_bytes) || !update.SerializeToString(&bytes)) {
    SPDLOG_ERROR("Failed to serialize calendar update.");
    return;
  }
  {
    std::lock_guard<std::mutex> lock_guard(MQTTManagerCalendar::_mutex);
    if (comparable_bytes.compare(MQTTManagerCalendar::_last_published) == 0) {
      return;
    }
    MQTTManagerCalendar::_last_published = comparable_bytes;
  }
  MQTTManagerCalendar::_topic_cleared = false;
  SPDLOG_DEBUG("Sending {} calendar events.", update.events_size());
  MQTT_Manager::publish(MQTTManagerCalendar::_topic(), bytes, true);
}
