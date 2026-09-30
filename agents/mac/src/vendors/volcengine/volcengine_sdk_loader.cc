#include "vendors/volcengine/volcengine_sdk_loader.h"

#include <memory>

namespace beacon::mac {

bool MockVolcengineSDKAdapter::Load() {
  loaded_ = true;
  return loaded_;
}

bool MockVolcengineSDKAdapter::Unload() {
  loaded_ = false;
  app_id_.clear();
  return true;
}

void MockVolcengineSDKAdapter::Configure(const std::string& app_id) {
  app_id_ = app_id;
}

bool MockVolcengineSDKAdapter::loaded() const {
  return loaded_;
}

std::string MockVolcengineSDKAdapter::version() const {
  return loaded_ ? "mock-volcengine-0.1" : "";
}

std::string MockVolcengineSDKAdapter::app_id() const {
  return app_id_;
}

std::unique_ptr<SDKLoader> CreateDefaultSDKLoader() {
  return std::make_unique<MockVolcengineSDKAdapter>();
}

}  // namespace beacon::mac
