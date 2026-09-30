#pragma once

#include <string>

#include "rtc/sdk_loader.h"

namespace beacon::mac {

// Agora 变体的 loader 适配器；SDK 中立边界见 sdk_loader.h。
class AgoraSDKAdapter : public SDKLoader {
 public:
  virtual ~AgoraSDKAdapter() = default;
  virtual bool Load() = 0;
  virtual bool Unload() = 0;
  virtual void Configure(const std::string& app_id) = 0;
  virtual bool loaded() const = 0;
  virtual std::string version() const = 0;
  virtual std::string app_id() const = 0;
};

class MockAgoraSDKAdapter : public AgoraSDKAdapter {
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

using AgoraSDKLoader = MockAgoraSDKAdapter;

}  // namespace beacon::mac
