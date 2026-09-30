#pragma once

#include <string>

#include "beacon/platform_log_bridge.h"
#include "beacon/runner_kernel.h"

namespace beacon::mac {

struct PlatformLogEntry {
  std::string level = "info";
  std::string subsystem;
  std::string category;
  std::string source;
  std::string permission_state;
  std::string collector;
  std::string relative_path;
  std::string message;
  int error = 0;
};

class PlatformLogBridge {
 public:
  explicit PlatformLogBridge(beacon::RunnerKernel* kernel);
  void Bind(beacon::RunnerKernel* kernel);
  beacon::LogEvent Record(const PlatformLogEntry& entry);

 private:
  beacon::RunnerKernel* kernel_;
  beacon::PlatformLogBridge bridge_;
};

}  // namespace beacon::mac
