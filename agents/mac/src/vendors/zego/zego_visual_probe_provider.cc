#include "vendors/zego/zego_visual_probe_provider.h"

#include <utility>

#include "beacon/target_contract.h"
#include "rtc/rtc_command_vocabulary.h"

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
ZegoVisualProbeProvider::ZegoVisualProbeProvider(
    std::shared_ptr<RTCBackend> backend)
    : backend_(std::move(backend)) {}

std::string ZegoVisualProbeProvider::sdk() const {
  return std::string(rtc_commands::kSdk);
}

std::string ZegoVisualProbeProvider::interface_name() const {
  return std::string(rtc_commands::kVisualProbeInterface);
}

bool ZegoVisualProbeProvider::Supports(const beacon::CallData &call) const {
  return call.sdk == rtc_commands::kSdk &&
         call.interface_name == rtc_commands::kVisualProbeInterface;
}

void ZegoVisualProbeProvider::RegisterInvocations(
    beacon::InvocationController &controller) {
  controller.RegisterInvocation(
      Key(rtc_commands::kVisualProbeInterface, rtc_commands::kVisualProbeClass,
          rtc_commands::kCaptureSnapshot),
      [this](const beacon::CallData &call) {
        if (!backend_)
          return beacon::CallResult{beacon::kBadRequest, "missing zego backend",
                                    "{}"};
        backend_->AttributeCallbacksTo(call);
        return backend_->CaptureSnapshot(call);
      });
  controller.RegisterInvocation(
      Key(rtc_commands::kVisualProbeInterface, rtc_commands::kVisualProbeClass,
          rtc_commands::kReleaseView),
      [this](const beacon::CallData &call) {
        return backend_ ? backend_->ReleaseView(call)
                        : beacon::CallResult{beacon::kBadRequest,
                                             "missing zego backend", "{}"};
      });
}

} // namespace beacon::mac
