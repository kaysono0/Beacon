#pragma once

#include <memory>
#include <string>

namespace beacon::mac {

// SDK 中立的 loader 边界：RTCBackend 工厂与 PlatformAdapter 只依赖它，
// 不依赖任何具体 vendor 的 loader 类型。各 vendor 的适配器继承本接口。
class SDKLoader {
 public:
  virtual ~SDKLoader() = default;
  virtual bool Load() = 0;
  virtual bool Unload() = 0;
  virtual void Configure(const std::string& app_id) = 0;
  virtual bool loaded() const = 0;
  virtual std::string version() const = 0;
  virtual std::string app_id() const = 0;
};

// 由当前编译变体（vendor）提供：返回该 vendor 的默认 loader 实现。
std::unique_ptr<SDKLoader> CreateDefaultSDKLoader();

}  // namespace beacon::mac
