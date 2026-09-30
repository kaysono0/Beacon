#include "beacon/target_contract.h"

#include <json/json.h>

#include <set>
#include <string>

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"

namespace beacon {

namespace {

const std::set<std::string>& TargetFields() {
  static const std::set<std::string> fields = {
      protocol::kSdk, protocol::kInterface, protocol::kClassName, protocol::kFunction, protocol::kOverload};
  return fields;
}

// 错误文案必须与 server/app/target_contract.py 完全一致，两侧由同一组 fixtures 断言。
std::string ProfileName(TargetProfile profile) {
  static const char* names[] = {"call", "callback", "registry", "assertion", "evidence", "system", "wire_compat"};
  return names[static_cast<size_t>(profile)];
}

// ADR-020：interface 是否必填只由 profile 决定，core 不认识任何具体 SDK 名字。
bool RequiresInterface(TargetProfile profile) {
  return profile == TargetProfile::kCall || profile == TargetProfile::kCallback || profile == TargetProfile::kRegistry;
}

TargetNormalizeResult Fail(const std::string& error) {
  TargetNormalizeResult result;
  result.ok = false;
  result.error = error;
  return result;
}

}  // namespace

TargetNormalizeResult NormalizeTarget(const TargetData& target, TargetProfile profile) {
  if (target.sdk.empty()) return Fail("target.sdk must be a non-empty string");
  if (target.class_name.empty()) return Fail("target.class_name must be a non-empty string");
  if (target.function_name.empty()) return Fail("target.function must be a non-empty string");
  if (RequiresInterface(profile) && target.interface_name.empty()) {
    return Fail("target.interface is required for SDK " + ProfileName(profile));
  }
  TargetNormalizeResult result;
  result.ok = true;
  result.target = target;
  return result;
}

TargetNormalizeResult NormalizeTargetValue(const Json::Value& value, TargetProfile profile) {
  if (!value.isObject()) {
    return Fail("target must be an object");
  }
  const std::set<std::string>& fields = TargetFields();
  for (const auto& field : value.getMemberNames()) {
    if (fields.count(field) == 0U) {
      return Fail("target contains unknown field: " + field);
    }
  }
  // 字段校验顺序必须与 server/app/target_contract.py 一致，否则同一份多重缺陷 target 两侧会报出不同字段。
  static const char* kOrderedFields[] = {protocol::kSdk, protocol::kClassName, protocol::kFunction,
                                         protocol::kInterface, protocol::kOverload};
  for (const char* field : kOrderedFields) {
    if (!value.isMember(field)) continue;
    const Json::Value& item = value[field];
    if (!item.isString() || item.asString().empty()) {
      return Fail(std::string("target.") + field + " must be a non-empty string");
    }
  }
  TargetData target;
  target.sdk = value.get(protocol::kSdk, "").asString();
  target.interface_name = value.get(protocol::kInterface, "").asString();
  target.class_name = value.get(protocol::kClassName, "").asString();
  target.function_name = value.get(protocol::kFunction, "").asString();
  target.overload = value.get(protocol::kOverload, "").asString();
  return NormalizeTarget(target, profile);
}

Json::Value TargetToJson(const TargetData& target) {
  Json::Value value(Json::objectValue);
  value[protocol::kClassName] = target.class_name;
  value[protocol::kFunction] = target.function_name;
  if (!target.interface_name.empty()) value[protocol::kInterface] = target.interface_name;
  if (!target.overload.empty()) value[protocol::kOverload] = target.overload;
  value[protocol::kSdk] = target.sdk;
  return value;
}

std::string TargetKey(const TargetData& target) {
  return WriteJson(TargetToJson(target));
}

}  // namespace beacon
