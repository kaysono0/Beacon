#include "rtc/rtc_invocation_provider.h"

#include <chrono>
#include <string>
#include <thread>
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

}  // namespace

RTCInvocationProvider::RTCInvocationProvider(std::shared_ptr<RTCBackend> backend) : backend_(std::move(backend)) {}

void RTCInvocationProvider::RegisterInvocations(beacon::InvocationController& controller) {
  Register(controller);
}

void RTCInvocationProvider::SetBackend(std::shared_ptr<RTCBackend> backend) {
  backend_ = std::move(backend);
}

void RegisterSystemInvocations(beacon::InvocationController& controller) {
  const auto wait_handler = [](const beacon::CallData& call) {
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const int ms = params.get("ms", 0).asInt();
    if (ms > 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(ms));
    }
    return beacon::CallResult{beacon::kOk, "waited", "{\"waited\":true}"};
  };
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSystemSdk, rtc_commands::kSystemInterface, rtc_commands::kSystemClass,
                   rtc_commands::kWaitInMs),
      wait_handler);
  controller.RegisterInvocation(
      CanonicalKey(rtc_commands::kSystemSdk, "", rtc_commands::kSystemClass, rtc_commands::kWaitInMs), wait_handler);
}

void RTCInvocationProvider::Reset() {
  if (backend_ != nullptr) {
    backend_->Reset();
  }
  audio_enabled_ = true;
  video_enabled_ = true;
}

bool RTCInvocationProvider::joined() const {
  return backend_ != nullptr && backend_->joined();
}

bool RTCInvocationProvider::initialized() const {
  return backend_ != nullptr && backend_->initialized();
}

bool RTCInvocationProvider::previewing() const {
  return backend_ != nullptr && backend_->previewing();
}

bool RTCInvocationProvider::registered() const {
  return registered_;
}

std::string RTCInvocationProvider::channel() const {
  return backend_ == nullptr ? "" : backend_->channel();
}

std::shared_ptr<RTCBackend> RTCInvocationProvider::backend() const {
  return backend_;
}

}  // namespace beacon::mac
