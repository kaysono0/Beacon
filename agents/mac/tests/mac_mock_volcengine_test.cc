// 火山变体的 Mac mock 桥层测试。与 Agora 变体共用一致性 helper，
// 但只校验 volcengine_rtc 的契约行（各自只注册自己那一路 provider）。
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"
#include "bridge_target_consistency.h"
#include "platform/platform_adapter.h"
#include "rtc/rtc_command_vocabulary.h"
#include "vendors/volcengine/volcengine_sdk_loader.h"

namespace {

using beacon::mac::test_support::CheckVendorTargetConsistency;

// SDK 加载失败的最小 loader：驱动 backend 的 "sdk not loaded" 防御分支。
class FailingVolcengineSDKAdapter : public beacon::mac::MockVolcengineSDKAdapter {
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

std::string Invoke(beacon::mac::PlatformAdapter* adapter, const std::string& op_id, const std::string& interface_name,
                   const std::string& class_name, const std::string& function_name, const std::string& params_json) {
  Json::Value packet(Json::objectValue);
  packet["common"]["action"] = "invokeRequest";
  packet["common"]["op_id"] = op_id;
  packet["common"]["timestamp_ms"] = 1;
  packet["data"]["node_id"] = "mac-mock-001";
  packet["data"]["sync"] = true;
  Json::Value item(Json::objectValue);
  item["target"]["sdk"] = std::string(beacon::mac::rtc_commands::kSdk);
  item["target"]["interface"] = interface_name;
  item["target"]["class_name"] = class_name;
  item["target"]["function"] = function_name;
  item["params"] = params_json;
  packet["data"]["list"].append(item);
  return adapter->kernel().HandleRequest(beacon::WriteJson(packet));
}

bool Contains(const std::string& response, const std::string& needle, const char* test_id) {
  if (response.find(needle) == std::string::npos) {
    std::cerr << test_id << " expected " << needle << " in " << response << "\n";
    return false;
  }
  return true;
}

// 断言调用结果 JSON（data.list[0].result 是字符串形式的 JSON，需解析后比较）。
bool ResultContains(const std::string& response, const std::string& needle, const char* test_id) {
  Json::Value root;
  if (!beacon::ParseJson(response, &root)) {
    std::cerr << test_id << " response is not valid json: " << response << "\n";
    return false;
  }
  const Json::Value& item = root["data"]["list"][0];
  const std::string result = item.get("result", "").asString();
  if (result.find(needle) == std::string::npos) {
    std::cerr << test_id << " expected " << needle << " in result " << result << "\n";
    return false;
  }
  return true;
}

bool ResponseCodeIs(const std::string& response, int expected, const char* test_id) {
  Json::Value root;
  if (!beacon::ParseJson(response, &root)) {
    std::cerr << test_id << " response is not valid json: " << response << "\n";
    return false;
  }
  const int code = root["data"]["list"][0].get("code", -1).asInt();
  if (code != expected) {
    std::cerr << test_id << " expected code " << expected << " but got " << code << ": " << response << "\n";
    return false;
  }
  return true;
}

int BuildVolcengine01() {
  beacon::mac::PlatformAdapter adapter;
  if (adapter.Init() != beacon::kOk) {
    std::cerr << "BUILD-MAC-VOLCENGINE-01 init failed\n";
    return 1;
  }
  if (adapter.sdk_loader().version() != "mock-volcengine-0.1") {
    std::cerr << "BUILD-MAC-VOLCENGINE-01 unexpected loader version " << adapter.sdk_loader().version() << "\n";
    return 1;
  }
  if (adapter.Register() != beacon::kOk || !adapter.rtc().registered()) {
    std::cerr << "BUILD-MAC-VOLCENGINE-01 register failed\n";
    return 1;
  }
  if (adapter.Bind() != beacon::kOk) {
    std::cerr << "BUILD-MAC-VOLCENGINE-01 bind failed\n";
    return 1;
  }
  return 0;
}

// loader 的完整表面：Configure/app_id/未加载时的 version/Load/Unload/loaded。
int BuildVolcengine02() {
  beacon::mac::MockVolcengineSDKAdapter sdk;
  sdk.Configure("app-1");
  if (sdk.app_id() != "app-1" || !sdk.version().empty() || sdk.loaded()) {
    std::cerr << "BUILD-MAC-VOLCENGINE-02 unloaded-state surface mismatch\n";
    return 1;
  }
  if (!sdk.Load() || !sdk.loaded() || sdk.version() != "mock-volcengine-0.1") {
    std::cerr << "BUILD-MAC-VOLCENGINE-02 load surface mismatch\n";
    return 1;
  }
  if (!sdk.Unload() || sdk.loaded() || !sdk.app_id().empty()) {
    std::cerr << "BUILD-MAC-VOLCENGINE-02 unload surface mismatch\n";
    return 1;
  }
  return 0;
}

// 直接驱动火山 mock backend 的完整 RTCBackend 表面：
// 已声明能力走真实分支，未声明能力必须显式返回不支持而不是静默成功。
int BridgeMacVolcengineBackendSurface() {
  beacon::RunnerKernel kernel;
  beacon::mac::RTCEventBridge events(&kernel);
  beacon::mac::MockVolcengineSDKAdapter sdk;
  beacon::mac::ViewRegistry views;
  auto backend = beacon::mac::CreateMockRTCBackend(&sdk, []() { return true; }, &events, &views);
  if (!backend || backend->Load() != beacon::kOk || !backend->initialized()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE load failed\n";
    return 1;
  }

  beacon::CallData join;
  join.params_json = R"({"room_id":"room-9","user_id":"user-9","token":"t"})";
  if (!backend->JoinChannel(join).ok() || !backend->joined() || backend->channel() != "room-9") {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE join failed\n";
    return 1;
  }
  if (backend->GetConnectionState(join).result_json.find("\"state\":1") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE joined state mismatch\n";
    return 1;
  }
  if (!backend->LeaveChannel().ok() || backend->joined()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE leave failed\n";
    return 1;
  }
  if (backend->GetConnectionState(join).result_json.find("\"state\":0") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE idle state mismatch\n";
    return 1;
  }

  const std::vector<beacon::CallResult> unsupported = {
      backend->EnableLocalAudio(true),
      backend->EnableLocalVideo(true),
      backend->RenewToken(join),
  };
  for (const auto& result : unsupported) {
    if (result.error != beacon::kBadRequest || result.message != "capability not declared for this vendor") {
      std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE undeclared capability did not fail closed\n";
      return 1;
    }
  }

  // 已声明画面能力：绑定 / 快照 / 释放 / 采集开关 / 合成源参数校验走真实分支。
  // 直连 backend 的绑定用 view_id（probe 层把 view_role 翻译为 view_id，见 provider）。
  int local_view = 1;
  int remote_view = 2;
  views.Attach("primary_local_preview", &local_view);
  views.Attach("primary_remote_view", &remote_view);
  beacon::CallData bind_local;
  bind_local.params_json = R"({"view_id":"primary_local_preview"})";
  if (!backend->BindLocalVideo(bind_local).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE bind local video failed\n";
    return 1;
  }
  beacon::CallData bind_local_unbound;
  bind_local_unbound.params_json = R"({"view_id":"missing_local_view"})";
  if (backend->BindLocalVideo(bind_local_unbound).error != 403) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE bind local with unknown view must fail\n";
    return 1;
  }
  beacon::CallData bind_remote;
  bind_remote.params_json = R"({"uid":"user-9","view_id":"primary_remote_view"})";
  if (!backend->BindRemoteVideo(bind_remote).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE bind remote video failed\n";
    return 1;
  }
  beacon::CallData missing_uid;
  missing_uid.params_json = R"({"view_id":"primary_remote_view"})";
  if (backend->BindRemoteVideo(missing_uid).error == beacon::kOk) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE remote bind accepted missing uid\n";
    return 1;
  }
  beacon::CallData bind_local_missing_view;
  bind_local_missing_view.params_json = "{}";
  if (backend->BindLocalVideo(bind_local_missing_view).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE local bind accepted missing view id\n";
    return 1;
  }
  beacon::CallData bind_remote_missing_view;
  bind_remote_missing_view.params_json = R"({"uid":"user-9"})";
  if (backend->BindRemoteVideo(bind_remote_missing_view).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE remote bind accepted missing view id\n";
    return 1;
  }
  beacon::CallData bind_remote_unbound_view;
  bind_remote_unbound_view.params_json = R"({"uid":1002,"view_id":"missing_remote_view"})";
  if (backend->BindRemoteVideo(bind_remote_unbound_view).error != 403) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE remote bind with unknown view must fail\n";
    return 1;
  }
  // 火山 uid 生产路径是字符串；数字 uid 仅覆盖用例写成数字的兼容分支。
  beacon::CallData bind_remote_numeric_uid;
  bind_remote_numeric_uid.params_json = R"({"uid":1002,"view_id":"primary_remote_view"})";
  if (!backend->BindRemoteVideo(bind_remote_numeric_uid).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE numeric uid bind failed\n";
    return 1;
  }
  beacon::CallData snapshot;
  snapshot.params_json = R"({"view_role":"primary_remote_view"})";
  if (!backend->CaptureSnapshot(snapshot).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE snapshot of bound view failed\n";
    return 1;
  }
  beacon::CallData snapshot_missing_role;
  snapshot_missing_role.params_json = "{}";
  if (backend->CaptureSnapshot(snapshot_missing_role).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE snapshot accepted missing view_role\n";
    return 1;
  }
  // 引擎身份优先取调用上下文（store_as / resource_ref），两条分支都要能供快照归因。
  beacon::CallData snapshot_store_as = snapshot;
  snapshot_store_as.store_as = "engine-9";
  beacon::CallData snapshot_resource_ref = snapshot;
  snapshot_resource_ref.resource_ref = "engine-ref-1";
  if (!backend->CaptureSnapshot(snapshot_store_as).ok() || !backend->CaptureSnapshot(snapshot_resource_ref).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE snapshot identity fallback failed\n";
    return 1;
  }
  beacon::CallData snapshot_unbound;
  snapshot_unbound.params_json = R"({"view_role":"peer_remote_view"})";
  if (backend->CaptureSnapshot(snapshot_unbound).error != 403) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE snapshot of unbound view must fail\n";
    return 1;
  }
  beacon::CallData release;
  release.params_json = R"({"view_role":"primary_remote_view"})";
  if (!backend->ReleaseView(release).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE release view failed\n";
    return 1;
  }
  if (backend->CaptureSnapshot(snapshot).error != 403) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE snapshot after release must fail\n";
    return 1;
  }
  if (!backend->StartPreview(join).ok() || !backend->previewing()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE start capture failed\n";
    return 1;
  }
  if (!backend->StopPreview().ok() || backend->previewing()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE stop capture failed\n";
    return 1;
  }
  beacon::CallData bad_synthetic;
  bad_synthetic.params_json = R"({"width":0,"height":480,"fps":15,"pattern":"bars"})";
  if (backend->StartSyntheticVideo(bad_synthetic).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE invalid synthetic params not rejected\n";
    return 1;
  }
  beacon::CallData synthetic;
  synthetic.params_json = R"({"width":320,"height":240,"fps":10,"pattern":"bars"})";
  if (!backend->StartSyntheticVideo(synthetic).ok() || !backend->StopSyntheticVideo().ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE synthetic start/stop failed\n";
    return 1;
  }

  beacon::CallData denied;
  denied.params_json = join.params_json;
  denied.extra_json = R"({"permission_fixture":"deny_media_for_testing"})";
  if (backend->JoinChannel(denied).error != beacon::mac::kPermissionDenied) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE permission fixture not honored\n";
    return 1;
  }
  beacon::CallData invalid_token;
  invalid_token.params_json = join.params_json;
  invalid_token.extra_json = R"({"token_fixture":"invalid_for_testing"})";
  const beacon::CallResult invalid_result = backend->JoinChannel(invalid_token);
  if (invalid_result.error != beacon::kUnauthorized || invalid_result.message != "invalid token") {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE invalid token fixture not honored\n";
    return 1;
  }
  beacon::CallData suppressed;
  suppressed.params_json = join.params_json;
  suppressed.extra_json = R"({"callback_fixture":"suppress_join_success_for_testing"})";
  if (!backend->JoinChannel(suppressed).ok() || !backend->joined()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE suppressed join failed\n";
    return 1;
  }
  // extra_json 不是对象时三条 fixture 都必须安全退化为"不注入"。
  beacon::CallData malformed_extra;
  malformed_extra.params_json = join.params_json;
  malformed_extra.extra_json = "not-json";
  if (!backend->JoinChannel(malformed_extra).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE malformed extra json not tolerated\n";
    return 1;
  }
  beacon::CallData empty_join;
  empty_join.params_json = "{}";
  if (backend->JoinChannel(empty_join).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE join accepted missing room/user\n";
    return 1;
  }
  beacon::CallData denied_preview;
  denied_preview.extra_json = R"({"permission_fixture":"deny_media_for_testing"})";
  if (backend->StartPreview(denied_preview).error != beacon::mac::kPermissionDenied) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE preview accepted denied media\n";
    return 1;
  }
  beacon::CallData release_missing_role;
  release_missing_role.params_json = "{}";
  if (backend->ReleaseView(release_missing_role).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE release accepted missing view_role\n";
    return 1;
  }
  if (!backend->BindLocalVideo(bind_local).ok()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE rebind local video failed\n";
    return 1;
  }
  beacon::CallData release_local;
  release_local.params_json = R"({"view_role":"primary_local_preview"})";
  const beacon::CallResult release_local_result = backend->ReleaseView(release_local);
  if (!release_local_result.ok() ||
      release_local_result.result_json.find("\"released\":true") == std::string::npos ||
      backend->CaptureSnapshot(release_local).error != 403) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE release local view mismatch\n";
    return 1;
  }
  const beacon::CallResult stop_again = backend->StopSyntheticVideo();
  if (!stop_again.ok() || stop_again.result_json.find("\"stopped\":false") == std::string::npos) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE stop when inactive mismatch\n";
    return 1;
  }

  backend->Reset();
  if (backend->joined() || backend->initialized() || !backend->channel().empty()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE reset incomplete\n";
    return 1;
  }
  if (backend->Unload() != beacon::kOk || !sdk.app_id().empty()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE unload failed\n";
    return 1;
  }

  // SDK 加载失败时所有已声明 op 都必须 fail closed，而不是静默成功。
  FailingVolcengineSDKAdapter failing_sdk;
  auto failing_backend = beacon::mac::CreateMockRTCBackend(&failing_sdk, []() { return true; }, nullptr, &views);
  if (failing_backend->Load() != beacon::kBadRequest ||
      failing_backend->JoinChannel(join).error != beacon::kBadRequest ||
      failing_backend->BindLocalVideo(bind_local).error != beacon::kBadRequest ||
      failing_backend->BindRemoteVideo(bind_remote).error != beacon::kBadRequest ||
      failing_backend->StartPreview(join).error != beacon::kBadRequest ||
      failing_backend->StartSyntheticVideo(synthetic).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE failing sdk was not surfaced\n";
    return 1;
  }
  auto no_sdk_backend = beacon::mac::CreateMockRTCBackend(nullptr, []() { return true; }, nullptr, &views);
  if (no_sdk_backend->Load() != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE null sdk load did not fail\n";
    return 1;
  }
  // mock 变体没有真实后端，CreateRealRTCBackend 必须回退到 mock 而不是返回空。
  auto real_fallback = beacon::mac::CreateRealRTCBackend(&sdk, []() { return true; }, &events, &views);
  if (real_fallback == nullptr || real_fallback->Load() != beacon::kOk) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE real backend fallback mismatch\n";
    return 1;
  }
  return 0;
}

// provider 在 backend 缺失时必须 fail closed（覆盖 createRTCEngine/joinRoom/leaveRoom 的缺 backend 分支）。
int BridgeMacVolcengineProviderFailures() {
  beacon::InvocationController controller;
  controller.Init();
  beacon::mac::RTCInvocationProvider provider(nullptr);
  provider.RegisterInvocations(controller);

  const std::string sdk(beacon::mac::rtc_commands::kSdk);
  const std::string engine_interface(beacon::mac::rtc_commands::kEngineInterface);
  const std::string room_interface(beacon::mac::rtc_commands::kRoomInterface);

  beacon::CallData create;
  create.sdk = sdk;
  create.interface_name = engine_interface;
  create.class_name = std::string(beacon::mac::rtc_commands::kEngineClass);
  create.function_name = std::string(beacon::mac::rtc_commands::kCreateEngine);
  beacon::CallData join = create;
  join.interface_name = room_interface;
  join.class_name = std::string(beacon::mac::rtc_commands::kRoomClass);
  join.function_name = std::string(beacon::mac::rtc_commands::kJoinRoom);
  beacon::CallData leave = join;
  leave.function_name = std::string(beacon::mac::rtc_commands::kLeaveRoom);
  beacon::CallData destroy = create;
  destroy.function_name = std::string(beacon::mac::rtc_commands::kDestroyEngine);

  if (controller.CallInvocation(create).error != beacon::kBadRequest ||
      controller.CallInvocation(join).error != beacon::kBadRequest ||
      controller.CallInvocation(leave).error != beacon::kBadRequest ||
      controller.CallInvocation(destroy).error != beacon::kOk) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES missing backend path mismatch\n";
    return 1;
  }
  if (provider.initialized() || provider.joined() || provider.previewing() || !provider.channel().empty() ||
      !provider.registered() || provider.backend() != nullptr) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES provider status mismatch\n";
    return 1;
  }
  if (provider.sdk() != sdk || provider.interface_name() != engine_interface) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES provider identity mismatch\n";
    return 1;
  }
  beacon::CallData foreign = join;
  foreign.sdk = "agora_rtc";
  if (provider.Supports(join) == false || provider.Supports(foreign)) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES supports routing mismatch\n";
    return 1;
  }

  // 画面探针 provider 缺 backend：身份可读，四个 op 都必须 fail closed。
  beacon::mac::VolcengineVisualProbeProvider visual_provider(nullptr);
  visual_provider.RegisterInvocations(controller);
  beacon::CallData visual_call;
  visual_call.sdk = sdk;
  visual_call.interface_name = std::string(beacon::mac::rtc_commands::kVisualProbeInterface);
  visual_call.class_name = std::string(beacon::mac::rtc_commands::kVisualProbeClass);
  beacon::CallData visual_bind_local = visual_call;
  visual_bind_local.function_name = std::string(beacon::mac::rtc_commands::kBindLocalVideo);
  beacon::CallData visual_bind_remote = visual_call;
  visual_bind_remote.function_name = std::string(beacon::mac::rtc_commands::kBindRemoteVideo);
  beacon::CallData visual_snapshot = visual_call;
  visual_snapshot.function_name = std::string(beacon::mac::rtc_commands::kCaptureSnapshot);
  beacon::CallData visual_release = visual_call;
  visual_release.function_name = std::string(beacon::mac::rtc_commands::kReleaseView);
  if (visual_provider.sdk() != sdk ||
      visual_provider.interface_name() != std::string(beacon::mac::rtc_commands::kVisualProbeInterface)) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES visual provider identity mismatch\n";
    return 1;
  }
  if (!visual_provider.Supports(visual_call) || visual_provider.Supports(join)) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES visual provider routing mismatch\n";
    return 1;
  }
  const std::vector<beacon::CallData> missing_visual_backend = {
      visual_bind_local, visual_bind_remote, visual_snapshot, visual_release,
  };
  for (const auto& call : missing_visual_backend) {
    if (controller.CallInvocation(call).error != beacon::kBadRequest) {
      std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES missing backend accepted " << call.function_name << "\n";
      return 1;
    }
  }

  // 采集与合成源 op 缺 backend：不得静默成功。
  beacon::CallData capture = create;
  capture.function_name = std::string(beacon::mac::rtc_commands::kStartVideoCapture);
  beacon::CallData stop_capture = create;
  stop_capture.function_name = std::string(beacon::mac::rtc_commands::kStopVideoCapture);
  beacon::CallData start_synthetic = create;
  start_synthetic.function_name = std::string(beacon::mac::rtc_commands::kStartSyntheticVideo);
  beacon::CallData stop_synthetic = create;
  stop_synthetic.function_name = std::string(beacon::mac::rtc_commands::kStopSyntheticVideo);
  if (controller.CallInvocation(capture).error != beacon::kBadRequest ||
      controller.CallInvocation(stop_capture).error != beacon::kBadRequest ||
      controller.CallInvocation(start_synthetic).error != beacon::kBadRequest ||
      controller.CallInvocation(stop_synthetic).error != beacon::kBadRequest) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES missing backend accepted video op\n";
    return 1;
  }

  // SDK 加载失败时 createRTCEngine 必须暴露失败，而不是留下"已创建"的假象。
  FailingVolcengineSDKAdapter failing_sdk;
  beacon::mac::ViewRegistry failing_views;
  std::shared_ptr<beacon::mac::RTCBackend> failing_backend(
      beacon::mac::CreateMockRTCBackend(&failing_sdk, []() { return true; }, nullptr, &failing_views).release());
  provider.SetBackend(failing_backend);
  if (controller.CallInvocation(create).error != beacon::kBadRequest || provider.initialized()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES failing sdk create did not fail closed\n";
    return 1;
  }
  provider.Reset();
  return 0;
}

int BridgeMacVolcengineVocabulary() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  constexpr size_t kPlatformHandlerCount = 10;
  if (beacon::mac::rtc_commands::kCommandSpecs.size() != beacon::mac::rtc_commands::kCommandNames.size() ||
      beacon::mac::rtc_commands::kCommandNames.size() + kPlatformHandlerCount !=
          adapter.kernel().invocations().size()) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-VOCABULARY handler count mismatch\n";
    return 1;
  }
  const auto& specs = beacon::mac::rtc_commands::kCommandSpecs;
  if (specs.size() != 12 || specs[2].name != beacon::mac::rtc_commands::kJoinRoom ||
      specs[2].params.find("room_id") == std::string_view::npos ||
      specs[2].result.find("joined") == std::string_view::npos ||
      specs[3].name != beacon::mac::rtc_commands::kLeaveRoom ||
      specs[4].name != beacon::mac::rtc_commands::kStartVideoCapture ||
      specs[5].name != beacon::mac::rtc_commands::kStopVideoCapture ||
      specs[6].name != beacon::mac::rtc_commands::kStartSyntheticVideo ||
      specs[7].name != beacon::mac::rtc_commands::kStopSyntheticVideo ||
      specs[8].name != beacon::mac::rtc_commands::kBindLocalVideo ||
      specs[9].name != beacon::mac::rtc_commands::kBindRemoteVideo ||
      specs[9].params.find("uid") == std::string_view::npos ||
      specs[10].name != beacon::mac::rtc_commands::kCaptureSnapshot ||
      specs[10].params.find("view_role") == std::string_view::npos ||
      specs[11].name != beacon::mac::rtc_commands::kReleaseView) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-VOCABULARY command table mismatch\n";
    return 1;
  }
  if (adapter.rtc().sdk() != std::string(beacon::mac::rtc_commands::kSdk) ||
      adapter.rtc().interface_name() != std::string(beacon::mac::rtc_commands::kEngineInterface)) {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-VOCABULARY provider identity mismatch\n";
    return 1;
  }
  return 0;
}

int BridgeMacVolcengineJoinLeave() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const std::string sdk(beacon::mac::rtc_commands::kSdk);
  const std::string engine_interface(beacon::mac::rtc_commands::kEngineInterface);
  const std::string room_interface(beacon::mac::rtc_commands::kRoomInterface);

  const std::string created =
      Invoke(&adapter, "op-create", engine_interface, "ByteRTCEngine", "createRTCEngine", R"({"app_id":"mock"})");
  if (!ResultContains(created, "\"created\":true", "BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE")) {
    return 1;
  }
  const std::string joined = Invoke(&adapter, "op-join", room_interface, "ByteRTCRoom", "joinRoom",
                                    R"({"room_id":"room-1","user_id":"user-1","token":"t"})");
  if (!ResultContains(joined, "\"joined\":true", "BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE") || !adapter.rtc().joined()) {
    return 1;
  }
  if (adapter.rtc().channel() != "room-1") {
    std::cerr << "BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE room id not tracked\n";
    return 1;
  }
  const std::string left = Invoke(&adapter, "op-leave", room_interface, "ByteRTCRoom", "leaveRoom", "{}");
  if (!ResultContains(left, "\"left\":true", "BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE") || adapter.rtc().joined()) {
    return 1;
  }
  const std::string destroyed =
      Invoke(&adapter, "op-destroy", engine_interface, "ByteRTCEngine", "destroyRTCEngine", "{}");
  if (!ResultContains(destroyed, "\"destroyed\":true", "BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE")) {
    return 1;
  }
  (void)sdk;
  return 0;
}

// room_joined_state 在 artifact 中记 unsupported，因此 Agent 侧没有注册 handler：
// 调用它必须落到「未注册」路径，而不是被静默当作成功。
// 注意：488/unsupported 的「不计 failed」分类由 Server 侧产生（Agent 只知道 unknown invocation）；
// 该分类是否读 provider_mappings 属服务端装配层工作，见 Layer 3。
int BridgeMacVolcengineUndeclaredState() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const std::string response = Invoke(&adapter, "op-joined-state", std::string(beacon::mac::rtc_commands::kRoomInterface),
                                      "ByteRTCRoom", "onRoomStateChangedWithReason",
                                      R"({"room_id":"room-1","user_id":"user-1"})");
  if (!Contains(response, "unknown invocation", "BRIDGE-MAC-VOLCENGINE-UNDECLARED-STATE")) {
    return 1;
  }
  return 0;
}

int BridgeMacVolcengineJoinMissingParams() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  Invoke(&adapter, "op-create", std::string(beacon::mac::rtc_commands::kEngineInterface), "ByteRTCEngine",
         "createRTCEngine", "{}");
  const std::string response = Invoke(&adapter, "op-join-bad", std::string(beacon::mac::rtc_commands::kRoomInterface),
                                      "ByteRTCRoom", "joinRoom", R"({"room_id":"room-1"})");
  if (!ResponseCodeIs(response, 400, "BRIDGE-MAC-VOLCENGINE-JOIN-PARAMS")) {
    return 1;
  }
  return 0;
}

// 画面探针 provider 经 kernel 的完整表面：view_role 由 provider 翻译为 view_id，
// 未绑定视图/缺参数必须 fail closed，绑定后快照与释放走真实分支。
int BridgeMacVolcengineVisualProbe() {
  constexpr const char* kTestId = "BRIDGE-MAC-VOLCENGINE-VISUAL-PROBE";
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const std::string probe_interface(beacon::mac::rtc_commands::kVisualProbeInterface);
  const std::string probe_class(beacon::mac::rtc_commands::kVisualProbeClass);

  if (!ResponseCodeIs(Invoke(&adapter, "op-probe-local-missing-role", probe_interface, probe_class, "bindLocalVideo",
                             "{}"),
                      400, kTestId) ||
      !ResponseCodeIs(Invoke(&adapter, "op-probe-local-unbound", probe_interface, probe_class, "bindLocalVideo",
                             R"({"view_role":"missing"})"),
                      403, kTestId) ||
      !ResponseCodeIs(Invoke(&adapter, "op-probe-remote-missing-uid", probe_interface, probe_class, "bindRemoteVideo",
                             R"({"view_role":"primary_remote_view"})"),
                      400, kTestId) ||
      !ResponseCodeIs(Invoke(&adapter, "op-probe-remote-unbound", probe_interface, probe_class, "bindRemoteVideo",
                             R"({"uid":"1002","view_role":"missing"})"),
                      403, kTestId) ||
      !ResponseCodeIs(Invoke(&adapter, "op-probe-snapshot-missing-role", probe_interface, probe_class, "captureSnapshot",
                             "{}"),
                      400, kTestId) ||
      !ResponseCodeIs(Invoke(&adapter, "op-probe-snapshot-unbound", probe_interface, probe_class, "captureSnapshot",
                             R"({"view_role":"missing"})"),
                      403, kTestId) ||
      !ResponseCodeIs(Invoke(&adapter, "op-probe-release-missing-role", probe_interface, probe_class, "releaseView", "{}"),
                      400, kTestId)) {
    return 1;
  }

  int local_view = 1;
  int remote_view = 2;
  adapter.views().Attach("primary_local_preview", &local_view);
  adapter.views().Attach("primary_remote_view", &remote_view);
  const std::string bound_local = Invoke(&adapter, "op-probe-bind-local", probe_interface, probe_class, "bindLocalVideo",
                                         R"({"view_role":"primary_local_preview"})");
  if (!ResultContains(bound_local, "\"configured\":true", kTestId)) {
    return 1;
  }
  const std::string bound_remote =
      Invoke(&adapter, "op-probe-bind-remote", probe_interface, probe_class, "bindRemoteVideo",
             R"({"uid":"1002","view_role":"primary_remote_view"})");
  if (!ResultContains(bound_remote, "\"uid\":\"1002\"", kTestId)) {
    return 1;
  }
  const std::string snapshot = Invoke(&adapter, "op-probe-snapshot", probe_interface, probe_class, "captureSnapshot",
                                      R"({"view_role":"primary_remote_view"})");
  if (!ResultContains(snapshot, "\"snapshot_requested\":true", kTestId)) {
    return 1;
  }
  const std::string released = Invoke(&adapter, "op-probe-release", probe_interface, probe_class, "releaseView",
                                      R"({"view_role":"primary_remote_view"})");
  if (!ResultContains(released, "\"released\":true", kTestId) ||
      !ResponseCodeIs(Invoke(&adapter, "op-probe-snapshot-after-release", probe_interface, probe_class, "captureSnapshot",
                             R"({"view_role":"primary_remote_view"})"),
                      403, kTestId)) {
    return 1;
  }
  return 0;
}

// 采集与合成源 op 经 kernel 的真实分支：开关状态与结果字段必须与合同一致。
int BridgeMacVolcengineVideoOps() {
  constexpr const char* kTestId = "BRIDGE-MAC-VOLCENGINE-VIDEO-OPS";
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const std::string engine_interface(beacon::mac::rtc_commands::kEngineInterface);

  const std::string created =
      Invoke(&adapter, "op-video-create", engine_interface, "ByteRTCEngine", "createRTCEngine", R"({"app_id":"mock"})");
  if (!ResultContains(created, "\"created\":true", kTestId)) {
    return 1;
  }
  const std::string started =
      Invoke(&adapter, "op-video-start", engine_interface, "ByteRTCEngine", "startVideoCapture", "{}");
  if (!ResultContains(started, "\"capturing\":true", kTestId) || !adapter.rtc().previewing()) {
    return 1;
  }
  const std::string stopped =
      Invoke(&adapter, "op-video-stop", engine_interface, "ByteRTCEngine", "stopVideoCapture", "{}");
  if (!ResultContains(stopped, "\"capturing\":false", kTestId) || adapter.rtc().previewing()) {
    return 1;
  }
  const std::string synthetic_started = Invoke(&adapter, "op-video-synthetic-start", engine_interface, "ByteRTCEngine",
                                               "startSyntheticVideo",
                                               R"({"width":320,"height":240,"fps":10,"pattern":"bars"})");
  if (!ResultContains(synthetic_started, "\"started\":true", kTestId)) {
    return 1;
  }
  const std::string synthetic_stopped =
      Invoke(&adapter, "op-video-synthetic-stop", engine_interface, "ByteRTCEngine", "stopSyntheticVideo", "{}");
  if (!ResultContains(synthetic_stopped, "\"stopped\":true", kTestId)) {
    return 1;
  }
  const std::string bad_synthetic = Invoke(&adapter, "op-video-synthetic-bad", engine_interface, "ByteRTCEngine",
                                           "startSyntheticVideo",
                                           R"({"width":0,"height":240,"fps":10,"pattern":"bars"})");
  if (!ResponseCodeIs(bad_synthetic, 400, kTestId)) {
    return 1;
  }
  return 0;
}

int BridgeMacVolcengineTargetConsistency() {
  return CheckVendorTargetConsistency();
}

struct TestCase {
  const char* id;
  int (*run)();
};

const std::vector<TestCase>& Tests() {
  static const std::vector<TestCase> tests = {
      {"BUILD-MAC-VOLCENGINE-01", BuildVolcengine01},
      {"BUILD-MAC-VOLCENGINE-02", BuildVolcengine02},
      {"BRIDGE-MAC-VOLCENGINE-BACKEND-SURFACE", BridgeMacVolcengineBackendSurface},
      {"BRIDGE-MAC-VOLCENGINE-PROVIDER-FAILURES", BridgeMacVolcengineProviderFailures},
      {"BRIDGE-MAC-VOLCENGINE-VOCABULARY", BridgeMacVolcengineVocabulary},
      {"BRIDGE-MAC-VOLCENGINE-JOIN-LEAVE", BridgeMacVolcengineJoinLeave},
      {"BRIDGE-MAC-VOLCENGINE-UNDECLARED-STATE", BridgeMacVolcengineUndeclaredState},
      {"BRIDGE-MAC-VOLCENGINE-JOIN-PARAMS", BridgeMacVolcengineJoinMissingParams},
      {"BRIDGE-MAC-VOLCENGINE-VISUAL-PROBE", BridgeMacVolcengineVisualProbe},
      {"BRIDGE-MAC-VOLCENGINE-VIDEO-OPS", BridgeMacVolcengineVideoOps},
      {"BRIDGE-MAC-VOLCENGINE-TARGET-CONSISTENCY", BridgeMacVolcengineTargetConsistency},
  };
  return tests;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::cerr << "usage: mac_mock_volcengine_test <TEST-ID>\n";
    return 2;
  }
  const std::string requested(argv[1]);
  for (const auto& test : Tests()) {
    if (requested == test.id) {
      return test.run();
    }
  }
  std::cerr << "unknown test id: " << requested << "\n";
  return 2;
}
