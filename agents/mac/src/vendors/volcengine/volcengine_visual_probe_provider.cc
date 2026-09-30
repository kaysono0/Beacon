#include "vendors/volcengine/volcengine_visual_probe_provider.h"

#include <utility>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"
#include "rtc/rtc_command_vocabulary.h"

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

std::string VisualParamsJson(const Json::Value& params) {
  Json::Value forwarded(Json::objectValue);
  forwarded["view_id"] = params.get("view_role", "").asString();
  if (params.isMember("uid")) {
    forwarded["uid"] = params["uid"];
  }
  return beacon::WriteJson(forwarded);
}

beacon::CallData ForwardVisualCall(const beacon::CallData& call, const Json::Value& params) {
  beacon::CallData forwarded = call;
  forwarded.interface_name = std::string(rtc_commands::kEngineInterface);
  forwarded.class_name = std::string(rtc_commands::kEngineClass);
  forwarded.params_json = VisualParamsJson(params);
  return forwarded;
}

}  // namespace

VolcengineVisualProbeProvider::VolcengineVisualProbeProvider(std::shared_ptr<RTCBackend> backend)
    : backend_(std::move(backend)) {}

std::string VolcengineVisualProbeProvider::sdk() const {
  return std::string(rtc_commands::kSdk);
}

std::string VolcengineVisualProbeProvider::interface_name() const {
  return std::string(rtc_commands::kVisualProbeInterface);
}

bool VolcengineVisualProbeProvider::Supports(const beacon::CallData& call) const {
  return call.sdk == rtc_commands::kSdk && call.interface_name == rtc_commands::kVisualProbeInterface;
}

void VolcengineVisualProbeProvider::RegisterInvocations(beacon::InvocationController& controller) {
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kVisualProbeInterface, rtc_commands::kVisualProbeClass,
                   rtc_commands::kBindLocalVideo),
      [this](const beacon::CallData& call) { return BindLocalVideo(call); });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kVisualProbeInterface, rtc_commands::kVisualProbeClass,
                   rtc_commands::kBindRemoteVideo),
      [this](const beacon::CallData& call) { return BindRemoteVideo(call); });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kVisualProbeInterface, rtc_commands::kVisualProbeClass,
                   rtc_commands::kCaptureSnapshot),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->CaptureSnapshot(call);
      });
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSdk, rtc_commands::kVisualProbeInterface, rtc_commands::kVisualProbeClass,
                   rtc_commands::kReleaseView),
      [this](const beacon::CallData& call) {
        return backend_ == nullptr ? beacon::CallResult{beacon::kBadRequest, "missing rtc backend", "{}"}
                                   : backend_->ReleaseView(call);
      });
}

beacon::CallResult VolcengineVisualProbeProvider::BindLocalVideo(const beacon::CallData& call) const {
  if (backend_ == nullptr) {
    return {beacon::kBadRequest, "missing rtc backend", "{}"};
  }
  Json::Value params;
  beacon::ParseJson(call.params_json, &params);
  beacon::CallData forwarded = ForwardVisualCall(call, params);
  forwarded.function_name = std::string(rtc_commands::kBindLocalVideo);
  return backend_->BindLocalVideo(forwarded);
}

beacon::CallResult VolcengineVisualProbeProvider::BindRemoteVideo(const beacon::CallData& call) const {
  if (backend_ == nullptr) {
    return {beacon::kBadRequest, "missing rtc backend", "{}"};
  }
  Json::Value params;
  beacon::ParseJson(call.params_json, &params);
  beacon::CallData forwarded = ForwardVisualCall(call, params);
  forwarded.function_name = std::string(rtc_commands::kBindRemoteVideo);
  return backend_->BindRemoteVideo(forwarded);
}

}  // namespace beacon::mac
