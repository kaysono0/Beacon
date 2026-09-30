#include "platform/platform_adapter.h"

#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "beacon/protocol_json.h"

namespace {

bool ParseJsonOrLog(const std::string& json, Json::Value* root, const char* test_id) {
  if (beacon::ParseJson(json, root)) {
    return true;
  }
  std::cerr << test_id << " response is not valid json: " << json << "\n";
  return false;
}

bool HasSingleCallResultWithResourceRef(const beacon::CallbackExecutionResult& execution,
                                        const std::string& expected_resource_ref,
                                        const char* test_id) {
  const bool has_resource_ref =
      execution.matched && execution.call_results.size() == 1U &&
      execution.call_results[0].call.resource_ref == expected_resource_ref;
  if (!has_resource_ref) {
    std::cerr << test_id << " callback context resource_ref mismatch\n";
  }
  return has_resource_ref;
}

bool HasExecutionContext(const beacon::CallbackExecutionResult& execution, const std::string& expected_provider,
                         const std::string& expected_resource_ref, const std::string& expected_instance_id,
                         uint64_t expected_sequence, const char* test_id) {
  if (!execution.matched) {
    std::cerr << test_id << " callback execution did not match\n";
    return false;
  }
  if (execution.context.provider != expected_provider ||
      execution.context.resource_ref != expected_resource_ref ||
      execution.context.instance_id != expected_instance_id ||
      execution.context.sequence != expected_sequence) {
    std::cerr << test_id << " callback execution context mismatch\n";
    return false;
  }
  return true;
}

std::string Invoke(beacon::mac::PlatformAdapter& adapter, const std::string& function,
                   const std::string& params_json) {
  return adapter.kernel().HandleRequest(
      std::string(
          R"({"common":{"action":"invokeRequest","op_id":"op-real","timestamp_ms":1},"data":{"node_id":"mac-real-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":")") +
      function + R"("},"params":")" + params_json + R"("}]}})");
}

std::string InvokeWithFields(beacon::mac::PlatformAdapter& adapter, const std::string& function,
                             const std::string& params_json, const std::string& fields_json) {
  return adapter.kernel().HandleRequest(
      std::string(
          R"({"common":{"action":"invokeRequest","op_id":"op-real-fields","timestamp_ms":1},"data":{"node_id":"mac-real-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":")") +
      function + R"("},"params":")" + params_json + R"(",)" + fields_json + R"(}]}})");
}

std::string InvokePreview(beacon::mac::PlatformAdapter& adapter, const std::string& function,
                          const std::string& params_json) {
  return adapter.kernel().HandleRequest(
      std::string(
          R"({"common":{"action":"invokeRequest","op_id":"op-preview","timestamp_ms":1},"data":{"node_id":"mac-real-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"video_preview","class_name":"AgoraRtcEngineKit","function":")") +
      function + R"("},"params":")" + params_json + R"("}]}})");
}

std::string InvokeVisual(beacon::mac::PlatformAdapter& adapter, const std::string& function,
                         const std::string& params_json) {
  return adapter.kernel().HandleRequest(
      std::string(
          R"({"common":{"action":"invokeRequest","op_id":"op-visual","timestamp_ms":1},"data":{"node_id":"mac-real-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"visual_probe","class_name":"AgoraVisualProbe","function":")") +
      function + R"("},"params":")" + params_json + R"("}]}})");
}

std::string InvokeMediaPlayer(beacon::mac::PlatformAdapter& adapter, const std::string& function,
                              const std::string& params_json) {
  return adapter.kernel().HandleRequest(
      std::string(
          R"({"common":{"action":"invokeRequest","op_id":"op-media-player","timestamp_ms":1},"data":{"node_id":"mac-real-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"media_player","class_name":"AgoraRtcMediaPlayerProtocol","function":")") +
      function + R"("},"params":")" + params_json + R"("}]}})");
}

std::string InvokeLifecycle(beacon::mac::PlatformAdapter& adapter, const std::string& function,
                            const std::string& params_json) {
  return adapter.kernel().HandleRequest(
      std::string(
          R"({"common":{"action":"invokeRequest","op_id":"op-lifecycle","timestamp_ms":1},"data":{"node_id":"mac-real-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"SDKLifecycle","function":")") +
      function + R"("},"params":")" + params_json + R"("}]}})");
}

bool EnsureSDKLoaded(beacon::mac::PlatformAdapter& adapter, const char* test_id) {
  // 真实 Adapter 单测只验证本地引擎创建和调用路由，不连接 Agora 服务；未提供真实配置时
  // 使用格式合法的测试 App ID，避免把缺失的测试前置条件误报为 SDK 加载失败。
  if (const char* app_id = std::getenv("AGORA_APP_ID"); app_id == nullptr || app_id[0] == '\0') {
    setenv("AGORA_APP_ID", "0123456789abcdef0123456789abcdef", 0);
  }
  const auto response = InvokeLifecycle(adapter, "loadSDK", "{}");
  const bool ok = response.find("\"code\":0") != std::string::npos;
  if (!ok) {
    std::cerr << test_id << " loadSDK response: " << response << "\n";
  }
  return ok;
}

std::string JoinParams(const std::string& channel, int uid) {
  const char* token = std::getenv("AGORA_RTC_TOKEN");
  if (token != nullptr && token[0] != '\0') {
    return std::string(R"({\"channel\":\")") + channel + R"(\",\"uid\":)" + std::to_string(uid) +
           R"(,\"token\":\")" + token + R"(\"})";
  }
  return std::string(R"({\"channel\":\")") + channel + R"(\",\"uid\":)" + std::to_string(uid) + "}";
}

void PumpRunLoopForMs(int ms) {
  NSDate* until = [NSDate dateWithTimeIntervalSinceNow:static_cast<NSTimeInterval>(ms) / 1000.0];
  [[NSRunLoop currentRunLoop] runUntilDate:until];
}

void AttachPreviewView(beacon::mac::PlatformAdapter& adapter, const std::string& view_id) {
  static NSMutableArray<NSWindow*>* preview_windows = nil;
  if (preview_windows == nil) {
    preview_windows = [[NSMutableArray alloc] init];
  }
  NSWindow* window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 320, 240)
                                                 styleMask:NSWindowStyleMaskTitled
                                                   backing:NSBackingStoreBuffered
                                                     defer:NO];
  [window setTitle:@"Beacon Test Preview Host"];
  [window orderFrontRegardless];
  [preview_windows addObject:window];
  NSView* view = [window contentView];
  adapter.views().Attach(view_id, (__bridge void*)view);
}

bool HasResponseCode(const std::string& response, int expected_code, const char* test_id) {
  Json::Value root;
  if (!ParseJsonOrLog(response, &root, test_id)) {
    return false;
  }
  const int code = root["data"].get("code", -1).asInt();
  if (code != expected_code) {
    std::cerr << test_id << " expected code " << expected_code << " response: " << response << "\n";
    return false;
  }
  return true;
}

bool ResponseResultContains(const std::string& response, const std::string& expected, const char* test_id) {
  Json::Value root;
  if (!ParseJsonOrLog(response, &root, test_id)) {
    return false;
  }
  const std::string result = root["data"]["list"][0].get("result", "").asString();
  if (result.find(expected) == std::string::npos) {
    std::cerr << test_id << " expected result containing " << expected << " response: " << response << "\n";
    return false;
  }
  return true;
}

int BridgeMacReal01() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  return adapter.Bind() == beacon::kOk && adapter.rtc().registered() ? 0 : 1;
}

int BridgeMacReal02() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "BRIDGE-MAC-REAL-02")) {
    return 1;
  }
  auto result = Invoke(adapter, "joinChannel", JoinParams("real-smoke", 1001));
  const bool ok = result.find("\"code\":0") != std::string::npos;
  Invoke(adapter, "leaveChannel", "{}");
  adapter.Destroy();
  return ok ? 0 : 1;
}

int ITAgora04() {
  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "IT-AGORA-04")) {
    return 1;
  }
  AttachPreviewView(adapter, "local_preview");
  adapter.events().SetNodeId("mac-real-001");
  auto preview = InvokePreview(adapter, "startPreview", "{}");
  return preview.find("\"code\":0") != std::string::npos && adapter.rtc().previewing() ? 0 : 1;
}

int ITAgoraVisualProbe() {
  Class delegate_class = NSClassFromString(@"BeaconAgoraDelegate");
  SEL first_frame_selector = @selector(rtcEngine:firstRemoteVideoFrameOfUid:size:elapsed:);
  SEL snapshot_selector = @selector(rtcEngine:snapshotTaken:filePath:width:height:errCode:);
  if (delegate_class == Nil || ![delegate_class instancesRespondToSelector:first_frame_selector] ||
      ![delegate_class instancesRespondToSelector:snapshot_selector]) {
    std::cerr << "IT-AGORA visual delegate selectors are not implemented\n";
    return 1;
  }

  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "IT-AGORA-VISUAL-PROBE")) {
    return 1;
  }
  AttachPreviewView(adapter, "local_preview");
  AttachPreviewView(adapter, "remote_view");
  adapter.events().SetNodeId("mac-real-001");
  const auto response = InvokeVisual(adapter, "bindLocalVideo", R"({\"view_role\":\"local_preview\"})");
  Json::Value root;
  if (!ParseJsonOrLog(response, &root, "IT-AGORA-VISUAL-PROBE")) {
    return 1;
  }
  const Json::Value& entry = root["data"]["list"][0];
  Json::Value result;
  const bool ok = root["data"].get("code", -1).asInt() == 0 &&
                  beacon::ParseJson(entry.get("result", "{}").asString(), &result) &&
                  result.get("configured", false).asBool() &&
                  result.get("view_id", "").asString() == "local_preview";
  if (!ok) {
    std::cerr << "IT-AGORA-VISUAL-PROBE local bind response: " << response << "\n";
  }
  if (!ok) {
    return 1;
  }
  const auto remote_response = InvokeVisual(adapter, "bindRemoteVideo", R"({\"uid\":1002,\"view_role\":\"remote_view\"})");
  Json::Value remote_root;
  if (!ParseJsonOrLog(remote_response, &remote_root, "IT-AGORA-VISUAL-PROBE-REMOTE-BIND")) {
    return 1;
  }
  const Json::Value& remote_entry = remote_root["data"]["list"][0];
  Json::Value remote_result;
  const bool remote_ok = remote_root["data"].get("code", -1).asInt() == 0 &&
                         beacon::ParseJson(remote_entry.get("result", "{}").asString(), &remote_result) &&
                         remote_result.get("configured", false).asBool() &&
                         remote_result.get("view_id", "").asString() == "remote_view" &&
                         remote_result.get("uid", 0).asInt() == 1002;
  if (!remote_ok) {
    std::cerr << "IT-AGORA-VISUAL-PROBE remote bind response: " << remote_response << "\n";
  }
  return remote_ok ? 0 : 1;
}

int ITAgoraMultiRemoteBindings() {
  const char* id = "IT-AGORA-MULTI-REMOTE-BINDINGS";
  setenv("BEACON_SHOW_VIDEO_WINDOWS", "all", 1);
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, id)) return 1;
  NSWindow* window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 640, 240)
      styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
  NSView* first = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 320, 240)];
  NSView* second = [[NSView alloc] initWithFrame:NSMakeRect(320, 0, 320, 240)];
  [window.contentView addSubview:first];
  [window.contentView addSubview:second];
  adapter.views().Attach("remote_a", (__bridge void*)first);
  adapter.views().Attach("remote_alias", (__bridge void*)first);
  adapter.views().Attach("remote_b", (__bridge void*)second);
  // 经真实协议入口绑定两路，验证别名不会覆盖同一原生画布。
  auto visual = [&](const char* function, const char* role, int uid = 0) {
    Json::Value params(Json::objectValue);
    params["view_role"] = role;
    if (uid != 0) params["uid"] = uid;
    Json::Value packet(Json::objectValue);
    packet["common"]["action"] = "invokeRequest";
    packet["common"]["op_id"] = id;
    packet["common"]["timestamp_ms"] = 1;
    packet["data"]["node_id"] = "mac-real-001";
    packet["data"]["sync"] = true;
    auto& item = packet["data"]["list"][0];
    item["target"]["sdk"] = "agora_rtc";
    item["target"]["interface"] = "visual_probe";
    item["target"]["class_name"] = "AgoraVisualProbe";
    item["target"]["function"] = function;
    item["params"] = beacon::WriteJson(params);
    const auto response = adapter.kernel().HandleRequest(beacon::WriteJson(packet));
    PumpRunLoopForMs(50);
    return response;
  };
  auto released = [&](const char* role, bool expected) {
    Json::Value root;
    Json::Value result;
    const auto response = visual("releaseView", role);
    const bool ok = beacon::ParseJson(response, &root) && root["data"].get("code", -1).asInt() == 0 &&
        beacon::ParseJson(root["data"]["list"][0].get("result", "{}").asString(), &result) &&
        result.get("released", !expected).asBool() == expected;
    if (!ok) std::cerr << id << " expected released=" << expected << " role=" << role << "\n";
    return ok;
  };
  if (!HasResponseCode(visual("bindRemoteVideo", "remote_a", 2001), 0, id) ||
      !HasResponseCode(visual("bindRemoteVideo", "remote_b", 2002), 0, id) ||
      !HasResponseCode(visual("bindRemoteVideo", "remote_alias", 2003), beacon::kBadRequest, id) ||
      !HasResponseCode(visual("bindRemoteVideo", "remote_b", 2001), beacon::kBadRequest, id)) return 1;
  if (!released("remote_a", true) || !window.visible ||
      !released("remote_a", false) ||
      !released("remote_b", true) || window.visible) return 1;
  if (!HasResponseCode(visual("bindRemoteVideo", "remote_a", 2001), 0, id) || !HasResponseCode(visual("bindRemoteVideo", "remote_b", 2002), 0, id)) return 1;
  adapter.rtc().Reset();
  adapter.rtc().Reset();
  PumpRunLoopForMs(50);
  if (window.visible || !released("remote_a", false) ||
      !released("remote_b", false)) return 1;
  if (!HasResponseCode(visual("bindRemoteVideo", "remote_a", 2001), 0, id) ||
      !HasResponseCode(visual("bindRemoteVideo", "remote_b", 2002), 0, id) ||
      !HasResponseCode(Invoke(adapter, "leaveChannel", "{}"), 0, id) ||
      !HasResponseCode(Invoke(adapter, "leaveChannel", "{}"), 0, id)) return 1;
  PumpRunLoopForMs(50);
  if (window.visible || !released("remote_a", false) ||
      !released("remote_b", false)) return 1;
  return 0;
}

int ITAgoraJoinCallback() {
  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "IT-AGORA-JOIN-CALLBACK")) {
    return 1;
  }
  adapter.events().SetNodeId("mac-real-001");
  std::vector<std::string> emitted_callbacks;
  beacon::CallbackExecutionResult matched_execution;
  bool has_matched_execution = false;
  std::mutex callback_mutex;
  adapter.events().SetObserver([&](
                                   const std::string& function,
                                   const std::string& payload,
                                   const beacon::CallbackExecutionResult& execution,
                                   const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) {
    std::lock_guard<std::mutex> lock(callback_mutex);
    emitted_callbacks.push_back(function + ":" + payload + ":" + origin.originating_op_id);
    if (execution.matched) {
      matched_execution = execution;
      has_matched_execution = true;
    }
  });
  const auto callback_response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"callbackRequest","op_id":"op-real-cb","timestamp_ms":1},"data":{"node_id":"mac-real-001","sync":true,"list":[{"event_target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineDelegate","function":"onJoinChannelSuccess"},"repeat":1,"call_elements":[{"target":{"sdk":"beacon_system","class_name":"SystemClock","function":"waitInMs"},"params":"{\"ms\":1}"}]}]}})");
  if (callback_response.find("\"code\":0") == std::string::npos) {
    std::cerr << "IT-AGORA-JOIN-CALLBACK callback install response: " << callback_response << "\n";
    return 1;
  }
  if (adapter.kernel().callbacks().size() != 1U) {
    std::cerr << "IT-AGORA-JOIN-CALLBACK callback registry size after install: "
              << adapter.kernel().callbacks().size() << "\n";
    return 1;
  }
  const auto join = Invoke(adapter, "joinChannel", JoinParams("real-smoke", 1001));
  if (join.find("\"code\":0") == std::string::npos) {
    std::cerr << "IT-AGORA-JOIN-CALLBACK join response: " << join << "\n";
    return 1;
  }
  const auto identity_after_join = adapter.events().active_engine_identity();
  if (!adapter.events().has_matched_callback() &&
      (!identity_after_join.resource_ref.empty() || !identity_after_join.instance_id.empty())) {
    std::cerr << "IT-AGORA-JOIN-CALLBACK active identity installed before join success callback\n";
    return 1;
  }
  for (int i = 0; i < 300; ++i) {
    beacon::CallbackExecutionResult execution;
    bool execution_ready = false;
    {
      std::lock_guard<std::mutex> lock(callback_mutex);
      execution_ready = has_matched_execution;
      execution = matched_execution;
    }
    if (adapter.events().has_matched_callback() && execution_ready) {
      Json::Value deferred_params;
      const bool has_call_result = execution.call_results.size() == 1U &&
                                   execution.call_results[0].call.function_name == "waitInMs" &&
                                   ParseJsonOrLog(execution.call_results[0].call.params_json, &deferred_params,
                                                  "IT-AGORA-JOIN-CALLBACK") &&
                                   deferred_params.get("ms", 0).asInt() == 1 &&
                                   execution.call_results[0].result.ok();
      if (!has_call_result) {
        std::cerr << "callback call_results missing\n";
      }
      if (!HasSingleCallResultWithResourceRef(execution, "engine_1", "IT-AGORA-JOIN-CALLBACK") ||
          !HasExecutionContext(execution,
                               "agora_rtc/rtc_engine",
                               "engine_1",
                               "engine_1",
                               1,
                               "IT-AGORA-JOIN-CALLBACK")) {
        return 1;
      }
      Invoke(adapter, "leaveChannel", "{}");
      adapter.Destroy();
      return has_call_result ? 0 : 1;
    }
    PumpRunLoopForMs(100);
  }
  Invoke(adapter, "leaveChannel", "{}");
  adapter.Destroy();
  std::cerr << "emitted callbacks:\n";
  {
    std::lock_guard<std::mutex> lock(callback_mutex);
    for (const auto& item : emitted_callbacks) {
      std::cerr << item << "\n";
    }
  }
  std::cerr << "last callback response: " << adapter.events().last_response() << "\n";
  return 1;
}

int ITAgoraLeaveChannel() {
  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "IT-AGORA-LEAVE-CHANNEL")) {
    return 1;
  }
  adapter.events().SetNodeId("mac-real-001");
  const auto join = Invoke(adapter, "joinChannel", JoinParams("real-smoke", 1001));
  const auto leave = Invoke(adapter, "leaveChannel", "{}");
  if (!adapter.events().active_engine_identity().resource_ref.empty() ||
      !adapter.events().active_engine_identity().instance_id.empty()) {
    std::cerr << "IT-AGORA-LEAVE-CHANNEL active identity not cleared after leave\n";
    return 1;
  }
  return join.find("\"code\":0") != std::string::npos && leave.find("\"code\":0") != std::string::npos &&
                 !adapter.rtc().joined()
             ? 0
             : 1;
}

int ITAgoraStopPreview() {
  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "IT-AGORA-STOP-PREVIEW")) {
    return 1;
  }
  adapter.events().SetNodeId("mac-real-001");
  const auto start = InvokePreview(adapter, "startPreview", "{}");
  const auto stop = InvokePreview(adapter, "stopPreview", "{}");
  const auto repeated_stop = InvokePreview(adapter, "stopPreview", "{}");
  return start.find("\"code\":0") != std::string::npos && stop.find("\"code\":0") != std::string::npos &&
                 repeated_stop.find("\"code\":0") != std::string::npos &&
                 !adapter.rtc().previewing()
             ? 0
             : 1;
}

int ITAgoraSyntheticVideo() {
  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "IT-AGORA-SYNTHETIC-VIDEO")) {
    return 1;
  }
  adapter.events().SetNodeId("mac-real-001");
  if (!HasResponseCode(Invoke(adapter, "startSyntheticVideo", R"({\"width\":0})"),
                       beacon::kBadRequest,
                       "IT-AGORA-SYNTHETIC-VIDEO")) {
    return 1;
  }
  if (!ResponseResultContains(Invoke(adapter, "stopSyntheticVideo", "{}"),
                              "\"stopped\":false",
                              "IT-AGORA-SYNTHETIC-VIDEO")) {
    return 1;
  }
  if (!ResponseResultContains(Invoke(adapter, "startSyntheticVideo", R"({\"width\":320,\"height\":240,\"fps\":15,\"pattern\":\"moving_stripe\"})"),
                              "\"started\":true",
                              "IT-AGORA-SYNTHETIC-VIDEO")) {
    return 1;
  }
  std::this_thread::sleep_for(std::chrono::milliseconds(1200));
  if (!ResponseResultContains(Invoke(adapter, "stopSyntheticVideo", "{}"),
                              "\"stopped\":true",
                              "IT-AGORA-SYNTHETIC-VIDEO") ||
      !ResponseResultContains(Invoke(adapter, "stopSyntheticVideo", "{}"),
                              "\"stopped\":false",
                              "IT-AGORA-SYNTHETIC-VIDEO")) {
    return 1;
  }
  if (!ResponseResultContains(Invoke(adapter, "startSyntheticVideo", R"({\"width\":320,\"height\":180,\"pattern\":\"animated_clip\"})"),
                              "\"started\":true",
                              "IT-AGORA-SYNTHETIC-VIDEO")) {
    return 1;
  }
  adapter.Reset();
  if (!ResponseResultContains(Invoke(adapter, "stopSyntheticVideo", "{}"),
                              "\"stopped\":false",
                              "IT-AGORA-SYNTHETIC-VIDEO")) {
    std::cerr << "IT-AGORA-SYNTHETIC-VIDEO adapter reset should deactivate synthetic source\n";
    return 1;
  }
  adapter.Destroy();
  return 0;
}

int ITAgoraMediaPlayer() {
  const char* id = "IT-AGORA-MEDIA-PLAYER";
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, id)) return 1;
  if (!HasResponseCode(InvokeMediaPlayer(adapter, "openMediaPlayer", R"({})"), beacon::kBadRequest, id) ||
      !ResponseResultContains(InvokeMediaPlayer(adapter, "openMediaPlayer",
                                                 R"({\"source_path\":\"test_cases/sample_960x400_ocean_with_audio.mp4\"})"),
                              "\"opened\":true", id)) {
    return 1;
  }
  std::string join_params = JoinParams("real-smoke-media-player", 1001);
  join_params.pop_back();
  join_params += R"(,\"publish_media_player\":true})";
  if (!HasResponseCode(Invoke(adapter, "joinChannel", join_params), beacon::kOk, id) ||
      !ResponseResultContains(InvokeMediaPlayer(adapter, "playMediaPlayer", "{}"), "\"playing\":true", id) ||
      !ResponseResultContains(InvokeMediaPlayer(adapter, "pauseMediaPlayer", "{}"), "\"paused\":true", id) ||
      !ResponseResultContains(InvokeMediaPlayer(adapter, "resumeMediaPlayer", "{}"), "\"playing\":true", id) ||
      !ResponseResultContains(InvokeMediaPlayer(adapter, "stopMediaPlayer", "{}"), "\"stopped\":true", id) ||
      !ResponseResultContains(InvokeMediaPlayer(adapter, "stopMediaPlayer", "{}"), "\"stopped\":false", id)) {
    Invoke(adapter, "leaveChannel", "{}");
    return 1;
  }
  Invoke(adapter, "leaveChannel", "{}");
  adapter.Destroy();
  return 0;
}

int ITAgoraPermissionDenied() {
  beacon::mac::PlatformAdapter adapter;
  adapter.DenyMediaPermissionForTesting();
  adapter.Init();
  adapter.Bind();
  adapter.events().SetNodeId("mac-real-001");
  const auto join = Invoke(adapter, "joinChannel", R"({\"channel\":\"denied\",\"uid\":1001})");
  const auto preview = InvokePreview(adapter, "startPreview", "{}");
  return join.find("\"code\":402") != std::string::npos && preview.find("\"code\":402") != std::string::npos ? 0 : 1;
}

bool VerifyProtocolMediaCommands(beacon::mac::PlatformAdapter& adapter) {
  const char* token = std::getenv("AGORA_RTC_TOKEN");
  const std::string renew_params =
      token == nullptr || token[0] == '\0' ? R"({\"token\":\"runtime-token\"})"
                                           : std::string(R"({\"token\":\")") + token + R"(\"})";
  if (!HasResponseCode(Invoke(adapter, "enableLocalAudio", R"({\"enabled\":false})"),
                       beacon::kOk,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(Invoke(adapter, "enableLocalAudio", R"({\"enabled\":true})"),
                              "\"audio\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(Invoke(adapter, "enableLocalVideo", R"({\"enabled\":false})"),
                       beacon::kOk,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(Invoke(adapter, "enableLocalVideo", R"({\"enabled\":true})"),
                              "\"video\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(Invoke(adapter, "renewToken", "{}"), beacon::kBadRequest, "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(Invoke(adapter, "renewToken", renew_params), beacon::kOk, "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(Invoke(adapter, "getConnectionState", "{}"), "\"idle\"", "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(Invoke(adapter, "joinChannel", "{}"), beacon::kBadRequest, "IT-AGORA-PROTOCOL-COMMANDS")) {
    return false;
  }
  return true;
}

bool VerifyPrimaryVisualCommands(beacon::mac::PlatformAdapter& adapter) {
  const auto join =
      InvokeWithFields(adapter,
                       "joinChannel",
                       JoinParams("real-smoke", 1001),
                       R"("store_as":"engine_store","extra":"{\"run_id\":\"run-real\",\"case_id\":\"IT-AGORA-PROTOCOL-COMMANDS\",\"step_id\":\"join\"}")");
  if (!HasResponseCode(join, beacon::kOk, "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeWithFields(adapter,
                                               "getConnectionState",
                                               "{}",
                                               R"("resource_ref":"engine_store","extra":"{\"run_id\":\"run-real\",\"case_id\":\"IT-AGORA-PROTOCOL-COMMANDS\",\"step_id\":\"state\"}")"),
                              "\"connected\"",
                              "IT-AGORA-PROTOCOL-COMMANDS")) {
    return false;
  }
  if (adapter.rtc().channel() != "real-smoke") {
    std::cerr << "IT-AGORA-PROTOCOL-COMMANDS backend channel mismatch\n";
    return false;
  }

  if (!HasResponseCode(InvokeVisual(adapter, "bindLocalVideo", "{}"),
                       beacon::kBadRequest,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindLocalVideo", R"({\"view_role\":\"missing\"})"),
                       403,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindLocalVideo", R"({\"view_role\":\"primary_local_preview\"})"),
                       beacon::kOk,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindRemoteVideo", "{}"),
                       beacon::kBadRequest,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindRemoteVideo", R"({\"uid\":1002})"),
                       beacon::kBadRequest,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindRemoteVideo", R"({\"uid\":1002,\"view_role\":\"missing\"})"),
                       403,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindRemoteVideo", R"({\"uid\":1002,\"view_role\":\"primary_remote_view\"})"),
                       beacon::kOk,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "captureSnapshot", "{}"),
                       beacon::kBadRequest,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"missing\"})"),
                       403,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"primary_local_preview\"})"),
                              "\"snapshot_requested\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"primary_remote_view\"})"),
                              "\"snapshot_requested\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"primary_remote_view\"})"),
                              "\"snapshot_requested\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "releaseView", R"({\"view_role\":\"primary_local_preview\"})"),
                              "\"released\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "releaseView", R"({\"view_role\":\"primary_remote_view\"})"),
                              "\"released\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "releaseView", R"({\"view_role\":\"unbound\"})"),
                              "\"released\":false",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "releaseView", "{}"), beacon::kBadRequest, "IT-AGORA-PROTOCOL-COMMANDS")) {
    return false;
  }
  return true;
}

bool VerifyPeerVisualCommands(beacon::mac::PlatformAdapter& adapter) {
  Invoke(adapter, "leaveChannel", "{}");
  const auto peer_join = Invoke(adapter, "joinChannel", JoinParams("real-smoke", 1002));
  if (!HasResponseCode(peer_join, beacon::kOk, "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"peer_local_preview\"})"),
                       403,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"peer_remote_view\"})"),
                       403,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindLocalVideo", R"({\"view_role\":\"peer_local_preview\"})"),
                       beacon::kOk,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !HasResponseCode(InvokeVisual(adapter, "bindRemoteVideo", R"({\"uid\":1001,\"view_role\":\"peer_remote_view\"})"),
                       beacon::kOk,
                       "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"peer_local_preview\"})"),
                              "\"snapshot_requested\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS") ||
      !ResponseResultContains(InvokeVisual(adapter, "captureSnapshot", R"({\"view_role\":\"peer_remote_view\"})"),
                              "\"snapshot_requested\":true",
                              "IT-AGORA-PROTOCOL-COMMANDS")) {
    return false;
  }
  return true;
}

int ITAgoraProtocolCommands() {
  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  if (!EnsureSDKLoaded(adapter, "IT-AGORA-PROTOCOL-COMMANDS")) {
    return 1;
  }
  if (!adapter.rtc().initialized()) {
    std::cerr << "IT-AGORA-PROTOCOL-COMMANDS backend not initialized after protocol load\n";
    return 1;
  }
  adapter.events().SetNodeId("mac-real-001");
  AttachPreviewView(adapter, "primary_local_preview");
  AttachPreviewView(adapter, "primary_remote_view");
  AttachPreviewView(adapter, "peer_local_preview");
  AttachPreviewView(adapter, "peer_remote_view");
  if (!VerifyProtocolMediaCommands(adapter) || !VerifyPrimaryVisualCommands(adapter) ||
      !VerifyPeerVisualCommands(adapter)) {
    return 1;
  }
  Invoke(adapter, "leaveChannel", "{}");
  adapter.Destroy();
  return 0;
}

int FIrtc01() {
  beacon::mac::PlatformAdapter adapter;
  adapter.permissions().RequestCamera();
  adapter.permissions().RequestMicrophone();
  adapter.Init();
  adapter.Bind();
  adapter.rtc().Reset();
  if (!adapter.events().active_engine_identity().resource_ref.empty() ||
      !adapter.events().active_engine_identity().instance_id.empty()) {
    std::cerr << "FI-RTC-01 active identity not cleared after reset\n";
    return 1;
  }
  adapter.Destroy();
  return adapter.rtc().joined() || adapter.rtc().previewing() ? 1 : 0;
}

}  // namespace

int main(int argc, char** argv) {
  const std::string id = argc > 1 ? argv[1] : "";
  if (id == "BRIDGE-MAC-REAL-01") return BridgeMacReal01();
  if (id == "BRIDGE-MAC-REAL-02") return BridgeMacReal02();
  if (id == "IT-AGORA-04") return ITAgora04();
  if (id == "IT-AGORA-VISUAL-PROBE") return ITAgoraVisualProbe();
  if (id == "IT-AGORA-MULTI-REMOTE-BINDINGS") return ITAgoraMultiRemoteBindings();
  if (id == "IT-AGORA-JOIN-CALLBACK") return ITAgoraJoinCallback();
  if (id == "IT-AGORA-LEAVE-CHANNEL") return ITAgoraLeaveChannel();
  if (id == "IT-AGORA-STOP-PREVIEW") return ITAgoraStopPreview();
  if (id == "IT-AGORA-SYNTHETIC-VIDEO") return ITAgoraSyntheticVideo();
  if (id == "IT-AGORA-MEDIA-PLAYER") return ITAgoraMediaPlayer();
  if (id == "IT-AGORA-PERMISSION-DENIED") return ITAgoraPermissionDenied();
  if (id == "IT-AGORA-PROTOCOL-COMMANDS") return ITAgoraProtocolCommands();
  if (id == "FI-RTC-01") return FIrtc01();
  std::cerr << "unknown mac real test id: " << id << "\n";
  return 1;
}
