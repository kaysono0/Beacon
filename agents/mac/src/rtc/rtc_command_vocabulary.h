#pragma once

#include <array>
#include <optional>
#include <string_view>

#include "rtc/rtc_vendor.h"
#include "rtc/rtc_vocabulary_common.h"

// 编译期 vendor 词表选择：每个变体只编译一个 vendor 的词表与后端。
// 调用点继续使用 `rtc_commands::kXxx`，与既有代码保持同一套名字。
#if defined(BEACON_MAC_RTC_VENDOR_VOLCENGINE)
#include "vendors/volcengine/rtc_vocabulary_volcengine.h"
namespace beacon::mac::rtc_commands {
using namespace volcengine;
}
#elif defined(BEACON_MAC_RTC_VENDOR_ZEGO)
#include "vendors/zego/rtc_vocabulary_zego.h"
namespace beacon::mac::rtc_commands {
using namespace zego;
}
#else
#include "vendors/agora/rtc_vocabulary_agora.h"
namespace beacon::mac::rtc_commands {
using namespace agora;
}
#endif

namespace beacon::mac::rtc_commands {

static_assert(kSdk == beacon::mac::kVendorSdk, "vocabulary sdk must match the compiled vendor");

}  // namespace beacon::mac::rtc_commands
