#ifndef MQTT_MANAGER_SCREENSAVER_CARDS_HPP
#define MQTT_MANAGER_SCREENSAVER_CARDS_HPP

#include <algorithm>
#include <boost/algorithm/string.hpp>
#include <cerrno>
#include <cstdlib>
#include <protobuf_nspanel.pb.h>
#include <spdlog/spdlog.h>
#include <string>
#include <vector>

// Parsing of the "screensaver_cards" and "screensaver_base_card_seconds" settings, which are sent to the panels in NSPanelConfig.
namespace screensaver_cards {

constexpr int DEFAULT_SECONDS = 10;
constexpr int MIN_SECONDS = 3;
constexpr int MAX_SECONDS = 300;

struct Card {
  NSPanelConfig_NSPanelScreensaverCardType type;
  int seconds;
};

// A number of seconds from a setting. Missing or invalid gives the default, anything else is limited to 3-300.
inline int parse_seconds(const std::string &text) {
  std::string trimmed = boost::algorithm::trim_copy(text);
  if (trimmed.empty()) {
    return DEFAULT_SECONDS;
  }
  char *end = nullptr;
  errno = 0;
  long value = std::strtol(trimmed.c_str(), &end, 10);
  if (errno != 0 || end == trimmed.c_str() || *end != '\0') {
    return DEFAULT_SECONDS;
  }
  return static_cast<int>(std::clamp(value, static_cast<long>(MIN_SECONDS), static_cast<long>(MAX_SECONDS)));
}

// "calendar:10,calendar:15" -> cards, in order. Unknown card types are logged and skipped.
inline std::vector<Card> parse_cards(const std::string &setting) {
  std::vector<Card> cards;
  std::vector<std::string> items;
  boost::algorithm::split(items, setting, boost::algorithm::is_any_of(","));
  for (std::string &item : items) {
    boost::algorithm::trim(item);
    if (item.empty()) {
      continue;
    }
    std::string name = item;
    std::string seconds;
    size_t colon = item.find(':');
    if (colon != std::string::npos) {
      name = item.substr(0, colon);
      seconds = item.substr(colon + 1);
    }
    boost::algorithm::trim(name);
    boost::algorithm::to_lower(name);

    if (name.compare("calendar") == 0) {
      cards.push_back({NSPanelConfig_NSPanelScreensaverCardType_SCREENSAVER_CARD_CALENDAR, parse_seconds(seconds)});
    } else {
      SPDLOG_WARN("Unknown screensaver card type '{}' in setting '{}'. Will skip it.", name, setting);
    }
  }
  return cards;
}

// Fill the card fields of a panel config from the setting strings.
inline void apply_to_config(NSPanelConfig &config, const std::string &cards_setting, const std::string &base_card_seconds_setting) {
  config.clear_screensaver_cards();
  for (const Card &card : parse_cards(cards_setting)) {
    NSPanelConfig_ScreensaverCard *added = config.add_screensaver_cards();
    added->set_type(card.type);
    added->set_seconds(card.seconds);
  }
  config.set_screensaver_base_card_seconds(parse_seconds(base_card_seconds_setting));
}

} // namespace screensaver_cards

#endif // !MQTT_MANAGER_SCREENSAVER_CARDS_HPP
