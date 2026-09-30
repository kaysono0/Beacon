#include <string>

#include "beacon/target_contract.h"
#include "rtc/rtc_command_vocabulary.h"
#include "rtc/rtc_invocation_provider.h"

namespace beacon::mac {
namespace {
std::string Key(std::string_view interface_name, std::string_view class_name,
                std::string_view function_name) {
  beacon::TargetData target;
  target.sdk = std::string(rtc_commands::kSdk);
  target.interface_name = std::string(interface_name);
  target.class_name = std::string(class_name);
  target.function_name = std::string(function_name);
  return beacon::TargetKey(target);
}
} // namespace

std::string RTCInvocationProvider::sdk() const {
  return std::string(rtc_commands::kSdk);
}
std::string RTCInvocationProvider::interface_name() const {
  return std::string(rtc_commands::kEngineInterface);
}
bool RTCInvocationProvider::Supports(const beacon::CallData &call) const {
  return call.sdk == rtc_commands::kSdk &&
         (call.interface_name == rtc_commands::kEngineInterface ||
          call.interface_name == rtc_commands::kRoomInterface ||
          call.interface_name == rtc_commands::kPreviewInterface ||
          call.interface_name == rtc_commands::kPublisherInterface ||
          call.interface_name == rtc_commands::kPlayerInterface);
}
void RTCInvocationProvider::Register(beacon::InvocationController &controller) {
  registered_ = true;
  controller.RegisterInvocation(
      Key(rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
          rtc_commands::kCreateEngine),
      [this](const beacon::CallData &call) {
        if (!backend_)
          return beacon::CallResult{beacon::kBadRequest, "missing zego backend",
                                    "{}"};
        backend_->AttributeCallbacksTo(call);
        return backend_->Load() == beacon::kOk
                   ? beacon::CallResult{beacon::kOk, "ZEGO engine created",
                                        "{\"created\":true}"}
                   : beacon::CallResult{beacon::kBadRequest,
                                        "ZEGO engine creation failed", "{}"};
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kEngineInterface, rtc_commands::kEngineClass,
          rtc_commands::kDestroyEngine),
      [this](const beacon::CallData &) {
        if (backend_)
          backend_->Unload();
        return beacon::CallResult{beacon::kOk, "ZEGO engine destroyed",
                                  "{\"destroyed\":true}"};
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kRoomInterface, rtc_commands::kRoomClass,
          rtc_commands::kJoinRoom),
      [this](const beacon::CallData &call) {
        if (!backend_)
          return beacon::CallResult{beacon::kBadRequest, "missing zego backend",
                                    "{}"};
        backend_->AttributeCallbacksTo(call);
        return backend_->JoinChannel(call);
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kRoomInterface, rtc_commands::kRoomClass,
          rtc_commands::kLeaveRoom),
      [this](const beacon::CallData &call) {
        if (!backend_)
          return beacon::CallResult{beacon::kBadRequest, "missing zego backend",
                                    "{}"};
        backend_->AttributeCallbacksTo(call);
        return backend_->LeaveChannel(call);
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPreviewInterface, rtc_commands::kEngineClass,
          rtc_commands::kStartPreview),
      [this](const beacon::CallData &call) {
        return backend_ ? backend_->StartPreview(call)
                        : beacon::CallResult{beacon::kBadRequest,
                                             "missing zego backend", "{}"};
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPreviewInterface, rtc_commands::kEngineClass,
          rtc_commands::kStopPreview),
      [this](const beacon::CallData &) {
        return backend_ ? backend_->StopPreview()
                        : beacon::CallResult{beacon::kBadRequest,
                                             "missing zego backend", "{}"};
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPublisherInterface, rtc_commands::kEngineClass,
          rtc_commands::kStartSyntheticVideo),
      [this](const beacon::CallData &call) {
        return backend_ ? backend_->StartSyntheticVideo(call)
                        : beacon::CallResult{beacon::kBadRequest,
                                             "missing zego backend", "{}"};
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPublisherInterface, rtc_commands::kEngineClass,
          rtc_commands::kStopSyntheticVideo),
      [this](const beacon::CallData &) {
        return backend_ ? backend_->StopSyntheticVideo()
                        : beacon::CallResult{beacon::kBadRequest,
                                             "missing zego backend", "{}"};
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPublisherInterface, rtc_commands::kEngineClass,
          rtc_commands::kStartPublishingStream),
      [this](const beacon::CallData &call) {
        if (!backend_)
          return beacon::CallResult{beacon::kBadRequest, "missing zego backend",
                                    "{}"};
        backend_->AttributeCallbacksTo(call);
        return backend_->StartPublishingStream(call);
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPublisherInterface, rtc_commands::kEngineClass,
          rtc_commands::kStopPublishingStream),
      [this](const beacon::CallData &) {
        return backend_ ? backend_->StopPublishingStream()
                        : beacon::CallResult{beacon::kBadRequest,
                                             "missing zego backend", "{}"};
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPlayerInterface, rtc_commands::kEngineClass,
          rtc_commands::kStartPlayingStream),
      [this](const beacon::CallData &call) {
        if (!backend_)
          return beacon::CallResult{beacon::kBadRequest, "missing zego backend",
                                    "{}"};
        backend_->AttributeCallbacksTo(call);
        return backend_->StartPlayingStream(call);
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kPlayerInterface, rtc_commands::kEngineClass,
          rtc_commands::kStopPlayingStream),
      [this](const beacon::CallData &call) {
        return backend_ ? backend_->StopPlayingStream(call)
                        : beacon::CallResult{beacon::kBadRequest,
                                             "missing zego backend", "{}"};
      });
  RegisterSystemInvocations(controller);
}
} // namespace beacon::mac
