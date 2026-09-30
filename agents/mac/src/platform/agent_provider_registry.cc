#include "platform/agent_provider_registry.h"

#include <utility>

namespace beacon::mac {

void AgentProviderRegistry::RegisterProvider(std::shared_ptr<InterfaceProvider> provider) {
  providers_.push_back(std::move(provider));
}

std::shared_ptr<InterfaceProvider> AgentProviderRegistry::Resolve(const beacon::CallData& call) const {
  for (const auto& provider : providers_) {
    if (provider->Supports(call)) {
      return provider;
    }
  }
  return nullptr;
}

const std::vector<std::shared_ptr<InterfaceProvider>>& AgentProviderRegistry::providers() const {
  return providers_;
}

}  // namespace beacon::mac
