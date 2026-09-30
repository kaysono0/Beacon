#pragma once

#include <array>
#include <optional>
#include <string_view>

#include "rtc/rtc_vocabulary_common.h"
#include "generated/rtc_event_targets_agora.h"

namespace beacon::mac::rtc_commands::agora {

inline constexpr std::string_view kSdk = "agora_rtc";
inline constexpr std::string_view kInterface = "rtc_engine";
inline constexpr std::string_view kPreviewInterface = "video_preview";
inline constexpr std::string_view kMediaPlayerInterface = "media_player";
inline constexpr std::string_view kVisualProbeInterface = "visual_probe";
inline constexpr std::string_view kLifecycleClass = "SDKLifecycle";
inline constexpr std::string_view kEngineClass = "AgoraRtcEngineKit";
inline constexpr std::string_view kVisualProbeClass = "AgoraVisualProbe";
inline constexpr std::string_view kMediaPlayerClass = "AgoraRtcMediaPlayerProtocol";
inline constexpr std::string_view kDelegateClass = "AgoraRtcEngineDelegate";

inline constexpr std::string_view kInit = "loadSDK";
inline constexpr std::string_view kDestroy = "unloadSDK";
inline constexpr std::string_view kJoinChannel = "joinChannel";
inline constexpr std::string_view kLeaveChannel = "leaveChannel";
inline constexpr std::string_view kRenewToken = "renewToken";
inline constexpr std::string_view kBindLocalVideo = "bindLocalVideo";
inline constexpr std::string_view kBindRemoteVideo = "bindRemoteVideo";
inline constexpr std::string_view kCaptureSnapshot = "captureSnapshot";
inline constexpr std::string_view kReleaseView = "releaseView";
inline constexpr std::string_view kStartPreview = "startPreview";
inline constexpr std::string_view kStopPreview = "stopPreview";
inline constexpr std::string_view kEnableLocalAudio = "enableLocalAudio";
inline constexpr std::string_view kEnableLocalVideo = "enableLocalVideo";
inline constexpr std::string_view kGetConnectionState = "getConnectionState";
inline constexpr std::string_view kGetLastMileStats = "getLastMileStats";
inline constexpr std::string_view kIsJoined = "isJoined";
inline constexpr std::string_view kIsPreviewing = "isPreviewing";
inline constexpr std::string_view kStartSyntheticVideo = "startSyntheticVideo";
inline constexpr std::string_view kStopSyntheticVideo = "stopSyntheticVideo";
inline constexpr std::string_view kSetDualStreamMode = "setDualStreamMode";
inline constexpr std::string_view kSetRemoteVideoStream = "setRemoteVideoStream";
inline constexpr std::string_view kOpenMediaPlayer = "openMediaPlayer";
inline constexpr std::string_view kPlayMediaPlayer = "playMediaPlayer";
inline constexpr std::string_view kPauseMediaPlayer = "pauseMediaPlayer";
inline constexpr std::string_view kResumeMediaPlayer = "resumeMediaPlayer";
inline constexpr std::string_view kStopMediaPlayer = "stopMediaPlayer";

inline constexpr std::string_view kContextProvider = "agora_rtc/rtc_engine";
inline constexpr std::string_view kJoinChannelSuccessEvent = "onJoinChannelSuccess";

inline constexpr std::string_view kLifecyclePrefix = "agora_rtc.SDKLifecycle.";
inline constexpr std::string_view kEnginePrefix = "agora_rtc.AgoraRtcEngineKit.";
inline constexpr std::string_view kDelegatePrefix = "agora_rtc.AgoraRtcEngineDelegate.";
inline constexpr std::string_view kSystemPrefix = "beacon_system.SystemClock.";

inline constexpr std::array<std::string_view, 26> kCommandNames = {
    kInit,
    kDestroy,
    kJoinChannel,
    kLeaveChannel,
    kRenewToken,
    kBindLocalVideo,
    kBindRemoteVideo,
    kCaptureSnapshot,
    kReleaseView,
    kStartPreview,
    kStopPreview,
    kEnableLocalAudio,
    kEnableLocalVideo,
    kGetConnectionState,
    kGetLastMileStats,
    kIsJoined,
    kIsPreviewing,
    kStartSyntheticVideo,
    kStopSyntheticVideo,
    kSetDualStreamMode,
    kSetRemoteVideoStream,
    kOpenMediaPlayer,
    kPlayMediaPlayer,
    kPauseMediaPlayer,
    kResumeMediaPlayer,
    kStopMediaPlayer,
};

inline constexpr std::array<CommandSpec, 26> kCommandSpecs = {{
    {kInit, "AgoraConfig subset", "{\"initialized\":true}"},
    {kDestroy, "{}", "{\"destroyed\":true}"},
    {kJoinChannel, "channel, uid, token", "{\"joined\":true}"},
    {kLeaveChannel, "{}", "{\"left\":true}"},
    {kRenewToken, "token", "{\"renewed\":true}"},
    {kBindLocalVideo, "view_role", "{\"configured\":true,\"view_id\":\"primary_local_preview\"}"},
    {kBindRemoteVideo, "uid, view_role", "{\"configured\":true,\"view_id\":\"primary_remote_view\",\"uid\":1002}"},
    {kCaptureSnapshot, "view_role", "{\"snapshot_requested\":true,\"view_role\":\"primary_remote_view\"}"},
    {kReleaseView, "view_role", "{\"released\":true,\"view_role\":\"primary_remote_view\"}"},
    {kStartPreview, "view_id", "{\"previewing\":true}"},
    {kStopPreview, "{}", "{\"previewing\":false}"},
    {kEnableLocalAudio, "enabled", "{\"audio\":true}"},
    {kEnableLocalVideo, "enabled", "{\"video\":true}"},
    {kGetConnectionState, "{}", "{\"state\":\"connected|idle\"}"},
    {kGetLastMileStats, "{}", "{\"available\":false}"},
    {kIsJoined, "{}", "true|false"},
    {kIsPreviewing, "{}", "true|false"},
    {kStartSyntheticVideo, "width, height, fps, pattern", "{\"started\":true}"},
    {kStopSyntheticVideo, "{}", "{\"stopped\":true}"},
    {kSetDualStreamMode, "mode, low_width, low_height, low_bitrate, low_fps", "{\"mode\":\"enabled\"}"},
    {kSetRemoteVideoStream, "uid, stream_type", "{\"uid\":1002,\"stream_type\":\"low\"}"},
    {kOpenMediaPlayer, "source_path", "{\"opened\":true,\"player_id\":1}"},
    {kPlayMediaPlayer, "{}", "{\"playing\":true}"},
    {kPauseMediaPlayer, "{}", "{\"paused\":true}"},
    {kResumeMediaPlayer, "{}", "{\"playing\":true}"},
    {kStopMediaPlayer, "{}", "{\"stopped\":true}"},
}};

// callback 路由由 Adapter Source 生成；未知函数仍按已有合同落到 Agora delegate。
inline std::optional<EventTargetSpec> ResolveEventTarget(std::string_view function_name) {
  return generated::ResolveEventTarget(function_name);
}

// demo 层需要的词表查询：会话结束 op 与「绑定远端视频」op（火山没有等价物）。
inline bool IsSessionEndingOp(std::string_view function_name) {
  return function_name == kLeaveChannel || function_name == kDestroy;
}

inline constexpr std::optional<std::string_view> kBindRemoteVideoOp = kBindRemoteVideo;

}  // namespace beacon::mac::rtc_commands::agora
