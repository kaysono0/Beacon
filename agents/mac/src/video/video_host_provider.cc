#include "video/video_host_provider.h"

#include <utility>

#include "beacon/target_contract.h"

namespace beacon::mac {
namespace {
constexpr const char* kSdk = "beacon_system";
constexpr const char* kInterface = "video_host";
constexpr const char* kClass = "VideoHost";

std::string Key(const char* function) {
  beacon::TargetData target;
  target.sdk = kSdk;
  target.interface_name = kInterface;
  target.class_name = kClass;
  target.function_name = function;
  return beacon::TargetKey(target);
}
}  // namespace

std::string VideoHostProvider::sdk() const {
  return kSdk;
}

std::string VideoHostProvider::interface_name() const {
  return kInterface;
}

bool VideoHostProvider::Supports(const beacon::CallData& call) const {
  return call.sdk == kSdk && call.interface_name == kInterface;
}

void VideoHostProvider::SetHandlers(Handler show, Handler hide, Handler focus, Handler rearrange) {
  show_ = std::move(show);
  hide_ = std::move(hide);
  focus_ = std::move(focus);
  rearrange_ = std::move(rearrange);
}

beacon::CallResult VideoHostProvider::Invoke(const beacon::CallData& call, const Handler& handler) const {
  return handler ? handler(call) : beacon::CallResult{488, "video host is unavailable", "{}"};
}

void VideoHostProvider::RegisterInvocations(beacon::InvocationController& controller) {
  controller.RegisterInvocation(Key("show"), [this](const beacon::CallData& call) { return Invoke(call, show_); });
  controller.RegisterInvocation(Key("hide"), [this](const beacon::CallData& call) { return Invoke(call, hide_); });
  controller.RegisterInvocation(Key("focus"), [this](const beacon::CallData& call) { return Invoke(call, focus_); });
  controller.RegisterInvocation(Key("rearrange"), [this](const beacon::CallData& call) { return Invoke(call, rearrange_); });
}
}  // namespace beacon::mac
