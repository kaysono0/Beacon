#pragma once

#include <array>
#include <optional>
#include <string_view>

#include "rtc/rtc_vocabulary_common.h"
#include "generated/rtc_event_targets_volcengine.h"

namespace beacon::mac::rtc_commands::volcengine {

// 火山按自身对象模型分引擎级与房间级 interface，不与 Agora 命名对齐。
inline constexpr std::string_view kSdk = "volcengine_rtc";
inline constexpr std::string_view kEngineInterface = "byte_rtc_engine";
inline constexpr std::string_view kRoomInterface = "byte_rtc_room";
inline constexpr std::string_view kVisualProbeInterface = "visual_probe";
inline constexpr std::string_view kEngineClass = "ByteRTCEngine";
inline constexpr std::string_view kRoomClass = "ByteRTCRoom";
inline constexpr std::string_view kVisualProbeClass = "ByteRTCVisualProbe";
inline constexpr std::string_view kEngineDelegateClass = "ByteRTCEngineDelegate";
inline constexpr std::string_view kRoomDelegateClass = "ByteRTCRoomDelegate";

inline constexpr std::string_view kCreateEngine = "createRTCEngine";
inline constexpr std::string_view kDestroyEngine = "destroyRTCEngine";
inline constexpr std::string_view kJoinRoom = "joinRoom";
inline constexpr std::string_view kLeaveRoom = "leaveRoom";

// 画面能力面：采集开关保留火山原生名（本地采集等价预览控制）；合成源与探针 op 是桥层
// 意图名（ADR-031：canvas/快照原生调用只是实现细节，不成为作者层 op）。
inline constexpr std::string_view kStartVideoCapture = "startVideoCapture";
inline constexpr std::string_view kStopVideoCapture = "stopVideoCapture";
inline constexpr std::string_view kStartSyntheticVideo = "startSyntheticVideo";
inline constexpr std::string_view kStopSyntheticVideo = "stopSyntheticVideo";
inline constexpr std::string_view kBindLocalVideo = "bindLocalVideo";
inline constexpr std::string_view kBindRemoteVideo = "bindRemoteVideo";
inline constexpr std::string_view kCaptureSnapshot = "captureSnapshot";
inline constexpr std::string_view kReleaseView = "releaseView";

// 加入成功证据：房间态回调 state == 0（火山没有 isJoined 等价查询）。
inline constexpr std::string_view kContextProvider = "volcengine_rtc/byte_rtc_room";
inline constexpr std::string_view kJoinChannelSuccessEvent = "onRoomStateChanged";
inline constexpr std::string_view kLeaveRoomEvent = "onLeaveRoom";
inline constexpr std::string_view kConnectionStateChangedEvent = "onConnectionStateChanged";
inline constexpr std::string_view kErrorEvent = "onError";

// 画面证据事件：公开词汇由 B-009 标准拥有，payload 里带原生函数名与 stream_id 以便溯源。
inline constexpr std::string_view kSnapshotRequestedEvent = "onSnapshotRequested";
inline constexpr std::string_view kSnapshotTakenEvent = "onSnapshotTaken";
inline constexpr std::string_view kFirstRemoteVideoFrameEvent = "onFirstRemoteVideoFrame";
inline constexpr std::string_view kLocalVideoStatsEvent = "onLocalVideoStats";
inline constexpr std::string_view kRemoteVideoStatsEvent = "onRemoteVideoStats";
inline constexpr std::string_view kRtcStatsEvent = "onRtcStats";

inline constexpr std::string_view kEnginePrefix = "volcengine_rtc.ByteRTCEngine.";
inline constexpr std::string_view kRoomPrefix = "volcengine_rtc.ByteRTCRoom.";
inline constexpr std::string_view kVisualProbePrefix = "volcengine_rtc.ByteRTCVisualProbe.";
inline constexpr std::string_view kSystemPrefix = "beacon_system.SystemClock.";

inline constexpr std::array<std::string_view, 12> kCommandNames = {
    kCreateEngine,
    kDestroyEngine,
    kJoinRoom,
    kLeaveRoom,
    kStartVideoCapture,
    kStopVideoCapture,
    kStartSyntheticVideo,
    kStopSyntheticVideo,
    kBindLocalVideo,
    kBindRemoteVideo,
    kCaptureSnapshot,
    kReleaseView,
};

inline constexpr std::array<CommandSpec, 12> kCommandSpecs = {{
    {kCreateEngine, "app_id", "{\"created\":true}"},
    {kDestroyEngine, "{}", "{\"destroyed\":true}"},
    {kJoinRoom, "room_id, user_id, token", "{\"joined\":true}"},
    {kLeaveRoom, "{}", "{\"left\":true}"},
    {kStartVideoCapture, "{}", "{\"capturing\":true}"},
    {kStopVideoCapture, "{}", "{\"capturing\":false}"},
    {kStartSyntheticVideo, "width, height, fps, pattern", "{\"started\":true}"},
    {kStopSyntheticVideo, "{}", "{\"stopped\":true}"},
    {kBindLocalVideo, "view_role", "{\"configured\":true,\"view_id\":\"primary_local_preview\"}"},
    {kBindRemoteVideo, "uid, view_role", "{\"configured\":true,\"view_id\":\"primary_remote_view\",\"uid\":\"peer-user\"}"},
    {kCaptureSnapshot, "view_role", "{\"snapshot_requested\":true,\"view_role\":\"primary_remote_view\"}"},
    {kReleaseView, "view_role", "{\"released\":true,\"view_role\":\"primary_remote_view\"}"},
}};

// 事件目标按 Adapter Source 声明生成。
inline std::optional<EventTargetSpec> ResolveEventTarget(std::string_view function_name) {
  return generated::ResolveEventTarget(function_name);
}

// demo 层需要的词表查询：会话结束 op 与「绑定远端视频」op（远端绑定证据靠它进入报告）。
inline bool IsSessionEndingOp(std::string_view function_name) {
  return function_name == kLeaveRoom || function_name == kDestroyEngine;
}

inline constexpr std::optional<std::string_view> kBindRemoteVideoOp = kBindRemoteVideo;

}  // namespace beacon::mac::rtc_commands::volcengine
