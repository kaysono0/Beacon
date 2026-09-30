#pragma once

#include <memory>
#include <string>

#include "beacon/invocation_controller.h"
#include "platform/interface_provider.h"
#include "rtc/rtc_backend.h"

namespace beacon::mac {

class RTCInvocationProvider final : public InterfaceProvider {
 public:
  explicit RTCInvocationProvider(std::shared_ptr<RTCBackend> backend);
  std::string sdk() const override;
  std::string interface_name() const override;
  bool Supports(const beacon::CallData& call) const override;
  void RegisterInvocations(beacon::InvocationController& controller) override;
  void SetBackend(std::shared_ptr<RTCBackend> backend);
  void Register(beacon::InvocationController& controller);
  void Reset();
  bool joined() const;
  bool initialized() const;
  bool previewing() const;
  bool registered() const;
  std::string channel() const;
  std::shared_ptr<RTCBackend> backend() const;

 private:
  bool registered_ = false;
  bool audio_enabled_ = true;
  bool video_enabled_ = true;
  std::shared_ptr<RTCBackend> backend_;
};

// 平台级（非 vendor 专有）op：beacon_system 时钟。由各 vendor 的 Register() 调用。
void RegisterSystemInvocations(beacon::InvocationController& controller);

}  // namespace beacon::mac
