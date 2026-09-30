#include "beacon/invocation_controller.h"

#include <exception>

#include "beacon/protocol_constants.h"
#include "beacon/protocol_json.h"

namespace beacon {

int InvocationController::Init() {
  return kOk;
}

void InvocationController::Clear() {
  handlers_.clear();
}

int InvocationController::RegisterInvocation(const std::string& key, Handler handler) {
  if (key.empty() || !handler) {
    return kBadRequest;
  }
  handlers_[key] = std::move(handler);
  return kOk;
}

void InvocationController::UnregisterInvocation(const std::string& key) {
  handlers_.erase(key);
}

CallResult InvocationController::CallInvocation(const CallData& info) const {
  auto it = handlers_.find(TargetKey(info));
  if (it == handlers_.end()) {
    return {kBadRequest, "unknown invocation", "{}"};
  }
  try {
    return it->second(info);
  } catch (const std::exception& exc) {
    return {kInternalError, exc.what(), "{}"};
  } catch (...) {
    return {kInternalError, "unknown invocation exception", "{}"};
  }
}

std::vector<CallResult> InvocationController::InvokeBatch(const std::vector<CallData>& calls) const {
  std::vector<CallResult> results;
  for (const auto& call : calls) {
    results.push_back(CallInvocation(call));
  }
  return results;
}

std::vector<CallResult> InvocationController::OnInvokeRequestBatch(const std::string& packet_json) const {
  Json::Value packet;
  if (!ParseJson(packet_json, &packet)) {
    return {{kBadRequest, "invalid JSON", "{}"}};
  }
  if (PacketAction(packet) != protocol::kInvokeRequest) {
    return {{kBadRequest, "not an invokeRequest", "{}"}};
  }
  const Json::Value data = PacketData(packet);
  if (data.isMember(protocol::kSync) && !data[protocol::kSync].asBool()) {
    return {{kBadRequest, "sync=false is not allowed", "{}"}};
  }
  return InvokeBatch(CallDataListFromPacket(packet));
}

CallResult InvocationController::OnInvokeRequest(const std::string& packet_json) const {
  const auto results = OnInvokeRequestBatch(packet_json);
  return results.empty() ? CallResult{kBadRequest, "missing call", "{}"} : results.front();
}

bool InvocationController::HasInvocation(const std::string& key) const {
  return handlers_.find(key) != handlers_.end();
}

size_t InvocationController::size() const {
  return handlers_.size();
}

}  // namespace beacon
