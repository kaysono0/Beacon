#pragma once

#include <string>

#include "rtc/sdk_loader.h"

namespace beacon::mac {

// 火山变体的 loader 适配器；本提交只提供 mock 实现，真实 SDK loader 随真实后端落地。
class VolcengineSDKAdapter : public SDKLoader {
 public:
  virtual ~VolcengineSDKAdapter() = default;
  virtual bool Load() = 0;
  virtual bool Unload() = 0;
  virtual void Configure(const std::string& app_id) = 0;
  virtual bool loaded() const = 0;
  virtual std::string version() const = 0;
  virtual std::string app_id() const = 0;
};

class MockVolcengineSDKAdapter : public VolcengineSDKAdapter {
 public:
  bool Load() override;
  bool Unload() override;
  void Configure(const std::string& app_id) override;
  bool loaded() const override;
  std::string version() const override;
  std::string app_id() const override;

 private:
  bool loaded_ = false;
  std::string app_id_;
};

}  // namespace beacon::mac
