#pragma once

#include <string>

#include "beacon/logging.h"
#include "beacon/models.h"

namespace beacon {

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

// 平台系统日志桥接基座。各平台 adapter 只负责采集，统一通过这里规范化为 LogEvent。
class PlatformLogBridge {
 public:
  PlatformLogBridge(LogReporter* logs, std::string platform);
  void Bind(LogReporter* logs);
  LogEvent Record(const PlatformLogEntry& entry);

 private:
  LogReporter* logs_;
  std::string platform_;
};

}  // namespace beacon
