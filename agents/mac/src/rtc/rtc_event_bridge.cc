#include "rtc/rtc_event_bridge.h"

#include <optional>
#include <utility>

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"
#include "rtc/rtc_command_vocabulary.h"

namespace beacon::mac {
namespace {

std::string ExtraString(const beacon::CallData& call, const char* name) {
  Json::Value extra;
  if (!beacon::ParseJson(call.extra_json, &extra) || !extra.isObject()) {
    return "";
  }
  return extra.get(name, "").asString();
}

bool HasOrigin(const RTCEventBridge::ActiveEngineIdentity& identity) {
  return !identity.resource_ref.empty() || !identity.instance_id.empty() || !identity.originating_op_id.empty();
}

bool SameOperation(const RTCEventBridge::ActiveEngineIdentity& left,
                   const RTCEventBridge::ActiveEngineIdentity& right) {
  if (!left.originating_op_id.empty()) {
    return left.originating_op_id == right.originating_op_id;
  }
  return left.resource_ref == right.resource_ref && left.instance_id == right.instance_id;
}

std::string MakeLocalCallbackReceipt(const beacon::CallbackExecutionResult& execution) {
  Json::Value packet(Json::objectValue);
  packet[beacon::protocol::kCommon][beacon::protocol::kAction] = beacon::protocol::kCallbackEventResponse;
  packet[beacon::protocol::kCommon][beacon::protocol::kOpId] = "op-mac-event";
  packet[beacon::protocol::kCommon][beacon::protocol::kTimestampMs] = 0;
  packet[beacon::protocol::kData][beacon::protocol::kCode] = beacon::kOk;
  packet[beacon::protocol::kData][beacon::protocol::kMessage] = execution.matched ? "ok" : "defer missing";
  packet[beacon::protocol::kData]["event_id"] = execution.fact.event_id;
  packet[beacon::protocol::kData]["receipt"]["received"] = true;
  packet[beacon::protocol::kData]["receipt"]["recorded"] = execution.matched;
  packet[beacon::protocol::kData]["receipt"]["duplicate"] = false;
  if (execution.matched) {
    packet[beacon::protocol::kData]["receipt"]["evidence_id"] = execution.fact.event_id;
  }
  return beacon::WriteJson(packet);
}

}  // namespace
RTCEventBridge::RTCEventBridge(beacon::RunnerKernel* kernel) : kernel_(kernel) {}

void RTCEventBridge::Bind(beacon::RunnerKernel* kernel) {
  std::lock_guard<std::mutex> lock(mutex_);
  kernel_ = kernel;
}

void RTCEventBridge::SetNodeId(std::string node_id) {
  std::lock_guard<std::mutex> lock(mutex_);
  node_id_ = std::move(node_id);
}

void RTCEventBridge::Suppress(bool suppressed) {
  std::lock_guard<std::mutex> lock(mutex_);
  suppressed_ = suppressed;
}

void RTCEventBridge::SetObserver(EventObserver observer) {
  std::lock_guard<std::mutex> lock(mutex_);
  observer_ = std::move(observer);
}

void RTCEventBridge::SuppressJoinSuccessForTesting(bool suppressed) {
  std::lock_guard<std::mutex> lock(mutex_);
  suppress_join_success_for_testing_ = suppressed;
}

void RTCEventBridge::SetActiveEngineIdentity(std::string resource_ref, std::string instance_id) {
  ActiveEngineIdentity identity;
  identity.resource_ref = std::move(resource_ref);
  identity.instance_id = std::move(instance_id);
  SetActiveEngineIdentity(std::move(identity));
}

void RTCEventBridge::SetActiveEngineIdentity(ActiveEngineIdentity identity) {
  std::lock_guard<std::mutex> lock(mutex_);
  active_engine_identity_ = std::move(identity);
  sequence_ = 0;
}

void RTCEventBridge::RestoreActiveEngineIdentity(ActiveEngineIdentity identity) {
  std::lock_guard<std::mutex> lock(mutex_);
  sequence_ = identity.sequence;
  active_engine_identity_ = std::move(identity);
}

void RTCEventBridge::TrackPendingEngineIdentity(ActiveEngineIdentity identity) {
  std::lock_guard<std::mutex> lock(mutex_);
  pending_engine_identity_ = std::move(identity);
}

void RTCEventBridge::ActivatePendingEngineIdentity(const ActiveEngineIdentity& identity) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (HasOrigin(identity) && SameOperation(identity, pending_engine_identity_)) {
    active_engine_identity_ = identity;
    sequence_ = 0;
  }
}

void RTCEventBridge::CancelPendingEngineIdentity(const ActiveEngineIdentity& identity) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (HasOrigin(identity) && SameOperation(identity, pending_engine_identity_)) {
    pending_engine_identity_ = {};
  }
}

RTCEventBridge::ActiveEngineIdentity RTCEventBridge::CaptureActiveEngineIdentity(
    const beacon::CallData& call,
    std::string resource_ref,
    std::string instance_id) const {
  ActiveEngineIdentity identity;
  identity.resource_ref = std::move(resource_ref);
  identity.instance_id = std::move(instance_id);
  identity.originating_op_id = call.op_id;
  identity.run_id = ExtraString(call, beacon::protocol::kRunId);
  identity.case_id = ExtraString(call, beacon::protocol::kCaseId);
  identity.device_role = ExtraString(call, "device_role");
  identity.step_id = ExtraString(call, beacon::protocol::kStepId);
  return identity;
}

void RTCEventBridge::ClearActiveEngineIdentity() {
  std::lock_guard<std::mutex> lock(mutex_);
  active_engine_identity_ = {};
  pending_engine_identity_ = {};
  sequence_ = 0;
}

RTCEventBridge::ActiveEngineIdentity RTCEventBridge::active_engine_identity() const {
  std::lock_guard<std::mutex> lock(mutex_);
  ActiveEngineIdentity identity = active_engine_identity_;
  identity.sequence = sequence_;
  return identity;
}

std::string RTCEventBridge::Emit(const std::string& function_name, const std::string& payload_json) {
  ActiveEngineIdentity identity;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    identity = active_engine_identity_;
    if (!HasOrigin(identity) && HasOrigin(pending_engine_identity_)) {
      identity = pending_engine_identity_;
    }
  }
  return Emit(function_name, payload_json, identity);
}

std::string RTCEventBridge::Emit(const std::string& function_name,
                                 const std::string& payload_json,
                                 const ActiveEngineIdentity& origin) {
  beacon::RunnerKernel* kernel = nullptr;
  EventObserver observer;
  ActiveEngineIdentity identity;
  ActiveEngineIdentity observed_identity;
  beacon::CallbackExecutionResult execution;
  uint64_t sequence = 0;
  std::string node_id;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (suppressed_) {
      return "";
    }
    if (suppress_join_success_for_testing_ &&
        function_name == std::string(rtc_commands::kJoinChannelSuccessEvent)) {
      return "";
    }
    kernel = kernel_;
    observer = observer_;
    identity = origin;
    node_id = node_id_;
    if (kernel != nullptr && HasOrigin(identity)) {
      sequence = ++sequence_;
    }
  }
  observed_identity = identity;
  observed_identity.sequence = sequence;
  beacon::CallbackEventFact fact;
  fact.node_id = node_id;
  fact.run_id = identity.run_id;
  fact.case_id = identity.case_id;
  fact.step_id = identity.step_id;
  fact.event_id = "op-mac-event";
  fact.event_target.sdk = std::string(rtc_commands::kSdk);
  const std::optional<rtc_commands::EventTargetSpec> event_target = rtc_commands::ResolveEventTarget(function_name);
  fact.event_target.interface_name = std::string(event_target ? event_target->interface_name : "");
  fact.event_target.class_name = std::string(event_target ? event_target->class_name : "");
  fact.event_target.function_name = function_name;
  Json::Value payload(Json::objectValue);
  beacon::ParseJson(payload_json, &payload);
  if (!payload.isObject()) {
    payload = Json::Value(Json::objectValue);
  }
  fact.payload_json = beacon::WriteJson(payload);
  if (kernel != nullptr) {
    beacon::CallbackExecutionContext context;
    if (HasOrigin(identity)) {
      context.provider = std::string(rtc_commands::kContextProvider);
      context.originating_op_id = identity.originating_op_id;
      context.resource_ref = identity.resource_ref;
      context.instance_id = identity.instance_id;
      context.sequence = sequence;
    }
    execution = kernel->ExecuteCallback(fact, context);
  }
  const std::string response = kernel ? MakeLocalCallbackReceipt(execution) : "";
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (execution.matched || !has_matched_callback_) {
      last_response_ = response;
    }
    if (execution.matched) {
      has_matched_callback_ = true;
    }
  }
  if (observer) {
    observer(function_name, payload_json, execution, observed_identity);
  }
  return response;
}

std::string RTCEventBridge::last_response() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return last_response_;
}

bool RTCEventBridge::has_matched_callback() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return has_matched_callback_;
}

}  // namespace beacon::mac
