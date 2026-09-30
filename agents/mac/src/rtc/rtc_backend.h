#pragma once

#include <functional>
#include <memory>
#include <string>

#include "beacon/models.h"
#include "rtc/sdk_loader.h"

namespace beacon::mac {

class RTCEventBridge;
class ViewRegistry;

inline constexpr int kPermissionDenied = 402;

inline beacon::CallResult UnsupportedCapability() {
  return {beacon::kBadRequest, "capability not declared for this vendor", "{}"};
}

class RTCBackend {
public:
  virtual ~RTCBackend() = default;
  virtual int Load() = 0;
  virtual int Unload() = 0;
  virtual beacon::CallResult EnableLocalAudio(bool) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult EnableLocalVideo(bool) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult JoinChannel(const beacon::CallData &call) = 0;
  virtual beacon::CallResult LeaveChannel() = 0;
  // 可选重载：需要把「本次调用期间产生的回调事件」归因到该调用的后端可覆盖它（默认忽略
  // call）。
  virtual beacon::CallResult LeaveChannel(const beacon::CallData &) {
    return LeaveChannel();
  }
  virtual beacon::CallResult RenewToken(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult BindLocalVideo(const beacon::CallData &call) = 0;
  virtual beacon::CallResult BindRemoteVideo(const beacon::CallData &call) = 0;
  virtual beacon::CallResult CaptureSnapshot(const beacon::CallData &call) = 0;
  virtual beacon::CallResult ReleaseView(const beacon::CallData &call) = 0;
  virtual beacon::CallResult StartPreview(const beacon::CallData &call) = 0;
  virtual beacon::CallResult StopPreview() = 0;
  virtual beacon::CallResult
  StartSyntheticVideo(const beacon::CallData &call) = 0;
  virtual beacon::CallResult StopSyntheticVideo() = 0;
  // Agora 原生双流控制：发布端配置低层，订阅端选择实际接收的高/低层。
  virtual beacon::CallResult SetDualStreamMode(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult SetRemoteVideoStream(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  // Agora MediaPlayer 是 SDK 自身的文件解码与发布链路；不与其他 vendor 的采集源混用。
  virtual beacon::CallResult OpenMediaPlayer(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult PlayMediaPlayer(const beacon::CallData&) { return UnsupportedCapability(); }
  virtual beacon::CallResult PauseMediaPlayer(const beacon::CallData&) { return UnsupportedCapability(); }
  virtual beacon::CallResult ResumeMediaPlayer(const beacon::CallData&) { return UnsupportedCapability(); }
  virtual beacon::CallResult StopMediaPlayer() { return UnsupportedCapability(); }
  // ZEGO 的推流/拉流是流级生命周期；其他 vendor 无需声明同名能力。
  virtual beacon::CallResult StartPublishingStream(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult StopPublishingStream() {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult StartPlayingStream(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult StopPlayingStream(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  virtual beacon::CallResult GetConnectionState(const beacon::CallData &) {
    return UnsupportedCapability();
  }
  // 可选钩子：把「该调用期间产生的回调事件」归因到本次调用的 run/case/step。
  // 需要这样做的后端覆盖它；默认无操作。
  virtual void AttributeCallbacksTo(const beacon::CallData &) {}
  virtual void Reset() = 0;
  virtual bool initialized() const = 0;
  virtual bool joined() const = 0;
  virtual bool previewing() const = 0;
  virtual std::string channel() const = 0;
};

using MediaPermissionCheck = std::function<bool()>;

std::unique_ptr<RTCBackend>
CreateMockRTCBackend(SDKLoader *sdk, MediaPermissionCheck has_media_permission,
                     RTCEventBridge *events, ViewRegistry *views);
std::unique_ptr<RTCBackend>
CreateRealRTCBackend(SDKLoader *sdk, MediaPermissionCheck has_media_permission,
                     RTCEventBridge *events, ViewRegistry *views);

} // namespace beacon::mac
