#pragma once

#include <memory>
#include <string>

#include "beacon/invocation_controller.h"
#include "platform/interface_provider.h"
#include "rtc/rtc_backend.h"

namespace beacon::mac {

class ZegoVisualProbeProvider final : public InterfaceProvider {
public:
  explicit ZegoVisualProbeProvider(std::shared_ptr<RTCBackend> backend);
  std::string sdk() const override;
  std::string interface_name() const override;
  bool Supports(const beacon::CallData &call) const override;
  void RegisterInvocations(beacon::InvocationController &controller) override;

private:
  std::shared_ptr<RTCBackend> backend_;
};

} // namespace beacon::mac
