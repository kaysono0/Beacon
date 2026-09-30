#include "beacon/runner_kernel.h"

#include <memory>

#include "beacon/logging_constants.h"
#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"

namespace beacon {

namespace {

std::string EchoConnectionLease(const std::string& response_json, const Json::Value& request_data) {
  Json::Value response;
  if (!ParseJson(response_json, &response)) {
    return response_json;
  }
  for (const auto* key : {"node_id", "lease_id"}) {
    if (request_data[key].isString() && !request_data[key].asString().empty()) {
      response[protocol::kData][key] = request_data[key].asString();
    }
  }
  return WriteJson(response);
}

}  // namespace

RuntimeCleaner::RuntimeCleaner(CallbackController* callbacks, ResourceVault* vault)
    : callbacks_(callbacks), vault_(vault) {}

void RuntimeCleaner::Reset() {
  if (callbacks_) {
    callbacks_->Reset();
  }
  if (vault_) {
    vault_->Reset();
  }
}

int RunnerKernel::Init() {
  invocations_.Init();
  callbacks_.Init();
  callbacks_.BindInvocationController(&invocations_);
  logs_.Init({std::make_shared<RingBufferLogSink>(logging::kDefaultRingBufferCapacity)});
  return kOk;
}

void RunnerKernel::Clear() {
  callbacks_.Clear();
  invocations_.Clear();
  vault_.Reset();
  logs_.Clear();
}

int RunnerKernel::RegisterInvocation(const std::string& key, InvocationController::Handler handler) {
  return invocations_.RegisterInvocation(key, std::move(handler));
}

void RunnerKernel::Reset() {
  RuntimeCleaner cleaner(&callbacks_, &vault_);
  cleaner.Reset();
  logs_.ResetSession();
}

std::string RunnerKernel::HandleRequest(const std::string& command_json) {
  Json::Value packet;
  const bool parsed = ParseJson(command_json, &packet);
  if (!validator_.ValidatePacket(command_json)) {
    return MakeCallResultJson({kBadRequest, "protocol validation failed", "{}"}, protocol::kInvokeResponse,
                              parsed ? PacketOpId(packet) : "");
  }
  const std::string action = PacketAction(packet);
  const std::string op_id = PacketOpId(packet);
  const Json::Value data = PacketData(packet);
  if (action == protocol::kInvokeRequest) {
    return EchoConnectionLease(
        MakeCallResultsJson(invocations_.OnInvokeRequestBatch(command_json), protocol::kInvokeResponse, op_id), data);
  }
  if (action == protocol::kCallbackRequest) {
    return EchoConnectionLease(MakeCallResultJson(callbacks_.OnCallbackRequest(command_json), protocol::kCallbackResponse, op_id),
                               data);
  }
  if (action == protocol::kCallbackEventRequest) {
    return MakeCallResultJson({kBadRequest, "callbackEventRequest is outbound-only", "{}"},
                              protocol::kCallbackEventResponse, op_id);
  }
  return MakeCallResultJson({kBadRequest, "unsupported request action", "{}"}, action + "Response", op_id);
}

CallbackExecutionResult RunnerKernel::ExecuteCallback(const CallbackEventFact& fact,
                                                      const CallbackExecutionContext& context) {
  return callbacks_.OnCallback(fact, context);
}

InvocationController& RunnerKernel::invocations() {
  return invocations_;
}

CallbackController& RunnerKernel::callbacks() {
  return callbacks_;
}

ResourceVault& RunnerKernel::vault() {
  return vault_;
}

LogReporter& RunnerKernel::logs() {
  return logs_;
}

}  // namespace beacon
