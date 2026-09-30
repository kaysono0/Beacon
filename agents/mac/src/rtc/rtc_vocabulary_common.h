#pragma once

#include <string_view>

namespace beacon::mac::rtc_commands {

// 非 vendor 专有的平台级词表：beacon_system 时钟与通用 op 描述结构。
struct CommandSpec {
  std::string_view name;
  std::string_view params;
  std::string_view result;
};

// callback 函数名到事件目标 (interface, class) 的解析结果。
struct EventTargetSpec {
  std::string_view interface_name;
  std::string_view class_name;
};

struct EventTargetRoute {
  std::string_view function_name;
  EventTargetSpec target;
};

inline constexpr std::string_view kSystemSdk = "beacon_system";
inline constexpr std::string_view kSystemInterface = "clock";
inline constexpr std::string_view kSystemClass = "SystemClock";
inline constexpr std::string_view kWaitInMs = "waitInMs";

}  // namespace beacon::mac::rtc_commands
