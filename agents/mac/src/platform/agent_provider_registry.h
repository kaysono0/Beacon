#pragma once

#include <memory>
#include <vector>

#include "platform/interface_provider.h"

namespace beacon::mac {

class AgentProviderRegistry {
 public:
  void RegisterProvider(std::shared_ptr<InterfaceProvider> provider);
  std::shared_ptr<InterfaceProvider> Resolve(const beacon::CallData& call) const;
  const std::vector<std::shared_ptr<InterfaceProvider>>& providers() const;

 private:
  std::vector<std::shared_ptr<InterfaceProvider>> providers_;
};

}  // namespace beacon::mac
