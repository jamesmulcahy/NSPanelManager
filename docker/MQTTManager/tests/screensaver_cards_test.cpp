// The screensaver card settings that are sent to the panels in NSPanelConfig.

#include <gtest/gtest.h>
#include <nspanel/screensaver_cards.hpp>

using screensaver_cards::parse_cards;
using screensaver_cards::parse_seconds;

TEST(ScreensaverCards, empty_setting_means_no_cards) {
  EXPECT_TRUE(parse_cards("").empty());
  EXPECT_TRUE(parse_cards(" , ,").empty());
}

TEST(ScreensaverCards, calendar_with_seconds) {
  auto cards = parse_cards("calendar:15");

  ASSERT_EQ(cards.size(), 1u);
  EXPECT_EQ(cards[0].type, NSPanelConfig_NSPanelScreensaverCardType_SCREENSAVER_CARD_CALENDAR);
  EXPECT_EQ(cards[0].seconds, 15);
}

TEST(ScreensaverCards, energy_after_the_calendar) {
  auto cards = parse_cards("calendar:10, Energy:20");

  ASSERT_EQ(cards.size(), 2u);
  EXPECT_EQ(cards[0].type, NSPanelConfig_NSPanelScreensaverCardType_SCREENSAVER_CARD_CALENDAR);
  EXPECT_EQ(cards[1].type, NSPanelConfig_NSPanelScreensaverCardType_SCREENSAVER_CARD_ENERGY);
  EXPECT_EQ(cards[1].seconds, 20);
}

TEST(ScreensaverCards, missing_or_bad_seconds_fall_back_to_ten) {
  for (const char *setting : {"calendar", "calendar:", "calendar:abc", "calendar:12x", "calendar:1.5"}) {
    auto cards = parse_cards(setting);
    ASSERT_EQ(cards.size(), 1u) << setting;
    EXPECT_EQ(cards[0].seconds, 10) << setting;
  }
}

TEST(ScreensaverCards, seconds_are_limited_to_3_to_300) {
  EXPECT_EQ(parse_cards("calendar:1")[0].seconds, 3);
  EXPECT_EQ(parse_cards("calendar:-5")[0].seconds, 3);
  EXPECT_EQ(parse_cards("calendar:3")[0].seconds, 3);
  EXPECT_EQ(parse_cards("calendar:300")[0].seconds, 300);
  EXPECT_EQ(parse_cards("calendar:9999")[0].seconds, 300);
}

TEST(ScreensaverCards, unknown_types_are_skipped_and_the_rest_kept) {
  auto cards = parse_cards("doorbell:5, calendar:20 ,bogus,Calendar:7");

  ASSERT_EQ(cards.size(), 2u);
  EXPECT_EQ(cards[0].seconds, 20);
  EXPECT_EQ(cards[1].seconds, 7);
}

TEST(ScreensaverCards, base_card_seconds) {
  EXPECT_EQ(parse_seconds("10"), 10);
  EXPECT_EQ(parse_seconds(" 25 "), 25);
  EXPECT_EQ(parse_seconds(""), 10);
  EXPECT_EQ(parse_seconds("soon"), 10);
  EXPECT_EQ(parse_seconds("2"), 3);
  EXPECT_EQ(parse_seconds("1000"), 300);
}

TEST(ScreensaverCards, apply_to_config_fills_both_fields) {
  NSPanelConfig config;
  config.add_screensaver_cards()->set_seconds(99); // Replaced, not appended to

  screensaver_cards::apply_to_config(config, "calendar:15", "20");

  ASSERT_EQ(config.screensaver_cards_size(), 1);
  EXPECT_EQ(config.screensaver_cards(0).type(), NSPanelConfig_NSPanelScreensaverCardType_SCREENSAVER_CARD_CALENDAR);
  EXPECT_EQ(config.screensaver_cards(0).seconds(), 15);
  EXPECT_EQ(config.screensaver_base_card_seconds(), 20);
}
