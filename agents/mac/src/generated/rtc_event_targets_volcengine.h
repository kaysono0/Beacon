// Generated from sdk_adapters; do not edit by hand.
#pragma once

#include <array>
#include <optional>
#include <string_view>

#include "rtc/rtc_vocabulary_common.h"

namespace beacon::mac::rtc_commands::volcengine::generated {

inline constexpr std::array<EventTargetRoute, 10> kEventTargetRoutes = {{
    {"onConnectionStateChanged", {"byte_rtc_engine", "ByteRTCEngineDelegate"}},
    {"onError", {"byte_rtc_engine", "ByteRTCEngineDelegate"}},
    {"onFirstRemoteVideoFrame", {"byte_rtc_engine", "ByteRTCEngineDelegate"}},
    {"onLeaveRoom", {"byte_rtc_room", "ByteRTCRoomDelegate"}},
    {"onLocalVideoStats", {"byte_rtc_room", "ByteRTCRoomDelegate"}},
    {"onRemoteVideoStats", {"byte_rtc_room", "ByteRTCRoomDelegate"}},
    {"onRoomStateChanged", {"byte_rtc_room", "ByteRTCRoomDelegate"}},
    {"onRtcStats", {"byte_rtc_room", "ByteRTCRoomDelegate"}},
    {"onSnapshotRequested", {"byte_rtc_engine", "ByteRTCEngineDelegate"}},
    {"onSnapshotTaken", {"byte_rtc_engine", "ByteRTCEngineDelegate"}},
}};

inline std::optional<EventTargetSpec> ResolveEventTarget(std::string_view function_name) {
  if (function_name == "onConnectionStateChanged") return EventTargetSpec{"byte_rtc_engine", "ByteRTCEngineDelegate"};
  if (function_name == "onError") return EventTargetSpec{"byte_rtc_engine", "ByteRTCEngineDelegate"};
  if (function_name == "onFirstRemoteVideoFrame") return EventTargetSpec{"byte_rtc_engine", "ByteRTCEngineDelegate"};
  if (function_name == "onLeaveRoom") return EventTargetSpec{"byte_rtc_room", "ByteRTCRoomDelegate"};
  if (function_name == "onLocalVideoStats") return EventTargetSpec{"byte_rtc_room", "ByteRTCRoomDelegate"};
  if (function_name == "onRemoteVideoStats") return EventTargetSpec{"byte_rtc_room", "ByteRTCRoomDelegate"};
  if (function_name == "onRoomStateChanged") return EventTargetSpec{"byte_rtc_room", "ByteRTCRoomDelegate"};
  if (function_name == "onRtcStats") return EventTargetSpec{"byte_rtc_room", "ByteRTCRoomDelegate"};
  if (function_name == "onSnapshotRequested") return EventTargetSpec{"byte_rtc_engine", "ByteRTCEngineDelegate"};
  if (function_name == "onSnapshotTaken") return EventTargetSpec{"byte_rtc_engine", "ByteRTCEngineDelegate"};
  return std::nullopt;
}

}  // namespace beacon::mac::rtc_commands::volcengine::generated
