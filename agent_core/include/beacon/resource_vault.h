#pragma once

#include <map>
#include <memory>
#include <string>

namespace beacon {

// 需要参与 reset/clear 生命周期的运行期资源。
class VaultResource {
 public:
  virtual ~VaultResource() = default;
  virtual int DestroyOrder() const = 0;
  virtual void Destroy() = 0;
};

// 资源保险箱负责按确定顺序释放运行期对象。
// 平台 adapter 可以放入 SDK 对象、视图绑定或其他需要显式销毁的资源。
class ResourceVault {
 public:
  int Set(const std::string& key, std::shared_ptr<VaultResource> object);
  std::shared_ptr<VaultResource> Get(const std::string& key) const;
  void Remove(const std::string& key);
  // Reset 按 DestroyOrder 和创建顺序反向销毁，避免依赖资源先被释放。
  void Reset();
  size_t size() const;

 private:
  struct Entry {
    std::shared_ptr<VaultResource> object;
    long long create_seq = 0;
  };

  long long next_seq_ = 1;
  std::map<std::string, Entry> resources_;
};

}  // namespace beacon
