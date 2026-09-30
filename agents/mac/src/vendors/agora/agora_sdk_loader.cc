#include "vendors/agora/agora_sdk_loader.h"

namespace beacon::mac {

bool MockAgoraSDKAdapter::Load() {
  loaded_ = true;
  return loaded_;
}

bool MockAgoraSDKAdapter::Unload() {
  loaded_ = false;
  app_id_.clear();
  return true;
}

void MockAgoraSDKAdapter::Configure(const std::string& app_id) {
  app_id_ = app_id;
}

bool MockAgoraSDKAdapter::loaded() const {
  return loaded_;
}

std::string MockAgoraSDKAdapter::version() const {
  return loaded_ ? "mock-agora-0.1" : "";
}

std::string MockAgoraSDKAdapter::app_id() const {
  return app_id_;
}

std::unique_ptr<SDKLoader> CreateDefaultSDKLoader() {
  return std::make_unique<MockAgoraSDKAdapter>();
}

}  // namespace beacon::mac
