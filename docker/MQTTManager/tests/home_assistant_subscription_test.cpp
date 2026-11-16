// HomeAssistantManager::subscribe and send_command_with_response: subscriptions that outlive reconnects, and one-shot
// commands other than call_service.

#include "test_helpers.hpp"
#include <gtest/gtest.h>
#include <home_assistant_manager/home_assistant_manager.hpp>
#include <vector>

namespace {

struct Received {
  bool success;
  nlohmann::json event;
};

class HomeAssistantSubscriptionTest : public nspm_test::SendCaptureTest {
protected:
  void SetUp() override {
    SendCaptureTest::SetUp();
    HomeAssistantManager::test_set_authenticated(true);
  }

  void TearDown() override {
    for (long handle : handles) {
      HomeAssistantManager::unsubscribe(handle);
    }
    HomeAssistantManager::test_disconnect();
    HomeAssistantManager::test_set_authenticated(false);
    HomeAssistantManager::test_take_sent_messages();
  }

  std::vector<long> handles;
  std::vector<Received> received;

  long subscribe_template(const std::string &text, std::vector<Received> &into) {
    long handle = HomeAssistantManager::subscribe({{"type", "render_template"}, {"template", text}},
                                                  [&into](bool success, const nlohmann::json &event) { into.push_back({success, event}); });
    handles.push_back(handle);
    return handle;
  }
};

} // namespace

TEST_F(HomeAssistantSubscriptionTest, sends_the_command_when_connected) {
  long handle = subscribe_template("{{ 1 }}", received);

  auto sent = HomeAssistantManager::test_take_sent_messages();
  ASSERT_EQ(sent.size(), 1u);
  EXPECT_EQ(sent[0]["type"], "render_template");
  EXPECT_EQ(sent[0]["template"], "{{ 1 }}");
  EXPECT_EQ(sent[0]["id"].get<long>(), HomeAssistantManager::test_subscription_id(handle));
  EXPECT_GT(handle, 0);
}

TEST_F(HomeAssistantSubscriptionTest, routes_events_to_their_own_subscription) {
  std::vector<Received> other;
  long first = subscribe_template("{{ 1 }}", received);
  long second = subscribe_template("{{ 2 }}", other);

  HomeAssistantManager::test_deliver_event(HomeAssistantManager::test_subscription_id(first), {{"result", 6}});
  HomeAssistantManager::test_deliver_event(HomeAssistantManager::test_subscription_id(second), {{"result", 3577}});
  HomeAssistantManager::test_deliver_event(HomeAssistantManager::test_subscription_id(first), {{"result", 7}});

  ASSERT_EQ(received.size(), 2u);
  EXPECT_TRUE(received[0].success);
  EXPECT_EQ(received[0].event["result"], 6);
  EXPECT_EQ(received[1].event["result"], 7);
  ASSERT_EQ(other.size(), 1u);
  EXPECT_EQ(other[0].event["result"], 3577);
}

TEST_F(HomeAssistantSubscriptionTest, waits_for_the_connection_and_resubscribes_after_a_reconnect) {
  HomeAssistantManager::test_disconnect();
  long handle = subscribe_template("{{ 1 }}", received);
  EXPECT_TRUE(HomeAssistantManager::test_take_sent_messages().empty());
  EXPECT_EQ(HomeAssistantManager::test_subscription_id(handle), 0);

  HomeAssistantManager::test_authenticate();
  auto sent = HomeAssistantManager::test_take_sent_messages();
  ASSERT_EQ(sent.size(), 1u);
  long first_id = sent[0]["id"].get<long>();
  EXPECT_EQ(HomeAssistantManager::test_subscription_id(handle), first_id);

  HomeAssistantManager::test_disconnect();
  EXPECT_EQ(HomeAssistantManager::test_subscription_id(handle), 0);
  HomeAssistantManager::test_authenticate();
  sent = HomeAssistantManager::test_take_sent_messages();
  ASSERT_EQ(sent.size(), 1u);
  EXPECT_EQ(sent[0]["template"], "{{ 1 }}");
  long second_id = sent[0]["id"].get<long>();
  EXPECT_NE(second_id, first_id);

  // The old connection's id means nothing now.
  HomeAssistantManager::test_deliver_event(first_id, {{"result", 1}});
  EXPECT_TRUE(received.empty());
  HomeAssistantManager::test_deliver_event(second_id, {{"result", 2}});
  ASSERT_EQ(received.size(), 1u);
  EXPECT_EQ(received[0].event["result"], 2);
}

TEST_F(HomeAssistantSubscriptionTest, sends_an_active_subscription_once_per_connection) {
  long handle = subscribe_template("{{ 1 }}", received);
  HomeAssistantManager::test_take_sent_messages();

  HomeAssistantManager::test_authenticate(); // Already active on this connection

  EXPECT_TRUE(HomeAssistantManager::test_take_sent_messages().empty());
  EXPECT_NE(HomeAssistantManager::test_subscription_id(handle), 0);
}

TEST_F(HomeAssistantSubscriptionTest, unsubscribe_sends_unsubscribe_events_and_stops_delivery) {
  long handle = subscribe_template("{{ 1 }}", received);
  long id = HomeAssistantManager::test_subscription_id(handle);
  HomeAssistantManager::test_take_sent_messages();

  HomeAssistantManager::unsubscribe(handle);

  auto sent = HomeAssistantManager::test_take_sent_messages();
  ASSERT_EQ(sent.size(), 1u);
  EXPECT_EQ(sent[0]["type"], "unsubscribe_events");
  EXPECT_EQ(sent[0]["subscription"].get<long>(), id);
  HomeAssistantManager::test_deliver_event(id, {{"result", 1}});
  EXPECT_TRUE(received.empty());

  HomeAssistantManager::test_disconnect();
  HomeAssistantManager::test_authenticate();
  EXPECT_TRUE(HomeAssistantManager::test_take_sent_messages().empty());
}

TEST_F(HomeAssistantSubscriptionTest, unsubscribing_while_disconnected_sends_nothing) {
  long handle = subscribe_template("{{ 1 }}", received);
  HomeAssistantManager::test_disconnect();
  HomeAssistantManager::test_take_sent_messages();

  HomeAssistantManager::unsubscribe(handle);
  HomeAssistantManager::unsubscribe(handle); // Unknown now: ignored

  EXPECT_TRUE(HomeAssistantManager::test_take_sent_messages().empty());
}

TEST_F(HomeAssistantSubscriptionTest, a_refused_subscription_reports_once_and_is_retried_on_the_next_connection) {
  long handle = subscribe_template("{{ broken", received);
  long id = HomeAssistantManager::test_subscription_id(handle);

  HomeAssistantManager::test_deliver_result(id, {{"code", "template_error"}, {"message", "unexpected end of template"}}, false);

  ASSERT_EQ(received.size(), 1u);
  EXPECT_FALSE(received[0].success);
  EXPECT_EQ(received[0].event["code"], "template_error");
  EXPECT_EQ(HomeAssistantManager::test_subscription_id(handle), 0);

  HomeAssistantManager::test_take_sent_messages();
  HomeAssistantManager::test_disconnect();
  HomeAssistantManager::test_authenticate();
  EXPECT_EQ(HomeAssistantManager::test_take_sent_messages().size(), 1u);
}

TEST_F(HomeAssistantSubscriptionTest, a_successful_result_for_the_subscribe_command_is_not_an_event) {
  long handle = subscribe_template("{{ 1 }}", received);

  HomeAssistantManager::test_deliver_result(HomeAssistantManager::test_subscription_id(handle), nullptr, true);

  EXPECT_TRUE(received.empty());
  EXPECT_NE(HomeAssistantManager::test_subscription_id(handle), 0);
}

TEST_F(HomeAssistantSubscriptionTest, send_command_with_response_pairs_the_reply) {
  std::vector<Received> replies;
  long id = HomeAssistantManager::send_command_with_response({{"type", "get_config"}}, [&replies](bool success, const nlohmann::json &result) { replies.push_back({success, result}); });

  auto sent = HomeAssistantManager::test_take_sent_messages();
  ASSERT_EQ(sent.size(), 1u);
  EXPECT_EQ(sent[0]["type"], "get_config");
  EXPECT_EQ(sent[0]["id"].get<long>(), id);

  HomeAssistantManager::test_deliver_result(id, {{"currency", "USD"}});
  ASSERT_EQ(replies.size(), 1u);
  EXPECT_TRUE(replies[0].success);
  EXPECT_EQ(replies[0].event["currency"], "USD");
}

TEST_F(HomeAssistantSubscriptionTest, send_command_with_response_fails_at_once_when_disconnected) {
  HomeAssistantManager::test_disconnect();
  std::vector<Received> replies;

  long id = HomeAssistantManager::send_command_with_response({{"type", "get_config"}}, [&replies](bool success, const nlohmann::json &result) { replies.push_back({success, result}); });

  EXPECT_EQ(id, 0);
  ASSERT_EQ(replies.size(), 1u);
  EXPECT_FALSE(replies[0].success);
}
