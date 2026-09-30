#include "beacon/callback_controller.h"

#include <algorithm>

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"

namespace beacon {

namespace {

std::string CallbackExecutionContextJson(const CallbackEventFact& fact, const CallbackExecutionContext& context) {
  Json::Value value(Json::objectValue);
  value["run_id"] = fact.run_id;
  value["case_id"] = fact.case_id;
  value["step_id"] = fact.step_id;
  value["event_id"] = fact.event_id;
  value[protocol::kTimestampMs] = Json::UInt64(fact.timestamp_ms);
  value["provider"] = context.provider;
  value[protocol::kOriginatingOpId] = context.originating_op_id;
  value["resource_ref"] = context.resource_ref;
  value["instance_id"] = context.instance_id;
  value["subscription_id"] = context.subscription_id;
  value["rule_id"] = context.rule_id;
  value["sequence"] = Json::UInt64(context.sequence);
  value[protocol::kEventTarget] = TargetToJson(fact.event_target);
  Json::Value payload;
  if (ParseJson(fact.payload_json, &payload)) {
    value[protocol::kPayload] = payload;
  } else {
    value[protocol::kPayload] = fact.payload_json;
  }
  return WriteJson(value);
}

}  // namespace

CallbackController::CallbackController(InvocationController* invocation_controller)
    : invocation_controller_(invocation_controller) {}

int CallbackController::Init() {
  return kOk;
}

void CallbackController::Clear() {
  defers_.clear();
  last_execution_result_ = {};
  last_matched_execution_result_ = {};
}

void CallbackController::BindInvocationController(InvocationController* invocation_controller) {
  invocation_controller_ = invocation_controller;
}

CallResult CallbackController::OnCallbackRequest(const std::string& packet_json) {
  Json::Value packet;
  if (!ParseJson(packet_json, &packet)) {
    return {kBadRequest, "invalid JSON", "{}"};
  }
  if (PacketAction(packet) != protocol::kCallbackRequest) {
    return {kBadRequest, "not a callbackRequest", "{}"};
  }
  const Json::Value data = PacketData(packet);
  if (data.isMember(protocol::kSync) && !data[protocol::kSync].asBool()) {
    return {kBadRequest, "sync=false is not allowed", "{}"};
  }
  const Json::Value descriptors = data[protocol::kList];
  if (!descriptors.isArray() || descriptors.empty()) {
    return {kBadRequest, "missing callback list", "{}"};
  }
  for (const auto& descriptor : descriptors) {
    const Json::Value& event_target_value = descriptor[protocol::kEventTarget];
    if (!NormalizeTargetValue(event_target_value, TargetProfile::kWireCompat).ok) {
      return {kBadRequest, "missing callback event target", "{}"};
    }
    const EventTarget event_target = EventTargetFromValue(event_target_value);

    DeferInfo info;
    info.event_target = event_target;
    info.repeat = descriptor.get(protocol::kRepeat, 1).asInt();
    if (info.repeat == 0 || info.repeat < -1) {
      return {kBadRequest, "repeat must be -1 or >= 1", "{}"};
    }
    if (!descriptor[protocol::kCallElements].isArray() || descriptor[protocol::kCallElements].empty()) {
      return {kBadRequest, "missing callback call", "{}"};
    }
    for (const auto& item : descriptor[protocol::kCallElements]) {
      info.calls.push_back(CallDataFromItem(item, PacketOpId(packet)));
    }
    defers_[TargetKey(event_target)].push_back(info);
  }
  return {kOk, "installed", "{}"};
}

CallbackExecutionResult CallbackController::OnCallback(const CallbackEventFact& fact,
                                                      const CallbackExecutionContext& context) {
  last_execution_result_ = {};
  auto it = defers_.find(TargetKey(fact.event_target));
  if (it == defers_.end()) {
    return {};
  }
  CallbackExecutionResult execution;
  execution.matched = true;
  execution.fact = fact;
  execution.context = context;
  last_matched_execution_result_ = execution;
  const std::string callback_context_json = CallbackExecutionContextJson(fact, context);
  std::vector<std::vector<CallData>> ready_calls;
  for (auto& defer : it->second) {
    std::vector<CallData> calls = defer.calls;
    for (auto& call : calls) {
      if (call.params_json.empty() || call.params_json == "{}") {
        call.params_json = fact.payload_json;
      }
      if (call.resource_ref.empty() && !context.resource_ref.empty()) {
        call.resource_ref = context.resource_ref;
      }
      call.callback_context_json = callback_context_json;
    }
    ready_calls.push_back(std::move(calls));
    if (defer.repeat > 0) {
      --defer.repeat;
    }
  }
  auto& defers = it->second;
  defers.erase(std::remove_if(defers.begin(), defers.end(), [](const DeferInfo& defer) { return defer.repeat == 0; }), defers.end());
  if (defers.empty()) {
    defers_.erase(it);
  }
  if (ready_calls.empty()) {
    return execution;
  }
  if (!invocation_controller_) {
    execution.call_results.push_back({CallData{}, {kInternalError, "invocation controller is not bound", "{}"}});
    last_matched_execution_result_ = execution;
    return execution;
  }
  for (auto& calls : ready_calls) {
    std::vector<CallResult> batch_results = invocation_controller_->InvokeBatch(calls);
    for (size_t index = 0; index < batch_results.size(); ++index) {
      execution.call_results.push_back({calls[index], batch_results[index]});
    }
  }
  last_execution_result_ = execution;
  last_matched_execution_result_ = execution;
  return execution;
}

const CallbackExecutionResult& CallbackController::last_execution_result() const {
  return last_execution_result_;
}

const CallbackExecutionResult& CallbackController::last_matched_execution_result() const {
  return last_matched_execution_result_;
}

void CallbackController::Reset() {
  defers_.clear();
  last_execution_result_ = {};
  last_matched_execution_result_ = {};
}

size_t CallbackController::size() const {
  return defers_.size();
}

}  // namespace beacon
