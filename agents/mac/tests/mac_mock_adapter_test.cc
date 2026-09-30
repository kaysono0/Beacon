#include "platform/agent_provider_registry.h"
#include "static_interface_provider.h"
#include "vendors/agora/agora_sdk_loader.h"
#include "vendors/agora/agora_visual_probe_provider.h"
#include "bridge_target_consistency.h"
#include "platform/platform_adapter.h"
#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"
#include "mac_real_agent_loopback_helper.h"
#include "mac_real_agent_packet_handler.h"
#include "platform/network_condition_provider.h"
#include "rtc/rtc_backend.h"
#include "rtc/rtc_command_vocabulary.h"
#include "rtc/rtc_invocation_provider.h"
#include "video/video_host_visibility.h"
#include "video/video_host_layout.h"
#include "video/video_stats_overlay.h"

#include <filesystem>
#include <fstream>
#include <cmath>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#ifdef __APPLE__
int BridgeMacVideoHostActivation();
#endif

namespace {

bool ParseJsonOrLog(const std::string& json, Json::Value* root, const char* test_id) {
  if (beacon::ParseJson(json, root)) {
    return true;
  }
  std::cerr << test_id << " response is not valid json\n";
  return false;
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

bool HasExecutionCallResultResourceRef(const beacon::CallbackExecutionResult& execution,
                                       const std::string& expected_resource_ref,
                                       const char* test_id) {
  if (!execution.matched || execution.call_results.empty()) {
    std::cerr << test_id << " callback execution missing call result: matched=" << execution.matched
              << " call_results=" << execution.call_results.size() << "\n";
    return false;
  }
  if (execution.call_results[0].call.resource_ref != expected_resource_ref) {
    std::cerr << test_id << " callback call result resource_ref mismatch\n";
    return false;
  }
  return true;
}

bool HasCallbackEventOrigin(const Json::Value& root, const std::string& expected_op_id,
                            const std::string& expected_resource_ref, const std::string& expected_run_id,
                            const std::string& expected_case_id, const std::string& expected_step_id,
                            const char* test_id) {
  const Json::Value& data = root["data"];
  const Json::Value& context = data["callback_context"];
  if (!context.isObject()) {
    std::cerr << test_id << " callback_context missing\n";
    return false;
  }
  if (context.get("originating_op_id", "").asString() != expected_op_id ||
      context.get("resource_ref", "").asString() != expected_resource_ref ||
      data.get("run_id", "").asString() != expected_run_id ||
      data.get("case_id", "").asString() != expected_case_id ||
      data.get("step_id", "").asString() != expected_step_id) {
    std::cerr << test_id << " callback origin mismatch: " << beacon::WriteJson(root) << "\n";
    return false;
  }
  if (data.get("event_id", "").asString().empty() ||
      data.get("event_id", "").asString() == expected_op_id ||
      root["common"].get("op_id", "").asString() != data.get("event_id", "").asString()) {
    std::cerr << test_id << " callback event_id is not independent: " << beacon::WriteJson(root) << "\n";
    return false;
  }
  return true;
}

bool HasReceiptOnlyCallbackResponse(const Json::Value& root, const char* test_id) {
  const Json::Value& data = root["data"];
  if (!data["receipt"].isObject() ||
      data.isMember("callback_context") ||
      data.isMember("run_id") ||
      data.isMember("case_id") ||
      data.isMember("step_id")) {
    std::cerr << test_id << " callbackEventResponse mirrors callback origin: " << beacon::WriteJson(root) << "\n";
    return false;
  }
  return true;
}


std::string Invoke(beacon::mac::PlatformAdapter* adapter, const std::string& op_id, const std::string& interface_name,
                   const std::string& class_name, const std::string& function_name,
                   const std::string& params_json = "{}", const std::string& extra_json = "{}",
                   const std::string& store_as = "") {
  Json::Value packet(Json::objectValue);
  packet["common"]["action"] = "invokeRequest";
  packet["common"]["op_id"] = op_id;
  packet["common"]["timestamp_ms"] = 1;
  packet["data"]["node_id"] = "mac-mock-001";
  packet["data"]["sync"] = true;
  Json::Value item(Json::objectValue);
  item["target"]["sdk"] = "agora_rtc";
  item["target"]["interface"] = interface_name;
  item["target"]["class_name"] = class_name;
  item["target"]["function"] = function_name;
  item["params"] = params_json;
  if (extra_json != "{}") {
    item["extra"] = extra_json;
  }
  if (!store_as.empty()) {
    item["store_as"] = store_as;
  }
  packet["data"]["list"].append(item);
  return adapter->kernel().HandleRequest(beacon::WriteJson(packet));
}

bool HasResponseCode(const std::string& response, int expected_code, const char* test_id) {
  Json::Value root;
  if (!ParseJsonOrLog(response, &root, test_id)) {
    return false;
  }
  const int actual_code = root["data"].get("code", -1).asInt();
  if (actual_code != expected_code) {
    std::cerr << test_id << " expected code " << expected_code << " but got " << actual_code
              << ": " << response << "\n";
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
    std::cerr << test_id << " result did not contain " << expected << ": " << response << "\n";
    return false;
  }
  return true;
}

class FailingSDKAdapter : public beacon::mac::AgoraSDKAdapter {
 public:
  bool Load() override { return false; }
  bool Unload() override { return true; }
  void Configure(const std::string& app_id) override { app_id_ = app_id; }
  bool loaded() const override { return false; }
  std::string version() const override { return ""; }
  std::string app_id() const override { return app_id_; }

 private:
  std::string app_id_;
};

beacon::CallData RtcCall(std::string function_name, std::string params_json = "{}") {
  beacon::CallData call;
  call.sdk = "agora_rtc";
  call.interface_name = "rtc_engine";
  call.class_name = "AgoraRtcEngineKit";
  call.function_name = std::move(function_name);
  call.params_json = std::move(params_json);
  return call;
}

beacon::CallData LifecycleCall(std::string function_name) {
  beacon::CallData call;
  call.sdk = "agora_rtc";
  call.interface_name = "rtc_engine";
  call.class_name = "SDKLifecycle";
  call.function_name = std::move(function_name);
  return call;
}

beacon::CallData VisualCall(std::string function_name, std::string params_json = "{}") {
  beacon::CallData call;
  call.sdk = "agora_rtc";
  call.interface_name = "visual_probe";
  call.class_name = "AgoraVisualProbe";
  call.function_name = std::move(function_name);
  call.params_json = std::move(params_json);
  return call;
}

int BridgeMacTargetConsistency() {
  return beacon::mac::test_support::CheckVendorTargetConsistency();
}

int BridgeMacVideoHostVisibility() {
  using beacon::mac::ShouldShowVideoHost;
  if (!ShouldShowVideoHost("mac-real-e2e-001", "", "") ||
      !ShouldShowVideoHost("mac-vendor-primary", "vendor,role:primary", "") ||
      !ShouldShowVideoHost("mac-vendor-peer", "vendor,role:peer", "all") ||
      ShouldShowVideoHost("mac-vendor-peer", "vendor,role:peer", "") ||
      ShouldShowVideoHost("mac-vendor-peer-b", "vendor,role:peer-b", "")) {
    std::cerr << "BRIDGE-MAC-VIDEO-HOST visibility policy mismatch\n";
    return 1;
  }
  return 0;
}

int BridgeMacVideoHostLayout() {
  const beacon::mac::VideoHostRect screen{0, 0, 1440, 900};
  const auto primary = beacon::mac::VideoHostFrameForRole("primary", screen);
  const auto peer = beacon::mac::VideoHostFrameForRole("peer", screen);
  const auto peer_b = beacon::mac::VideoHostFrameForRole("peer-b", screen);
  const auto within = [](const beacon::mac::VideoHostRect& frame, const beacon::mac::VideoHostRect& bounds) {
    return frame.x >= bounds.x && frame.y >= bounds.y && frame.x + frame.width <= bounds.x + bounds.width &&
           frame.y + frame.height <= bounds.y + bounds.height &&
           std::abs(frame.width * 9.0 - frame.height * 16.0) < 0.001;
  };
  if (!within(primary, screen) || !within(peer, screen) || !within(peer_b, screen) ||
      beacon::mac::VideoHostRectsOverlap(primary, peer) || beacon::mac::VideoHostRectsOverlap(primary, peer_b) ||
      beacon::mac::VideoHostRectsOverlap(peer, peer_b)) {
    std::cerr << "BRIDGE-MAC-VIDEO-HOST-LAYOUT clamp or multi-observer layout mismatch\n";
    return 1;
  }
  const beacon::mac::VideoHostRect constrained{20, 40, 480, 270};
  const auto clamped = beacon::mac::VideoHostFrameForRole("primary", constrained);
  return within(clamped, constrained) ? 0 : 1;
}

int BridgeMacVideoStatsOverlay() {
  beacon::mac::VideoRenderOverlay overlay;
  overlay.case_id = "TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE";
  overlay.publisher = "Remote uid 1002";
  overlay.state = "Rendering";
  overlay.layer = "Low";
  overlay.width = 640;
  overlay.height = 360;
  overlay.frame_rate = 15;
  overlay.bitrate_direction = "RX";
  overlay.bitrate = 145;
  overlay.updated_at = "12:34:56";
  if (beacon::mac::FormatVideoRenderOverlay(overlay) !=
      "Case: TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE"
      "\nPublisher: Remote uid 1002 · State: Rendering"
      "\nLayer: Low · Frame: 640 x 360 · 15 fps"
      "\nBitrate: RX 145 kbps · Updated: 12:34:56") {
    return 1;
  }

  beacon::mac::VideoRenderOverlay missing;
  missing.publisher = "Remote stream zego-test";
  missing.state = "Awaiting first frame";
  missing.layer = "N/A";
  missing.bitrate_direction = "RX";
  missing.updated_at = "Not reported";
  return beacon::mac::FormatVideoRenderOverlay(missing) ==
                 "Case: Not reported"
                 "\nPublisher: Remote stream zego-test · State: Awaiting first frame"
                 "\nLayer: N/A · Frame: Not reported · Not reported fps"
                 "\nBitrate: RX Not reported · Updated: Not reported"
             ? 0
             : 1;
}

int BridgeMacSimulcast() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto backend = adapter.rtc().backend();
  if (backend == nullptr || backend->Load() != beacon::kOk ||
      backend->SetDualStreamMode(RtcCall("setDualStreamMode", R"({"mode":"enabled","low_width":320,"low_height":180,"low_bitrate":150,"low_fps":15})")).error != beacon::kOk ||
      backend->SetRemoteVideoStream(RtcCall("setRemoteVideoStream", R"({"uid":1002,"stream_type":"low"})")).error != beacon::kOk ||
      backend->SetDualStreamMode(RtcCall("setDualStreamMode", R"({"mode":"unsupported"})")).error != beacon::kBadRequest ||
      backend->SetRemoteVideoStream(RtcCall("setRemoteVideoStream", R"({"uid":1002,"stream_type":"unsupported"})")).error != beacon::kBadRequest) {
    return 1;
  }
  adapter.Destroy();
  return 0;
}

int BuildMac01() {
  beacon::mac::PlatformAdapter adapter;
  return adapter.Init() == beacon::kOk ? 0 : 1;
}

int BridgeMac01() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  adapter.sdk_loader().Configure("mock-app-id");
  return adapter.sdk_loader().Load() && !adapter.sdk_loader().version().empty() &&
                 adapter.sdk_loader().app_id() == "mock-app-id"
             ? 0
             : 1;
}

int BridgeMac02() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  adapter.sdk_loader().Load();
  return adapter.sdk_loader().Unload() && !adapter.sdk_loader().loaded() ? 0 : 1;
}

int BridgeMac03() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  return adapter.permissions().Camera() == beacon::mac::PermissionState::kGranted &&
                 adapter.permissions().Microphone() == beacon::mac::PermissionState::kGranted &&
                 adapter.permissions().ScreenCapture() == beacon::mac::PermissionState::kGranted &&
                 adapter.permissions().RequestCamera() == beacon::mac::PermissionState::kGranted &&
                 adapter.permissions().RequestMicrophone() == beacon::mac::PermissionState::kGranted
             ? 0
             : 1;
}

int BridgeMac04() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  int view = 7;
  adapter.views().Attach("local", &view);
  if (adapter.views().GetHandle("local") != &view) {
    return 1;
  }
  adapter.views().Detach("local");
  adapter.views().RegisterView("remote", "remote-view-handle");
  if (adapter.views().GetView("remote") != "remote-view-handle" || !adapter.views().GetView("missing").empty()) {
    return 1;
  }
  int dynamic_view = 8;
  int resolver_calls = 0;
  adapter.views().SetHandleResolver([&](const std::string& view_role) -> void* {
    if (view_role != "remote_view_8") {
      return nullptr;
    }
    ++resolver_calls;
    adapter.views().Attach(view_role, &dynamic_view);
    return &dynamic_view;
  });
  if (adapter.views().GetHandle("remote_view_8") != &dynamic_view ||
      adapter.views().GetHandle("remote_view_8") != &dynamic_view || resolver_calls != 1) {
    return 1;
  }
  adapter.views().Clear();
  return adapter.views().GetHandle("local") == nullptr && adapter.views().GetView("remote").empty() &&
                 adapter.views().GetHandle("remote_view_8") == &dynamic_view && resolver_calls == 2
             ? 0
             : 1;
}

int BridgeMac06() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto join = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-invoke","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"smoke\"}"}]}})");
  if (join.find("\"code\":0") == std::string::npos || !adapter.rtc().joined() || adapter.rtc().channel() != "smoke") {
    return 1;
  }
  const auto state = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-state","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"getConnectionState"},"params":"{}","extra":"{\"run_id\":\"run-state\",\"case_id\":\"TC-STATE\",\"step_id\":\"observe\"}"}]}})");
  if (state.find("connected") == std::string::npos) {
    return 1;
  }
  const auto state_origin = adapter.events().active_engine_identity();
  if (state_origin.originating_op_id != "op-mac-state" || state_origin.resource_ref != "engine_1" ||
      state_origin.run_id != "run-state" || state_origin.case_id != "TC-STATE" ||
      state_origin.step_id != "observe") {
    std::cerr << "BRIDGE-MAC-06 state observation did not update callback origin\n";
    return 1;
  }
  const auto joined = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-joined","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"isJoined"},"params":"{}"}]}})");
  if (joined.find("\"result\":\"true\"") == std::string::npos) {
    return 1;
  }
  const auto preview = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-preview-start","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"video_preview","class_name":"AgoraRtcEngineKit","function":"startPreview"},"params":"{}"}]}})");
  if (preview.find("\"code\":0") == std::string::npos) {
    return 1;
  }
  const auto previewing = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-previewing","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"video_preview","class_name":"AgoraRtcEngineKit","function":"isPreviewing"},"params":"{}"}]}})");
  if (previewing.find("\"result\":\"true\"") == std::string::npos) {
    return 1;
  }
  return 0;
}

int BridgeMacEvent() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  beacon::mac::agent_runtime::TraceStore trace_store;
  beacon::mac::agent_runtime::LoopbackHelperManager helper_manager("");
  beacon::mac::agent_runtime::AgentPacketHandler packet_handler(adapter, trace_store, helper_manager, "mac-mock-001");
  std::vector<std::string> callback_packets;
  const auto join = packet_handler.Handle(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-join","timestamp_ms":1},"data":{"node_id":"mac-mock-001","lease_id":"lease-mac-cbctx","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"callback-smoke\"}","extra":"{\"run_id\":\"run-cbctx-a\",\"case_id\":\"case-cbctx-a\",\"device_role\":\"primary\",\"step_id\":\"step-cbctx-a\"}"}]}})",
      [](const std::string&) {});
  if (join.find("\"code\":0") == std::string::npos || !adapter.rtc().joined()) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 joinChannel setup failed\n";
    return 1;
  }
  const auto origin_a = adapter.events().active_engine_identity();
  const auto install = packet_handler.Handle(
      R"({"common":{"action":"callbackRequest","op_id":"op-mac-cb","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"event_target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineDelegate","function":"onJoinChannelSuccess"},"repeat":-1,"call_elements":[{"target":{"sdk":"beacon_system","class_name":"SystemClock","function":"waitInMs"},"params":"{\"ms\":1}"}]}]}})",
      [](const std::string&) {});
  if (install.find("\"code\":0") == std::string::npos) {
    return 1;
  }
  adapter.events().Suppress(true);
  if (!adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001})").empty()) {
    return 1;
  }
  adapter.events().Suppress(false);
  adapter.events().Bind(nullptr);
  if (!adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001})").empty()) {
    return 1;
  }
  adapter.events().Bind(&adapter.kernel());
  adapter.events().SetObserver([&](const std::string& function_name,
                                   const std::string& payload_json,
                                   const beacon::CallbackExecutionResult& execution,
                                   const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) {
    callback_packets.push_back(packet_handler.MakeCallbackEvent(function_name, payload_json, execution, origin));
  });
  const auto event = adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001})");
  Json::Value root;
  Json::Value deferred_params;
  const auto& callback_execution = adapter.kernel().callbacks().last_execution_result();
  if (callback_execution.call_results.size() != 1U ||
      !ParseJsonOrLog(callback_execution.call_results[0].call.params_json, &deferred_params, "BRIDGE-MAC-CBCTX-01") ||
      deferred_params.get("ms", 0).asInt() != 1) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 deferred call params changed\n";
    return 1;
  }
  if (!ParseJsonOrLog(event, &root, "BRIDGE-MAC-CBCTX-01") ||
      !HasReceiptOnlyCallbackResponse(root, "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionCallResultResourceRef(adapter.kernel().callbacks().last_execution_result(),
                                         "engine_1",
                                         "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionContext(adapter.kernel().callbacks().last_execution_result(),
                           "agora_rtc/rtc_engine",
                           "engine_1",
                           "engine_1",
                           1,
                           "BRIDGE-MAC-CBCTX-01")) {
    return 1;
  }
  if (callback_packets.empty()) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 direct callbackEventRequest was not captured\n";
    return 1;
  }
  Json::Value first_callback_packet;
  if (!ParseJsonOrLog(callback_packets.back(), &first_callback_packet, "BRIDGE-MAC-CBCTX-01") ||
      first_callback_packet["data"].get("device_role", "").asString() != "primary" ||
      !HasCallbackEventOrigin(first_callback_packet,
                              "op-mac-join",
                              "engine_1",
                              "run-cbctx-a",
                              "case-cbctx-a",
                              "step-cbctx-a",
                              "BRIDGE-MAC-CBCTX-01")) {
    return 1;
  }
  if (adapter.events().active_engine_identity().resource_ref != "engine_1" ||
      adapter.events().active_engine_identity().instance_id != "engine_1") {
    std::cerr << "BRIDGE-MAC-CBCTX-01 active identity mismatch after join\n";
    return 1;
  }

  beacon::mac::PlatformAdapter adapter_b;
  adapter_b.Bind();
  const auto install_json =
      R"({"common":{"action":"callbackRequest","op_id":"op-mac-cbctx-iso","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"event_target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineDelegate","function":"onJoinChannelSuccess"},"repeat":-1,"call_elements":[{"target":{"sdk":"beacon_system","class_name":"SystemClock","function":"waitInMs"},"params":"{\"ms\":1}"}]}]}})";
  if (adapter_b.kernel().HandleRequest(install_json).find("\"code\":0") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 second callback install failed\n";
    return 1;
  }
  const auto join_b = adapter_b.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-cbctx-iso-b","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"callback-b\"}","store_as":"engine_beta"}]}})");
  if (join_b.find("\"code\":0") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 second joinChannel failed\n";
    return 1;
  }
  if (adapter_b.events().active_engine_identity().resource_ref != "engine_beta" ||
      adapter_b.events().active_engine_identity().instance_id != "engine_beta") {
    std::cerr << "BRIDGE-MAC-CBCTX-01 second active identity mismatch\n";
    return 1;
  }
  Json::Value second_adapter_root;
  if (!ParseJsonOrLog(adapter_b.events().Emit("onJoinChannelSuccess", R"({"uid":1002})"), &second_adapter_root,
                      "BRIDGE-MAC-CBCTX-01") ||
      !HasReceiptOnlyCallbackResponse(second_adapter_root, "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionCallResultResourceRef(adapter_b.kernel().callbacks().last_execution_result(),
                                         "engine_beta",
                                         "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionContext(adapter_b.kernel().callbacks().last_execution_result(),
                           "agora_rtc/rtc_engine",
                           "engine_beta",
                           "engine_beta",
                           1,
                           "BRIDGE-MAC-CBCTX-01")) {
    return 1;
  }
  Json::Value isolated_root;
  if (!ParseJsonOrLog(adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001})"), &isolated_root,
                      "BRIDGE-MAC-CBCTX-01") ||
      !HasReceiptOnlyCallbackResponse(isolated_root, "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionCallResultResourceRef(adapter.kernel().callbacks().last_execution_result(),
                                         "engine_1",
                                         "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionContext(adapter.kernel().callbacks().last_execution_result(),
                           "agora_rtc/rtc_engine",
                           "engine_1",
                           "engine_1",
                           2,
                           "BRIDGE-MAC-CBCTX-01")) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 cross-instance identity leaked\n";
    return 1;
  }
  const auto origin_before_snapshot_failure = adapter.events().active_engine_identity();
  if (origin_before_snapshot_failure.sequence != 2) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 unexpected pre-restore callback sequence\n";
    return 1;
  }
  auto failed_snapshot_origin = origin_before_snapshot_failure;
  failed_snapshot_origin.originating_op_id = "op-failed-snapshot";
  failed_snapshot_origin.resource_ref = "engine_failed_snapshot";
  failed_snapshot_origin.instance_id = "engine_failed_snapshot";
  adapter.events().SetActiveEngineIdentity(failed_snapshot_origin);
  adapter.events().RestoreActiveEngineIdentity(origin_before_snapshot_failure);
  Json::Value restored_sequence_root;
  if (!ParseJsonOrLog(adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001,"restored":true})"),
                      &restored_sequence_root,
                      "BRIDGE-MAC-CBCTX-01") ||
      !HasReceiptOnlyCallbackResponse(restored_sequence_root, "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionContext(adapter.kernel().callbacks().last_execution_result(),
                           "agora_rtc/rtc_engine",
                           "engine_1",
                           "engine_1",
                           3,
                           "BRIDGE-MAC-CBCTX-01")) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 snapshot failure reset callback sequence\n";
    return 1;
  }

  const auto second_same_device_join = packet_handler.Handle(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-join-later","timestamp_ms":2},"data":{"node_id":"mac-mock-001","lease_id":"lease-mac-cbctx","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"callback-later\"}","store_as":"engine_later","extra":"{\"run_id\":\"run-cbctx-b\",\"case_id\":\"case-cbctx-b\",\"step_id\":\"step-cbctx-b\"}"}]}})",
      [](const std::string&) {});
  if (second_same_device_join.find("\"code\":0") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 second same-device join failed\n";
    return 1;
  }
  if (adapter.events().active_engine_identity().originating_op_id != "op-mac-join-later") {
    std::cerr << "BRIDGE-MAC-CBCTX-01 later invoke did not become active before delayed callback\n";
    return 1;
  }
  const size_t callback_count_before_delayed_a = callback_packets.size();
  adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001,"delayed":true})", origin_a);
  if (callback_packets.size() != callback_count_before_delayed_a + 1) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 delayed callback was not emitted\n";
    return 1;
  }
  Json::Value delayed_a_packet;
  if (!ParseJsonOrLog(callback_packets.back(), &delayed_a_packet, "BRIDGE-MAC-CBCTX-01") ||
      !HasCallbackEventOrigin(delayed_a_packet,
                              "op-mac-join",
                              "engine_1",
                              "run-cbctx-a",
                              "case-cbctx-a",
                              "step-cbctx-a",
                              "BRIDGE-MAC-CBCTX-01")) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 delayed callback was rebound to the later invoke\n";
    return 1;
  }

  const auto leave = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-mac-cbctx-leave","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"leaveChannel"},"params":"{}"}]}})");
  if (leave.find("\"code\":0") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 leaveChannel failed\n";
    return 1;
  }
  if (!adapter.events().active_engine_identity().resource_ref.empty() ||
      !adapter.events().active_engine_identity().instance_id.empty()) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 active identity not cleared after leave\n";
    return 1;
  }
  Json::Value stale_root;
  if (!ParseJsonOrLog(adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1003})"), &stale_root,
                      "BRIDGE-MAC-CBCTX-01") ||
      !HasReceiptOnlyCallbackResponse(stale_root, "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionCallResultResourceRef(adapter.kernel().callbacks().last_execution_result(),
                                         "",
                                         "BRIDGE-MAC-CBCTX-01") ||
      !HasExecutionContext(adapter.kernel().callbacks().last_execution_result(), "", "", "", 0,
                           "BRIDGE-MAC-CBCTX-01")) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 stale identity leaked after leave\n";
    return 1;
  }
  beacon::mac::RTCEventBridge::ActiveEngineIdentity pending_a;
  pending_a.originating_op_id = "op-pending-a";
  pending_a.resource_ref = "engine_a";
  pending_a.instance_id = "engine_a";
  beacon::mac::RTCEventBridge::ActiveEngineIdentity pending_b;
  pending_b.originating_op_id = "op-pending-b";
  pending_b.resource_ref = "engine_b";
  pending_b.instance_id = "engine_b";
  adapter.events().TrackPendingEngineIdentity(pending_a);
  adapter.events().TrackPendingEngineIdentity(pending_b);
  adapter.events().ActivatePendingEngineIdentity(pending_a);
  if (!adapter.events().active_engine_identity().originating_op_id.empty()) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 delayed callback promoted stale pending identity\n";
    return 1;
  }
  adapter.events().ActivatePendingEngineIdentity(pending_b);
  if (adapter.events().active_engine_identity().originating_op_id != "op-pending-b") {
    std::cerr << "BRIDGE-MAC-CBCTX-01 latest pending identity was not promoted\n";
    return 1;
  }
  adapter.events().ClearActiveEngineIdentity();
  beacon::mac::RTCEventBridge::ActiveEngineIdentity pending_failure;
  pending_failure.originating_op_id = "op-pending-failure";
  pending_failure.resource_ref = "engine_failure";
  pending_failure.instance_id = "engine_failure";
  pending_failure.run_id = "run-pending-failure";
  pending_failure.case_id = "case-pending-failure";
  pending_failure.step_id = "step-pending-failure";
  adapter.events().TrackPendingEngineIdentity(pending_failure);
  const size_t callback_count_before_pending_failure = callback_packets.size();
  adapter.events().Emit("onError", R"({"code":110})");
  if (callback_packets.size() != callback_count_before_pending_failure + 1) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 pending failure callback was not emitted\n";
    return 1;
  }
  Json::Value pending_failure_packet;
  if (!ParseJsonOrLog(callback_packets.back(), &pending_failure_packet, "BRIDGE-MAC-CBCTX-01") ||
      !HasCallbackEventOrigin(pending_failure_packet,
                              "op-pending-failure",
                              "engine_failure",
                              "run-pending-failure",
                              "case-pending-failure",
                              "step-pending-failure",
                              "BRIDGE-MAC-CBCTX-01")) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 pending failure callback lost join trace\n";
    return 1;
  }
  adapter.events().ClearActiveEngineIdentity();
  beacon::mac::RTCEventBridge::ActiveEngineIdentity cancelled_pending;
  cancelled_pending.originating_op_id = "op-cancelled-pending";
  cancelled_pending.resource_ref = "engine_cancelled";
  cancelled_pending.instance_id = "engine_cancelled";
  cancelled_pending.run_id = "run-cancelled-pending";
  cancelled_pending.case_id = "case-cancelled-pending";
  cancelled_pending.step_id = "step-cancelled-pending";
  adapter.events().TrackPendingEngineIdentity(cancelled_pending);
  adapter.events().CancelPendingEngineIdentity(cancelled_pending);
  const size_t callback_count_before_cancelled_pending = callback_packets.size();
  Json::Value cancelled_pending_packet;
  adapter.events().Emit("onError", R"({"code":110})");
  if (callback_packets.size() != callback_count_before_cancelled_pending + 1 ||
      !ParseJsonOrLog(callback_packets.back(), &cancelled_pending_packet, "BRIDGE-MAC-CBCTX-01") ||
      cancelled_pending_packet["data"].isMember("callback_context") ||
      cancelled_pending_packet["data"].isMember("run_id") ||
      cancelled_pending_packet["data"].isMember("case_id") ||
      cancelled_pending_packet["data"].isMember("step_id")) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 cancelled pending identity leaked into callback\n";
    return 1;
  }
  if (!adapter.events().has_matched_callback() || adapter.events().last_response().empty()) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 last matched callback receipt missing\n";
    return 1;
  }
  adapter.events().SetNodeId("mac-mock-node");
  adapter.events().SetActiveEngineIdentity("engine_string", "engine_string");
  Json::Value string_identity_root;
  if (!ParseJsonOrLog(adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1004})"), &string_identity_root,
                      "BRIDGE-MAC-CBCTX-01") ||
      !adapter.events().has_matched_callback() ||
      adapter.kernel().callbacks().last_execution_result().fact.node_id != "mac-mock-node" ||
      !HasExecutionContext(adapter.kernel().callbacks().last_execution_result(),
                           "agora_rtc/rtc_engine",
                           "engine_string",
                           "engine_string",
                           1,
                           "BRIDGE-MAC-CBCTX-01")) {
    std::cerr << "BRIDGE-MAC-CBCTX-01 string identity or node id was not propagated\n";
    return 1;
  }
  const size_t callback_count_before_invalid_payload = callback_packets.size();
  adapter.events().Emit("onJoinChannelSuccess", "not-json");
  if (callback_packets.size() != callback_count_before_invalid_payload + 1 ||
      adapter.kernel().callbacks().last_execution_result().fact.payload_json != "{}") {
    std::cerr << "BRIDGE-MAC-CBCTX-01 invalid payload was not normalized\n";
    return 1;
  }
  return 0;
}

int BridgeMacLifecycle() {
  beacon::mac::MockAgoraSDKAdapter sdk;
  beacon::mac::PlatformAdapter adapter(&sdk);
  if (adapter.Init() != beacon::kOk || !sdk.loaded() ||
      adapter.state() != beacon::mac::PlatformLifecycleState::kInitialized) {
    return 1;
  }
  if (adapter.Register() != beacon::kOk || !adapter.rtc().registered() ||
      adapter.state() != beacon::mac::PlatformLifecycleState::kRegistered) {
    return 1;
  }
  if (adapter.Bind() != beacon::kOk || adapter.state() != beacon::mac::PlatformLifecycleState::kBound) {
    return 1;
  }
  int view = 1;
  adapter.views().Attach("local", &view);
  adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-life","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"life\"}"}]}})");
  adapter.kernel().HandleRequest(
      R"({"common":{"action":"callbackRequest","op_id":"op-life-cb","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"event_target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineDelegate","function":"onJoinChannelSuccess"},"repeat":1,"call_elements":[{"target":{"sdk":"beacon_system","class_name":"SystemClock","function":"waitInMs"},"params":"{\"ms\":1}"}]}]}})");
  adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-life-preview","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"video_preview","class_name":"AgoraRtcEngineKit","function":"startPreview"},"params":"{}"}]}})");
  if (!adapter.rtc().joined() || !adapter.rtc().previewing() || adapter.views().GetHandle("local") == nullptr) {
    return 1;
  }
  const auto session_reset = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-life-reset-session","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"beacon_system","interface":"runtime","class_name":"AgentRuntime","function":"resetSession"},"params":"{}"}]}})");
  Json::Value session_reset_root;
  if (!ParseJsonOrLog(session_reset, &session_reset_root, "BRIDGE-MAC-LIFECYCLE") ||
      session_reset_root["data"].get("code", -1).asInt() != beacon::kOk ||
      adapter.rtc().joined() || adapter.rtc().previewing() ||
      adapter.views().GetHandle("local") == nullptr ||
      adapter.state() != beacon::mac::PlatformLifecycleState::kBound) {
    std::cerr << "BRIDGE-MAC-LIFECYCLE session reset did not isolate runtime state\n";
    return 1;
  }
  const auto repeated_session_reset = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-life-reset-session-again","timestamp_ms":2},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"beacon_system","interface":"runtime","class_name":"AgentRuntime","function":"resetSession"},"params":"{}"}]}})");
  if (!ParseJsonOrLog(repeated_session_reset, &session_reset_root, "BRIDGE-MAC-LIFECYCLE") ||
      session_reset_root["data"].get("code", -1).asInt() != beacon::kOk || adapter.rtc().joined() ||
      adapter.rtc().previewing() || adapter.views().GetHandle("local") == nullptr) {
    std::cerr << "BRIDGE-MAC-LIFECYCLE repeated session reset retained state\n";
    return 1;
  }
  const auto reset_event = adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001})");
  Json::Value reset_event_root;
  if (!ParseJsonOrLog(reset_event, &reset_event_root, "BRIDGE-MAC-LIFECYCLE") ||
      reset_event_root["data"]["receipt"].get("recorded", true).asBool() ||
      adapter.kernel().callbacks().last_execution_result().matched) {
    std::cerr << "BRIDGE-MAC-LIFECYCLE session reset retained callback state\n";
    return 1;
  }
  adapter.Reset();
  adapter.Reset();
  const auto event = adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001})");
  Json::Value event_root;
  if (adapter.rtc().joined() || adapter.views().GetHandle("local") != nullptr ||
      !adapter.events().active_engine_identity().resource_ref.empty() ||
      !adapter.events().active_engine_identity().instance_id.empty() ||
      adapter.state() != beacon::mac::PlatformLifecycleState::kInitialized ||
      !ParseJsonOrLog(event, &event_root, "BRIDGE-MAC-LIFECYCLE") ||
      !HasReceiptOnlyCallbackResponse(event_root, "BRIDGE-MAC-LIFECYCLE") ||
      event_root["data"]["receipt"].get("recorded", true).asBool() ||
      adapter.kernel().callbacks().last_execution_result().matched) {
    return 1;
  }
  adapter.Destroy();
  return !sdk.loaded() && adapter.state() == beacon::mac::PlatformLifecycleState::kDestroyed ? 0 : 1;
}

int BridgeMacVocabulary() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  constexpr size_t kPlatformHandlerCount = 10;
  if (beacon::mac::rtc_commands::kCommandSpecs.size() != beacon::mac::rtc_commands::kCommandNames.size() ||
      beacon::mac::rtc_commands::kCommandNames.size() + kPlatformHandlerCount !=
          adapter.kernel().invocations().size()) {
    return 1;
  }
  if (beacon::mac::rtc_commands::kCommandSpecs[2].name != beacon::mac::rtc_commands::kJoinChannel ||
      beacon::mac::rtc_commands::kCommandSpecs[2].params.find("channel") == std::string_view::npos ||
      beacon::mac::rtc_commands::kCommandSpecs[2].result.find("joined") == std::string_view::npos) {
    return 1;
  }
  const auto& specs = beacon::mac::rtc_commands::kCommandSpecs;
  if (specs.size() != 26 ||
      specs[17].name != beacon::mac::rtc_commands::kStartSyntheticVideo ||
      specs[17].params.find("pattern") == std::string_view::npos ||
      specs[17].result.find("started") == std::string_view::npos ||
      specs[18].name != beacon::mac::rtc_commands::kStopSyntheticVideo ||
      specs[18].result.find("stopped") == std::string_view::npos ||
      specs[19].name != beacon::mac::rtc_commands::kSetDualStreamMode ||
      specs[20].name != beacon::mac::rtc_commands::kSetRemoteVideoStream) {
    return 1;
  }
  const auto legacy = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-legacy","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"method":"rtc.joinChannel","params":"{\"channel\":\"legacy\"}"}]}})");
  return legacy.find("\"code\":400") != std::string::npos ? 0 : 1;
}

int BridgeMacProvider() {
  beacon::mac::AgentProviderRegistry registry;
  auto provider = std::make_shared<beacon::mac::testing::StaticInterfaceProvider>("agora_rtc", "rtc_engine");
  registry.RegisterProvider(provider);
  beacon::InvocationController controller;
  controller.Init();
  provider->RegisterInvocations(controller);
  if (provider->sdk() != "agora_rtc" || provider->interface_name() != "rtc_engine") {
    std::cerr << "BRIDGE-MAC-PROVIDER static provider identity mismatch\n";
    return 1;
  }
  beacon::CallData call;
  call.sdk = "agora_rtc";
  call.interface_name = "rtc_engine";
  call.class_name = "AgoraRtcEngineKit";
  call.function_name = "joinChannel";
  if (!registry.Resolve(call)) {
    std::cerr << "BRIDGE-MAC-PROVIDER provider not resolved\n";
    return 1;
  }
  call.interface_name = "video_preview";
  if (registry.Resolve(call)) {
    std::cerr << "BRIDGE-MAC-PROVIDER wrong provider resolved\n";
    return 1;
  }
  return 0;
}

int BridgeMacProviderRoute() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();

  beacon::CallData rtc_call;
  rtc_call.sdk = "agora_rtc";
  rtc_call.interface_name = "rtc_engine";
  rtc_call.class_name = "AgoraRtcEngineKit";
  rtc_call.function_name = "joinChannel";

  auto* provider = adapter.provider_registry().Resolve(rtc_call).get();
  if (provider == nullptr) {
    std::cerr << "BRIDGE-MAC-PROVIDER-ROUTE no provider for rtc_engine\n";
    return 1;
  }

  beacon::CallData preview_call = rtc_call;
  preview_call.interface_name = "video_preview";
  preview_call.function_name = "isPreviewing";
  if (adapter.provider_registry().Resolve(preview_call) == nullptr) {
    std::cerr << "BRIDGE-MAC-PROVIDER-ROUTE no provider for video_preview\n";
    return 1;
  }
  beacon::CallData visual_call = rtc_call;
  visual_call.interface_name = "visual_probe";
  visual_call.class_name = "AgoraVisualProbe";
  visual_call.function_name = "captureSnapshot";
  if (adapter.provider_registry().Resolve(visual_call) == nullptr) {
    std::cerr << "BRIDGE-MAC-PROVIDER-ROUTE no provider for visual_probe\n";
    return 1;
  }
  beacon::CallData network_call;
  network_call.sdk = "beacon_system";
  network_call.interface_name = "network_condition";
  network_call.class_name = "NetworkCondition";
  network_call.function_name = "applyImpairment";
  if (adapter.provider_registry().Resolve(network_call) == nullptr) {
    std::cerr << "BRIDGE-MAC-PROVIDER-ROUTE no provider for network_condition\n";
    return 1;
  }

  beacon::CallData video_host_call;
  video_host_call.sdk = "beacon_system";
  video_host_call.interface_name = "video_host";
  video_host_call.class_name = "VideoHost";
  if (adapter.provider_registry().Resolve(video_host_call) == nullptr) {
    std::cerr << "BRIDGE-MAC-PROVIDER-ROUTE no provider for video_host\n";
    return 1;
  }
  for (const char* function_name : {"show", "hide", "focus", "rearrange"}) {
    video_host_call.function_name = function_name;
    if (adapter.kernel().invocations().CallInvocation(video_host_call).error != 488) {
      std::cerr << "BRIDGE-MAC-PROVIDER-ROUTE unbound video_host should be unavailable\n";
      return 1;
    }
  }
  return 0;
}

int BridgeMacBackendWiring() {
  beacon::RunnerKernel kernel;
  beacon::mac::RTCEventBridge expected_bridge(&kernel);
  beacon::mac::RTCEventBridge other_bridge(&kernel);
  beacon::mac::MockAgoraSDKAdapter sdk;
  beacon::mac::ViewRegistry views;
  auto backend =
      beacon::mac::CreateMockRTCBackend(&sdk, []() { return true; }, &expected_bridge, &views);
  beacon::CallData call;
  call.params_json = R"({"channel":"wired"})";
  call.store_as = "engine_wired";
  if (!backend || !backend->JoinChannel(call).ok()) {
    std::cerr << "BRIDGE-MAC-BACKEND-WIRING joinChannel failed\n";
    return 1;
  }
  if (expected_bridge.active_engine_identity().resource_ref != "engine_wired" ||
      expected_bridge.active_engine_identity().instance_id != "engine_wired") {
    std::cerr << "BRIDGE-MAC-BACKEND-WIRING expected bridge did not receive identity\n";
    return 1;
  }
  if (!other_bridge.active_engine_identity().resource_ref.empty() ||
      !other_bridge.active_engine_identity().instance_id.empty()) {
    std::cerr << "BRIDGE-MAC-BACKEND-WIRING identity leaked to unrelated bridge\n";
    return 1;
  }
  backend->Reset();
  if (!expected_bridge.active_engine_identity().resource_ref.empty() ||
      !expected_bridge.active_engine_identity().instance_id.empty()) {
    std::cerr << "BRIDGE-MAC-BACKEND-WIRING expected bridge identity not cleared on reset\n";
    return 1;
  }
  return 0;
}

int BridgeMacBackendFailures() {
  beacon::mac::PlatformAdapter denied_adapter;
  denied_adapter.Bind();
  denied_adapter.DenyMediaPermissionForTesting();
  if (!HasResponseCode(Invoke(&denied_adapter, "op-backend-denied-join", "rtc_engine", "AgoraRtcEngineKit",
                              "joinChannel", R"({"channel":"denied"})"),
                       beacon::mac::kPermissionDenied, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&denied_adapter, "op-backend-denied-preview", "video_preview", "AgoraRtcEngineKit",
                              "startPreview"),
                       beacon::mac::kPermissionDenied, "BRIDGE-MAC-BACKEND-FAILURES")) {
    std::cerr << "BRIDGE-MAC-BACKEND-FAILURES media permission failures were not surfaced\n";
    return 1;
  }

  beacon::mac::ViewRegistry views;
  FailingSDKAdapter failing_sdk;
  auto failing_backend = beacon::mac::CreateMockRTCBackend(&failing_sdk, []() { return true; }, nullptr, &views);
  if (failing_backend->Load() != beacon::kBadRequest ||
      failing_backend->JoinChannel(RtcCall("joinChannel", R"({"channel":"sdk-fail"})")).error !=
          beacon::kBadRequest ||
      failing_backend->BindLocalVideo(RtcCall("bindLocalVideo", R"({"view_id":"local"})")).error !=
          beacon::kBadRequest ||
      failing_backend->BindRemoteVideo(RtcCall("bindRemoteVideo", R"({"uid":1002,"view_id":"remote"})")).error !=
          beacon::kBadRequest ||
      failing_backend->StartPreview(RtcCall("startPreview")).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-BACKEND-FAILURES SDK load failures were not surfaced\n";
    return 1;
  }

  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  if (!HasResponseCode(Invoke(&adapter, "op-backend-local-missing-role", "visual_probe", "AgoraVisualProbe",
                              "bindLocalVideo", "{}"),
                       beacon::kBadRequest, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&adapter, "op-backend-local-missing-handle", "visual_probe", "AgoraVisualProbe",
                              "bindLocalVideo", R"({"view_role":"missing"})"),
                       403, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&adapter, "op-backend-remote-missing-uid", "visual_probe", "AgoraVisualProbe",
                              "bindRemoteVideo", "{}"),
                       beacon::kBadRequest, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&adapter, "op-backend-remote-missing-view", "visual_probe", "AgoraVisualProbe",
                              "bindRemoteVideo", R"({"uid":1002})"),
                       beacon::kBadRequest, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&adapter, "op-backend-remote-missing-handle", "visual_probe", "AgoraVisualProbe",
                              "bindRemoteVideo", R"({"uid":1002,"view_role":"missing"})"),
                       403, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&adapter, "op-backend-snapshot-missing-role", "visual_probe", "AgoraVisualProbe",
                              "captureSnapshot", "{}"),
                       beacon::kBadRequest, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&adapter, "op-backend-snapshot-unbound", "visual_probe", "AgoraVisualProbe",
                              "captureSnapshot", R"({"view_role":"missing"})"),
                       403, "BRIDGE-MAC-BACKEND-FAILURES")) {
    std::cerr << "BRIDGE-MAC-BACKEND-FAILURES view validation failures were not surfaced\n";
    return 1;
  }
  int local_view = 1;
  adapter.views().Attach("local", &local_view);
  if (!HasResponseCode(Invoke(&adapter, "op-backend-local-ok", "visual_probe", "AgoraVisualProbe",
                              "bindLocalVideo", R"({"view_role":"local"})"),
                       beacon::kOk, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(Invoke(&adapter, "op-backend-snapshot-ok", "visual_probe", "AgoraVisualProbe",
                              "captureSnapshot", R"({"view_role":"local"})"),
                       beacon::kOk, "BRIDGE-MAC-BACKEND-FAILURES")) {
    std::cerr << "BRIDGE-MAC-BACKEND-FAILURES valid local view did not bind\n";
    return 1;
  }
  const auto release_unbound = Invoke(&adapter, "op-backend-release-unbound", "visual_probe", "AgoraVisualProbe",
                                      "releaseView", R"({"view_role":"remote"})");
  if (!HasResponseCode(Invoke(&adapter, "op-backend-release-missing-role", "visual_probe", "AgoraVisualProbe",
                              "releaseView", "{}"),
                       beacon::kBadRequest, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !HasResponseCode(release_unbound, beacon::kOk, "BRIDGE-MAC-BACKEND-FAILURES") ||
      !ResponseResultContains(release_unbound, "\"released\":false", "BRIDGE-MAC-BACKEND-FAILURES")) {
    std::cerr << "BRIDGE-MAC-BACKEND-FAILURES release edge response mismatch\n";
    return 1;
  }
  if (!ResponseResultContains(Invoke(&adapter, "op-backend-idle", "rtc_engine", "AgoraRtcEngineKit",
                                     "getConnectionState"),
                              "\"idle\"", "BRIDGE-MAC-BACKEND-FAILURES")) {
    std::cerr << "BRIDGE-MAC-BACKEND-FAILURES idle state was not reported\n";
    return 1;
  }
  if (!HasResponseCode(Invoke(&adapter, "op-backend-unload", "rtc_engine", "SDKLifecycle", "unloadSDK"),
                       beacon::kOk, "BRIDGE-MAC-BACKEND-FAILURES") ||
      adapter.sdk_loader().loaded() || adapter.rtc().initialized() ||
      adapter.rtc().joined() || adapter.rtc().previewing()) {
    std::cerr << "BRIDGE-MAC-BACKEND-FAILURES unload did not reset backend state\n";
    return 1;
  }
  return 0;
}

int BridgeMacProviderFailures() {
  beacon::InvocationController controller;
  controller.Init();
  beacon::mac::RTCInvocationProvider rtc_provider(nullptr);
  beacon::mac::AgoraVisualProbeProvider visual_provider(nullptr);
  rtc_provider.RegisterInvocations(controller);
  visual_provider.RegisterInvocations(controller);

  beacon::CallData preview_call = RtcCall("startPreview");
  preview_call.interface_name = "video_preview";
  beacon::CallData unsupported_call = RtcCall("joinChannel");
  unsupported_call.sdk = "other_sdk";
  if (!rtc_provider.Supports(RtcCall("joinChannel")) || !rtc_provider.Supports(preview_call) ||
      rtc_provider.Supports(unsupported_call) ||
      !visual_provider.Supports(VisualCall("captureSnapshot")) ||
      visual_provider.Supports(RtcCall("joinChannel"))) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES supports routing mismatch\n";
    return 1;
  }

  const std::vector<beacon::CallData> missing_backend_calls = {
      RtcCall("joinChannel", R"({"channel":"missing-backend"})"),
      RtcCall("leaveChannel"),
      RtcCall("renewToken", R"({"token":"token"})"),
      RtcCall("enableLocalAudio", R"({"enabled":false})"),
      RtcCall("enableLocalVideo", R"({"enabled":false})"),
      RtcCall("getConnectionState"),
      VisualCall("bindLocalVideo", R"({"view_role":"local"})"),
      VisualCall("bindRemoteVideo", R"({"uid":1002,"view_role":"remote"})"),
      VisualCall("captureSnapshot", R"({"view_role":"remote"})"),
      VisualCall("releaseView", R"({"view_role":"remote"})"),
  };
  for (const auto& call : missing_backend_calls) {
    if (controller.CallInvocation(call).error != beacon::kBadRequest) {
      std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES missing backend accepted " << call.function_name << "\n";
      return 1;
    }
  }
  if (controller.CallInvocation(preview_call).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES preview missing backend was accepted\n";
    return 1;
  }
  beacon::CallData stop_preview_call = preview_call;
  stop_preview_call.function_name = "stopPreview";
  if (controller.CallInvocation(stop_preview_call).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES stop preview missing backend was accepted\n";
    return 1;
  }
  if (controller.CallInvocation(RtcCall("getLastMileStats")).error != beacon::kOk ||
      controller.CallInvocation(RtcCall("isJoined")).result_json != "false" ||
      controller.CallInvocation(stop_preview_call).error != beacon::kBadRequest ||
      rtc_provider.initialized() || rtc_provider.joined() || rtc_provider.previewing() ||
      !rtc_provider.channel().empty() || !rtc_provider.registered()) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES provider status mismatch\n";
    return 1;
  }
  if (controller.CallInvocation(LifecycleCall("loadSDK")).error != beacon::kBadRequest ||
      controller.CallInvocation(LifecycleCall("unloadSDK")).error != beacon::kOk) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES lifecycle missing backend mismatch\n";
    return 1;
  }

  beacon::mac::MockAgoraSDKAdapter sdk;
  beacon::mac::ViewRegistry views;
  int local_view = 1;
  views.Attach("local", &local_view);
  std::shared_ptr<beacon::mac::RTCBackend> backend(
      beacon::mac::CreateMockRTCBackend(&sdk, []() { return true; }, nullptr, &views).release());
  rtc_provider.SetBackend(backend);
  if (controller.CallInvocation(LifecycleCall("loadSDK")).error != beacon::kOk ||
      !rtc_provider.initialized()) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES set backend did not enable lifecycle\n";
    return 1;
  }
  beacon::InvocationController visual_controller;
  visual_controller.Init();
  beacon::mac::AgoraVisualProbeProvider visual_with_backend(backend);
  visual_with_backend.RegisterInvocations(visual_controller);
  if (visual_controller.CallInvocation(VisualCall("bindLocalVideo", R"({"view_role":"local"})")).error !=
      beacon::kOk) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES visual local forwarding failed\n";
    return 1;
  }
  if (controller.CallInvocation(LifecycleCall("unloadSDK")).error != beacon::kOk ||
      rtc_provider.initialized()) {
    std::cerr << "BRIDGE-MAC-PROVIDER-FAILURES destroy did not unload backend\n";
    return 1;
  }
  rtc_provider.Reset();
  return 0;
}

int BridgeMacPermissionFixture() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto denied = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-perm-denied","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"denied\"}","extra":"{\"permission_fixture\":\"deny_media_for_testing\"}"}]}})");
  if (denied.find("\"code\":402") == std::string::npos || adapter.rtc().joined()) {
    std::cerr << "BRIDGE-MAC-PERMISSION-FIXTURE denied join did not fail as expected\n";
    return 1;
  }

  const auto normal = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-perm-normal","timestamp_ms":2},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"normal\"}","extra":"{}"}]}})");
  if (normal.find("\"code\":0") == std::string::npos || !adapter.rtc().joined() || adapter.rtc().channel() != "normal") {
    std::cerr << "BRIDGE-MAC-PERMISSION-FIXTURE fixture leaked into next join\n";
    return 1;
  }
  return 0;
}

int BridgeMacRenewToken() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto load = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-renew-load","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"SDKLifecycle","function":"loadSDK"},"params":"{}"}]}})");
  Json::Value load_root;
  if (!ParseJsonOrLog(load, &load_root, "BRIDGE-MAC-RENEW-TOKEN-LOAD") ||
      load_root["data"].get("code", -1).asInt() != 0) {
    std::cerr << "BRIDGE-MAC-RENEW-TOKEN load failed: " << load << "\n";
    return 1;
  }
  const auto missing = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-renew-missing","timestamp_ms":2},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"renewToken"},"params":"{}"}]}})");
  Json::Value missing_root;
  if (!ParseJsonOrLog(missing, &missing_root, "BRIDGE-MAC-RENEW-TOKEN-MISSING") ||
      missing_root["data"].get("code", -1).asInt() == 0) {
    std::cerr << "BRIDGE-MAC-RENEW-TOKEN missing token should fail: " << missing << "\n";
    return 1;
  }
  const auto renewed = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-renew-ok","timestamp_ms":3},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"renewToken"},"params":"{\"token\":\"runtime-token\"}"}]}})");
  Json::Value renewed_root;
  if (!ParseJsonOrLog(renewed, &renewed_root, "BRIDGE-MAC-RENEW-TOKEN-OK") ||
      renewed_root["data"].get("code", -1).asInt() != 0 ||
      renewed_root["data"]["list"][0].get("result", "").asString().find("\"renewed\":true") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-RENEW-TOKEN unexpected response: " << renewed << "\n";
    return 1;
  }
  return 0;
}

int BridgeMacSyntheticVideo() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto unloaded_start = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-unloaded-start","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"startSyntheticVideo"},"params":"{}"}]}})");
  Json::Value unloaded_start_root;
  if (!ParseJsonOrLog(unloaded_start, &unloaded_start_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      unloaded_start_root["data"].get("code", -1).asInt() != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO start before loadSDK should fail: " << unloaded_start << "\n";
    return 1;
  }
  const auto unloaded_stop = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-unloaded-stop","timestamp_ms":2},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"stopSyntheticVideo"},"params":"{}"}]}})");
  Json::Value unloaded_stop_root;
  if (!ParseJsonOrLog(unloaded_stop, &unloaded_stop_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      unloaded_stop_root["data"].get("code", -1).asInt() != beacon::kOk ||
      unloaded_stop_root["data"]["list"][0].get("result", "").asString().find("\"stopped\":false") ==
          std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO stop before loadSDK should stay idle: " << unloaded_stop << "\n";
    return 1;
  }
  const auto load = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-load","timestamp_ms":3},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"SDKLifecycle","function":"loadSDK"},"params":"{}"}]}})");
  Json::Value load_root;
  if (!ParseJsonOrLog(load, &load_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      load_root["data"].get("code", -1).asInt() != beacon::kOk) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO load failed: " << load << "\n";
    return 1;
  }
  const auto invalid_width = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-bad-width","timestamp_ms":4},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"startSyntheticVideo"},"params":"{\"width\":0}"}]}})");
  if (invalid_width.find("\"code\":400") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO zero width should fail: " << invalid_width << "\n";
    return 1;
  }
  const auto invalid_pattern = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-bad-pattern","timestamp_ms":5},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"startSyntheticVideo"},"params":"{\"pattern\":\"nope\"}"}]}})");
  if (invalid_pattern.find("\"code\":400") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO unknown pattern should fail: " << invalid_pattern << "\n";
    return 1;
  }
  const auto started = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-start","timestamp_ms":6},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"startSyntheticVideo"},"params":"{\"width\":320,\"height\":240,\"fps\":15,\"pattern\":\"moving_stripe\"}"}]}})");
  Json::Value started_root;
  if (!ParseJsonOrLog(started, &started_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      started_root["data"].get("code", -1).asInt() != beacon::kOk ||
      started_root["data"]["list"][0].get("result", "").asString().find("\"started\":true") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO start failed: " << started << "\n";
    return 1;
  }
  const auto restarted = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-restart","timestamp_ms":7},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"startSyntheticVideo"},"params":"{}"}]}})");
  Json::Value restarted_root;
  if (!ParseJsonOrLog(restarted, &restarted_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      restarted_root["data"].get("code", -1).asInt() != beacon::kOk ||
      restarted_root["data"]["list"][0].get("result", "").asString().find("\"started\":true") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO restart should stay active: " << restarted << "\n";
    return 1;
  }
  const auto stopped = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-stop","timestamp_ms":8},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"stopSyntheticVideo"},"params":"{}"}]}})");
  Json::Value stopped_root;
  if (!ParseJsonOrLog(stopped, &stopped_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      stopped_root["data"].get("code", -1).asInt() != beacon::kOk ||
      stopped_root["data"]["list"][0].get("result", "").asString().find("\"stopped\":true") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO stop failed: " << stopped << "\n";
    return 1;
  }
  const auto stopped_again = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-stop-again","timestamp_ms":9},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"stopSyntheticVideo"},"params":"{}"}]}})");
  Json::Value stopped_again_root;
  if (!ParseJsonOrLog(stopped_again, &stopped_again_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      stopped_again_root["data"].get("code", -1).asInt() != beacon::kOk ||
      stopped_again_root["data"]["list"][0].get("result", "").asString().find("\"stopped\":false") ==
          std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO double stop should report idle: " << stopped_again << "\n";
    return 1;
  }
  const auto started_before_reset = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-start-before-reset","timestamp_ms":10},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"startSyntheticVideo"},"params":"{}"}]}})");
  if (started_before_reset.find("\"code\":0") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO start before reset failed: " << started_before_reset << "\n";
    return 1;
  }
  const auto session_reset = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-reset-session","timestamp_ms":11},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"beacon_system","interface":"runtime","class_name":"AgentRuntime","function":"resetSession"},"params":"{}"}]}})");
  Json::Value session_reset_root;
  if (!ParseJsonOrLog(session_reset, &session_reset_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      session_reset_root["data"].get("code", -1).asInt() != beacon::kOk) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO resetSession failed: " << session_reset << "\n";
    return 1;
  }
  const auto stopped_after_reset = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-synth-stop-after-reset","timestamp_ms":12},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"stopSyntheticVideo"},"params":"{}"}]}})");
  Json::Value stopped_after_reset_root;
  if (!ParseJsonOrLog(stopped_after_reset, &stopped_after_reset_root, "BRIDGE-MAC-SYNTHETIC-VIDEO") ||
      stopped_after_reset_root["data"].get("code", -1).asInt() != beacon::kOk ||
      stopped_after_reset_root["data"]["list"][0].get("result", "").asString().find("\"stopped\":false") ==
          std::string::npos) {
    std::cerr << "BRIDGE-MAC-SYNTHETIC-VIDEO resetSession should deactivate synthetic source: "
              << stopped_after_reset << "\n";
    return 1;
  }
  return 0;
}

int BridgeMacJoinCallbackTimeoutFixture() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto join = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-join-timeout","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"timeout\"}","extra":"{\"callback_fixture\":\"suppress_join_success_for_testing\"}"}]}})");
  if (join.find("\"code\":0") == std::string::npos || !adapter.rtc().joined() || adapter.rtc().channel() != "timeout") {
    std::cerr << "BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE join should still succeed\n";
    return 1;
  }
  if (!adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1001})").empty()) {
    std::cerr << "BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE join callback was not suppressed\n";
    return 1;
  }

  const auto normal = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-join-normal","timestamp_ms":2},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"normal\"}","extra":"{}"}]}})");
  if (normal.find("\"code\":0") == std::string::npos || !adapter.rtc().joined() || adapter.rtc().channel() != "normal") {
    std::cerr << "BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE fixture leaked into next join\n";
    return 1;
  }
  const auto event = adapter.events().Emit("onJoinChannelSuccess", R"({"uid":1002})");
  Json::Value event_root;
  if (!ParseJsonOrLog(event, &event_root, "BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE") ||
      !HasReceiptOnlyCallbackResponse(event_root, "BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE") ||
      event_root["data"]["receipt"].get("recorded", true).asBool() ||
      adapter.kernel().callbacks().last_execution_result().matched) {
    std::cerr << "BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE normal callback path did not recover\n";
    return 1;
  }
  return 0;
}

int BridgeMacLocalMediaEnable() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto disable_video = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-enable-video-off","timestamp_ms":1},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"enableLocalVideo"},"params":"{\"enabled\":false}"}]}})");
  Json::Value disable_video_root;
  if (!ParseJsonOrLog(disable_video, &disable_video_root, "BRIDGE-MAC-LOCAL-MEDIA-ENABLE")) {
    return 1;
  }
  const auto disable_video_result = disable_video_root["data"]["list"][0].get("result", "").asString();
  if (disable_video_root["data"].get("code", -1).asInt() != 0 ||
      disable_video_result.find("\"video\":false") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-LOCAL-MEDIA-ENABLE disable video failed: " << disable_video << "\n";
    return 1;
  }
  const auto enable_video = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-enable-video-on","timestamp_ms":2},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"enableLocalVideo"},"params":"{\"enabled\":true}"}]}})");
  Json::Value enable_video_root;
  if (!ParseJsonOrLog(enable_video, &enable_video_root, "BRIDGE-MAC-LOCAL-MEDIA-ENABLE")) {
    return 1;
  }
  const auto enable_video_result = enable_video_root["data"]["list"][0].get("result", "").asString();
  if (enable_video_root["data"].get("code", -1).asInt() != 0 ||
      enable_video_result.find("\"video\":true") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-LOCAL-MEDIA-ENABLE enable video failed: " << enable_video << "\n";
    return 1;
  }
  const auto disable_audio = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-enable-audio-off","timestamp_ms":3},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"enableLocalAudio"},"params":"{\"enabled\":false}"}]}})");
  Json::Value disable_audio_root;
  if (!ParseJsonOrLog(disable_audio, &disable_audio_root, "BRIDGE-MAC-LOCAL-MEDIA-ENABLE")) {
    return 1;
  }
  const auto disable_audio_result = disable_audio_root["data"]["list"][0].get("result", "").asString();
  if (disable_audio_root["data"].get("code", -1).asInt() != 0 ||
      disable_audio_result.find("\"audio\":false") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-LOCAL-MEDIA-ENABLE disable audio failed: " << disable_audio << "\n";
    return 1;
  }
  const auto enable_audio = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-enable-audio-on","timestamp_ms":4},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"enableLocalAudio"},"params":"{\"enabled\":true}"}]}})");
  Json::Value enable_audio_root;
  if (!ParseJsonOrLog(enable_audio, &enable_audio_root, "BRIDGE-MAC-LOCAL-MEDIA-ENABLE")) {
    return 1;
  }
  const auto enable_audio_result = enable_audio_root["data"]["list"][0].get("result", "").asString();
  if (enable_audio_root["data"].get("code", -1).asInt() != 0 ||
      enable_audio_result.find("\"audio\":true") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-LOCAL-MEDIA-ENABLE enable audio failed: " << enable_audio << "\n";
    return 1;
  }
  return 0;
}

int BridgeMacVisualProbe() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  int remote_view = 8;
  adapter.views().Attach("primary_remote_view", &remote_view);
  const auto bind_response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-visual-bind","timestamp_ms":8},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"visual_probe","class_name":"AgoraVisualProbe","function":"bindRemoteVideo"},"params":"{\"uid\":1002,\"view_role\":\"primary_remote_view\"}"}]}})");
  Json::Value bind_root;
  if (!ParseJsonOrLog(bind_response, &bind_root, "BRIDGE-MAC-VISUAL-PROBE-BIND")) {
    return 1;
  }
  if (bind_root["data"].get("code", -1).asInt() != 0 ||
      bind_root["data"]["list"][0].get("result", "").asString().find("\"view_id\":\"primary_remote_view\"") ==
          std::string::npos) {
    std::cerr << "BRIDGE-MAC-VISUAL-PROBE-BIND unexpected response: " << bind_response << "\n";
    return 1;
  }
  const auto snapshot_response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-visual-snapshot","timestamp_ms":9},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"visual_probe","class_name":"AgoraVisualProbe","function":"captureSnapshot"},"params":"{\"view_role\":\"primary_remote_view\"}","extra":"{\"run_id\":\"run-visual\",\"case_id\":\"TC-VISUAL\",\"step_id\":\"capture\"}"}]}})");
  Json::Value snapshot_root;
  if (!ParseJsonOrLog(snapshot_response, &snapshot_root, "BRIDGE-MAC-VISUAL-PROBE-SNAPSHOT")) {
    return 1;
  }
  if (snapshot_root["data"].get("code", -1).asInt() != 0 ||
      snapshot_root["data"]["list"][0].get("result", "").asString().find("\"snapshot_requested\":true") ==
          std::string::npos) {
    std::cerr << "BRIDGE-MAC-VISUAL-PROBE-SNAPSHOT unexpected response: " << snapshot_response << "\n";
    return 1;
  }
  const auto snapshot_origin = adapter.events().active_engine_identity();
  if (snapshot_origin.originating_op_id != "op-visual-snapshot" || snapshot_origin.resource_ref != "engine_1" ||
      snapshot_origin.run_id != "run-visual" || snapshot_origin.case_id != "TC-VISUAL" ||
      snapshot_origin.step_id != "capture") {
    std::cerr << "BRIDGE-MAC-VISUAL-PROBE-SNAPSHOT did not update callback origin\n";
    return 1;
  }
  const auto release_response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-visual-release","timestamp_ms":10},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"visual_probe","class_name":"AgoraVisualProbe","function":"releaseView"},"params":"{\"view_role\":\"primary_remote_view\"}"}]}})");
  Json::Value release_root;
  if (!ParseJsonOrLog(release_response, &release_root, "BRIDGE-MAC-VISUAL-PROBE-RELEASE")) {
    return 1;
  }
  if (release_root["data"].get("code", -1).asInt() != 0 ||
      release_root["data"]["list"][0].get("result", "").asString().find("\"released\":true") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-VISUAL-PROBE-RELEASE unexpected response: " << release_response << "\n";
    return 1;
  }
  const auto after_release_snapshot = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-visual-snapshot-after-release","timestamp_ms":11},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"visual_probe","class_name":"AgoraVisualProbe","function":"captureSnapshot"},"params":"{\"view_role\":\"primary_remote_view\"}"}]}})");
  Json::Value after_release_root;
  if (!ParseJsonOrLog(after_release_snapshot, &after_release_root, "BRIDGE-MAC-VISUAL-PROBE-AFTER-RELEASE")) {
    return 1;
  }
  if (after_release_root["data"].get("code", -1).asInt() != 403) {
    std::cerr << "BRIDGE-MAC-VISUAL-PROBE-AFTER-RELEASE unexpected response: " << after_release_snapshot << "\n";
    return 1;
  }
  return 0;
}

int BridgeMacPlatformLog() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  beacon::TraceContext trace;
  trace.node_id = "mac-mock-platform-log";
  trace.lease_id = "lease-platform-log";
  trace.run_id = "run-platform-log";
  trace.case_id = "TC-PLATFORM-LOG";
  trace.step_id = "capture";
  trace.op_id = "op-platform-log";
  adapter.kernel().logs().SetTraceContext(trace);

  const auto event = adapter.platform_logs().Record(beacon::mac::PlatformLogEntry{
      .level = "error",
      .subsystem = "com.apple.avfoundation",
      .category = "capture",
      .source = "unified_log",
      .message = "camera failure token=secret",
      .error = 5601,
  });

  beacon::LogQuery query;
  query.node_id = "mac-mock-platform-log";
  query.lease_id = "lease-platform-log";
  query.run_id = "run-platform-log";
  query.case_id = "TC-PLATFORM-LOG";
  query.step_id = "capture";
  query.op_id = "op-platform-log";
  const auto logs = adapter.kernel().logs().Query(query);
  if (event.module != "platform" || event.event != "platform.system.log" || logs.size() != 1U) {
    std::cerr << "BRIDGE-MAC-PLATFORM-LOG event not routed through LogReporter\n";
    return 1;
  }
  const auto& log = logs[0];
  if (log.level != "error" || log.error != 5601 || log.extra.get("platform", "").asString() != "mac" ||
      log.extra.get("subsystem", "").asString() != "com.apple.avfoundation" ||
      log.extra.get("category", "").asString() != "capture" ||
      log.extra.get("source", "").asString() != "unified_log") {
    std::cerr << "BRIDGE-MAC-PLATFORM-LOG structured fields missing\n";
    return 1;
  }
  if (log.message.find("secret") != std::string::npos || log.message.find("<redacted>") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-PLATFORM-LOG message was not redacted: " << log.message << "\n";
    return 1;
  }
  return 0;
}

// 锁死五类脱敏覆盖面：token、app cert、app id、Authorization/Bearer、本机用户路径。
int BridgeMacRedaction() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Init();
  beacon::TraceContext trace;
  trace.node_id = "mac-mock-redaction";
  trace.lease_id = "lease-redaction";
  trace.run_id = "run-redaction";
  trace.case_id = "TC-REDACTION";
  trace.step_id = "capture";
  trace.op_id = "op-redaction";
  adapter.kernel().logs().SetTraceContext(trace);

  Json::Value extra(Json::objectValue);
  extra["AGORA_APP_CERT"] = "cert-value";
  extra["AGORA_APP_ID"] = "app-id-value";
  extra["token"] = "extra-token-value";
  extra["dump_path"] = "/Users/example/Library/Logs/Beacon/agora.log";
  const auto event = adapter.kernel().logs().Log(
      "error", "agora", "agora.join.failed",
      "token=abc Authorization Bearer secret AGORA_APP_CERT=cert-value AGORA_APP_ID=app-id-value "
      "/Users/example/Library/Logs/Beacon/agora.log $HOME/Library/Logs/Beacon/agora.log",
      109, extra);

  for (const char* leaked : {"abc", "cert-value", "app-id-value", "secret", "example", "Library/Logs/Beacon"}) {
    if (event.message.find(leaked) != std::string::npos) {
      std::cerr << "BRIDGE-MAC-REDACTION message leaked " << leaked << ": " << event.message << "\n";
      return 1;
    }
  }
  if (event.message.find("<redacted>") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-REDACTION message lost the redaction placeholder: " << event.message << "\n";
    return 1;
  }
  if (event.extra["AGORA_APP_CERT"].asString() != "<redacted>" ||
      event.extra["AGORA_APP_ID"].asString() != "<redacted>" ||
      event.extra["token"].asString() != "<redacted>" ||
      event.extra["dump_path"].asString().find("Library/Logs/Beacon") != std::string::npos) {
    std::cerr << "BRIDGE-MAC-REDACTION structured extra was not redacted\n";
    return 1;
  }
  return 0;
}

int NetworkConditionFixture() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const auto apply_response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-network-apply","timestamp_ms":12},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"beacon_system","interface":"network_condition","class_name":"NetworkCondition","function":"applyImpairment"},"params":"{\"profile\":\"weak_network\",\"duration_ms\":1000}"}]}})");
  Json::Value apply_root;
  if (!ParseJsonOrLog(apply_response, &apply_root, "FI-NETWORK-CONDITION-01-APPLY")) {
    return 1;
  }
  if (apply_root["data"].get("code", -1).asInt() != 0 ||
      apply_root["data"]["list"][0].get("result", "").asString().find("\"profile\":\"weak_network\"") ==
          std::string::npos) {
    std::cerr << "FI-NETWORK-CONDITION-01 apply unexpected response: " << apply_response << "\n";
    return 1;
  }

  const auto state_response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-network-state","timestamp_ms":13},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"beacon_system","interface":"network_condition","class_name":"NetworkCondition","function":"getConditionState"},"params":"{}"}]}})");
  Json::Value state_root;
  if (!ParseJsonOrLog(state_response, &state_root, "FI-NETWORK-CONDITION-01-STATE")) {
    return 1;
  }
  if (state_root["data"].get("code", -1).asInt() != 0 ||
      state_root["data"]["list"][0].get("result", "").asString().find("\"active\":true") == std::string::npos) {
    std::cerr << "FI-NETWORK-CONDITION-01 state unexpected response: " << state_response << "\n";
    return 1;
  }

  const auto reset_response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-network-reset","timestamp_ms":14},"data":{"node_id":"mac-mock-001","sync":true,"list":[{"target":{"sdk":"beacon_system","interface":"network_condition","class_name":"NetworkCondition","function":"resetImpairment"},"params":"{}"}]}})");
  Json::Value reset_root;
  if (!ParseJsonOrLog(reset_response, &reset_root, "FI-NETWORK-CONDITION-01-RESET")) {
    return 1;
  }
  if (reset_root["data"].get("code", -1).asInt() != 0 ||
      reset_root["data"]["list"][0].get("result", "").asString().find("\"active\":false") == std::string::npos) {
    std::cerr << "FI-NETWORK-CONDITION-01 reset unexpected response: " << reset_response << "\n";
    return 1;
  }
  return 0;
}

int NetworkConditionMacosBackendRequiresExplicitPrivilege() {
  beacon::mac::NetworkConditionProvider provider(
      beacon::mac::NetworkConditionProvider::Config{
          .backend = "macos_pf",
          .allow_privileged = false,
      },
      [](const std::string&) { return 0; });
  beacon::CallData call;
  call.params_json = R"({"profile":"weak_network","duration_ms":1000})";

  const auto result = provider.ApplyForTesting(call);

  if (result.error != 403 || result.result_json.find("\"backend\":\"macos_pf\"") == std::string::npos ||
      result.result_json.find("\"privileged_required\":true") == std::string::npos) {
    std::cerr << "FI-NETWORK-CONDITION-02 unexpected fail-closed response: " << result.result_json << "\n";
    return 1;
  }
  return 0;
}

int NetworkConditionMacosBackendBuildsProof() {
  std::vector<std::string> commands;
  beacon::mac::NetworkConditionProvider provider(
      beacon::mac::NetworkConditionProvider::Config{
          .backend = "macos_pf",
          .allow_privileged = true,
      },
      [&commands](const std::string& command) {
        commands.push_back(command);
        return 0;
      });
  beacon::CallData call;
  call.params_json = R"({"profile":"weak_network","duration_ms":1000})";

  const auto apply = provider.ApplyForTesting(call);
  const auto reset = provider.ResetForTesting();

  if (apply.error != 0 || reset.error != 0 || commands.size() != 5) {
    std::cerr << "FI-NETWORK-CONDITION-03 command count or result mismatch\n";
    return 1;
  }
  if (commands[0].find("/usr/sbin/dnctl pipe 9001 config") == std::string::npos ||
      commands[1].find("/sbin/pfctl -a com.beacon.network_condition -f -") == std::string::npos ||
      commands[2] != "/sbin/pfctl -E" ||
      commands[3] != "/sbin/pfctl -a com.beacon.network_condition -F all" ||
      commands[4] != "/usr/sbin/dnctl delete 9001") {
    std::cerr << "FI-NETWORK-CONDITION-03 unexpected commands\n";
    return 1;
  }
  if (apply.result_json.find("\"backend\":\"macos_pf\"") == std::string::npos ||
      apply.result_json.find("\"anchor\":\"com.beacon.network_condition\"") == std::string::npos ||
      apply.result_json.find("\"pipe\":9001") == std::string::npos ||
      apply.result_json.find("\"proof\"") == std::string::npos) {
    std::cerr << "FI-NETWORK-CONDITION-03 proof missing: " << apply.result_json << "\n";
    return 1;
  }
  return 0;
}

int NetworkConditionMacosBackendResetCleansActiveImpairment() {
  std::vector<std::string> commands;
  beacon::mac::NetworkConditionProvider provider(
      beacon::mac::NetworkConditionProvider::Config{
          .backend = "macos_pf",
          .allow_privileged = true,
      },
      [&commands](const std::string& command) {
        commands.push_back(command);
        return 0;
      });
  beacon::CallData call;
  call.params_json = R"({"profile":"weak_network","duration_ms":1000})";

  const auto apply = provider.ApplyForTesting(call);
  provider.Reset();

  if (apply.error != 0 || commands.size() != 5 ||
      commands[3] != "/sbin/pfctl -a com.beacon.network_condition -F all" ||
      commands[4] != "/usr/sbin/dnctl delete 9001") {
    std::cerr << "FI-NETWORK-CONDITION-04 Reset did not clean active macOS impairment\n";
    return 1;
  }
  return 0;
}

int NetworkConditionMacosBackendFailures() {
  beacon::mac::NetworkConditionProvider provider(
      beacon::mac::NetworkConditionProvider::Config{
          .backend = "macos_pf",
          .allow_privileged = true,
      },
      [](const std::string&) { return 0; });
  beacon::CallData missing_profile;
  missing_profile.params_json = "{}";
  if (provider.ApplyForTesting(missing_profile).error != beacon::kBadRequest) {
    std::cerr << "FI-NETWORK-CONDITION-05 missing profile was accepted\n";
    return 1;
  }
  beacon::CallData unsupported_profile;
  unsupported_profile.params_json = R"({"profile":"satellite","duration_ms":1000})";
  if (provider.ApplyForTesting(unsupported_profile).error != beacon::kBadRequest) {
    std::cerr << "FI-NETWORK-CONDITION-05 unsupported macOS profile was accepted\n";
    return 1;
  }
  int apply_attempt = 0;
  beacon::mac::NetworkConditionProvider apply_failure_provider(
      beacon::mac::NetworkConditionProvider::Config{
          .backend = "macos_pf",
          .allow_privileged = true,
      },
      [&apply_attempt](const std::string&) {
        apply_attempt++;
        return apply_attempt == 2 ? 17 : 0;
      });
  beacon::CallData weak_network;
  weak_network.params_json = R"({"profile":"weak_network","duration_ms":1000})";
  const auto apply_failure = apply_failure_provider.ApplyForTesting(weak_network);
  if (apply_failure.error != 17 ||
      apply_failure.result_json.find("\"exit_codes\"") == std::string::npos ||
      apply_failure.result_json.find("\"active\":false") == std::string::npos) {
    std::cerr << "FI-NETWORK-CONDITION-05 apply command failure did not include proof\n";
    return 1;
  }

  beacon::mac::NetworkConditionProvider reset_no_privilege(
      beacon::mac::NetworkConditionProvider::Config{
          .backend = "macos_pf",
          .allow_privileged = false,
      },
      [](const std::string&) { return 0; });
  if (reset_no_privilege.ResetForTesting().error != 403) {
    std::cerr << "FI-NETWORK-CONDITION-05 reset without privilege was accepted\n";
    return 1;
  }

  int command_count = 0;
  beacon::mac::NetworkConditionProvider reset_failure_provider(
      beacon::mac::NetworkConditionProvider::Config{
          .backend = "macos_pf",
          .allow_privileged = true,
      },
      [&command_count](const std::string&) {
        command_count++;
        return command_count == 4 ? 23 : 0;
      });
  if (reset_failure_provider.ApplyForTesting(weak_network).error != beacon::kOk ||
      reset_failure_provider.ResetForTesting().error != 23) {
    std::cerr << "FI-NETWORK-CONDITION-05 reset command failure was not surfaced\n";
    return 1;
  }

  beacon::mac::NetworkConditionProvider fixture_provider;
  beacon::CallData network_call;
  network_call.sdk = "beacon_system";
  network_call.interface_name = "network_condition";
  if (!fixture_provider.Supports(network_call)) {
    std::cerr << "FI-NETWORK-CONDITION-05 fixture provider did not support network_condition\n";
    return 1;
  }
  network_call.interface_name = "other";
  if (fixture_provider.Supports(network_call)) {
    std::cerr << "FI-NETWORK-CONDITION-05 wrong interface was supported\n";
    return 1;
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  const std::string id = argc > 1 ? argv[1] : "";
  if (id == "BUILD-MAC-01") return BuildMac01();
#ifdef __APPLE__
  if (id == "BRIDGE-MAC-VIDEO-HOST-ACTIVATION") return BridgeMacVideoHostActivation();
#endif
  if (id == "BRIDGE-MAC-01") return BridgeMac01();
  if (id == "BRIDGE-MAC-02") return BridgeMac02();
  if (id == "BRIDGE-MAC-03") return BridgeMac03();
  if (id == "BRIDGE-MAC-04") return BridgeMac04();
  if (id == "BRIDGE-MAC-06") return BridgeMac06();
  if (id == "BRIDGE-MAC-EVENT") return BridgeMacEvent();
  if (id == "BRIDGE-MAC-LIFECYCLE") return BridgeMacLifecycle();
  if (id == "BRIDGE-MAC-PROVIDER") return BridgeMacProvider();
  if (id == "BRIDGE-MAC-PROVIDER-ROUTE") return BridgeMacProviderRoute();
  if (id == "BRIDGE-MAC-TARGET-CONSISTENCY") return BridgeMacTargetConsistency();
  if (id == "BRIDGE-MAC-VIDEO-HOST") return BridgeMacVideoHostVisibility();
  if (id == "BRIDGE-MAC-VIDEO-HOST-LAYOUT") return BridgeMacVideoHostLayout();
  if (id == "BRIDGE-MAC-VIDEO-STATS-OVERLAY") return BridgeMacVideoStatsOverlay();
  if (id == "BRIDGE-MAC-SIMULCAST") return BridgeMacSimulcast();
  if (id == "BRIDGE-MAC-BACKEND-WIRING") return BridgeMacBackendWiring();
  if (id == "BRIDGE-MAC-BACKEND-FAILURES") return BridgeMacBackendFailures();
  if (id == "BRIDGE-MAC-PROVIDER-FAILURES") return BridgeMacProviderFailures();
  if (id == "BRIDGE-MAC-PERMISSION-FIXTURE") return BridgeMacPermissionFixture();
  if (id == "BRIDGE-MAC-RENEW-TOKEN") return BridgeMacRenewToken();
  if (id == "BRIDGE-MAC-JOIN-CALLBACK-TIMEOUT-FIXTURE") return BridgeMacJoinCallbackTimeoutFixture();
  if (id == "BRIDGE-MAC-LOCAL-MEDIA-ENABLE") return BridgeMacLocalMediaEnable();
  if (id == "BRIDGE-MAC-SYNTHETIC-VIDEO") return BridgeMacSyntheticVideo();
  if (id == "BRIDGE-MAC-VISUAL-PROBE") return BridgeMacVisualProbe();
  if (id == "BRIDGE-MAC-VOCABULARY") return BridgeMacVocabulary();
  if (id == "BRIDGE-MAC-PLATFORM-LOG") return BridgeMacPlatformLog();
  if (id == "BRIDGE-MAC-REDACTION") return BridgeMacRedaction();
  if (id == "FI-NETWORK-CONDITION-01") return NetworkConditionFixture();
  if (id == "FI-NETWORK-CONDITION-02") return NetworkConditionMacosBackendRequiresExplicitPrivilege();
  if (id == "FI-NETWORK-CONDITION-03") return NetworkConditionMacosBackendBuildsProof();
  if (id == "FI-NETWORK-CONDITION-04") return NetworkConditionMacosBackendResetCleansActiveImpairment();
  if (id == "FI-NETWORK-CONDITION-05") return NetworkConditionMacosBackendFailures();
  std::cerr << "unknown mac mock test id: " << id << "\n";
  return 1;
}
