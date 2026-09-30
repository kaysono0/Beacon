// 火山真实后端的桥层测试（需要本机放置 VolcEngineRTC macOS SDK）。
//
// 这批用例的价值有两层：①证明多 framework + dylib 在运行期能被 dyld 解析（解析失败会在
// 进程启动阶段直接 abort）；②证明真实后端在没有凭证时 fail closed，而不是崩溃或静默成功。
// 真实 join/leave 需要有效凭证与网络，由 `test-mac-volcengine-real` runner 覆盖。
//
// 注意：`PlatformAdapter::Init()` 只加载 loader；凭证校验与 backend 初始化发生在
// `createRTCEngine`（lifecycle op），因此这些用例必须通过内核真正驱动 target。
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "platform/platform_adapter.h"
#include "rtc/rtc_command_vocabulary.h"

namespace {

const char* kDummyAppId = "0123456789abcdef01234567";

void SetCredentials(const char* app_id) {
  if (app_id == nullptr) {
    unsetenv("VOLCENGINE_RTC_ID");
    return;
  }
  setenv("VOLCENGINE_RTC_ID", app_id, 1);
}

std::string TargetKeyJson(const std::string& interface_name, const std::string& class_name,
                          const std::string& function_name) {
  Json::Value target(Json::objectValue);
  target["sdk"] = std::string(beacon::mac::rtc_commands::kSdk);
  target["interface"] = interface_name;
  target["class_name"] = class_name;
  target["function"] = function_name;
  return beacon::WriteJson(target);
}

// 通过内核驱动一次真实后端调用，返回 invokeResponse 的解析结果。
Json::Value Invoke(beacon::mac::PlatformAdapter* adapter, const std::string& op_id, const std::string& interface_name,
                   const std::string& class_name, const std::string& function_name, const std::string& params_json) {
  Json::Value packet(Json::objectValue);
  packet["common"]["action"] = "invokeRequest";
  packet["common"]["op_id"] = op_id;
  packet["common"]["timestamp_ms"] = 1;
  packet["data"]["node_id"] = "mac-real-volcengine-001";
  packet["data"]["sync"] = true;
  Json::Value item(Json::objectValue);
  item["target"]["sdk"] = std::string(beacon::mac::rtc_commands::kSdk);
  item["target"]["interface"] = interface_name;
  item["target"]["class_name"] = class_name;
  item["target"]["function"] = function_name;
  item["params"] = params_json;
  packet["data"]["list"].append(item);

  const std::string response = adapter->kernel().HandleRequest(beacon::WriteJson(packet));
  Json::Value root;
  if (!beacon::ParseJson(response, &root)) {
    return Json::Value(Json::objectValue);
  }
  return root["data"]["list"][0];
}

int ResultCode(const Json::Value& item) { return item.get("code", -1).asInt(); }

// 无凭证时 createRTCEngine 必须 fail closed：不崩溃、不静默成功。
int BuildVolcengineReal01() {
  SetCredentials(nullptr);
  beacon::mac::PlatformAdapter adapter;
  if (adapter.Bind() != beacon::kOk) {
    std::cerr << "BUILD-MAC-VOLCENGINE-REAL-01 bind failed\n";
    return 1;
  }
  const Json::Value result = Invoke(&adapter, "op-create", std::string(beacon::mac::rtc_commands::kEngineInterface),
                                    "ByteRTCEngine", "createRTCEngine", "{}");
  if (ResultCode(result) != beacon::kBadRequest) {
    std::cerr << "BUILD-MAC-VOLCENGINE-REAL-01 expected kBadRequest without credentials, got " << ResultCode(result)
              << "\n";
    return 1;
  }
  if (adapter.rtc().initialized()) {
    std::cerr << "BUILD-MAC-VOLCENGINE-REAL-01 backend must not be initialized without credentials\n";
    return 1;
  }
  return 0;
}

// 有凭证形状（24 字符 app id）时，引擎创建路径必须可执行且不崩溃；未声明能力 fail closed。
int ItVolcengineReal01() {
  SetCredentials(kDummyAppId);
  beacon::mac::PlatformAdapter adapter;
  if (adapter.Bind() != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-01 bind failed\n";
    return 1;
  }
  const Json::Value created = Invoke(&adapter, "op-create", std::string(beacon::mac::rtc_commands::kEngineInterface),
                                     "ByteRTCEngine", "createRTCEngine", "{}");
  if (ResultCode(created) != beacon::kOk || !adapter.rtc().initialized()) {
    std::cerr << "IT-VOLCENGINE-REAL-01 engine creation failed with a well-formed app id: " << ResultCode(created)
              << "\n";
    return 1;
  }
  if (!adapter.rtc().channel().empty()) {
    std::cerr << "IT-VOLCENGINE-REAL-01 channel must be empty before any join\n";
    return 1;
  }
  // 未进房时直接 leave：真实链路上 runtime isolation 的收尾会这么调，必须安全返回 ok。
  if (!adapter.rtc().backend()->LeaveChannel().ok() || adapter.rtc().joined()) {
    std::cerr << "IT-VOLCENGINE-REAL-01 leave without a room must succeed and stay unjoined\n";
    return 1;
  }
  // joinRoom 缺少 user_id 必须在本地 fail closed（不发网络请求）。
  const Json::Value bad_join =
      Invoke(&adapter, "op-join-bad", std::string(beacon::mac::rtc_commands::kRoomInterface), "ByteRTCRoom", "joinRoom",
             R"({"room_id":"only-room"})");
  if (ResultCode(bad_join) != beacon::kBadRequest) {
    std::cerr << "IT-VOLCENGINE-REAL-01 join without user_id was not rejected locally\n";
    return 1;
  }
  // room_joined_state 未声明 handler：必须走 unsupported 路径而不是静默成功。
  const Json::Value joined_state =
      Invoke(&adapter, "op-joined", std::string(beacon::mac::rtc_commands::kRoomInterface), "ByteRTCRoom",
             "onRoomStateChangedWithReason", "{}");
  if (ResultCode(joined_state) == beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-01 undeclared target must not succeed\n";
    return 1;
  }
  const Json::Value destroyed = Invoke(&adapter, "op-destroy", std::string(beacon::mac::rtc_commands::kEngineInterface),
                                       "ByteRTCEngine", "destroyRTCEngine", "{}");
  if (ResultCode(destroyed) != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-01 destroyRTCEngine failed: " << ResultCode(destroyed) << "\n";
    return 1;
  }
  // 卸载路径必须可重复调用且不崩溃（Reset 不依赖本地 joined 标志）。
  adapter.Reset();
  adapter.Destroy();
  if (adapter.rtc().initialized() || adapter.rtc().joined()) {
    std::cerr << "IT-VOLCENGINE-REAL-01 reset/destroy left backend state behind\n";
    return 1;
  }
  return 0;
}

// 未声明能力（连接态查询 / 音频开关 / token 续期）在真实后端上必须显式返回不支持；
// B-020 起画面能力已声明，这些调用必须走真实校验分支而不是继续以「未声明」搪塞。
int ItVolcengineReal02() {
  SetCredentials(kDummyAppId);
  beacon::mac::PlatformAdapter adapter;
  if (adapter.Bind() != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-02 bind failed\n";
    return 1;
  }
  const Json::Value created = Invoke(&adapter, "op-create", std::string(beacon::mac::rtc_commands::kEngineInterface),
                                     "ByteRTCEngine", "createRTCEngine", "{}");
  if (ResultCode(created) != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-02 createRTCEngine failed\n";
    return 1;
  }
  // 未注册 target：内核返回 unknown invocation。
  const Json::Value preview =
      Invoke(&adapter, "op-preview", std::string(beacon::mac::rtc_commands::kRoomInterface), "ByteRTCRoom", "startPreview",
             "{}");
  if (ResultCode(preview) == beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-02 undeclared preview target must not succeed\n";
    return 1;
  }
  // 仍未声明的能力：4 个方法都必须显式返回「不支持」。
  auto backend = adapter.rtc().backend();
  beacon::CallData call;
  call.params_json = "{}";
  const std::vector<beacon::CallResult> unsupported = {
      backend->GetConnectionState(call),
      backend->EnableLocalAudio(true),
      backend->EnableLocalVideo(true),
      backend->RenewToken(call),
  };
  for (const auto& result : unsupported) {
    if (result.error != beacon::kBadRequest || result.message != "capability not declared for this vendor") {
      std::cerr << "IT-VOLCENGINE-REAL-02 undeclared capability did not fail closed\n";
      return 1;
    }
  }
  // 已声明画面能力的参数校验分支：不碰真实 SDK，只证明能力面确实收进来了。
  struct DeclaredCheck {
    beacon::CallResult result;
    int error;
    const char* message;
  };
  const std::vector<DeclaredCheck> declared = {
      {backend->BindLocalVideo(call), beacon::kBadRequest, "missing view_id"},
      {backend->BindRemoteVideo(call), beacon::kBadRequest, "missing uid"},
      {backend->CaptureSnapshot(call), beacon::kBadRequest, "missing view_role"},
      {backend->ReleaseView(call), beacon::kBadRequest, "missing view_role"},
  };
  for (const auto& check : declared) {
    if (check.result.error != check.error || check.result.message != check.message) {
      std::cerr << "IT-VOLCENGINE-REAL-02 declared capability left the validation path: " << check.result.message << "\n";
      return 1;
    }
  }
  // 未绑定视图的快照请求必须在本地 fail closed（未进房时也不得触碰 SDK）。
  beacon::CallData unbound_snapshot;
  unbound_snapshot.params_json = R"({"view_role":"primary_local_preview"})";
  if (backend->CaptureSnapshot(unbound_snapshot).error != 403) {
    std::cerr << "IT-VOLCENGINE-REAL-02 unbound snapshot request did not fail closed\n";
    return 1;
  }
  // 合成源参数校验同样在本地完成（width=0 不合法）。
  beacon::CallData bad_synthetic;
  bad_synthetic.params_json = R"({"width":0,"height":480,"fps":15,"pattern":"bars"})";
  if (backend->StartSyntheticVideo(bad_synthetic).message != "invalid synthetic video params") {
    std::cerr << "IT-VOLCENGINE-REAL-02 synthetic video accepted invalid params\n";
    return 1;
  }
  // 采集开关与预览相关方法在真实后端会触碰摄像头/SDK：本用例不调用，
  // 其真实行为由 Terminal 链上的 `make test-mac-console-volcengine` 覆盖。
  if (backend->previewing()) {
    std::cerr << "IT-VOLCENGINE-REAL-02 previewing must stay false\n";
    return 1;
  }
  // 权限夹具与无效 token 夹具必须在本地 fail closed（不发网络请求）。
  beacon::CallData denied;
  denied.params_json = R"({"room_id":"r","user_id":"u","token":"t"})";
  denied.extra_json = R"({"permission_fixture":"deny_media_for_testing"})";
  if (backend->JoinChannel(denied).error != beacon::mac::kPermissionDenied) {
    std::cerr << "IT-VOLCENGINE-REAL-02 permission fixture not honored\n";
    return 1;
  }
  beacon::CallData invalid_token = denied;
  invalid_token.extra_json = R"({"token_fixture":"invalid_for_testing"})";
  const beacon::CallResult invalid_result = backend->JoinChannel(invalid_token);
  if (invalid_result.error != beacon::kUnauthorized || invalid_result.message != "invalid token") {
    std::cerr << "IT-VOLCENGINE-REAL-02 invalid token fixture not honored\n";
    return 1;
  }
  adapter.Destroy();
  return 0;
}

// 真实 join/leave：需要服务端签发的 room token（`VOLCENGINE_RTC_TOKEN`）与真实网络。
// 由覆盖率 gate 注入 token；无 token 时本用例跳过（返回 0 并在 stderr 说明），
// 使真实凭证缺失不会把门禁变成假绿。
int ItVolcengineReal03() {
  const char* token = std::getenv("VOLCENGINE_RTC_TOKEN");
  if (token == nullptr || token[0] == '\0') {
    std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE skipped: VOLCENGINE_RTC_TOKEN is not set\n";
    return 0;
  }
  const char* room_id = std::getenv("VOLCENGINE_RTC_ROOM_ID");
  const char* user_id = std::getenv("VOLCENGINE_RTC_USER_ID");
  const std::string room = room_id != nullptr && room_id[0] != '\0' ? room_id : "beacon-volcengine-l1-room";
  const std::string user = user_id != nullptr && user_id[0] != '\0' ? user_id : "beacon-user-001";

  // 必须用真实 app id：token 的 app id 要与引擎一致，且 SDK 的内部子系统（如 rangeAudio）
  // 只有在 app id 有效时才会被真正初始化——用占位 id 建引擎后走 leave 会踩到未初始化的对象。
  SetCredentials(std::getenv("VOLCENGINE_RTC_ID"));
  beacon::mac::PlatformAdapter adapter;
  if (adapter.Bind() != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE bind failed\n";
    return 1;
  }
  const Json::Value created = Invoke(&adapter, "op-create", std::string(beacon::mac::rtc_commands::kEngineInterface),
                                     "ByteRTCEngine", "createRTCEngine", "{}");
  if (ResultCode(created) != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE createRTCEngine failed\n";
    return 1;
  }
  const std::string join_params = std::string("{\"room_id\":\"") + room + "\",\"user_id\":\"" + user +
                                  "\",\"token\":\"" + token + "\"}";
  const Json::Value joined = Invoke(&adapter, "op-join", std::string(beacon::mac::rtc_commands::kRoomInterface),
                                    "ByteRTCRoom", "joinRoom", join_params);
  if (ResultCode(joined) != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE real join failed with code " << ResultCode(joined) << " (room=" << room
              << " user=" << user << ")\n";
    return 1;
  }
  if (!adapter.rtc().joined() || adapter.rtc().channel() != room) {
    std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE backend did not track the joined room\n";
    return 1;
  }
  // 必须等到 SDK 报告加入成功（onRoomStateChanged state=0）再离开：joinRoom 返回只代表
  // 请求已受理，SDK 仍在自己的消息队列上完成加入；此时立刻 leave/destroy 会让 SDK 在
  // 派发回调里访问尚未就绪的对象（真实 gate 复现过段错误，手动跑则可能因时序侥幸通过）。
  {
    std::atomic<int> observed_state{-1};
    adapter.events().SetObserver([&observed_state](const std::string& function, const std::string& payload_json,
                                                  const beacon::CallbackExecutionResult&,
                                                  const beacon::mac::RTCEventBridge::ActiveEngineIdentity&) {
      if (function != "onRoomStateChanged") {
        return;
      }
      Json::Value payload;
      if (beacon::ParseJson(payload_json, &payload) && payload.isObject()) {
        observed_state.store(payload.get("state", -1).asInt());
      }
    });
    for (int waited_ms = 0; waited_ms < 8000 && observed_state.load() != 0; waited_ms += 50) {
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    adapter.events().SetObserver(nullptr);
    if (observed_state.load() != 0) {
      std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE did not observe a successful join callback (state="
                << observed_state.load() << ")\n";
      return 1;
    }
  }
  const Json::Value left = Invoke(&adapter, "op-leave", std::string(beacon::mac::rtc_commands::kRoomInterface),
                                  "ByteRTCRoom", "leaveRoom", "{}");
  if (ResultCode(left) != beacon::kOk || adapter.rtc().joined()) {
    std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE real leave failed with code " << ResultCode(left) << "\n";
    return 1;
  }
  // 重复 leave 不依赖本地状态：房间对象已释放，仍必须成功返回。
  const Json::Value left_again = Invoke(&adapter, "op-leave-again", std::string(beacon::mac::rtc_commands::kRoomInterface),
                                        "ByteRTCRoom", "leaveRoom", "{}");
  if (ResultCode(left_again) != beacon::kOk) {
    std::cerr << "IT-VOLCENGINE-REAL-JOIN-LEAVE repeated leave failed\n";
    return 1;
  }
  adapter.Destroy();
  return 0;
}

struct TestCase {
  const char* id;
  int (*run)();
};

int ItVolcengineMultiRemoteBindings() {
  setenv("BEACON_SHOW_VIDEO_WINDOWS", "all", 1);
  SetCredentials(kDummyAppId);
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  if (ResultCode(Invoke(&adapter, "op-create", "byte_rtc_engine", "ByteRTCEngine", "createRTCEngine", "{}")) != 0) return 1;
  NSWindow* window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 640, 240)
      styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
  NSView* first = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 320, 240)];
  NSView* second = [[NSView alloc] initWithFrame:NSMakeRect(320, 0, 320, 240)];
  [window.contentView addSubview:first];
  [window.contentView addSubview:second];
  adapter.views().Attach("remote_a", (__bridge void*)first);
  adapter.views().Attach("remote_alias", (__bridge void*)first);
  adapter.views().Attach("remote_b", (__bridge void*)second);
  auto visual = [&](const char* function, const char* role, const char* uid = "") {
    Json::Value params(Json::objectValue);
    params["view_role"] = role;
    if (uid[0] != '\0') params["uid"] = uid;
    const auto result = Invoke(&adapter, "op-visual", "visual_probe", "ByteRTCVisualProbe", function, beacon::WriteJson(params));
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    return result;
  };
  if (ResultCode(visual("bindRemoteVideo", "remote_a", "alice")) != 0 ||
      ResultCode(visual("bindRemoteVideo", "remote_b", "bob")) != 0 ||
      ResultCode(visual("bindRemoteVideo", "remote_alias", "charlie")) != beacon::kBadRequest ||
      ResultCode(visual("bindRemoteVideo", "remote_b", "alice")) != beacon::kBadRequest) return 1;
  auto released = [&](const char* role, bool expected) {
    const auto item = visual("releaseView", role);
    Json::Value result;
    return ResultCode(item) == 0 && beacon::ParseJson(item.get("result", "{}").asString(), &result) &&
        result.get("released", !expected).asBool() == expected;
  };
  if (!released("remote_a", true) || !window.visible || !released("remote_a", false) ||
      !released("remote_b", true) || window.visible) return 1;
  if (ResultCode(visual("bindRemoteVideo", "remote_a", "alice")) != 0 ||
      ResultCode(visual("bindRemoteVideo", "remote_b", "bob")) != 0) return 1;
  adapter.rtc().Reset();
  [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
  if (window.visible || !released("remote_a", false) || !released("remote_b", false)) return 1;
  if (ResultCode(visual("bindRemoteVideo", "remote_a", "alice")) != 0 ||
      ResultCode(visual("bindRemoteVideo", "remote_b", "bob")) != 0 ||
      adapter.rtc().backend()->LeaveChannel().error != 0) return 1;
  [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
  if (window.visible || !released("remote_a", false) || !released("remote_b", false)) return 1;
  return 0;
}

const std::vector<TestCase>& Tests() {
  static const std::vector<TestCase> tests = {
      {"IT-VOLCENGINE-REAL-MULTI-REMOTE-BINDINGS", ItVolcengineMultiRemoteBindings},
      {"BUILD-MAC-VOLCENGINE-REAL-01", BuildVolcengineReal01},
      {"IT-VOLCENGINE-REAL-01", ItVolcengineReal01},
      {"IT-VOLCENGINE-REAL-02", ItVolcengineReal02},
      {"IT-VOLCENGINE-REAL-JOIN-LEAVE", ItVolcengineReal03},
  };
  return tests;
}


}  // namespace

int main(int argc, char** argv) {
  @autoreleasepool {
    if (argc < 2) {
      std::cerr << "usage: mac_real_volcengine_adapter_test <TEST-ID>\n";
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
}
