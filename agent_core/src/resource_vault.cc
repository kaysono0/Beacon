#include "beacon/resource_vault.h"

#include <algorithm>
#include <vector>

#include "beacon/models.h"

namespace beacon {

int ResourceVault::Set(const std::string& key, std::shared_ptr<VaultResource> object) {
  if (key.empty() || !object) {
    return kBadRequest;
  }
  resources_[key] = {std::move(object), next_seq_++};
  return 0;
}

std::shared_ptr<VaultResource> ResourceVault::Get(const std::string& key) const {
  auto it = resources_.find(key);
  return it == resources_.end() ? nullptr : it->second.object;
}

void ResourceVault::Remove(const std::string& key) {
  auto it = resources_.find(key);
  if (it == resources_.end()) {
    return;
  }
  it->second.object->Destroy();
  resources_.erase(it);
}

void ResourceVault::Reset() {
  std::vector<Entry> entries;
  for (const auto& item : resources_) {
    entries.push_back(item.second);
  }
  resources_.clear();
  // 先按显式 DestroyOrder，再按创建顺序反向销毁，避免依赖资源提前释放。
  std::sort(entries.begin(), entries.end(), [](const Entry& left, const Entry& right) {
    if (left.object->DestroyOrder() != right.object->DestroyOrder()) {
      return left.object->DestroyOrder() > right.object->DestroyOrder();
    }
    return left.create_seq > right.create_seq;
  });
  for (const auto& entry : entries) {
    entry.object->Destroy();
  }
}

size_t ResourceVault::size() const {
  return resources_.size();
}

}  // namespace beacon
