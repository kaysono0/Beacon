#pragma once

#include <functional>
#include <string>

#include "platform/interface_provider.h"

namespace beacon::mac {

class VideoHostProvider final : public InterfaceProvider {
 public:
  using Handler = std::function<beacon::CallResult(const beacon::CallData&)>;

  std::string sdk() const override;
  std::string interface_name() const override;
  bool Supports(const beacon::CallData& call) const override;
  void RegisterInvocations(beacon::InvocationController& controller) override;
  void SetHandlers(Handler show, Handler hide, Handler focus, Handler rearrange);

 private:
  beacon::CallResult Invoke(const beacon::CallData& call, const Handler& handler) const;
  Handler show_;
  Handler hide_;
  Handler focus_;
  Handler rearrange_;
};

}  // namespace beacon::mac
