#include "beacon/protocol_validator.h"

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"

#include <set>

namespace beacon {

namespace {

bool IsJsonString(const Json::Value& value) {
  if (!value.isString()) {
    return false;
  }
  Json::Value parsed;
  return ParseJson(value.asString(), &parsed);
}

bool HasString(const Json::Value& value, const char* field) {
  return value.isMember(field) && value[field].isString() && !value[field].asString().empty();
}

bool HasInt(const Json::Value& value, const char* field) {
  return value.isMember(field) && value[field].isInt();
}

bool HasBool(const Json::Value& value, const char* field) {
  return value.isMember(field) && value[field].isBool();
}

bool IsValidTarget(const Json::Value& target) {
  return NormalizeTargetValue(target, TargetProfile::kWireCompat).ok;
}

bool IsValidCallItem(const Json::Value& item) {
  if (!item.isObject() || !IsValidTarget(item[protocol::kTarget])) {
    return false;
  }
  return (!item.isMember(protocol::kParams) || IsJsonString(item[protocol::kParams])) &&
         (!item.isMember(protocol::kExtra) || IsJsonString(item[protocol::kExtra])) &&
         (!item.isMember(protocol::kResourceRef) || HasString(item, protocol::kResourceRef)) &&
         (!item.isMember(protocol::kStoreAs) || HasString(item, protocol::kStoreAs));
}

bool HasOnlyFields(const Json::Value& value, const std::set<std::string>& fields) {
  if (!value.isObject()) {
    return false;
  }
  for (const auto& field : value.getMemberNames()) {
    if (fields.count(field) == 0U) {
      return false;
    }
  }
  return true;
}

bool IsValidCallResultItem(const Json::Value& item) {
  static const std::set<std::string> kFields = {
      protocol::kTarget,
      protocol::kResourceRef,
      protocol::kError,
      protocol::kMessage,
      protocol::kReturnValue,
  };
  return HasOnlyFields(item, kFields) && IsValidTarget(item[protocol::kTarget]) &&
         (!item.isMember(protocol::kResourceRef) || HasString(item, protocol::kResourceRef)) &&
         HasInt(item, protocol::kError) && item[protocol::kMessage].isString() &&
         item[protocol::kReturnValue].isString();
}

bool IsValidCallResultList(const Json::Value& list) {
  if (!list.isArray()) {
    return false;
  }
  for (const auto& item : list) {
    if (!IsValidCallResultItem(item)) {
      return false;
    }
  }
  return true;
}

bool IsValidCallbackExecution(const Json::Value& execution) {
  static const std::set<std::string> kFields = {"defer_matched", "defer_executed", "call_results"};
  return HasOnlyFields(execution, kFields) && HasBool(execution, "defer_matched") &&
         HasBool(execution, "defer_executed") && IsValidCallResultList(execution["call_results"]);
}

bool IsValidReceipt(const Json::Value& receipt) {
  static const std::set<std::string> kFields = {"received", "recorded", "duplicate", "evidence_id"};
  return HasOnlyFields(receipt, kFields) && HasBool(receipt, "received") && HasBool(receipt, "recorded") &&
         HasBool(receipt, "duplicate") &&
         (!receipt.isMember("evidence_id") || receipt["evidence_id"].isString());
}

bool IsValidCallbackContext(const Json::Value& context) {
  if (!context.isObject()) {
    return false;
  }
  static const std::set<std::string> kFields = {
      "provider",
      protocol::kOriginatingOpId,
      protocol::kResourceRef,
      "instance_id",
      "subscription_id",
      "rule_id",
      "sequence",
  };
  return HasOnlyFields(context, kFields) && HasString(context, protocol::kResourceRef) && HasString(context, "instance_id") &&
         context["sequence"].isUInt64() &&
         (!context.isMember("provider") || HasString(context, "provider")) &&
         (!context.isMember(protocol::kOriginatingOpId) || HasString(context, protocol::kOriginatingOpId)) &&
         (!context.isMember("subscription_id") || HasString(context, "subscription_id")) &&
         (!context.isMember("rule_id") || HasString(context, "rule_id"));
}

bool IsValidRepeat(const Json::Value& value) {
  return value.isInt() && (value.asInt() == -1 || value.asInt() >= 1);
}

bool HasAction(const std::string& action) {
  static const std::set<std::string> kActions = {
      "registerRequest",
      "registerResponse",
      "unregisterRequest",
      "unregisterResponse",
      protocol::kInvokeRequest,
      protocol::kInvokeResponse,
      protocol::kCallbackRequest,
      protocol::kCallbackResponse,
      protocol::kCallbackEventRequest,
      protocol::kCallbackEventResponse,
      "reconnectRequest",
      "reconnectResponse",
      "logReportRequest",
      "logReportResponse",
      "artifactUploadReq",
      "artifactUploadResp",
  };
  return kActions.count(action) != 0;
}

}  // namespace

bool ProtocolValidator::ValidatePacket(const std::string& packet_json) const {
  Json::Value packet;
  if (!ParseJson(packet_json, &packet) || !packet.isObject()) {
    return false;
  }
  if (!packet.isMember(protocol::kCommon) || !packet[protocol::kCommon].isObject() ||
      !packet.isMember(protocol::kData) || !packet[protocol::kData].isObject()) {
    return false;
  }
  const Json::Value common = packet[protocol::kCommon];
  const Json::Value data = packet[protocol::kData];
  if (!common[protocol::kAction].isString() || !common[protocol::kOpId].isString() ||
      !common[protocol::kTimestampMs].isInt64()) {
    return false;
  }
  const std::string action = common[protocol::kAction].asString();
  if (action.empty() || !HasAction(action) || common[protocol::kOpId].asString().empty()) {
    return false;
  }
  for (const char* field : {protocol::kParams, protocol::kExtra, protocol::kResult}) {
    if (data.isMember(field) && !IsJsonString(data[field])) {
      return false;
    }
  }
  if (action == protocol::kInvokeRequest) {
    if (!HasString(data, "node_id") || !HasBool(data, protocol::kSync) || !data[protocol::kSync].asBool()) {
      return false;
    }
    if (!data[protocol::kList].isArray() || data[protocol::kList].empty()) {
      return false;
    }
    for (const auto& item : data[protocol::kList]) {
      if (!IsValidCallItem(item)) {
        return false;
      }
    }
    return true;
  }
  if (action == protocol::kCallbackRequest) {
    if (!HasString(data, "node_id") || !HasBool(data, protocol::kSync) || !data[protocol::kSync].asBool()) {
      return false;
    }
    if (!data[protocol::kList].isArray() || data[protocol::kList].empty()) {
      return false;
    }
    for (const auto& descriptor : data[protocol::kList]) {
      if (!descriptor.isObject() || !IsValidTarget(descriptor[protocol::kEventTarget]) ||
          !IsValidRepeat(descriptor[protocol::kRepeat]) || !descriptor[protocol::kCallElements].isArray() ||
          descriptor[protocol::kCallElements].empty()) {
        return false;
      }
      for (const auto& item : descriptor[protocol::kCallElements]) {
        if (!IsValidCallItem(item)) {
          return false;
        }
      }
    }
    return true;
  }
  if (action == protocol::kCallbackEventRequest) {
    return HasString(data, "node_id") && HasString(data, "event_id") &&
           IsValidTarget(data[protocol::kEventTarget]) && data[protocol::kPayload].isObject() &&
           IsValidCallbackExecution(data["callback_execution"]) &&
           (!data.isMember(protocol::kCallbackContext) || IsValidCallbackContext(data[protocol::kCallbackContext]));
  }
  if (action == "registerRequest") {
    return HasString(data, "node_id") && data.isMember("capabilities") && data["capabilities"].isArray();
  }
  if (action == protocol::kInvokeResponse) {
    return HasInt(data, protocol::kCode) && HasString(data, protocol::kMessage) &&
           IsJsonString(data[protocol::kResult]) &&
           (!data.isMember(protocol::kList) || data[protocol::kList].isArray());
  }
  if (action == protocol::kCallbackResponse) {
    return HasInt(data, protocol::kCode) && HasString(data, protocol::kMessage);
  }
  if (action == protocol::kCallbackEventResponse) {
    return HasInt(data, protocol::kCode) && HasString(data, protocol::kMessage) &&
           HasString(data, "event_id") && IsValidReceipt(data["receipt"]);
  }
  if (action == "reconnectResponse") {
    return HasInt(data, protocol::kCode) && HasString(data, protocol::kMessage) &&
           HasInt(data, protocol::kState) && (data[protocol::kState].asInt() == 0 || data[protocol::kState].asInt() == 1);
  }
  if (action.empty()) {
    return false;
  }
  return true;
}

}  // namespace beacon
