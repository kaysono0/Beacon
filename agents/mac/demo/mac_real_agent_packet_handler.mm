#include "mac_real_agent_packet_handler.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <optional>
#include <utility>

#include <json/json.h>

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"
#include "mac_real_agent_loopback_helper.h"
#include "platform/platform_adapter.h"
#include "rtc/rtc_command_vocabulary.h"

namespace beacon::mac::agent_runtime {
namespace {

int64_t NowMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::string NextEventId() {
  static std::atomic<uint64_t> sequence{0};
  return "event-mac-" + std::to_string(NowMs()) + "-" +
         std::to_string(sequence.fetch_add(1, std::memory_order_relaxed));
}

AgentTraceContext ExtractTraceContext(const Json::Value& packet) {
  AgentTraceContext trace;
  const Json::Value& data = packet["data"];
  trace.lease_id = data.get("lease_id", "").asString();
  return trace;
}

Json::Value EventPacketFrom(const std::string& node_id,
                            const std::string& lease_id,
                            const std::string& function_name,
                            const std::string& payload_json,
                            const beacon::CallbackExecutionResult& execution,
                            const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) {
  Json::Value packet(Json::objectValue);
  const std::string event_id = NextEventId();
  packet["common"]["action"] = beacon::protocol::kCallbackEventRequest;
  packet["common"]["op_id"] = event_id;
  packet["common"]["timestamp_ms"] = Json::Int64(NowMs());
  packet["data"]["node_id"] = node_id;
  packet["data"]["event_id"] = event_id;
  if (!lease_id.empty()) {
    packet["data"]["lease_id"] = lease_id;
  }
  if (!origin.run_id.empty()) {
    packet["data"][beacon::protocol::kRunId] = origin.run_id;
  }
  if (!origin.case_id.empty()) {
    packet["data"][beacon::protocol::kCaseId] = origin.case_id;
  }
  if (!origin.device_role.empty()) {
    packet["data"]["device_role"] = origin.device_role;
  }
  if (!origin.step_id.empty()) {
    packet["data"][beacon::protocol::kStepId] = origin.step_id;
  }
  packet["data"]["event_target"]["sdk"] = std::string(beacon::mac::rtc_commands::kSdk);
  // 事件目标按当前变体词表解析：火山的事件分属房间级与引擎级两个 delegate，不能写死一个类名。
  const std::optional<beacon::mac::rtc_commands::EventTargetSpec> event_target =
      beacon::mac::rtc_commands::ResolveEventTarget(function_name);
  packet["data"]["event_target"]["interface"] = std::string(event_target ? event_target->interface_name : "");
  packet["data"]["event_target"]["class_name"] = std::string(event_target ? event_target->class_name : "");
  packet["data"]["event_target"]["function"] = function_name;
  Json::Value payload(Json::objectValue);
  beacon::ParseJson(payload_json, &payload);
  if (!payload.isObject()) {
    payload = Json::Value(Json::objectValue);
  }
  packet["data"]["payload"] = payload;
  if (!origin.originating_op_id.empty() || !origin.resource_ref.empty() || !origin.instance_id.empty()) {
    Json::Value context(Json::objectValue);
    // 回调上下文 provider 由当前变体的词表决定，不在 demo 层写死某个 SDK。
    context["provider"] = std::string(rtc_commands::kContextProvider);
    if (!origin.originating_op_id.empty()) {
      context[beacon::protocol::kOriginatingOpId] = origin.originating_op_id;
    }
    if (!origin.resource_ref.empty()) {
      context[beacon::protocol::kResourceRef] = origin.resource_ref;
      packet["data"][beacon::protocol::kResourceRef] = origin.resource_ref;
    }
    if (!origin.instance_id.empty()) {
      context["instance_id"] = origin.instance_id;
    }
    context["sequence"] = Json::UInt64(origin.sequence);
    packet["data"][beacon::protocol::kCallbackContext] = context;
  }
  bool executed = execution.matched && !execution.call_results.empty();
  packet["data"]["callback_execution"]["defer_matched"] = execution.matched;
  packet["data"]["callback_execution"]["call_results"] = Json::arrayValue;
  for (const auto& call_result : execution.call_results) {
    Json::Value item(Json::objectValue);
    item[beacon::protocol::kTarget][beacon::protocol::kSdk] = call_result.call.sdk;
    if (!call_result.call.interface_name.empty()) {
      item[beacon::protocol::kTarget][beacon::protocol::kInterface] = call_result.call.interface_name;
    }
    item[beacon::protocol::kTarget][beacon::protocol::kClassName] = call_result.call.class_name;
    item[beacon::protocol::kTarget][beacon::protocol::kFunction] = call_result.call.function_name;
    if (!call_result.call.overload.empty()) {
      item[beacon::protocol::kTarget][beacon::protocol::kOverload] = call_result.call.overload;
    }
    if (!call_result.call.resource_ref.empty()) {
      item[beacon::protocol::kResourceRef] = call_result.call.resource_ref;
    }
    item[beacon::protocol::kError] = call_result.result.error;
    item[beacon::protocol::kMessage] = call_result.result.message;
    item[beacon::protocol::kReturnValue] = call_result.result.result_json;
    if (!call_result.result.ok()) {
      executed = false;
    }
    packet["data"]["callback_execution"]["call_results"].append(item);
  }
  packet["data"]["callback_execution"]["defer_executed"] = executed;
  return packet;
}

std::optional<std::string> FirstSuccessfulResultPayload(const std::string& response) {
  Json::Value root;
  if (!beacon::ParseJson(response, &root) || root["data"].get("code", -1).asInt() != beacon::kOk) {
    return std::nullopt;
  }
  const Json::Value& list = root["data"]["list"];
  if (!list.isArray()) {
    return std::nullopt;
  }
  for (const Json::Value& item : list) {
    if (item.get("code", -1).asInt() != beacon::kOk) {
      continue;
    }
    const Json::Value& result = item["result"];
    return result.isString() ? result.asString() : beacon::WriteJson(result);
  }
  return std::nullopt;
}

std::string MakeLocalErrorResponse(const Json::Value& request, int code, const std::string& message) {
  Json::Value response(Json::objectValue);
  response["common"]["action"] = beacon::protocol::kInvokeResponse;
  response["common"]["op_id"] = request["common"].get("op_id", "").asString();
  response["common"]["timestamp_ms"] = Json::Int64(NowMs());
  response["data"]["node_id"] = request["data"].get("node_id", "").asString();
  response["data"]["lease_id"] = request["data"].get("lease_id", "").asString();
  response["data"]["code"] = code;
  response["data"]["message"] = message;
  response["data"]["list"] = Json::arrayValue;
  return beacon::WriteJson(response);
}

bool PacketContainsFunction(const Json::Value& packet, const std::string& function_name) {
  const Json::Value& list = packet["data"]["list"];
  if (!list.isArray()) {
    return false;
  }
  for (const Json::Value& item : list) {
    if (item["target"].get("function", "").asString() == function_name) {
      return true;
    }
  }
  return false;
}

// 会话结束 op 由当前变体的词表判定（Agora：leaveChannel/unloadSDK；火山：leaveRoom/destroyRTCEngine）。
bool PacketContainsSessionEndingOp(const Json::Value& packet) {
  const Json::Value& list = packet["data"]["list"];
  if (!list.isArray()) {
    return false;
  }
  for (const Json::Value& item : list) {
    if (beacon::mac::rtc_commands::IsSessionEndingOp(item["target"].get("function", "").asString())) {
      return true;
    }
  }
  return false;
}

}  // namespace

void TraceStore::Set(const AgentTraceContext& trace) {
  std::lock_guard<std::mutex> lock(mutex_);
  trace_ = trace;
}

AgentTraceContext TraceStore::Get() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return trace_;
}

std::string MakeRegisterPacket(const std::string& node_id,
                               const std::string& group_id,
                               const std::vector<std::string>& tags,
                               const std::vector<std::string>& capabilities) {
  Json::Value packet(Json::objectValue);
  packet["common"]["action"] = beacon::protocol::kRegisterRequest;
  packet["common"]["op_id"] = "op-direct-register";
  packet["common"]["timestamp_ms"] = Json::Int64(NowMs());
  packet["data"]["node_id"] = node_id;
  packet["data"]["platform"] = "mac";
  if (!group_id.empty()) {
    packet["data"]["group_id"] = group_id;
  }
  for (const auto& tag : tags) {
    packet["data"]["tags"].append(tag);
  }
  for (const auto& capability : capabilities) {
    packet["data"]["capabilities"].append(capability);
  }
  return beacon::WriteJson(packet);
}

AgentPacketHandler::AgentPacketHandler(beacon::mac::PlatformAdapter& adapter,
                                       TraceStore& trace_store,
                                       LoopbackHelperManager& helper_manager,
                                       std::string node_id)
    : adapter_(adapter), trace_store_(trace_store), helper_manager_(helper_manager), node_id_(std::move(node_id)) {}

std::string AgentPacketHandler::Handle(const std::string& packet_json, const EventEmitter& emit_event) {
  Json::Value packet;
  if (!beacon::ParseJson(packet_json, &packet)) {
    return "";
  }
  const std::string action = packet["common"].get("action", "").asString();
  if (action == beacon::protocol::kInvokeRequest) {
    trace_store_.Set(ExtractTraceContext(packet));
    if (const auto helper = ExtractLoopbackHelperConfig(packet)) {
      std::string error_message;
      if (!helper_manager_.EnsureStarted(*helper, &error_message)) {
        return MakeLocalErrorResponse(packet, 500, error_message);
      }
    }
  }
  const std::string response = adapter_.kernel().HandleRequest(packet_json);
  // 以下两处判断按当前变体的词表进行：不同 vendor 的 op 名不同，demo 层不得写死某个 SDK。
  if (action == beacon::protocol::kInvokeRequest &&
      beacon::mac::rtc_commands::kBindRemoteVideoOp.has_value() &&
      PacketContainsFunction(packet, std::string(*beacon::mac::rtc_commands::kBindRemoteVideoOp))) {
    if (const auto payload = FirstSuccessfulResultPayload(response)) {
      emit_event(beacon::WriteJson(EventPacketFrom(node_id_, trace_store_.Get().lease_id,
                                                   std::string(*beacon::mac::rtc_commands::kBindRemoteVideoOp),
                                                   *payload,
                                                   beacon::CallbackExecutionResult{},
                                                   beacon::mac::RTCEventBridge::ActiveEngineIdentity{})));
    }
  }
  if (action == beacon::protocol::kInvokeRequest && PacketContainsSessionEndingOp(packet)) {
    helper_manager_.Stop();
  }
  return response;
}

std::string AgentPacketHandler::MakeCallbackEvent(const std::string& function_name,
                                                  const std::string& payload_json,
                                                  const beacon::CallbackExecutionResult& execution,
                                                  const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) const {
  return beacon::WriteJson(EventPacketFrom(node_id_, trace_store_.Get().lease_id, function_name, payload_json, execution, origin));
}

}  // namespace beacon::mac::agent_runtime
