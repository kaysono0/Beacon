#include "vendors/zego/zego_sdk_loader.h"

#include <memory>

namespace beacon::mac {

bool ZegoSDKLoader::Load() { return loaded_ = true; }
bool ZegoSDKLoader::Unload() { return !(loaded_ = false); }
void ZegoSDKLoader::Configure(const std::string& app_id) { app_id_ = app_id; }
bool ZegoSDKLoader::loaded() const { return loaded_; }
std::string ZegoSDKLoader::version() const { return loaded_ ? "zego-express-native" : ""; }
std::string ZegoSDKLoader::app_id() const { return app_id_; }
std::unique_ptr<SDKLoader> CreateDefaultSDKLoader() { return std::make_unique<ZegoSDKLoader>(); }

}  // namespace beacon::mac
