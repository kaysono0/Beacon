// Generated from sdk_adapters; do not edit by hand.
#pragma once

#include <array>
#include <optional>
#include <string_view>

#include "rtc/rtc_vocabulary_common.h"

namespace beacon::mac::rtc_commands::agora::generated {

inline constexpr std::array<EventTargetRoute, 11> kEventTargetRoutes = {{
    {"onConnectionStateChanged", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onError", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onFirstRemoteVideoFrame", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onJoinChannelSuccess", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onLocalVideoStats", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onMediaPlayerStateChanged", {"media_player", "AgoraRtcMediaPlayerDelegate"}},
    {"onRemoteAudioStats", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onRemoteVideoStats", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onRtcStats", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onSnapshotRequested", {"rtc_engine", "AgoraRtcEngineDelegate"}},
    {"onSnapshotTaken", {"rtc_engine", "AgoraRtcEngineDelegate"}},
}};

inline std::optional<EventTargetSpec> ResolveEventTarget(std::string_view function_name) {
  if (function_name == "onConnectionStateChanged") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onError") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onFirstRemoteVideoFrame") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onJoinChannelSuccess") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onLocalVideoStats") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onMediaPlayerStateChanged") return EventTargetSpec{"media_player", "AgoraRtcMediaPlayerDelegate"};
  if (function_name == "onRemoteAudioStats") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onRemoteVideoStats") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onRtcStats") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onSnapshotRequested") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  if (function_name == "onSnapshotTaken") return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
  return EventTargetSpec{"rtc_engine", "AgoraRtcEngineDelegate"};
}

}  // namespace beacon::mac::rtc_commands::agora::generated
