// Agora 变体的 provider 身份与 invocation 注册；只在 Agora 变体编译。
#include <string>
#include <utility>

#include <json/json.h>

#include "beacon/protocol_json.h"
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
  return std::string(rtc_commands::kInterface);
}

bool RTCInvocationProvider::Supports(const beacon::CallData& call) const {
  return call.sdk == rtc_commands::kSdk &&
         (call.interface_name == rtc_commands::kInterface || call.interface_name == rtc_commands::kPreviewInterface ||
          call.interface_name == rtc_commands::kMediaPlayerInterface);
}

void RTCInvocationProvider::Register(beacon::InvocationController& controller) {
  registered_ = true;
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kLifecycleClass, rtc_commands::kInit),
      [this](const beacon::CallData&) {
        if (backend_ == nullptr || backend_->Load() != beacon::kOk) {
          return beacon::CallResult{beacon::kBadRequest, "sdk not loaded", "{}"};
        }
        return beacon::CallResult{beacon::kOk, "initialized", "{\"initialized\":true}"};
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kLifecycleClass, rtc_commands::kDestroy),
      [this](const beacon::CallData&) {
        if (backend_ != nullptr) {
          backend_->Unload();
        }
        return beacon::CallResult{beacon::kOk, "destroyed", "{\"destroyed\":true}"};
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kJoinChannel),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->JoinChannel(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kLeaveChannel),
      [this](const beacon::CallData&) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->LeaveChannel();
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kRenewToken),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->RenewToken(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(
          rtc_commands::kSdk, rtc_commands::kPreviewInterface, rtc_commands::kEngineClass, rtc_commands::kStartPreview),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StartPreview(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(
          rtc_commands::kSdk, rtc_commands::kPreviewInterface, rtc_commands::kEngineClass, rtc_commands::kStopPreview),
      [this](const beacon::CallData&) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StopPreview();
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kEnableLocalAudio),
      [this](const beacon::CallData& call) {
        Json::Value params;
        beacon::ParseJson(call.params_json, &params);
        const bool enabled = params.get("enabled", true).asBool();
        audio_enabled_ = enabled;
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->EnableLocalAudio(enabled);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kEnableLocalVideo),
      [this](const beacon::CallData& call) {
        Json::Value params;
        beacon::ParseJson(call.params_json, &params);
        const bool enabled = params.get("enabled", true).asBool();
        video_enabled_ = enabled;
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->EnableLocalVideo(enabled);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kGetConnectionState),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->GetConnectionState(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kGetLastMileStats),
      [](const beacon::CallData&) {
        return beacon::CallResult{beacon::kOk, "ok", "{\"available\":false}"};
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass, rtc_commands::kIsJoined),
      [this](const beacon::CallData&) {
        return beacon::CallResult{beacon::kOk, "ok", joined() ? "true" : "false"};
      });
  controller.RegisterInvocation(
      CanonicalKey(
          rtc_commands::kSdk, rtc_commands::kPreviewInterface, rtc_commands::kEngineClass, rtc_commands::kIsPreviewing),
      [this](const beacon::CallData&) {
        return beacon::CallResult{beacon::kOk, "ok", previewing() ? "true" : "false"};
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass,
                   rtc_commands::kStartSyntheticVideo),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StartSyntheticVideo(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass,
                   rtc_commands::kStopSyntheticVideo),
      [this](const beacon::CallData&) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StopSyntheticVideo();
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass,
                   rtc_commands::kSetDualStreamMode),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->SetDualStreamMode(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kInterface, rtc_commands::kEngineClass,
                   rtc_commands::kSetRemoteVideoStream),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->SetRemoteVideoStream(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kMediaPlayerInterface, rtc_commands::kMediaPlayerClass,
                   rtc_commands::kOpenMediaPlayer),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->OpenMediaPlayer(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kMediaPlayerInterface, rtc_commands::kMediaPlayerClass,
                   rtc_commands::kPlayMediaPlayer),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->PlayMediaPlayer(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kMediaPlayerInterface, rtc_commands::kMediaPlayerClass,
                   rtc_commands::kPauseMediaPlayer),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->PauseMediaPlayer(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kMediaPlayerInterface, rtc_commands::kMediaPlayerClass,
                   rtc_commands::kResumeMediaPlayer),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->ResumeMediaPlayer(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kMediaPlayerInterface, rtc_commands::kMediaPlayerClass,
                   rtc_commands::kStopMediaPlayer),
      [this](const beacon::CallData&) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->StopMediaPlayer();
      });
  RegisterSystemInvocations(controller);
}

}  // namespace beacon::mac
