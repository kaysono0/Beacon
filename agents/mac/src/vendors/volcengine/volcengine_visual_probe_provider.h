#pragma once

#include <memory>
#include <string>

#include "beacon/invocation_controller.h"
#include "platform/interface_provider.h"
#include "rtc/rtc_backend.h"

namespace beacon::mac {

// 火山变体的作者层画面入口（ADR-031 的 provider 边界）：作者只写 view_role/uid，
// 具体 canvas 与快照原生调用留在后端实现里。
class VolcengineVisualProbeProvider final : public InterfaceProvider {
 public:
  explicit VolcengineVisualProbeProvider(std::shared_ptr<RTCBackend> backend);
  std::string sdk() const override;
  std::string interface_name() const override;
  bool Supports(const beacon::CallData& call) const override;
  void RegisterInvocations(beacon::InvocationController& controller) override;

 private:
  beacon::CallResult BindLocalVideo(const beacon::CallData& call) const;
  beacon::CallResult BindRemoteVideo(const beacon::CallData& call) const;

  std::shared_ptr<RTCBackend> backend_;
};

}  // namespace beacon::mac
