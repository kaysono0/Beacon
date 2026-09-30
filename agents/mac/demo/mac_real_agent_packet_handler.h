#pragma once

#include <functional>
#include <mutex>
#include <string>
#include <vector>

#include "beacon/models.h"
#include "rtc/rtc_event_bridge.h"

namespace beacon::mac {
class PlatformAdapter;
}

namespace beacon::mac::agent_runtime {

class LoopbackHelperManager;

struct AgentTraceContext {
  std::string lease_id;
};

class TraceStore {
 public:
  void Set(const AgentTraceContext& trace);
  AgentTraceContext Get() const;

 private:
  mutable std::mutex mutex_;
  AgentTraceContext trace_;
};

using EventEmitter = std::function<void(const std::string&)>;

std::string MakeRegisterPacket(const std::string& node_id,
                               const std::string& group_id,
                               const std::vector<std::string>& tags,
                               const std::vector<std::string>& capabilities);

class AgentPacketHandler {
 public:
  AgentPacketHandler(beacon::mac::PlatformAdapter& adapter,
                     TraceStore& trace_store,
                     LoopbackHelperManager& helper_manager,
                     std::string node_id);

  std::string Handle(const std::string& packet_json, const EventEmitter& emit_event);
  std::string MakeCallbackEvent(const std::string& function_name,
                                const std::string& payload_json,
                                const beacon::CallbackExecutionResult& execution,
                                const beacon::mac::RTCEventBridge::ActiveEngineIdentity& origin) const;

 private:
  beacon::mac::PlatformAdapter& adapter_;
  TraceStore& trace_store_;
  LoopbackHelperManager& helper_manager_;
  std::string node_id_;
};

}  // namespace beacon::mac::agent_runtime
