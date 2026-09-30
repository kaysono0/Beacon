#include "platform/platform_log_bridge.h"

namespace beacon::mac {

PlatformLogBridge::PlatformLogBridge(beacon::RunnerKernel* kernel)
    : kernel_(kernel), bridge_(kernel == nullptr ? nullptr : &kernel->logs(), "mac") {}

void PlatformLogBridge::Bind(beacon::RunnerKernel* kernel) {
  kernel_ = kernel;
  bridge_.Bind(kernel == nullptr ? nullptr : &kernel->logs());
}

beacon::LogEvent PlatformLogBridge::Record(const PlatformLogEntry& entry) {
  if (kernel_ == nullptr) {
    return {};
  }
  return bridge_.Record(beacon::PlatformLogEntry{
      .level = entry.level,
      .subsystem = entry.subsystem,
      .category = entry.category,
      .source = entry.source,
      .permission_state = entry.permission_state,
      .collector = entry.collector,
      .relative_path = entry.relative_path,
      .message = entry.message,
      .error = entry.error,
  });
}

}  // namespace beacon::mac
