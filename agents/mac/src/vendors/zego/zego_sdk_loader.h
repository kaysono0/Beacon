#pragma once

#include <string>

#include "rtc/sdk_loader.h"

namespace beacon::mac {

class ZegoSDKLoader final : public SDKLoader {
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
