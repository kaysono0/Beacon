#include "beacon/platform_log_bridge.h"

#include <utility>

#include <json/json.h>

namespace beacon {

namespace {

std::string NormalizePlatformLogLevel(const std::string& level) {
  if (level == "trace" || level == "debug" || level == "info" || level == "warn" || level == "error" ||
      level == "fatal") {
    return level;
  }
  return "info";
}

}  // namespace

PlatformLogBridge::PlatformLogBridge(LogReporter* logs, std::string platform)
    : logs_(logs), platform_(std::move(platform)) {}

void PlatformLogBridge::Bind(LogReporter* logs) {
  logs_ = logs;
}

LogEvent PlatformLogBridge::Record(const PlatformLogEntry& entry) {
  if (logs_ == nullptr) {
    return {};
  }
  Json::Value extra(Json::objectValue);
  extra["platform"] = platform_;
  extra["subsystem"] = entry.subsystem;
  extra["category"] = entry.category;
  extra["source"] = entry.source;
  extra["permission_state"] = entry.permission_state;
  extra["collector"] = entry.collector;
  extra["relative_path"] = entry.relative_path;
  return logs_->Log(NormalizePlatformLogLevel(entry.level), "platform", "platform.system.log", entry.message,
                    entry.error, extra);
}

}  // namespace beacon
