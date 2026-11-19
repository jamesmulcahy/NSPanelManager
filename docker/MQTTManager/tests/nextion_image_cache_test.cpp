#include <gtest/gtest.h>
#include <memory>
#include <mutex>
#include <nextion_image_server/nextion_image_server.hpp>
#include <string>

// Exercises the converted image cache of NextionImageServer: LRU eviction when it is full.
class NextionImageCacheTest : public ::testing::Test {
protected:
  using Server = NextionImageServer;

  void SetUp() override {
    Server::_converted_images.clear();
    source = std::make_shared<const std::string>("album art");
  }

  void TearDown() override {
    Server::_converted_images.clear();
  }

  static Server::ConvertedImageKey key(uint32_t id) {
    return {.media_player_id = id, .width = 100, .height = 100, .format = Server::ImageFormat::RGB565};
  }

  void store(uint32_t id) {
    std::lock_guard<std::mutex> lock(Server::_converted_images_mutex);
    Server::_store_cached_image(key(id), source, std::make_shared<const Server::ConvertedImage>(Server::ConvertedImage{.width = 100, .height = 100, .data = ""}));
  }

  bool cached(uint32_t id) {
    std::lock_guard<std::mutex> lock(Server::_converted_images_mutex);
    return Server::_find_cached_image(key(id), source) != nullptr;
  }

  void fill() {
    for (uint32_t id = 0; id < Server::max_converted_images; id++) {
      store(id);
    }
  }

  std::shared_ptr<const std::string> source;
};

TEST_F(NextionImageCacheTest, EvictsOnlyTheLeastRecentlyUsedEntryWhenFull) {
  fill();
  ASSERT_EQ(Server::_converted_images.size(), Server::max_converted_images);

  store(1000);

  EXPECT_EQ(Server::_converted_images.size(), Server::max_converted_images);
  EXPECT_TRUE(cached(1000));
  // Entry 0 was stored first and never used again, so it is the one evicted.
  EXPECT_EQ(Server::_converted_images.count(key(0)), 0u);
  for (uint32_t id = 1; id < Server::max_converted_images; id++) {
    EXPECT_EQ(Server::_converted_images.count(key(id)), 1u) << "entry " << id << " was evicted";
  }
}

TEST_F(NextionImageCacheTest, RecentlyHitEntrySurvivesEviction) {
  fill();
  // Entry 0 would be evicted next, a hit makes entry 1 the oldest instead.
  EXPECT_TRUE(cached(0));

  store(1000);

  EXPECT_EQ(Server::_converted_images.count(key(0)), 1u);
  EXPECT_EQ(Server::_converted_images.count(key(1)), 0u);
  EXPECT_EQ(Server::_converted_images.size(), Server::max_converted_images);
}

TEST_F(NextionImageCacheTest, EvictsInLeastRecentlyUsedOrderAcrossInsertions) {
  fill();
  EXPECT_TRUE(cached(0));
  EXPECT_TRUE(cached(1));

  store(1000);
  store(1001);

  // 2 and 3 were the least recently used, 0 and 1 were hit after everything was stored.
  EXPECT_EQ(Server::_converted_images.count(key(2)), 0u);
  EXPECT_EQ(Server::_converted_images.count(key(3)), 0u);
  EXPECT_EQ(Server::_converted_images.count(key(0)), 1u);
  EXPECT_EQ(Server::_converted_images.count(key(1)), 1u);
  EXPECT_EQ(Server::_converted_images.size(), Server::max_converted_images);
}

TEST_F(NextionImageCacheTest, ReplacingAnExistingKeyEvictsNothing) {
  fill();

  store(5);

  EXPECT_EQ(Server::_converted_images.size(), Server::max_converted_images);
  for (uint32_t id = 0; id < Server::max_converted_images; id++) {
    EXPECT_EQ(Server::_converted_images.count(key(id)), 1u) << "entry " << id << " was evicted";
  }
}

TEST_F(NextionImageCacheTest, ChangedSourceIsAMiss) {
  store(1);
  EXPECT_TRUE(cached(1));

  source = std::make_shared<const std::string>("different album art");
  EXPECT_FALSE(cached(1));
}
