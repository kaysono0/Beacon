#pragma once

#include <memory>

#include "platform/agent_provider_registry.h"
#include "beacon/runner_kernel.h"
#include "platform/network_condition_provider.h"
#include "platform/permission_manager.h"
#include "platform/platform_log_bridge.h"
#include "rtc/rtc_event_bridge.h"
#include "rtc/rtc_invocation_provider.h"
#include "rtc/rtc_vendor.h"
#include "rtc/sdk_loader.h"
#include "video/view_registry.h"
#include "video/video_host_provider.h"
#if defined(BEACON_MAC_RTC_VENDOR_VOLCENGINE)
#include "vendors/volcengine/volcengine_visual_probe_provider.h"
#elif defined(BEACON_MAC_RTC_VENDOR_ZEGO)
#include "vendors/zego/zego_visual_probe_provider.h"
#else
#include "vendors/agora/agora_visual_probe_provider.h"
#endif

namespace beacon::mac {

enum class PlatformLifecycleState {
  kCreated,
  kInitialized,
  kRegistered,
  kBound,
  kDestroyed,
};

class PlatformAdapter {
 public:
  PlatformAdapter();
  explicit PlatformAdapter(SDKLoader* sdk);
  int Init();
  int Register();
  int Bind();
  int ResetSession();
  int Reset();
  int Destroy();
  PlatformLifecycleState state() const;
  beacon::RunnerKernel& kernel();
  AgentProviderRegistry& provider_registry();
  RTCInvocationProvider& rtc();
  RTCEventBridge& events();
  SDKLoader& sdk_loader();
  PermissionManager& permissions();
  PlatformLogBridge& platform_logs();
  bool HasMediaPermission() const;
  void DenyMediaPermissionForTesting();
  ViewRegistry& views();
  VideoHostProvider& video_host();

 private:
  std::unique_ptr<SDKLoader> default_sdk_;
  SDKLoader* sdk_;
  PlatformLifecycleState state_ = PlatformLifecycleState::kCreated;
  beacon::RunnerKernel kernel_;
  PermissionManager permissions_;
  PlatformLogBridge platform_logs_{&kernel_};
  bool media_permission_denied_for_testing_ = false;
  ViewRegistry views_;
  RTCEventBridge events_{&kernel_};
  AgentProviderRegistry providers_;
  std::shared_ptr<RTCInvocationProvider> rtc_provider_;
  // 画面探针 provider 按 vendor 词表装配：interface 名与实现类都来自当前变体。
#if defined(BEACON_MAC_RTC_VENDOR_VOLCENGINE)
  using VisualProbeProvider = VolcengineVisualProbeProvider;
#elif defined(BEACON_MAC_RTC_VENDOR_ZEGO)
  using VisualProbeProvider = ZegoVisualProbeProvider;
#else
  using VisualProbeProvider = AgoraVisualProbeProvider;
#endif
  std::shared_ptr<VisualProbeProvider> visual_probe_provider_;
  std::shared_ptr<NetworkConditionProvider> network_condition_provider_;
  std::shared_ptr<VideoHostProvider> video_host_provider_;
};

}  // namespace beacon::mac
