#include "beacon/runner_kernel.h"
#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"

#include <iostream>
#include <json/json.h>

namespace {

bool ContainsKeyValue(const Json::Value& root, const std::string& key, const std::string& value) {
  return root.isMember(key) && root[key].asString() == value;
}

std::string CanonicalKey(const std::string& sdk, const std::string& class_name, const std::string& function_name,
                         const std::string& interface_name = "", const std::string& overload = "") {
  beacon::TargetData target;
  target.sdk = sdk;
  target.interface_name = interface_name;
  target.class_name = class_name;
  target.function_name = function_name;
  target.overload = overload;
  return beacon::TargetKey(target);
}

}  // namespace

int main() {
  beacon::RunnerKernel kernel;
  kernel.Init();
  int invocations = 0;
  std::string last_resource_ref;
  kernel.RegisterInvocation(CanonicalKey("mock", "Mock", "join"), [&](const beacon::CallData&) {
    invocations++;
    return beacon::CallResult{beacon::kOk, "joined", "{\"joined\":true}"};
  });
  kernel.RegisterInvocation(CanonicalKey("mock", "Mock", "joinWithContext"), [&](const beacon::CallData& call) {
    invocations++;
    last_resource_ref = call.resource_ref;
    return beacon::CallResult{beacon::kOk, "joined", "{\"joined\":true}"};
  });

  auto invoke_response = kernel.HandleRequest(R"({"common":{"action":"invokeRequest","op_id":"op-inv","timestamp_ms":1},"data":{"node_id":"n1","lease_id":"lease-1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params":"{}"}]}})");
  Json::Value invoke_root;
  if (!beacon::ParseJson(invoke_response, &invoke_root) ||
      !ContainsKeyValue(invoke_root["common"], "action", "invokeResponse") ||
      invoke_root["data"]["code"].asInt() != 0 ||
      invoke_root["data"]["lease_id"].asString() != "lease-1" ||
      invocations != 1) {
    std::cerr << "UT-MC-01 HandleRequest invoke path failed\n";
    std::cerr << "Got: " << invoke_response << "\n";
    return 1;
  }

  auto callback_response = kernel.HandleRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb","timestamp_ms":1},"data":{"node_id":"n1","lease_id":"lease-1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params":"{}"}]}]}})");
  Json::Value callback_root;
  if (!beacon::ParseJson(callback_response, &callback_root) ||
      !ContainsKeyValue(callback_root["common"], "action", "callbackResponse") ||
      callback_root["data"]["lease_id"].asString() != "lease-1" ||
      callback_root["data"]["code"].asInt() != 0) {
    std::cerr << "UT-CBEVT-01 HandleRequest callback install failed\n";
    std::cerr << "Got: " << callback_response << "\n";
    return 1;
  }
  beacon::CallbackEventFact event_fact;
  event_fact.node_id = "n1";
  event_fact.event_id = "evt-1";
  event_fact.event_target = beacon::EventTarget("mock", "MockDelegate", "onJoin");
  event_fact.payload_json = "{}";
  const auto event_execution = kernel.ExecuteCallback(event_fact, {});
  if (!event_execution.matched || event_execution.fact.event_id != "evt-1" || invocations != 2) {
    std::cerr << "UT-CBEVT-02 callback event path failed\n";
    return 1;
  }
  beacon::CallbackEventFact missing_fact = event_fact;
  missing_fact.event_id = "evt-missing";
  missing_fact.event_target.function_name = "onMissing";
  if (kernel.ExecuteCallback(missing_fact, {}).matched) {
    std::cerr << "UT-CBEVT-04 missing defer event evidence failed\n";
    return 1;
  }
  auto callback_context_response = kernel.HandleRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb-ctx","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoinWithContext"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"joinWithContext"},"params":"{}"}]}]}})");
  Json::Value callback_context_root;
  if (!beacon::ParseJson(callback_context_response, &callback_context_root) ||
      callback_context_root["data"]["code"].asInt() != 0) {
    std::cerr << "UT-CBEVT-05 callback context install failed\n";
    std::cerr << "Got: " << callback_context_response << "\n";
    return 1;
  }
  beacon::CallbackEventFact callback_context_fact;
  callback_context_fact.node_id = "n1";
  callback_context_fact.run_id = "run-1";
  callback_context_fact.case_id = "case-1";
  callback_context_fact.step_id = "step-1";
  callback_context_fact.event_id = "evt-ctx";
  callback_context_fact.event_target = beacon::EventTarget("mock", "MockDelegate", "onJoinWithContext");
  callback_context_fact.payload_json = R"({"uid":9})";
  callback_context_fact.timestamp_ms = 2;
  beacon::CallbackExecutionContext callback_context;
  callback_context.originating_op_id = "op-origin-join";
  callback_context.resource_ref = "engine_1";
  callback_context.instance_id = "engine_1";
  callback_context.sequence = 7;
  const auto execution = kernel.ExecuteCallback(callback_context_fact, callback_context);
  if (!execution.matched || last_resource_ref != "engine_1") {
    std::cerr << "UT-CBEVT-06 callback context ingest failed\n";
    return 1;
  }
  if (execution.fact.node_id != "n1" || execution.fact.run_id != "run-1" || execution.fact.case_id != "case-1" ||
      execution.fact.step_id != "step-1" || execution.context.originating_op_id != "op-origin-join" ||
      execution.context.resource_ref != "engine_1" || execution.context.instance_id != "engine_1" ||
      execution.context.sequence != 7) {
    std::cerr << "UT-CBEVT-07 callback context fields were parsed from the wrong location\n";
    return 1;
  }

  auto bad_response = kernel.HandleRequest(R"({"common":{"action":"invokeRequest","op_id":"op-bad"},"data":{"node_id":"n1","sync":false,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params":"{}"}]}})");
  Json::Value bad_root;
  if (!beacon::ParseJson(bad_response, &bad_root) || bad_root["data"]["code"].asInt() != 400) {
    std::cerr << "UT-MC-02 validator path did not reject bad request\n";
    std::cerr << "Got: " << bad_response << "\n";
    return 1;
  }
  auto callback_event_response = kernel.HandleRequest(R"({"common":{"action":"callbackEventRequest","op_id":"op-event-outbound","timestamp_ms":1},"data":{"node_id":"n1","event_id":"evt-1","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":{},"callback_execution":{"defer_matched":false,"defer_executed":false,"call_results":[]}}})");
  Json::Value callback_event_root;
  if (!beacon::ParseJson(callback_event_response, &callback_event_root) ||
      !ContainsKeyValue(callback_event_root["common"], "action", "callbackEventResponse") ||
      callback_event_root["data"]["code"].asInt() != beacon::kBadRequest) {
    std::cerr << "UT-MC-03 outbound callbackEventRequest was not rejected\n";
    std::cerr << "Got: " << callback_event_response << "\n";
    return 1;
  }

  kernel.Clear();
  if (kernel.invocations().size() != 0 || kernel.callbacks().size() != 0 || kernel.vault().size() != 0) {
    std::cerr << "UT-MC-05 clear did not reset runtime controllers\n";
    return 1;
  }
  return 0;
}
