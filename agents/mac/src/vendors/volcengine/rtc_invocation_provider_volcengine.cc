// 火山变体的 provider 身份与 invocation 注册；只在火山变体编译。
// 注册火山声明里 mac/supported 的引擎级与房间级 op（生命周期、房间、画面能力面）；
// room_joined_state 在 artifact 中记为 unsupported，因此这里刻意不注册 handler。
#include <string>
#include <utility>

#include "beacon/target_contract.h"
#include "rtc/rtc_command_vocabulary.h"
#include "rtc/rtc_invocation_provider.h"

namespace beacon::mac {

namespace {

std::string CanonicalKey(std::string_view sdk, std::string_view interface_name, std::string_view class_name,
                         std::string_view function_name) {
  beacon::TargetData target;
  target.sdk = std::string(sdk);
  target.interface_name = std::string(interface_name);
  target.class_name = std::string(class_name);
  target.function_name = std::string(function_name);
  return beacon::TargetKey(target);
}

}  // namespace

std::string RTCInvocationProvider::sdk() const {
  return std::string(rtc_commands::kSdk);
}

std::string RTCInvocationProvider::interface_name() const {
  return std::string(rtc_commands::kEngineInterface);
}

bool RTCInvocationProvider::Supports(const beacon::CallData& call) const {
  return call.sdk == rtc_commands::kSdk &&
         (call.interface_name == rtc_commands::kEngineInterface || call.interface_name == rtc_commands::kRoomInterface);
}

void RTCInvocationProvider::Register(beacon::InvocationController& controller) {
  registered_ = true;
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
                   rtc_commands::kCreateEngine),
      [this](const beacon::CallData& call) {
        if (backend_ == nullptr) {
          return beacon::CallResult{beacon::kBadRequest, "sdk not loaded", "{}"};
        }
        // 创建引擎时 SDK 就会回调连接态，先归因到本次调用，否则该事件没有 trace。
        backend_->AttributeCallbacksTo(call);
        if (backend_->Load() != beacon::kOk) {
          return beacon::CallResult{beacon::kBadRequest, "sdk not loaded", "{}"};
        }
        return beacon::CallResult{beacon::kOk, "engine created", "{\"created\":true}"};
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
                   rtc_commands::kDestroyEngine),
      [this](const beacon::CallData&) {
        if (backend_ != nullptr) {
          backend_->Unload();
        }
        return beacon::CallResult{beacon::kOk, "engine destroyed", "{\"destroyed\":true}"};
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kRoomInterface, rtc_commands::kRoomClass, rtc_commands::kJoinRoom),
      [this](const beacon::CallData& call) {
        if (backend_ == nullptr) {
          return beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"};
        }
        // join 期间会产生房间态回调，先归因到本次调用，否则事件没有 trace。
        backend_->AttributeCallbacksTo(call);
        return backend_->JoinChannel(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kRoomInterface, rtc_commands::kRoomClass, rtc_commands::kLeaveRoom),
      [this](const beacon::CallData& call) {
        if (backend_ == nullptr) {
          return beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"};
        }
        // leave 期间会产生离开回调，先归因到本次调用，否则事件会被算到 join 步骤。
        backend_->AttributeCallbacksTo(call);
        return backend_->LeaveChannel(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
                   rtc_commands::kStartVideoCapture),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StartPreview(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
                   rtc_commands::kStopVideoCapture),
      [this](const beacon::CallData&) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StopPreview();
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
                   rtc_commands::kStartSyntheticVideo),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StartSyntheticVideo(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
                   rtc_commands::kStopSyntheticVideo),
      [this](const beacon::CallData&) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StopSyntheticVideo();
      });
  RegisterSystemInvocations(controller);
}

}  // namespace beacon::mac
