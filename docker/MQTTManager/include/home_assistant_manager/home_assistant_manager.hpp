#ifndef MQTT_MANAGER_HOME_ASSISTANT_MANAGER_HPP
#define MQTT_MANAGER_HOME_ASSISTANT_MANAGER_HPP

#include <atomic>
#include <boost/ptr_container/ptr_map.hpp>
#include <boost/signals2.hpp>
#include <chrono>
#include <functional>
#include <ixwebsocket/IXWebSocket.h>
#include <ixwebsocket/IXWebSocketMessage.h>
#include <mutex>
#include <nlohmann/json_fwd.hpp>
#include <string>
#include <unordered_map>

#if defined(TEST_MODE) && TEST_MODE == 1
#include <nlohmann/json.hpp>
#include <utility>
#include <vector>
#endif

class HomeAssistantManager {
public:
  static void init(); // Start a new thread and connect to HA.

  static void connect();

  /*
   * Reload config from DB and if needed, reconnect.
   */
  static void reload_config();

  static void send_json(nlohmann::json &data); // Helper to convert from JSON to std::string and then send

  // Called with the outcome of a request. On success `result` is the "result" member of Home Assistant's reply; on
  // failure (error reply, lost connection or no reply within 30 s) it is the error object, or null.
  using ResultCallback = std::function<void(bool success, const nlohmann::json &result)>;

  /**
   * Call a Home Assistant service that returns data and hand the reply to `callback`. Sends
   * {"type":"call_service", domain, service, target, service_data, "return_response":true}.
   * The callback is invoked exactly once, never while an internal lock is held and possibly on another thread, and is
   * failed with success=false if Home Assistant is not connected, the connection is lost, or 30 s pass without a reply.
   * Returns the message id used for the request, or 0 if it was failed without being sent.
   */
  static long call_service_with_response(const std::string &domain, const std::string &service, nlohmann::json target, nlohmann::json service_data, ResultCallback callback);

  /**
   * Send any one-shot command (e.g. {"type":"get_config"}) and hand the reply to `callback`, with the same guarantees as
   * call_service_with_response(). The "id" member is set here.
   */
  static long send_command_with_response(nlohmann::json command, ResultCallback callback);

  // Called with each event of a subscription: success=true and the "event" member of the message. If Home Assistant
  // refuses the subscribe command, it is called once with success=false and the error.
  using SubscriptionCallback = std::function<void(bool success, const nlohmann::json &event)>;

  /**
   * Keep a subscription (e.g. {"type":"render_template","template":"..."}) open for as long as the manager runs: it
   * is sent now if Home Assistant is connected, and again after every (re)connect, so callers need not watch the
   * connection. Callbacks run on the websocket thread, never while an internal lock is held, and must not block.
   * Returns a handle for unsubscribe().
   */
  static long subscribe(nlohmann::json command, SubscriptionCallback callback);

  // Stop a subscription. Sends unsubscribe_events if it is active. Unknown handles are ignored.
  static void unsubscribe(long handle);

  // True while connected to and authenticated with Home Assistant.
  static bool is_authenticated() { return HomeAssistantManager::_authenticated; }

  /**
   * Attach a function that is called every time authentication with Home Assistant succeeds (including after a reconnect).
   * It runs on the websocket thread, so it must not block.
   */
  template <typename CALLBACK_BIND>
  static void attach_authenticated_observer(CALLBACK_BIND callback) {
    HomeAssistantManager::_authenticated_observers.disconnect(callback);
    HomeAssistantManager::_authenticated_observers.connect(callback);
  }

  template <typename CALLBACK_BIND>
  static void detach_authenticated_observer(CALLBACK_BIND callback) {
    HomeAssistantManager::_authenticated_observers.disconnect(callback);
  }

  /**
   * Attach an event listener to handle Openhab events.
   */
  template <typename CALLBACK_BIND>
  static void attach_event_observer(std::string item, CALLBACK_BIND callback) {
    HomeAssistantManager::_home_assistant_observers[item].disconnect(callback); // Disconnect first in case it was already connected, otherwise multiple signals will be sent.
    HomeAssistantManager::_home_assistant_observers[item].connect(callback);
    HomeAssistantManager::_request_all_states();
  }

  /**
   * Detach an event listener for Openhab events.
   */
  template <typename CALLBACK_BIND>
  static void detach_event_observer(std::string item, CALLBACK_BIND callback) {
    HomeAssistantManager::_home_assistant_observers[item].disconnect(callback);
  }

#if defined(TEST_MODE) && TEST_MODE == 1
  // Pretend to be connected to and authenticated with Home Assistant, so that requests are sent.
  static void test_set_authenticated(bool authenticated) {
    HomeAssistantManager::_connected = authenticated;
    HomeAssistantManager::_authenticated = authenticated;
  }

  // Deliver a "result" message for a request id as if it had been received from Home Assistant.
  static void test_deliver_result(long id, const nlohmann::json &result, bool success = true) {
    nlohmann::json message = {{"type", "result"}, {"id", id}, {"success", success}};
    message[success ? "result" : "error"] = result;
    HomeAssistantManager::_process_websocket_message(message.dump());
  }

  // Do what happens when the websocket closes.
  static void test_disconnect() { HomeAssistantManager::_handle_connection_lost(); }

  // Deliver a raw message as if received from Home Assistant.
  static void test_process_websocket_message(const std::string &message) { HomeAssistantManager::_process_websocket_message(message); }

  // Deliver an event message for a request id as if it had been received from Home Assistant.
  static void test_deliver_event(long id, const nlohmann::json &event) {
    nlohmann::json message = {{"type", "event"}, {"id", id}, {"event", event}};
    HomeAssistantManager::_process_websocket_message(message.dump());
  }

  // Do what happens when authentication succeeds, without the state requests (which tests take as sent messages).
  static void test_authenticate() {
    HomeAssistantManager::_connected = true;
    HomeAssistantManager::_authenticated = true;
    HomeAssistantManager::_resubscribe_all();
  }

  // The websocket id a subscription is active under; 0: not active.
  static long test_subscription_id(long handle) {
    std::lock_guard<std::mutex> lock_guard(HomeAssistantManager::_subscriptions_mutex);
    auto it = HomeAssistantManager::_subscriptions.find(handle);
    return it == HomeAssistantManager::_subscriptions.end() ? 0 : it->second.id;
  }

  static size_t test_pending_call_count() {
    std::lock_guard<std::mutex> lock_guard(HomeAssistantManager::_pending_calls_mutex);
    return HomeAssistantManager::_pending_calls.size();
  }

  // Called with each message just after it has been recorded as sent, before send_json returns. Lets a test answer a request "instantly".
  static void test_set_send_hook(std::function<void(const nlohmann::json &)> hook) {
    std::lock_guard<std::mutex> lock_guard(HomeAssistantManager::_test_sent_messages_mutex);
    HomeAssistantManager::_test_send_hook = std::move(hook);
  }

  // Fail the pending calls that have passed their deadline at `now`.
  static void test_expire_pending_calls(std::chrono::steady_clock::time_point now) { HomeAssistantManager::_expire_pending_calls(now); }

  // Everything passed to send_json since the last call, whether or not Home Assistant is connected.
  static std::vector<nlohmann::json> test_take_sent_messages() {
    std::lock_guard<std::mutex> lock_guard(HomeAssistantManager::_test_sent_messages_mutex);
    return std::exchange(HomeAssistantManager::_test_sent_messages, {});
  }

  // Deliver an event as if it had been received from Home Assistant.
  static void test_process_event(nlohmann::json &event_data) {
    HomeAssistantManager::_process_home_assistant_event(event_data);
  }
#endif

private:
#if defined(TEST_MODE) && TEST_MODE == 1
  static inline std::mutex _test_sent_messages_mutex;
  static inline std::vector<nlohmann::json> _test_sent_messages;
  static inline std::function<void(const nlohmann::json &)> _test_send_hook;
#endif

  static void _send_json_with_id(nlohmann::json &data, long id);

  struct PendingCall {
    ResultCallback callback;
    std::chrono::steady_clock::time_point deadline;
  };
  static inline std::mutex _pending_calls_mutex;
  static inline std::unordered_map<long, PendingCall> _pending_calls;
  static constexpr std::chrono::seconds _pending_call_timeout{30};
  static void _complete_pending_call(long id, bool success, const nlohmann::json &result);
  static void _fail_pending_calls(bool all, std::chrono::steady_clock::time_point now);
  static void _expire_pending_calls(std::chrono::steady_clock::time_point now = std::chrono::steady_clock::now()) { HomeAssistantManager::_fail_pending_calls(false, now); }
  static void _handle_connection_lost(); // Marks the connection as down and fails every pending call.

  struct Subscription {
    std::string command; // Serialised: the header only forward-declares nlohmann::json
    SubscriptionCallback callback;
    long id = 0; // The websocket id it is active under; 0: not sent on this connection
  };
  static inline std::mutex _subscriptions_mutex;
  static inline std::unordered_map<long, Subscription> _subscriptions; // By handle
  static inline std::unordered_map<long, long> _subscription_handles;   // Websocket id -> handle
  static inline std::atomic<long> _next_subscription_handle = 1;
  static void _send_subscription(long handle); // Sends it unless it is already active on this connection.
  static void _resubscribe_all();
  // Hand a message for a subscription's id to it. False: the id is not a subscription's.
  static bool _process_subscription_message(long id, const nlohmann::json &data);

  static inline boost::signals2::signal<void()> _authenticated_observers;

  // Request all states that Home Assistant has as there is no way to only request state of one object.
  static void _request_all_states();

  static inline boost::ptr_map<std::string, boost::signals2::signal<void(nlohmann::json data)>> _home_assistant_observers;
  static void _process_home_assistant_event(nlohmann::json &event_data);

  static inline std::mutex _mutex_websocket_write_access; // Mutex to prevent simultaneous write access to WebSocket
  static void _send_auth();                               // Send login information when authentication is required.
  static void _send_string(std::string &data);            // Lowest level send function. Will handle mutex.

  static inline ix::WebSocket *_websocket = nullptr;
  static void _websocket_message_callback(const ix::WebSocketMessagePtr &msg);
  static void _process_websocket_message(const std::string &data);

  static inline std::atomic<bool> _authenticated = false;
  static inline std::atomic<bool> _connected = false;
  static inline std::atomic<long> _next_message_id = 1;
  static inline std::atomic<long> _all_statues_request_message_id;

  static inline std::mutex _settings_mutex;
  static inline std::string _home_assistant_address;
  static inline std::string _home_assistant_token;
};

#endif // !MQTT_MANAGER_HOME_ASSISTANT_MANAGER_HPP
