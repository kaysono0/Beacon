#include "beacon/callback_controller.h"
#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"

#include <iostream>

namespace {

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
  auto make_fact = [](const beacon::EventTarget& event_target, const std::string& payload_json) {
    beacon::CallbackEventFact fact;
    fact.event_target = event_target;
    fact.payload_json = payload_json;
    return fact;
  };
  const beacon::CallbackExecutionContext empty_context;
  beacon::InvocationController invocations;
  int calls = 0;
  std::string last_resource_ref;
  invocations.RegisterInvocation(CanonicalKey("mock", "Mock", "onJoin"), [&](const beacon::CallData& call) {
    calls++;
    last_resource_ref = call.resource_ref;
    return beacon::CallResult{beacon::kOk, "ok", "{\"called\":true}"};
  });
  beacon::CallbackController callbacks(&invocations);
  callbacks.Init();
  beacon::EventTarget join_event{"mock", "MockDelegate", "join"};
  beacon::EventTarget persistent_event{"mock", "MockDelegate", "persistent"};
  beacon::EventTarget a_event{"mock", "MockDelegate", "a"};
  beacon::EventTarget b_event{"mock", "MockDelegate", "b"};

  const std::string first = R"({"common":{"action":"callbackRequest","op_id":"op-cb","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"join"},"repeat":2,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"resource_ref":"engine_1","params":"{}"}]}]}})";
  if (!callbacks.OnCallbackRequest(first).ok() || callbacks.size() != 1) {
    std::cerr << "UT-CB-01 install failed\n";
    return 1;
  }
  if (callbacks.OnCallbackRequest("not-json").error != beacon::kBadRequest ||
      callbacks.OnCallbackRequest(R"({"common":{"action":"invokeRequest"},"data":{}})").error !=
          beacon::kBadRequest ||
      callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest"},"data":{"sync":false,"list":[]}})")
              .error != beacon::kBadRequest ||
      callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest"},"data":{"sync":true}})").error !=
          beacon::kBadRequest ||
      callbacks.OnCallbackRequest(
                   R"({"common":{"action":"callbackRequest"},"data":{"sync":true,"list":[{"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}]}})")
              .error != beacon::kBadRequest ||
      callbacks.OnCallbackRequest(
                   R"({"common":{"action":"callbackRequest"},"data":{"sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"invalid"},"repeat":0,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}]}})")
              .error != beacon::kBadRequest ||
      callbacks.OnCallbackRequest(
                   R"({"common":{"action":"callbackRequest"},"data":{"sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"invalid"},"repeat":-2,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}]}})")
              .error != beacon::kBadRequest ||
      callbacks.OnCallbackRequest(
                   R"({"common":{"action":"callbackRequest"},"data":{"sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"invalid"},"repeat":1,"call_elements":[]}]}})")
              .error != beacon::kBadRequest) {
    std::cerr << "UT-CB-10 invalid callbackRequest was accepted\n";
    return 1;
  }
  callbacks.OnCallback(make_fact(join_event, "{\"uid\":1}"), empty_context);
  if (calls != 1 || callbacks.size() != 1 || last_resource_ref != "engine_1") {
    std::cerr << "UT-CB-02 repeat=2 first execution failed\n";
    return 1;
  }
  callbacks.OnCallback(make_fact(join_event, "{\"uid\":1}"), empty_context);
  if (calls != 2 || callbacks.size() != 0) {
    std::cerr << "UT-CB-03 repeat cleanup failed\n";
    return 1;
  }

  callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb2","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"join"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}]}})");
  callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb3","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"join"},"repeat":3,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}]}})");
  if (callbacks.size() != 1) {
    std::cerr << "UT-CB-04 overwrite failed\n";
    return 1;
  }
  callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb4","timestamp_ms":1},"data":{"node_id":"n1","list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"persistent"},"repeat":-1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}],"sync":true}})");
  callbacks.OnCallback(make_fact(persistent_event, "{\"uid\":1}"), empty_context);
  callbacks.OnCallback(make_fact(persistent_event, "{\"uid\":2}"), empty_context);
  if (calls != 4 || callbacks.size() != 2) {
    std::cerr << "UT-CB-05 repeat=-1 persistent defer failed\n";
    return 1;
  }
  beacon::InvocationController multi_invocations;
  int multi_calls = 0;
  multi_invocations.RegisterInvocation(CanonicalKey("mock", "Mock", "onJoinOne"), [&](const beacon::CallData&) {
    multi_calls++;
    return beacon::CallResult{beacon::kOk, "ok", "{\"called\":1}"};
  });
  multi_invocations.RegisterInvocation(CanonicalKey("mock", "Mock", "onJoinTwo"), [&](const beacon::CallData&) {
    multi_calls++;
    return beacon::CallResult{beacon::kOk, "ok", "{\"called\":2}"};
  });
  beacon::CallbackController multi_callbacks(&multi_invocations);
  multi_callbacks.Init();
  if (!multi_callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb6","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"join"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoinOne"},"params":"{}"},{"target":{"sdk":"mock","class_name":"Mock","function":"onJoinTwo"},"params":"{}"}]}]}})").ok() || multi_callbacks.size() != 1) {
    std::cerr << "UT-CB-06 nested call_elements install failed\n";
    return 1;
  }
  multi_callbacks.OnCallback(make_fact(join_event, "{\"uid\":9}"), empty_context);
  if (multi_calls != 2 || multi_callbacks.size() != 0) {
    std::cerr << "UT-CB-07 nested call_elements execute failed\n";
    return 1;
  }
  beacon::CallbackController context_callbacks(&invocations);
  context_callbacks.Init();
  if (!context_callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb-ctx","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"join"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}]}})").ok() ||
      context_callbacks.size() != 1) {
    std::cerr << "UT-CB-CTX-00 install failed\n";
    return 1;
  }
  beacon::CallbackEventFact fact;
  fact.event_id = "evt-1";
  fact.event_target = join_event;
  fact.payload_json = "{\"uid\":9}";
  fact.timestamp_ms = 1;
  beacon::CallbackExecutionContext context;
  context.resource_ref = "engine_1";
  context.instance_id = "engine_1";
  context.sequence = 7;
  const auto execution = context_callbacks.OnCallback(fact, context);
  if (!execution.matched || execution.call_results.size() != 1 ||
      execution.call_results[0].call.resource_ref != "engine_1" ||
      execution.context.resource_ref != "engine_1" ||
      execution.context.instance_id != "engine_1" ||
      execution.context.sequence != 7) {
    std::cerr << "UT-CB-CTX-01 callback context was not preserved\n";
    return 1;
  }
  beacon::InvocationController rich_context_invocations;
  int rich_context_calls = 0;
  rich_context_invocations.RegisterInvocation(CanonicalKey("mock", "Mock", "onJoinWithContext"), [&](const beacon::CallData& call) {
    Json::Value callback_context_json;
    if (!beacon::ParseJson(call.callback_context_json, &callback_context_json) ||
        callback_context_json["event_id"].asString() != "evt-ctx-2" ||
        callback_context_json["run_id"].asString() != "run-9" ||
        callback_context_json["case_id"].asString() != "case-9" ||
        callback_context_json["step_id"].asString() != "step-9" ||
        callback_context_json["event_target"]["function"].asString() != "join" ||
        callback_context_json["payload"]["uid"].asInt() != 42 ||
        callback_context_json["provider"].asString() != "agora_rtc/rtc_engine" ||
        callback_context_json["resource_ref"].asString() != "engine_ctx" ||
        callback_context_json["instance_id"].asString() != "engine_ctx" ||
        callback_context_json["sequence"].asUInt64() != 11) {
      return beacon::CallResult{beacon::kBadRequest, "missing callback execution context", "{}"};
    }
    rich_context_calls++;
    return beacon::CallResult{beacon::kOk, "ok", "{\"context\":true}"};
  });
  beacon::CallbackController rich_context_callbacks(&rich_context_invocations);
  rich_context_callbacks.Init();
  if (!rich_context_callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb-ctx-2","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"join"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoinWithContext"},"params":"{}"}]}]}})").ok() ||
      rich_context_callbacks.size() != 1) {
    std::cerr << "UT-CB-CTX-02 install failed\n";
    return 1;
  }
  beacon::CallbackEventFact rich_fact;
  rich_fact.run_id = "run-9";
  rich_fact.case_id = "case-9";
  rich_fact.step_id = "step-9";
  rich_fact.event_id = "evt-ctx-2";
  rich_fact.event_target = join_event;
  rich_fact.payload_json = "{\"uid\":42}";
  rich_fact.timestamp_ms = 2;
  beacon::CallbackExecutionContext rich_context;
  rich_context.provider = "agora_rtc/rtc_engine";
  rich_context.resource_ref = "engine_ctx";
  rich_context.instance_id = "engine_ctx";
  rich_context.sequence = 11;
  const auto rich_execution = rich_context_callbacks.OnCallback(rich_fact, rich_context);
  if (!rich_execution.matched || rich_context_calls != 1 || rich_execution.call_results.size() != 1 ||
      rich_execution.call_results[0].result.error != beacon::kOk ||
      rich_execution.call_results[0].call.callback_context_json.empty() ||
      rich_execution.call_results[0].call.callback_context_json == "{}") {
    std::cerr << "UT-CB-CTX-03 execution context was not delivered to invocation handler\n";
    return 1;
  }
  beacon::CallbackController unbound_callbacks(nullptr);
  unbound_callbacks.Init();
  if (!unbound_callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-unbound","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"join"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}]}})").ok()) {
    std::cerr << "UT-CB-11 unbound install failed\n";
    return 1;
  }
  const auto unbound_execution = unbound_callbacks.OnCallback(make_fact(join_event, "payload-as-text"), empty_context);
  if (!unbound_execution.matched || unbound_execution.call_results.size() != 1 ||
      unbound_execution.call_results[0].result.error != beacon::kInternalError ||
      !unbound_callbacks.last_matched_execution_result().matched) {
    std::cerr << "UT-CB-11 unbound invocation controller was not surfaced\n";
    return 1;
  }
  unbound_callbacks.Clear();
  if (unbound_callbacks.size() != 0 || unbound_callbacks.last_matched_execution_result().matched) {
    std::cerr << "UT-CB-12 clear did not reset execution state\n";
    return 1;
  }
  callbacks.OnCallbackRequest(R"({"common":{"action":"callbackRequest","op_id":"op-cb5","timestamp_ms":1},"data":{"node_id":"n1","list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"a"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]},{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"b"},"repeat":1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"onJoin"},"params":"{}"}]}],"sync":true}})");
  callbacks.OnCallback(make_fact(a_event, "{}"), empty_context);
  callbacks.OnCallback(make_fact(b_event, "{}"), empty_context);
  if (calls != 7 || callbacks.size() != 2) {
    std::cerr << "UT-CB-08 multiple defer install failed\n";
    return 1;
  }
  callbacks.Reset();
  if (callbacks.size() != 0) {
    std::cerr << "UT-CB-09 reset failed\n";
    return 1;
  }
  return 0;
}
