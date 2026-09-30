#include "beacon/protocol_json.h"

#include <memory>

#include "beacon/protocol_constants.h"
#include "beacon/target_contract.h"

namespace beacon {

namespace {

TargetData ToTargetData(const EventTarget& target) {
  TargetData out;
  out.sdk = target.sdk;
  out.interface_name = target.interface_name;
  out.class_name = target.class_name;
  out.function_name = target.function_name;
  out.overload = target.overload;
  return out;
}

TargetData ToTargetData(const CallData& call) {
  TargetData out;
  out.sdk = call.sdk;
  out.interface_name = call.interface_name;
  out.class_name = call.class_name;
  out.function_name = call.function_name;
  out.overload = call.overload;
  return out;
}

}  // namespace

bool ParseJson(const std::string& json_text, Json::Value* output) {
  Json::CharReaderBuilder builder;
  builder["collectComments"] = false;
  std::string errors;
  std::unique_ptr<Json::CharReader> reader(builder.newCharReader());
  return reader->parse(json_text.data(), json_text.data() + json_text.size(), output, &errors);
}

std::string WriteJson(const Json::Value& value) {
  Json::StreamWriterBuilder builder;
  builder["indentation"] = "";
  return Json::writeString(builder, value);
}

std::string PacketAction(const Json::Value& packet) {
  return packet[protocol::kCommon][protocol::kAction].asString();
}

std::string PacketOpId(const Json::Value& packet) {
  return packet[protocol::kCommon][protocol::kOpId].asString();
}

Json::Value PacketData(const Json::Value& packet) {
  return packet[protocol::kData];
}

EventTarget EventTargetFromValue(const Json::Value& value) {
  EventTarget target;
  target.sdk = value.get(protocol::kSdk, "").asString();
  target.interface_name = value.get(protocol::kInterface, "").asString();
  target.class_name = value.get(protocol::kClassName, "").asString();
  target.function_name = value.get(protocol::kFunction, "").asString();
  target.overload = value.get(protocol::kOverload, "").asString();
  return target;
}

Json::Value TargetToJson(const EventTarget& target) {
  return beacon::TargetToJson(ToTargetData(target));
}

std::string TargetKey(const EventTarget& target) {
  return beacon::TargetKey(ToTargetData(target));
}

std::string TargetKey(const CallData& call) {
  return beacon::TargetKey(ToTargetData(call));
}

CallData CallDataFromPacket(const Json::Value& packet) {
  const Json::Value data = PacketData(packet);
  return CallDataFromItem(data, PacketOpId(packet));
}

CallData CallDataFromItem(const Json::Value& item, const std::string& op_id) {
  CallData call;
  call.op_id = op_id;
  const EventTarget target = EventTargetFromValue(item[protocol::kTarget]);
  call.sdk = target.sdk;
  call.interface_name = target.interface_name;
  call.class_name = target.class_name;
  call.function_name = target.function_name;
  call.overload = target.overload;
  call.resource_ref = item.get(protocol::kResourceRef, "").asString();
  call.store_as = item.get(protocol::kStoreAs, "").asString();
  call.params_json = item.get(protocol::kParams, "{}").asString();
  call.extra_json = item.get(protocol::kExtra, "{}").asString();
  call.sync = item.get(protocol::kSync, true).asBool();
  return call;
}

std::vector<CallData> CallDataListFromPacket(const Json::Value& packet) {
  const Json::Value data = PacketData(packet);
  const std::string op_id = PacketOpId(packet);
  std::vector<CallData> calls;
  if (data[protocol::kList].isArray()) {
    for (const auto& item : data[protocol::kList]) {
      calls.push_back(CallDataFromItem(item, op_id));
    }
    return calls;
  }
  calls.push_back(CallDataFromItem(data, op_id));
  return calls;
}

std::string MakeCallResultJson(const CallResult& result, const std::string& action, const std::string& op_id) {
  Json::Value packet(Json::objectValue);
  packet[protocol::kCommon][protocol::kAction] = action;
  packet[protocol::kCommon][protocol::kOpId] = op_id;
  packet[protocol::kCommon][protocol::kTimestampMs] = 0;
  packet[protocol::kData][protocol::kCode] = result.error;
  packet[protocol::kData][protocol::kMessage] = result.message;
  packet[protocol::kData][protocol::kResult] = result.result_json;
  return WriteJson(packet);
}

std::string MakeCallResultsJson(const std::vector<CallResult>& results, const std::string& action,
                                const std::string& op_id) {
  Json::Value packet(Json::objectValue);
  packet[protocol::kCommon][protocol::kAction] = action;
  packet[protocol::kCommon][protocol::kOpId] = op_id;
  packet[protocol::kCommon][protocol::kTimestampMs] = 0;
  packet[protocol::kData][protocol::kCode] = kOk;
  packet[protocol::kData][protocol::kMessage] = "ok";
  packet[protocol::kData][protocol::kResult] = "{}";
  packet[protocol::kData][protocol::kList] = Json::arrayValue;
  for (const auto& result : results) {
    Json::Value item(Json::objectValue);
    item[protocol::kCode] = result.error;
    item[protocol::kMessage] = result.message;
    item[protocol::kResult] = result.result_json;
    packet[protocol::kData][protocol::kList].append(item);
    if (packet[protocol::kData][protocol::kCode].asInt() == kOk && !result.ok()) {
      packet[protocol::kData][protocol::kCode] = result.error;
      packet[protocol::kData][protocol::kMessage] = result.message;
    }
  }
  return WriteJson(packet);
}

std::string LogEventToJson(const LogEvent& event) {
  Json::Value value(Json::objectValue);
  value["event_id"] = event.event_id;
  value[protocol::kTimestampMs] = Json::Int64(event.timestamp_ms);
  value["level"] = event.level;
  value["node_id"] = event.trace.node_id;
  value["lease_id"] = event.trace.lease_id;
  value["run_id"] = event.trace.run_id;
  value["case_id"] = event.trace.case_id;
  value["step_id"] = event.trace.step_id;
  value[protocol::kOpId] = event.trace.op_id;
  value["module"] = event.module;
  value["event"] = event.event;
  value[protocol::kMessage] = event.message;
  value["error"] = event.error;
  value[protocol::kExtra] = event.extra;
  return WriteJson(value);
}

}  // namespace beacon
