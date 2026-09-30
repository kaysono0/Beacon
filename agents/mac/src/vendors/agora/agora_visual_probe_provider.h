#pragma once

#include <memory>
#include <string>

#include "beacon/invocation_controller.h"
#include "platform/interface_provider.h"
#include "rtc/rtc_backend.h"

namespace beacon::mac {

class AgoraVisualProbeProvider final : public InterfaceProvider {
 public:
  explicit AgoraVisualProbeProvider(std::shared_ptr<RTCBackend> backend);
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
