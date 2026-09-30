// Generated from sdk_adapters; do not edit by hand.
#pragma once

#include <array>
#include <optional>
#include <string_view>

#include "rtc/rtc_vocabulary_common.h"

namespace beacon::mac::rtc_commands::zego::generated {

inline constexpr std::array<EventTargetRoute, 5> kEventTargetRoutes = {{
    {"onPlayerRenderVideoFirstFrame", {"zego_player", "ZegoEventHandler"}},
    {"onPlayerStateUpdate", {"zego_player", "ZegoEventHandler"}},
    {"onPublisherStateUpdate", {"zego_publisher", "ZegoEventHandler"}},
    {"onRenderedViewSnapshot", {"zego_visual_probe", "BeaconZegoVisualProbe"}},
    {"onRoomStateUpdate", {"zego_room", "ZegoEventHandler"}},
}};

inline std::optional<EventTargetSpec> ResolveEventTarget(std::string_view function_name) {
  if (function_name == "onPlayerRenderVideoFirstFrame") return EventTargetSpec{"zego_player", "ZegoEventHandler"};
  if (function_name == "onPlayerStateUpdate") return EventTargetSpec{"zego_player", "ZegoEventHandler"};
  if (function_name == "onPublisherStateUpdate") return EventTargetSpec{"zego_publisher", "ZegoEventHandler"};
  if (function_name == "onRenderedViewSnapshot") return EventTargetSpec{"zego_visual_probe", "BeaconZegoVisualProbe"};
  if (function_name == "onRoomStateUpdate") return EventTargetSpec{"zego_room", "ZegoEventHandler"};
  return EventTargetSpec{"zego_room", "ZegoEventHandler"};
}

}  // namespace beacon::mac::rtc_commands::zego::generated
