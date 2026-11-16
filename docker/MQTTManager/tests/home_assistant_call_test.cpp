// HomeAssistantManager::call_service_with_response: pairing replies with the calls that asked for them.

#include "test_helpers.hpp"
#include <chrono>
#include <gtest/gtest.h>
#include <home_assistant_manager/home_assistant_manager.hpp>
#include <vector>

namespace {

struct Reply {
  bool success;
  nlohmann::json result;
};

class HomeAssistantCallTest : public nspm_test::SendCaptureTest {
protected:
  void SetUp() override {
    SendCaptureTest::SetUp();
    HomeAssistantManager::test_set_authenticated(true);
  }

  void TearDown() override {
    HomeAssistantManager::test_set_send_hook(nullptr);
    HomeAssistantManager::test_disconnect(); // Fails (and so removes) anything a test left pending
    HomeAssistantManager::test_set_authenticated(false);
  }

  long call(std::vector<Reply> &replies) {
    return HomeAssistantManager::call_service_with_response("calendar", "get_events", {{"entity_id", {"calendar.family"}}}, {{"duration", {{"hours", 48}}}},
                                                            [&replies](bool success, const nlohmann::json &result) { replies.push_back({success, result}); });
  }
};

} // namespace

TEST_F(HomeAssistantCallTest, sends_a_call_service_asking_for_the_response) {
  std::vector<Reply> replies;

  long id = call(replies);

  auto sent = HomeAssistantManager::test_take_sent_messages();
  ASSERT_EQ(sent.size(), 1u);
  EXPECT_EQ(sent[0]["type"], "call_service");
  EXPECT_EQ(sent[0]["domain"], "calendar");
  EXPECT_EQ(sent[0]["service"], "get_events");
  EXPECT_EQ(sent[0]["target"], (nlohmann::json{{"entity_id", {"calendar.family"}}}));
  EXPECT_EQ(sent[0]["service_data"], (nlohmann::json{{"duration", {{"hours", 48}}}}));
  EXPECT_EQ(sent[0]["return_response"], true);
  EXPECT_EQ(sent[0]["id"].get<long>(), id);
  EXPECT_GT(id, 0);
  EXPECT_TRUE(replies.empty());
}

TEST_F(HomeAssistantCallTest, the_callback_fires_once_for_its_own_id) {
  std::vector<Reply> first, second;
  long first_id = call(first);
  long second_id = call(second);
  EXPECT_NE(first_id, second_id);

  HomeAssistantManager::test_deliver_result(second_id, {{"response", {{"calendar.family", {{"events", nlohmann::json::array()}}}}}});

  EXPECT_TRUE(first.empty());
  ASSERT_EQ(second.size(), 1u);
  EXPECT_TRUE(second[0].success);
  EXPECT_TRUE(second[0].result["response"].contains("calendar.family"));

  // A second reply with the same id has nobody to go to.
  HomeAssistantManager::test_deliver_result(second_id, {{"again", true}});
  EXPECT_EQ(second.size(), 1u);
  EXPECT_TRUE(first.empty());
  EXPECT_EQ(HomeAssistantManager::test_pending_call_count(), 1u);
}

TEST_F(HomeAssistantCallTest, a_reply_to_an_unknown_id_is_ignored) {
  std::vector<Reply> replies;
  call(replies);

  HomeAssistantManager::test_deliver_result(987654, {{"ignored", true}});

  EXPECT_TRUE(replies.empty());
  EXPECT_EQ(HomeAssistantManager::test_pending_call_count(), 1u);
}

TEST_F(HomeAssistantCallTest, an_error_reply_fails_the_call_with_the_error) {
  std::vector<Reply> replies;
  long id = call(replies);

  HomeAssistantManager::test_deliver_result(id, {{"code", "home_assistant_error"}, {"message", "boom"}}, false);

  ASSERT_EQ(replies.size(), 1u);
  EXPECT_FALSE(replies[0].success);
  EXPECT_EQ(replies[0].result["code"], "home_assistant_error");
  EXPECT_EQ(HomeAssistantManager::test_pending_call_count(), 0u);
}

TEST_F(HomeAssistantCallTest, a_reply_that_arrives_before_the_send_returns_is_delivered) {
  HomeAssistantManager::test_set_send_hook([](const nlohmann::json &message) {
    HomeAssistantManager::test_deliver_result(message["id"].get<long>(), {{"fast", true}});
  });
  std::vector<Reply> replies;

  call(replies);

  ASSERT_EQ(replies.size(), 1u);
  EXPECT_TRUE(replies[0].success);
  EXPECT_EQ(replies[0].result["fast"], true);
}

TEST_F(HomeAssistantCallTest, disconnecting_fails_every_pending_call) {
  std::vector<Reply> first, second;
  call(first);
  call(second);

  HomeAssistantManager::test_disconnect();

  ASSERT_EQ(first.size(), 1u);
  ASSERT_EQ(second.size(), 1u);
  EXPECT_FALSE(first[0].success);
  EXPECT_FALSE(second[0].success);
  EXPECT_EQ(HomeAssistantManager::test_pending_call_count(), 0u);
  EXPECT_FALSE(HomeAssistantManager::is_authenticated());
}

TEST_F(HomeAssistantCallTest, a_call_while_disconnected_fails_at_once_without_sending) {
  HomeAssistantManager::test_set_authenticated(false);
  std::vector<Reply> replies;

  long id = call(replies);

  EXPECT_EQ(id, 0);
  ASSERT_EQ(replies.size(), 1u);
  EXPECT_FALSE(replies[0].success);
  EXPECT_TRUE(HomeAssistantManager::test_take_sent_messages().empty());
  EXPECT_EQ(HomeAssistantManager::test_pending_call_count(), 0u);
}

TEST_F(HomeAssistantCallTest, calls_without_a_reply_expire_after_30_seconds) {
  std::vector<Reply> replies;
  call(replies);
  auto now = std::chrono::steady_clock::now();

  HomeAssistantManager::test_expire_pending_calls(now + std::chrono::seconds(20));
  EXPECT_TRUE(replies.empty());

  HomeAssistantManager::test_expire_pending_calls(now + std::chrono::seconds(31));
  ASSERT_EQ(replies.size(), 1u);
  EXPECT_FALSE(replies[0].success);
  EXPECT_EQ(HomeAssistantManager::test_pending_call_count(), 0u);
}

TEST_F(HomeAssistantCallTest, other_results_are_left_alone) {
  std::vector<Reply> replies;
  call(replies);

  // A reply to a plain send_json() request, which is not in the pending map.
  nlohmann::json plain = {{"type", "get_states"}};
  HomeAssistantManager::send_json(plain);
  HomeAssistantManager::test_deliver_result(plain["id"].get<long>(), nlohmann::json::array());

  EXPECT_TRUE(replies.empty());
  EXPECT_EQ(HomeAssistantManager::test_pending_call_count(), 1u);
}
