#pragma once

#include <string>

#include <json/json.h>

namespace beacon {

enum class TargetProfile { kCall, kCallback, kRegistry, kAssertion, kEvidence, kSystem, kWireCompat };

struct TargetData {
  std::string sdk;
  std::string interface_name;
  std::string class_name;
  std::string function_name;
  std::string overload;
};

struct TargetNormalizeResult {
  bool ok = false;
  TargetData target;
  std::string error;
};

TargetNormalizeResult NormalizeTarget(const TargetData& target, TargetProfile profile);
TargetNormalizeResult NormalizeTargetValue(const Json::Value& value, TargetProfile profile);
Json::Value TargetToJson(const TargetData& target);
std::string TargetKey(const TargetData& target);

}  // namespace beacon
