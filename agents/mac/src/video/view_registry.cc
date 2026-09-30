#include "video/view_registry.h"

#include <utility>

namespace beacon::mac {

void ViewRegistry::Attach(const std::string& key, void* handle) {
  handles_[key] = handle;
}

void ViewRegistry::SetHandleResolver(HandleResolver resolver) {
  handle_resolver_ = std::move(resolver);
}

void ViewRegistry::Detach(const std::string& key) {
  handles_.erase(key);
  views_.erase(key);
}

void ViewRegistry::Clear() {
  handles_.clear();
  views_.clear();
}

void ViewRegistry::RegisterView(const std::string& key, const std::string& handle) {
  views_[key] = handle;
}

std::string ViewRegistry::GetView(const std::string& key) const {
  auto it = views_.find(key);
  return it == views_.end() ? "" : it->second;
}

void* ViewRegistry::GetHandle(const std::string& key) {
  auto it = handles_.find(key);
  if (it != handles_.end()) {
    return it->second;
  }
  return handle_resolver_ ? handle_resolver_(key) : nullptr;
}

}  // namespace beacon::mac
