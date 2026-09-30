#pragma once

#include <string_view>

namespace beacon::mac {

// 编译期 vendor 选择：CMake 每个变体只编译一个 vendor 的词表、loader 与后端，
// 不做单二进制内的运行期切换（两家媒体栈不进同一进程）。
// 默认（未定义任何 vendor 宏）为 agora，保持既有 mock/默认构建行为不变。
#if defined(BEACON_MAC_RTC_VENDOR_VOLCENGINE)
inline constexpr std::string_view kVendorName = "volcengine";
inline constexpr std::string_view kVendorSdk = "volcengine_rtc";
#elif defined(BEACON_MAC_RTC_VENDOR_ZEGO)
inline constexpr std::string_view kVendorName = "zego";
inline constexpr std::string_view kVendorSdk = "zego_express";
#else
inline constexpr std::string_view kVendorName = "agora";
inline constexpr std::string_view kVendorSdk = "agora_rtc";
#endif

}  // namespace beacon::mac
