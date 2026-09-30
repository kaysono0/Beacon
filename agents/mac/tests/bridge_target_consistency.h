#pragma once

// BRIDGE-MAC-TARGET-CONSISTENCY 的共享实现：遍历 SDK Registry 编译产物，要求
// 「声明了 mac + supported + 非空 provider」的 call/state 契约行在 Agent 侧有已注册 handler。
// 每个 vendor 变体只校验自己那一路 SDK 的行（各自只注册自己那一路 provider）。

#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"
#include "platform/platform_adapter.h"
#include "rtc/rtc_vendor.h"

namespace beacon::mac::test_support {

inline bool RequiresMacInvocationHandler(const Json::Value& row) {
  const std::string kind = row.get("kind", "").asString();
  if (kind != "call" && kind != "state") {
    return false;
  }
  for (const auto& mapping : row["provider_mappings"]) {
    if (mapping.get("platform", "").asString() == "mac" &&
        mapping.get("status", "").asString() == "supported" &&
        !mapping.get("provider", "").asString().empty()) {
      return true;
    }
  }
  return false;
}

inline beacon::TargetData RegistryTarget(const Json::Value& value) {
  beacon::TargetData target;
  target.sdk = value.get("sdk", "").asString();
  target.interface_name = value.get("interface", "").asString();
  target.class_name = value.get("class_name", "").asString();
  target.function_name = value.get("function", "").asString();
  target.overload = value.get("overload", "").asString();
  return target;
}

inline bool LoadJsonFile(const std::filesystem::path& path, Json::Value* root) {
  std::ifstream input(path);
  std::ostringstream buffer;
  buffer << input.rdbuf();
  return input.good() && beacon::ParseJson(buffer.str(), root);
}

// 只校验 target.sdk 等于当前 vendor 的行；跨 vendor 的行由对应 vendor 变体负责。
inline int CheckVendorTargetConsistency() {
  beacon::mac::PlatformAdapter adapter;
  adapter.Bind();
  const std::string vendor_sdk(kVendorSdk);
  size_t checked = 0;
  for (const auto& entry : std::filesystem::directory_iterator("sdk_registry/compiled")) {
    if (entry.path().extension() != ".json") {
      continue;
    }
    Json::Value artifact;
    if (!LoadJsonFile(entry.path(), &artifact)) {
      std::cerr << "BRIDGE-MAC-TARGET-CONSISTENCY invalid registry artifact: " << entry.path() << "\n";
      return 1;
    }
    for (const auto& row : artifact["contract_matrix"]) {
      if (row["target"].get("sdk", "").asString() != vendor_sdk || !RequiresMacInvocationHandler(row)) {
        continue;
      }
      ++checked;
      const std::string key = beacon::TargetKey(RegistryTarget(row["target"]));
      if (!adapter.kernel().invocations().HasInvocation(key)) {
        std::cerr << "BRIDGE-MAC-TARGET-CONSISTENCY missing_handler: " << key << "\n";
        return 1;
      }
    }
  }
  if (checked == 0) {
    std::cerr << "BRIDGE-MAC-TARGET-CONSISTENCY no supported mac targets checked for " << vendor_sdk << "\n";
    return 1;
  }
  return 0;
}

}  // namespace beacon::mac::test_support
