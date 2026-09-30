#include "platform/platform_adapter.h"

#include <array>
#include <utility>

#include "beacon/target_contract.h"

namespace beacon::mac {

namespace {

constexpr std::string_view kRuntimeSdk = "beacon_system";
constexpr std::string_view kRuntimeInterface = "runtime";
constexpr std::string_view kRuntimeClass = "AgentRuntime";
constexpr std::string_view kResetSession = "resetSession";

// Agora 凭证字段名与 macOS 本机用户路径形态属于适配层知识，按 ADR-002 不得下沉到 Agent Core。
constexpr std::array<std::string_view, 2> kSensitiveKeys = {
    "AGORA_APP_CERT",
    "AGORA_APP_ID",
};
constexpr std::array<std::string_view, 2> kPathPatterns = {
    R"(/Users/[^\s,:;"']+(?:/[^\s,:;"']*)?)",
    R"(\$HOME(?:/[^\s,:;"']*)?)",
};

beacon::PlatformRedactionProfile MacRedactionProfile() {
  beacon::PlatformRedactionProfile profile;
  for (const auto& key : kSensitiveKeys) {
    profile.sensitive_keys.emplace_back(key);
  }
  for (const auto& pattern : kPathPatterns) {
    profile.path_patterns.emplace_back(pattern);
  }
  return profile;
}

std::shared_ptr<RTCBackend> MakeBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission,
                                        RTCEventBridge* events, ViewRegistry* views) {
#ifdef BEACON_MAC_REAL_BACKEND
  return std::shared_ptr<RTCBackend>(CreateRealRTCBackend(sdk, std::move(has_media_permission), events, views));
#else
  return std::shared_ptr<RTCBackend>(CreateMockRTCBackend(sdk, std::move(has_media_permission), events, views));
#endif
}

std::string RuntimeResetKey() {
  beacon::TargetData target;
  target.sdk = std::string(kRuntimeSdk);
  target.interface_name = std::string(kRuntimeInterface);
  target.class_name = std::string(kRuntimeClass);
  target.function_name = std::string(kResetSession);
  return beacon::TargetKey(target);
}

}  // namespace

PlatformAdapter::PlatformAdapter()
    : default_sdk_(CreateDefaultSDKLoader()),
      sdk_(default_sdk_.get()),
      rtc_provider_(std::make_shared<RTCInvocationProvider>(
          MakeBackend(sdk_, [this]() { return HasMediaPermission(); }, &events_, &views_))),
      visual_probe_provider_(std::make_shared<VisualProbeProvider>(rtc_provider_->backend())),
      network_condition_provider_(std::make_shared<NetworkConditionProvider>()),
      video_host_provider_(std::make_shared<VideoHostProvider>()) {
  providers_.RegisterProvider(rtc_provider_);
  providers_.RegisterProvider(visual_probe_provider_);
  providers_.RegisterProvider(network_condition_provider_);
  providers_.RegisterProvider(video_host_provider_);
}

PlatformAdapter::PlatformAdapter(SDKLoader* sdk)
    : default_sdk_(CreateDefaultSDKLoader()),
      sdk_(sdk == nullptr ? default_sdk_.get() : sdk),
      rtc_provider_(std::make_shared<RTCInvocationProvider>(
          MakeBackend(sdk_, [this]() { return HasMediaPermission(); }, &events_, &views_))),
      visual_probe_provider_(std::make_shared<VisualProbeProvider>(rtc_provider_->backend())),
      network_condition_provider_(std::make_shared<NetworkConditionProvider>()),
      video_host_provider_(std::make_shared<VideoHostProvider>()) {
  providers_.RegisterProvider(rtc_provider_);
  providers_.RegisterProvider(visual_probe_provider_);
  providers_.RegisterProvider(network_condition_provider_);
  providers_.RegisterProvider(video_host_provider_);
}

int PlatformAdapter::Init() {
  kernel_.Init();
  // 必须在第一条日志写出前注入，否则平台专有敏感值会漏进 sink。
  kernel_.logs().RegisterPlatformRedaction(MacRedactionProfile());
  Json::Value permission_state(Json::objectValue);
  permission_state["camera_status"] = PermissionStateName(permissions_.Camera());
  permission_state["microphone_status"] = PermissionStateName(permissions_.Microphone());
  kernel_.logs().Log("Info", "platform", "platform.permissions.current", "media permission status", beacon::kOk,
                     permission_state);
  if (!sdk_->Load()) {
    return beacon::kBadRequest;
  }
  state_ = PlatformLifecycleState::kInitialized;
  return beacon::kOk;
}

int PlatformAdapter::Register() {
  if (state_ == PlatformLifecycleState::kCreated && Init() != beacon::kOk) {
    return beacon::kBadRequest;
  }
  for (const auto& provider : providers_.providers()) {
    provider->RegisterInvocations(kernel_.invocations());
  }
  kernel_.RegisterInvocation(RuntimeResetKey(), [this](const beacon::CallData&) {
    const int code = ResetSession();
    return beacon::CallResult{
        code,
        code == beacon::kOk ? "runtime session reset" : "runtime session reset failed",
        code == beacon::kOk ? "{\"reset\":true}" : "{\"reset\":false}",
    };
  });
  state_ = PlatformLifecycleState::kRegistered;
  return beacon::kOk;
}

int PlatformAdapter::Bind() {
  if (!rtc_provider_->registered() && Register() != beacon::kOk) {
    return beacon::kBadRequest;
  }
  events_.Bind(&kernel_);
  state_ = PlatformLifecycleState::kBound;
  return beacon::kOk;
}

int PlatformAdapter::Reset() {
  ResetSession();
  views_.Clear();
  if (state_ != PlatformLifecycleState::kDestroyed) {
    state_ = PlatformLifecycleState::kInitialized;
  }
  return beacon::kOk;
}

int PlatformAdapter::ResetSession() {
  events_.Suppress(true);
  kernel_.Reset();
  rtc_provider_->Reset();
  network_condition_provider_->Reset();
  events_.ClearActiveEngineIdentity();
  events_.Bind(&kernel_);
  events_.Suppress(false);
  return beacon::kOk;
}

int PlatformAdapter::Destroy() {
  events_.Bind(nullptr);
  platform_logs_.Bind(nullptr);
  rtc_provider_->Reset();
  network_condition_provider_->Reset();
  views_.Clear();
  sdk_->Unload();
  kernel_.invocations().Clear();
  state_ = PlatformLifecycleState::kDestroyed;
  return beacon::kOk;
}

beacon::RunnerKernel& PlatformAdapter::kernel() {
  return kernel_;
}

AgentProviderRegistry& PlatformAdapter::provider_registry() {
  return providers_;
}

RTCInvocationProvider& PlatformAdapter::rtc() {
  return *rtc_provider_;
}

RTCEventBridge& PlatformAdapter::events() {
  return events_;
}

PlatformLifecycleState PlatformAdapter::state() const {
  return state_;
}

SDKLoader& PlatformAdapter::sdk_loader() {
  return *sdk_;
}

PermissionManager& PlatformAdapter::permissions() {
  return permissions_;
}

bool PlatformAdapter::HasMediaPermission() const {
  return !media_permission_denied_for_testing_ && permissions_.HasMediaPermission();
}

void PlatformAdapter::DenyMediaPermissionForTesting() {
  media_permission_denied_for_testing_ = true;
}

ViewRegistry& PlatformAdapter::views() {
  return views_;
}

VideoHostProvider& PlatformAdapter::video_host() { return *video_host_provider_; }

PlatformLogBridge& PlatformAdapter::platform_logs() {
  return platform_logs_;
}

}  // namespace beacon::mac
