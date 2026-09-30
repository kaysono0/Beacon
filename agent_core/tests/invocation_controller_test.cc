#include "beacon/invocation_controller.h"
#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"

#include <iostream>
#include <stdexcept>

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
  beacon::InvocationController controller;
  controller.Init();
  const std::string ok_key = CanonicalKey("mock", "Mock", "ok");
  const std::string throw_key = CanonicalKey("mock", "Mock", "throw");
  const std::string extra_key = CanonicalKey("mock", "Mock", "extra");
  controller.RegisterInvocation(ok_key, [](const beacon::CallData& call) {
    std::string method_value = beacon::TargetKey(call);
    // Escape quotes for JSON embedding
    std::string escaped_method;
    for (char c : method_value) {
      if (c == '"') escaped_method += "\\\"";
      else escaped_method += c;
    }
    return beacon::CallResult{beacon::kOk, "ok", "{\"method\":\"" + escaped_method + "\"}"};
  });
  controller.RegisterInvocation(throw_key, [](const beacon::CallData&) -> beacon::CallResult {
    throw std::runtime_error("boom");
  });
  if (controller.RegisterInvocation("", [](const beacon::CallData&) {
        return beacon::CallResult{beacon::kOk, "ok", "{}"};
      }) != beacon::kBadRequest ||
      controller.RegisterInvocation("invalid", nullptr) != beacon::kBadRequest) {
    std::cerr << "UT-INV-09 invalid handler registration accepted\n";
    return 1;
  }

  if (!controller.HasInvocation(ok_key) || controller.HasInvocation(CanonicalKey("mock", "Mock", "missing"))) {
    std::cerr << "UT-INV-08 registered invocation introspection mismatch\n";
    return 1;
  }

  auto ok_result = controller.CallInvocation({"op-1", "mock", "Mock", "ok", "", "{}"});
  if (!ok_result.ok() ||
      ok_result.result_json.find("{\\\"class_name\\\":\\\"Mock\\\",\\\"function\\\":\\\"ok\\\",\\\"sdk\\\":\\\"mock\\\"}") == std::string::npos) {
    std::cerr << "UT-INV-01 canonical invocation key mismatch\n";
    std::cerr << "Got: " << ok_result.result_json << "\n";
    return 1;
  }
  if (controller.CallInvocation({"op-2", "mock", "Mock", "missing", "", "{}"}).error != beacon::kBadRequest) {
    std::cerr << "UT-INV-02 unknown invocation not rejected\n";
    return 1;
  }
  if (controller.CallInvocation({"op-3", "mock", "Mock", "throw", "", "{}"}).error != beacon::kInternalError) {
    std::cerr << "UT-INV-03 exception not converted\n";
    return 1;
  }
  controller.RegisterInvocation(CanonicalKey("mock", "Mock", "throwUnknown"), [](const beacon::CallData&) -> beacon::CallResult {
    throw 7;
  });
  if (controller.CallInvocation({"op-3b", "mock", "Mock", "throwUnknown", "", "{}"}).error !=
      beacon::kInternalError) {
    std::cerr << "UT-INV-03B unknown exception not converted\n";
    return 1;
  }
  auto results = controller.InvokeBatch({{"op-4", "mock", "Mock", "ok", "", "{}"}, {"op-5", "mock", "Mock", "missing", "", "{}"}});
  if (results.size() != 2 || !results[0].ok() || results[1].error != beacon::kBadRequest) {
    std::cerr << "UT-INV-04 batch aggregation failed\n";
    return 1;
  }
  if (!controller.OnInvokeRequest(R"({"common":{"action":"invokeRequest","op_id":"op-6","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"ok"},"params":"{}"}]}})").ok()) {
    std::cerr << "UT-INV-05 invoke request path failed\n";
    return 1;
  }
  controller.RegisterInvocation(extra_key, [](const beacon::CallData& call) {
    if (call.extra_json.find("cpp") == std::string::npos) {
      return beacon::CallResult{beacon::kBadRequest, "missing extra", "{}"};
    }
    return beacon::CallResult{beacon::kOk, "ok", "{}"};
  });
  if (!controller.OnInvokeRequest(R"({"common":{"action":"invokeRequest","op_id":"op-7","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"extra"},"params":"{}","extra":"{\"lang_name\":\"cpp\"}"}]}})").ok()) {
    std::cerr << "UT-INV-06 extra JSON was not preserved\n";
    return 1;
  }
  auto list_results = controller.OnInvokeRequestBatch(R"({"common":{"action":"invokeRequest","op_id":"op-8","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"ok"},"params":"{}"},{"target":{"sdk":"mock","class_name":"Mock","function":"missing"},"params":"{}"}]}})");
  if (list_results.size() != 2 || !list_results[0].ok() || list_results[1].error != beacon::kBadRequest) {
    std::cerr << "UT-INV-07 invokeRequest list was not executed in order\n";
    return 1;
  }
  if (controller.OnInvokeRequestBatch("not-json").front().error != beacon::kBadRequest ||
      controller.OnInvokeRequestBatch(R"({"common":{"action":"callbackRequest"},"data":{}})").front().error !=
          beacon::kBadRequest ||
      controller.OnInvokeRequestBatch(
                    R"({"common":{"action":"invokeRequest"},"data":{"sync":false,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"ok"},"params":"{}"}]}})")
              .front()
              .error != beacon::kBadRequest) {
    std::cerr << "UT-INV-10 invalid invokeRequest was accepted\n";
    return 1;
  }
  if (controller.OnInvokeRequest(R"({"common":{"action":"invokeRequest"},"data":{"sync":true,"list":[]}})").error !=
      beacon::kBadRequest) {
    std::cerr << "UT-INV-11 missing call was not rejected\n";
    return 1;
  }
  controller.UnregisterInvocation(ok_key);
  if (controller.HasInvocation(ok_key)) {
    std::cerr << "UT-INV-12 unregister failed\n";
    return 1;
  }
  controller.Clear();
  if (controller.size() != 0) {
    std::cerr << "UT-INV-13 clear failed\n";
    return 1;
  }
  return 0;
}
