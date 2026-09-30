#pragma once

#include <optional>
#include <string_view>

#include "generated/rtc_event_targets_zego.h"

namespace beacon::mac::rtc_commands::zego {

inline constexpr std::string_view kSdk = "zego_express";
inline constexpr std::string_view kEngineInterface = "zego_engine";
inline constexpr std::string_view kRoomInterface = "zego_room";
inline constexpr std::string_view kInterface = kRoomInterface;
inline constexpr std::string_view kPreviewInterface = "zego_preview";
inline constexpr std::string_view kPublisherInterface = "zego_publisher";
inline constexpr std::string_view kPlayerInterface = "zego_player";
inline constexpr std::string_view kVisualProbeInterface = "zego_visual_probe";
inline constexpr std::string_view kEngineClass = "ZegoExpressEngine";
inline constexpr std::string_view kRoomClass = "ZegoExpressEngine";
inline constexpr std::string_view kVisualProbeClass = "ZegoVisualProbe";
inline constexpr std::string_view kCreateEngine = "createEngineWithProfile";
inline constexpr std::string_view kDestroyEngine = "destroyEngine";
inline constexpr std::string_view kJoinRoom = "loginRoom";
inline constexpr std::string_view kLeaveRoom = "logoutRoom";
inline constexpr std::string_view kJoinChannel = kJoinRoom;
inline constexpr std::string_view kLeaveChannel = kLeaveRoom;
inline constexpr std::string_view kStartPreview = "startPreview";
inline constexpr std::string_view kStopPreview = "stopPreview";
inline constexpr std::string_view kStartSyntheticVideo = "startSyntheticVideo";
inline constexpr std::string_view kStopSyntheticVideo = "stopSyntheticVideo";
inline constexpr std::string_view kStartPublishingStream =
    "startPublishingStream";
inline constexpr std::string_view kStopPublishingStream =
    "stopPublishingStream";
inline constexpr std::string_view kStartPlayingStream = "startPlayingStream";
inline constexpr std::string_view kStopPlayingStream = "stopPlayingStream";
inline constexpr std::string_view kCaptureSnapshot = "captureSnapshot";
inline constexpr std::string_view kReleaseView = "releaseView";
inline constexpr std::string_view kBindLocalVideo = "bindLocalVideo";
inline constexpr std::string_view kBindRemoteVideo = "bindRemoteVideo";
inline constexpr std::string_view kContextProvider = "zego_express/zego_room";
inline constexpr std::string_view kJoinChannelSuccessEvent =
    "onRoomStateUpdate";

inline bool IsSessionEndingOp(std::string_view function_name) {
  return function_name == kLeaveRoom || function_name == kDestroyEngine;
}

inline constexpr std::optional<std::string_view> kBindRemoteVideoOp =
    std::nullopt;

inline std::optional<EventTargetSpec>
ResolveEventTarget(std::string_view function_name) {
  return generated::ResolveEventTarget(function_name);
}

} // namespace beacon::mac::rtc_commands::zego
