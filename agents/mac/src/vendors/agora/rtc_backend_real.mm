// Agora 真实 RTC 后端（Objective-C++）：把 RTCBackend 操作映射到原生 SDK，
// 管理引擎、媒体源和画面绑定，并由 delegate 将原生回调转为 RTCEventBridge 事件。
// SDK 同步返回值表示请求受理结果；异步回调与快照事件供上层收集证据，测试判定由上层负责。
// bridge 为借用指针，需由外层保证其在 SDK 回调期间有效；回调上下文仅提供关联线索。
#include "rtc/rtc_backend.h"

#import <AgoraRtcKit/AgoraRtcEngineKit.h>
#import <AppKit/AppKit.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <Foundation/Foundation.h>

#include <cstdlib>
#include <condition_variable>
#include <map>
#include <mutex>
#include <string>
#include <utility>
#include <vector>
#include <unistd.h>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "rtc/rtc_command_vocabulary.h"
#include "rtc/rtc_event_bridge.h"
#include "video/synthetic_video_clip.h"
#include "video/video_host_visibility.h"
#include "video/view_registry.h"

@interface BeaconAgoraDelegate : NSObject <AgoraRtcEngineDelegate>
- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge;
- (void)registerSnapshot:(NSString*)path role:(const std::string&)role;
- (void)clearSnapshots;
- (void)discardSnapshot:(NSString*)path;
- (void)discardSnapshotsForRole:(const std::string&)role;
@end

@interface BeaconAgoraMediaPlayerDelegate : NSObject <AgoraRtcMediaPlayerDelegate>
- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge;
- (BOOL)waitForOpenWithTimeoutMs:(NSInteger)timeout_ms;
@end

@implementation BeaconAgoraMediaPlayerDelegate {
  beacon::mac::RTCEventBridge* bridge_;
  std::mutex state_mutex_;
  std::condition_variable state_condition_;
  bool open_completed_;
  bool open_failed_;
}

- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge {
  self = [super init];
  if (self) {
    bridge_ = bridge;
    open_completed_ = false;
    open_failed_ = false;
  }
  return self;
}

- (void)AgoraRtcMediaPlayer:(id<AgoraRtcMediaPlayerProtocol>)playerKit
          didChangedToState:(AgoraMediaPlayerState)state
                      reason:(AgoraMediaPlayerReason)reason {
  Json::Value payload(Json::objectValue);
  payload["player_id"] = [playerKit getMediaPlayerId];
  payload["state"] = static_cast<int>(state);
  payload["reason"] = static_cast<int>(reason);
  if (bridge_ != nullptr) bridge_->Emit("onMediaPlayerStateChanged", beacon::WriteJson(payload));
  {
    std::lock_guard<std::mutex> lock(state_mutex_);
    if (state == AgoraMediaPlayerStateOpenCompleted) open_completed_ = true;
    if (reason != AgoraMediaPlayerReasonNone) open_failed_ = true;
  }
  state_condition_.notify_all();
}

- (BOOL)waitForOpenWithTimeoutMs:(NSInteger)timeout_ms {
  std::unique_lock<std::mutex> lock(state_mutex_);
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
  while (!open_completed_ && !open_failed_) {
    if (state_condition_.wait_until(lock, deadline) == std::cv_status::timeout) return NO;
  }
  return open_completed_;
}

@end

@implementation BeaconAgoraDelegate {
  beacon::mac::RTCEventBridge* bridge_;
  std::mutex snapshot_mutex_;
  std::map<std::string, std::pair<std::string, beacon::mac::RTCEventBridge::ActiveEngineIdentity>> snapshots_;
}

- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge {
  self = [super init];
  if (self) {
    bridge_ = bridge;
  }
  return self;
}

- (void)emit:(const std::string&)function payload:(const std::string&)payload {
  if (bridge_ != nullptr) {
    bridge_->Emit(function, payload);
  }
}

- (void)registerSnapshot:(NSString*)path role:(const std::string&)role {
  // 按请求路径保存上下文副本，异步回调不能再读取可能已被后续调用替换的 active。
  std::lock_guard<std::mutex> lock(snapshot_mutex_);
  snapshots_[[path UTF8String]] = {role, bridge_ == nullptr
      ? beacon::mac::RTCEventBridge::ActiveEngineIdentity{} : bridge_->active_engine_identity()};
}

- (void)discardSnapshot:(NSString*)path {
  std::lock_guard<std::mutex> lock(snapshot_mutex_);
  snapshots_.erase([path UTF8String]);
}

- (void)discardSnapshotsForRole:(const std::string&)role {
  std::lock_guard<std::mutex> lock(snapshot_mutex_);
  for (auto it = snapshots_.begin(); it != snapshots_.end();) {
    if (it->second.first == role) it = snapshots_.erase(it);
    else ++it;
  }
}

- (void)clearSnapshots {
  std::lock_guard<std::mutex> lock(snapshot_mutex_);
  snapshots_.clear();
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine didJoinChannel:(NSString*)channel withUid:(NSUInteger)uid elapsed:(NSInteger)elapsed {
  Json::Value payload(Json::objectValue);
  payload["channel"] = channel == nil ? "" : [channel UTF8String];
  payload["uid"] = Json::UInt64(uid);
  payload["elapsed"] = Json::Int64(elapsed);
  [self emit:std::string(beacon::mac::rtc_commands::kJoinChannelSuccessEvent) payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine didOccurError:(AgoraErrorCode)errorCode {
  Json::Value payload(Json::objectValue);
  payload["code"] = static_cast<int>(errorCode);
  [self emit:"onError" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine didLeaveChannelWithStats:(AgoraChannelStats*)stats {
  Json::Value payload(Json::objectValue);
  payload["duration"] = Json::UInt64(stats.duration);
  payload["tx_bytes"] = Json::UInt64(stats.txBytes);
  payload["rx_bytes"] = Json::UInt64(stats.rxBytes);
  [self emit:"onLeaveChannel" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine connectionChangedToState:(AgoraConnectionState)state reason:(AgoraConnectionChangedReason)reason {
  Json::Value payload(Json::objectValue);
  payload["state"] = static_cast<int>(state);
  payload["reason"] = static_cast<int>(reason);
  [self emit:"onConnectionStateChanged" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine reportRtcStats:(AgoraChannelStats*)stats {
  Json::Value payload(Json::objectValue);
  payload["duration"] = Json::UInt64(stats.duration);
  payload["tx_bytes"] = Json::UInt64(stats.txBytes);
  payload["rx_bytes"] = Json::UInt64(stats.rxBytes);
  payload["tx_audio_kbitrate"] = Json::UInt64(stats.txAudioKBitrate);
  payload["rx_audio_kbitrate"] = Json::UInt64(stats.rxAudioKBitrate);
  payload["tx_video_kbitrate"] = Json::UInt64(stats.txVideoKBitrate);
  payload["rx_video_kbitrate"] = Json::UInt64(stats.rxVideoKBitrate);
  [self emit:"onRtcStats" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine localVideoStats:(AgoraRtcLocalVideoStats*)stats sourceType:(AgoraVideoSourceType)sourceType {
  Json::Value payload(Json::objectValue);
  payload["uid"] = Json::UInt64(stats.uid);
  payload["sent_bitrate"] = Json::UInt64(stats.sentBitrate);
  payload["sent_frame_rate"] = Json::UInt64(stats.sentFrameRate);
  payload["capture_frame_rate"] = Json::Int64(stats.captureFrameRate);
  payload["source_type"] = static_cast<int>(sourceType);
  [self emit:"onLocalVideoStats" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine
    firstLocalVideoFrameWithSize:(CGSize)size
                         elapsed:(NSInteger)elapsed
                      sourceType:(AgoraVideoSourceType)sourceType {
  Json::Value payload(Json::objectValue);
  payload["width"] = Json::Int64(size.width);
  payload["height"] = Json::Int64(size.height);
  payload["elapsed"] = Json::Int64(elapsed);
  payload["source_type"] = static_cast<int>(sourceType);
  [self emit:"onFirstLocalVideoFrame" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine
    firstLocalVideoFramePublishedWithElapsed:(NSInteger)elapsed
                                  sourceType:(AgoraVideoSourceType)sourceType {
  Json::Value payload(Json::objectValue);
  payload["elapsed"] = Json::Int64(elapsed);
  payload["source_type"] = static_cast<int>(sourceType);
  [self emit:"onFirstLocalVideoFramePublished" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine didJoinedOfUid:(NSUInteger)uid elapsed:(NSInteger)elapsed {
  Json::Value payload(Json::objectValue);
  payload["uid"] = Json::UInt64(uid);
  payload["elapsed"] = Json::Int64(elapsed);
  [self emit:"onUserJoined" payload:beacon::WriteJson(payload)];
}

- (void)emitFirstRemoteVideoFrameOfUid:(NSUInteger)uid size:(CGSize)size elapsed:(NSInteger)elapsed {
  Json::Value payload(Json::objectValue);
  payload["uid"] = Json::UInt64(uid);
  payload["width"] = Json::Int64(size.width);
  payload["height"] = Json::Int64(size.height);
  payload["elapsed"] = Json::Int64(elapsed);
  [self emit:"onFirstRemoteVideoFrame" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine
    firstRemoteVideoFrameOfUid:(NSUInteger)uid
                          size:(CGSize)size
                       elapsed:(NSInteger)elapsed {
  [self emitFirstRemoteVideoFrameOfUid:uid size:size elapsed:elapsed];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine
    firstRemoteVideoDecodedOfUid:(NSUInteger)uid
                            size:(CGSize)size
                         elapsed:(NSInteger)elapsed {
  [self emitFirstRemoteVideoFrameOfUid:uid size:size elapsed:elapsed];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine remoteAudioStats:(AgoraRtcRemoteAudioStats*)stats {
  Json::Value payload(Json::objectValue);
  payload["uid"] = Json::UInt64(stats.uid);
  payload["quality"] = Json::UInt64(stats.quality);
  payload["received_bitrate"] = Json::UInt64(stats.receivedBitrate);
  [self emit:"onRemoteAudioStats" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine remoteVideoStats:(AgoraRtcRemoteVideoStats*)stats {
  Json::Value payload(Json::objectValue);
  payload["uid"] = Json::UInt64(stats.uid);
  payload["width"] = Json::UInt64(stats.width);
  payload["height"] = Json::UInt64(stats.height);
  payload["received_bitrate"] = Json::UInt64(stats.receivedBitrate);
  payload["rx_stream_type"] = static_cast<int>(stats.rxStreamType);
  payload["decoder_output_frame_rate"] = Json::Int64(stats.decoderOutputFrameRate);
  payload["renderer_output_frame_rate"] = Json::Int64(stats.rendererOutputFrameRate);
  [self emit:"onRemoteVideoStats" payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(AgoraRtcEngineKit*)engine
    snapshotTaken:(NSUInteger)uid
          filePath:(NSString*)filePath
             width:(NSInteger)width
            height:(NSInteger)height
           errCode:(NSInteger)errCode {
  Json::Value payload(Json::objectValue);
  payload["uid"] = Json::UInt64(uid);
  payload["file_path"] = filePath == nil ? "" : [filePath UTF8String];
  payload["width"] = Json::Int64(width);
  payload["height"] = Json::Int64(height);
  payload["err_code"] = Json::Int64(errCode);
  std::pair<std::string, beacon::mac::RTCEventBridge::ActiveEngineIdentity> request;
  {
    std::lock_guard<std::mutex> lock(snapshot_mutex_);
    const auto it = snapshots_.find(filePath == nil ? "" : [filePath UTF8String]);
    if (it == snapshots_.end()) {
      return;
    }
    request = it->second;
    snapshots_.erase(it);
  }
  payload["view_role"] = request.first;
  payload["artifact_key"] = request.first;
  // 取出并移除请求后再发事件，避免桥层的 kernel/observer 调用占用 snapshot_mutex_。
  if (bridge_ != nullptr) {
    bridge_->Emit("onSnapshotTaken", beacon::WriteJson(payload), request.second);
  }
}

@end

namespace beacon::mac {

namespace {

NSString* ToNSString(const std::string& value) {
  return [NSString stringWithUTF8String:value.c_str()];
}

NSString* DefaultAgoraLogPath() {
  NSArray<NSString*>* library_paths = NSSearchPathForDirectoriesInDomains(NSLibraryDirectory, NSUserDomainMask, YES);
  NSString* library_path = library_paths.count > 0 ? library_paths.firstObject : NSTemporaryDirectory();
  NSString* logs_path = [library_path stringByAppendingPathComponent:@"Logs"];
  [[NSFileManager defaultManager] createDirectoryAtPath:logs_path withIntermediateDirectories:YES attributes:nil error:nil];
  const char* helper_mode = std::getenv("BEACON_LOOPBACK_HELPER_MODE");
  const NSString* role = (helper_mode != nullptr && helper_mode[0] == '1' && helper_mode[1] == '\0') ? @"helper" : @"primary";
  return [logs_path stringByAppendingPathComponent:[NSString stringWithFormat:@"beacon-agora-%@-%d.log", role, getpid()]];
}

NSString* SnapshotPathForRole(NSString* role) {
  NSString* directory = [[[NSFileManager defaultManager] currentDirectoryPath]
      stringByAppendingPathComponent:@"reports/latest/agora_visual_artifacts"];
  [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
  long long timestamp_ms = static_cast<long long>([[NSDate date] timeIntervalSince1970] * 1000.0);
  NSString* file_name = [NSString stringWithFormat:@"sdk-snapshot-%d-%lld-%@.jpg", getpid(), timestamp_ms, role];
  return [directory stringByAppendingPathComponent:file_name];
}

std::string GetString(const Json::Value& params, const char* name) {
  return params.get(name, "").asString();
}

std::string GetViewId(const Json::Value& params) {
  const std::string view_id = GetString(params, "view_id");
  return view_id.empty() ? GetString(params, "view") : view_id;
}

int GetInt(const Json::Value& params, const char* name, int default_value) {
  return params.get(name, default_value).asInt();
}

NSUInteger GetUid(const Json::Value& params) {
  return static_cast<NSUInteger>(params.get("uid", 0).asUInt());
}

void ShowWindowForHandle(void* handle) {
  if (handle == nullptr || !ShouldShowVideoHostFromEnvironment()) {
    return;
  }
  NSView* view = (__bridge NSView*)handle;
  dispatch_async(dispatch_get_main_queue(), ^{
    [view setHidden:NO];
    [view.superview setNeedsLayout:YES];
    [[view window] orderFrontRegardless];
  });
}

void HideTileForHandle(void* handle) {
  if (handle == nullptr) {
    return;
  }
  NSView* view = (__bridge NSView*)handle;
  dispatch_async(dispatch_get_main_queue(), ^{
    [view setHidden:YES];
    [view.superview setNeedsLayout:YES];
  });
}

void HideWindowForHandle(void* handle) {
  if (handle == nullptr) {
    return;
  }
  NSView* view = (__bridge NSView*)handle;
  dispatch_async(dispatch_get_main_queue(), ^{
    [view setHidden:YES];
    [view.superview setNeedsLayout:YES];
    [[view window] orderOut:nil];
  });
}

int SetupLocalVideoCanvas(AgoraRtcEngineKit* engine, void* handle) {
  __block int code = beacon::kBadRequest;
  void (^setup_block)(void) = ^{
    AgoraRtcVideoCanvas* canvas = [[AgoraRtcVideoCanvas alloc] init];
    canvas.view = (__bridge NSView*)handle;
    canvas.renderMode = AgoraVideoRenderModeHidden;
    code = [engine setupLocalVideo:canvas];
  };
  if ([NSThread isMainThread]) {
    setup_block();
  } else {
    dispatch_sync(dispatch_get_main_queue(), setup_block);
  }
  return code;
}

int SetupRemoteVideoCanvas(AgoraRtcEngineKit* engine, NSUInteger uid, void* handle) {
  __block int code = beacon::kBadRequest;
  void (^setup_block)(void) = ^{
    AgoraRtcVideoCanvas* canvas = [[AgoraRtcVideoCanvas alloc] init];
    canvas.uid = uid;
    canvas.view = (__bridge NSView*)handle;
    canvas.renderMode = AgoraVideoRenderModeHidden;
    code = [engine setupRemoteVideo:canvas];
  };
  if ([NSThread isMainThread]) {
    setup_block();
  } else {
    dispatch_sync(dispatch_get_main_queue(), setup_block);
  }
  return code;
}

std::string ResultJson(const char* name, bool value) {
  Json::Value result(Json::objectValue);
  result[name] = value;
  return beacon::WriteJson(result);
}

std::string ResolveEngineIdentity(const beacon::CallData& call) {
  if (!call.store_as.empty()) {
    return call.store_as;
  }
  if (!call.resource_ref.empty()) {
    return call.resource_ref;
  }
  return "engine_1";
}

bool ShouldDenyMediaPermissionForTesting(const beacon::CallData& call) {
  Json::Value extra;
  if (!beacon::ParseJson(call.extra_json, &extra) || !extra.isObject()) {
    return false;
  }
  return extra.get("permission_fixture", "").asString() == "deny_media_for_testing";
}

bool ShouldSuppressJoinSuccessForTesting(const beacon::CallData& call) {
  Json::Value extra;
  if (!beacon::ParseJson(call.extra_json, &extra) || !extra.isObject()) {
    return false;
  }
  return extra.get("callback_fixture", "").asString() == "suppress_join_success_for_testing";
}

class RealRTCBackend final : public RTCBackend {
 public:
  RealRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission, RTCEventBridge* events,
                 ViewRegistry* views)
      : sdk_(sdk), has_media_permission_(std::move(has_media_permission)), events_(events), views_(views) {}

  ~RealRTCBackend() override {
    Unload();
  }

  int Load() override {
    @autoreleasepool {
      const char* app_id = std::getenv("AGORA_APP_ID");
      if (app_id == nullptr || app_id[0] == '\0' || sdk_ == nullptr || !sdk_->Load()) {
        return beacon::kBadRequest;
      }
      if (engine_ == nil) {
        delegate_ = [[BeaconAgoraDelegate alloc] initWithBridge:events_];
        AgoraRtcEngineConfig* config = [[AgoraRtcEngineConfig alloc] init];
        config.appId = ToNSString(app_id);
        AgoraLogConfig* log_config = [[AgoraLogConfig alloc] init];
        NSString* log_path = DefaultAgoraLogPath();
        log_config.filePath = log_path;
        config.logConfig = log_config;
        engine_ = [AgoraRtcEngineKit sharedEngineWithConfig:config delegate:delegate_];
        if (engine_ != nil) {
          const int log_code = [engine_ setLogFile:log_path];
          if (log_code != beacon::kOk) {
            return log_code;
          }
        }
        sdk_->Configure(app_id);
      }
      initialized_ = engine_ != nil;
      return initialized_ ? beacon::kOk : beacon::kBadRequest;
    }
  }

  int Unload() override {
    Reset();
    @autoreleasepool {
      if (engine_ != nil) {
        engine_.delegate = nil;
        [engine_ leaveChannel:nil];
        engine_ = nil;
      }
      delegate_ = nil;
      [AgoraRtcEngineKit destroy];
    }
    if (sdk_ != nullptr) {
      sdk_->Unload();
    }
    return beacon::kOk;
  }

  beacon::CallResult EnableLocalAudio(bool enabled) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    const int code = [engine_ enableLocalAudio:enabled];
    if (code != beacon::kOk) {
      return {code, "enableLocalAudio failed", "{}"};
    }
    if (synthetic_audio_track_id_ >= 0) {
      const int volume_code = [engine_ adjustCustomAudioPublishVolume:synthetic_audio_track_id_
                                                               volume:enabled ? 100 : 0];
      if (volume_code != beacon::kOk) {
        return {volume_code, "adjustCustomAudioPublishVolume failed", "{}"};
      }
    }
    audio_enabled_ = enabled;
    return {beacon::kOk, "audio updated", ResultJson("audio", enabled)};
  }

  beacon::CallResult EnableLocalVideo(bool enabled) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    if (enabled) {
      const int video_code = [engine_ enableVideo];
      if (video_code != beacon::kOk) {
        return {video_code, "enableVideo failed", "{}"};
      }
    }
    const int code = [engine_ enableLocalVideo:enabled];
    if (code != beacon::kOk) {
      return {code, "enableLocalVideo failed", "{}"};
    }
    video_enabled_ = enabled;
    return {beacon::kOk, "video updated", ResultJson("video", enabled)};
  }

  beacon::CallResult JoinChannel(const beacon::CallData& call) override {
    if (ShouldDenyMediaPermissionForTesting(call) || !HasMediaPermission()) {
      return {kPermissionDenied, "media permission denied", "{}"};
    }
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string channel = GetString(params, "channel");
    if (channel.empty()) {
      return {beacon::kBadRequest, "missing channel", "{}"};
    }
    const bool publish_camera = params.get("publish_camera", false).asBool();
    const bool publish_microphone = params.get("publish_microphone", false).asBool();
    const bool publish_synthetic_audio = params.get("publish_synthetic_audio", false).asBool();
    const bool publish_media_player = params.get("publish_media_player", false).asBool();
    if (publish_synthetic_audio && publish_microphone) {
      return {beacon::kBadRequest, "synthetic audio cannot publish with microphone", "{}"};
    }
    if (publish_media_player && media_player_ == nil) {
      return {beacon::kBadRequest, "media player must be opened before join", "{}"};
    }
    const AgoraClientRole role = (publish_camera || publish_microphone || publish_synthetic_audio || publish_media_player)
                                     ? AgoraClientRoleBroadcaster : AgoraClientRoleAudience;
    const int uid = GetInt(params, "uid", 0);
    const std::string token = GetString(params, "token");
    const std::string identity = ResolveEngineIdentity(call);
    RTCEventBridge::ActiveEngineIdentity callback_origin;
    if (events_ != nullptr) {
      // 请求前先登记 pending，使 active 尚为空时的早到 delegate 回调也有上下文。
      // 成功 block 捕获副本，避免后续调用改写其 originating_op_id。
      events_->SuppressJoinSuccessForTesting(ShouldSuppressJoinSuccessForTesting(call));
      callback_origin = events_->CaptureActiveEngineIdentity(call, identity, identity);
      events_->TrackPendingEngineIdentity(callback_origin);
    }
    @autoreleasepool {
      if (publish_synthetic_audio) {
        const int profile_code = [engine_ setAudioProfile:AgoraAudioProfileMusicHighQualityStereo];
        if (profile_code != beacon::kOk) {
          if (events_ != nullptr) events_->CancelPendingEngineIdentity(callback_origin);
          return {profile_code, "set synthetic audio profile failed", "{}"};
        }
        const int scenario_code = [engine_ setAudioScenario:AgoraAudioScenarioGameStreaming];
        if (scenario_code != beacon::kOk) {
          if (events_ != nullptr) events_->CancelPendingEngineIdentity(callback_origin);
          return {scenario_code, "set synthetic audio scenario failed", "{}"};
        }
      }
      if (publish_synthetic_audio && !PrepareSyntheticAudio()) {
        return {beacon::kBadRequest, "synthetic audio clip unavailable", "{}"};
      }
      const int role_code = [engine_ setClientRole:role];
      if (role_code != beacon::kOk) {
        if (events_ != nullptr) {
          events_->CancelPendingEngineIdentity(callback_origin);
        }
        return {role_code, "setClientRole failed", "{}"};
      }
      if (publish_media_player) {
        const int video_code = [engine_ enableVideo];
        if (video_code != beacon::kOk) {
          if (events_ != nullptr) events_->CancelPendingEngineIdentity(callback_origin);
          return {video_code, "enableVideo for media player failed", "{}"};
        }
      }
      AgoraRtcChannelMediaOptions* options = [[AgoraRtcChannelMediaOptions alloc] init];
      options.autoSubscribeAudio = params.get("auto_subscribe_audio", false).asBool();
      options.autoSubscribeVideo = params.get("auto_subscribe_video", false).asBool();
      options.publishCameraTrack = publish_camera;
      options.publishMicrophoneTrack = publish_microphone;
      options.publishCustomAudioTrack = publish_synthetic_audio;
      if (publish_synthetic_audio) {
        options.publishCustomAudioTrackId = synthetic_audio_track_id_;
      }
      options.publishMediaPlayerAudioTrack = publish_media_player;
      options.publishMediaPlayerVideoTrack = publish_media_player;
      if (publish_media_player) options.publishMediaPlayerId = [media_player_ getMediaPlayerId];
      options.clientRoleType = role;
      RTCEventBridge* events = events_;
      const int code = [engine_ joinChannelByToken:token.empty() ? nil : ToNSString(token)
                                        channelId:ToNSString(channel)
                                              uid:static_cast<NSUInteger>(uid)
                                     mediaOptions:options
                                      joinSuccess:^(NSString* joined_channel, NSUInteger joined_uid, NSInteger elapsed) {
                                        Json::Value payload(Json::objectValue);
                                        payload["channel"] = joined_channel == nil ? "" : [joined_channel UTF8String];
                                        payload["uid"] = Json::UInt64(joined_uid);
                                        payload["elapsed"] = Json::Int64(elapsed);
                                        if (events != nullptr) {
                                          events->ActivatePendingEngineIdentity(callback_origin);
                                          events->Emit(std::string(rtc_commands::kJoinChannelSuccessEvent),
                                                       beacon::WriteJson(payload),
                                                       callback_origin);
                                        }
                                      }];
      if (code != beacon::kOk) {
        if (events_ != nullptr) {
          events_->CancelPendingEngineIdentity(callback_origin);
        }
        return {code, "joinChannel failed", "{}"};
      }
    }
    // 此处 joined_ 记录 SDK 同步受理结果；入房成功仍需观察 onJoinChannelSuccess。
    joined_ = true;
    channel_ = channel;
    if (publish_synthetic_audio) StartSyntheticAudio();
    media_player_published_ = publish_media_player;
    return {beacon::kOk, "joined", ResultJson("joined", true)};
  }

  beacon::CallResult LeaveChannel() override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    StopSyntheticAudioInternal();
    StopSyntheticVideoInternal();
    StopMediaPlayerInternal();
    const int release_code = ReleaseVideoViews();
    if (release_code != beacon::kOk) return {release_code, "video cleanup failed", "{}"};
    const int code = [engine_ leaveChannel:nil];
    if (code != beacon::kOk) {
      return {code, "leaveChannel failed", "{}"};
    }
    joined_ = false;
    channel_.clear();
    if (events_ != nullptr) {
      events_->SuppressJoinSuccessForTesting(false);
      events_->ClearActiveEngineIdentity();
    }
    return {beacon::kOk, "left", ResultJson("left", true)};
  }

  beacon::CallResult RenewToken(const beacon::CallData& call) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string token = GetString(params, "token");
    if (token.empty()) {
      return {beacon::kBadRequest, "missing token", "{}"};
    }
    const int code = [engine_ renewToken:ToNSString(token)];
    if (code != beacon::kOk) {
      return {code, "renewToken failed", "{}"};
    }
    return {beacon::kOk, "token renewed", ResultJson("renewed", true)};
  }

  beacon::CallResult BindLocalVideo(const beacon::CallData& call) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_id = GetViewId(params);
    if (view_id.empty()) {
      return {beacon::kBadRequest, "missing view_id", "{}"};
    }
    if (views_ == nullptr) {
      return {403, "view registry unavailable", "{}"};
    }
    void* handle = views_->GetHandle(view_id);
    if (handle == nullptr) {
      return {403, "view handle not found", "{}"};
    }
    for (const auto& binding : remote_bindings_) {
      if (views_->GetHandle(binding.first) == handle) {
        return {beacon::kBadRequest, "view already bound remotely", "{}"};
      }
    }
    [engine_ enableVideo];
    const int code = SetupLocalVideoCanvas(engine_, handle);
    if (code != beacon::kOk) {
      return {code, "setupLocalVideo failed", "{}"};
    }
    local_view_id_ = view_id;
    ShowWindowForHandle(handle);
    Json::Value result(Json::objectValue);
    result["configured"] = true;
    result["view_id"] = view_id;
    return {beacon::kOk, "local video configured", beacon::WriteJson(result)};
  }

  beacon::CallResult BindRemoteVideo(const beacon::CallData& call) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_id = GetViewId(params);
    const NSUInteger uid = GetUid(params);
    if (uid == 0) {
      return {beacon::kBadRequest, "missing uid", "{}"};
    }
    if (view_id.empty()) {
      return {beacon::kBadRequest, "missing view_id", "{}"};
    }
    if (views_ == nullptr) {
      return {403, "view registry unavailable", "{}"};
    }
    void* handle = views_->GetHandle(view_id);
    if (handle == nullptr) {
      return {403, "view handle not found", "{}"};
    }
    for (const auto& binding : remote_bindings_) {
      if (binding.first == view_id && binding.second.uid == uid) continue;
      if (binding.second.uid == uid || views_->GetHandle(binding.first) == handle) {
        return {beacon::kBadRequest, "remote publisher or view already bound", "{}"};
      }
    }
    if (views_->GetHandle(local_view_id_) == handle) {
      return {beacon::kBadRequest, "view already bound locally", "{}"};
    }
    const auto existing = remote_bindings_.find(view_id);
    if (existing != remote_bindings_.end() && existing->second.uid != uid) {
      return {beacon::kBadRequest, "release view before rebinding publisher", "{}"};
    }
    [engine_ enableVideo];
    const int code = SetupRemoteVideoCanvas(engine_, uid, handle);
    if (code != beacon::kOk) {
      return {code, "setupRemoteVideo failed", "{}"};
    }
    remote_bindings_[view_id] = RemoteBinding{uid};
    ShowWindowForHandle(handle);
    Json::Value result(Json::objectValue);
    result["configured"] = true;
    result["view_id"] = view_id;
    result["uid"] = Json::UInt64(uid);
    return {beacon::kOk, "remote video configured", beacon::WriteJson(result)};
  }

  beacon::CallResult CaptureSnapshot(const beacon::CallData& call) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_role = params.get("view_role", "").asString();
    if (view_role.empty()) {
      return {beacon::kBadRequest, "missing view_role", "{}"};
    }
    RTCEventBridge::ActiveEngineIdentity previous_origin;
    if (events_ != nullptr) {
      // 先切换上下文供 registerSnapshot 捕获；未受理时连同序号恢复原上下文。
      // 受理后保留当前 active，onSnapshotTaken 使用按路径保存的副本。
      previous_origin = events_->active_engine_identity();
      const std::string identity = ResolveEngineIdentity(call);
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
    }
    if (!RequestVisualSnapshot(view_role)) {
      if (events_ != nullptr) {
        events_->RestoreActiveEngineIdentity(std::move(previous_origin));
      }
      return {403, "view role not bound", "{}"};
    }
    Json::Value result(Json::objectValue);
    result["snapshot_requested"] = true;
    result["view_role"] = view_role;
    return {beacon::kOk, "snapshot requested", beacon::WriteJson(result)};
  }

  beacon::CallResult ReleaseView(const beacon::CallData& call) override {
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_role = params.get("view_role", "").asString();
    if (view_role.empty()) {
      return {beacon::kBadRequest, "missing view_role", "{}"};
    }
    bool released = false;
    if (view_role == local_view_id_) {
      void* handle = views_ == nullptr ? nullptr : views_->GetHandle(view_role);
      if (engine_ != nil) {
        const int code = SetupLocalVideoCanvas(engine_, nullptr);
        if (code != beacon::kOk) return {code, "local canvas release failed", "{}"};
      }
      local_view_id_.clear();
      HideTileForHandle(handle);
      if (remote_bindings_.empty()) {
        HideWindowForHandle(handle);
      }
      released = true;
    }
    const auto remote = remote_bindings_.find(view_role);
    if (remote != remote_bindings_.end()) {
      void* handle = views_ == nullptr ? nullptr : views_->GetHandle(view_role);
      if (engine_ != nil) {
        const int code = SetupRemoteVideoCanvas(engine_, remote->second.uid, nullptr);
        if (code != beacon::kOk) return {code, "remote canvas release failed", "{}"};
      }
      remote_bindings_.erase(remote);
      HideTileForHandle(handle);
      if (local_view_id_.empty() && remote_bindings_.empty()) HideWindowForHandle(handle);
      released = true;
    }
    if (released) [delegate_ discardSnapshotsForRole:view_role];
    Json::Value result(Json::objectValue);
    result["released"] = released;
    result["view_role"] = view_role;
    return {beacon::kOk, "view released", beacon::WriteJson(result)};
  }

  beacon::CallResult StartPreview(const beacon::CallData& call) override {
    if (ShouldDenyMediaPermissionForTesting(call) || !HasMediaPermission()) {
      return {kPermissionDenied, "media permission denied", "{}"};
    }
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    [engine_ enableVideo];
    const int code = [engine_ startPreview];
    if (code != beacon::kOk) {
      return {code, "startPreview failed", "{}"};
    }
    previewing_ = true;
    return {beacon::kOk, "preview started", ResultJson("previewing", true)};
  }

  beacon::CallResult StopPreview() override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    const int code = [engine_ stopPreview];
    if (code != beacon::kOk) {
      return {code, "stopPreview failed", "{}"};
    }
    previewing_ = false;
    return {beacon::kOk, "preview stopped", ResultJson("previewing", false)};
  }

  beacon::CallResult StartSyntheticVideo(const beacon::CallData& call) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const int width = params.get("width", 640).asInt();
    const int height = params.get("height", 480).asInt();
    const int fps = params.get("fps", 15).asInt();
    const std::string pattern = params.get("pattern", "animated_clip").asString();
    if (width <= 0 || height <= 0 || fps <= 0 ||
        (pattern != "animated_clip" && pattern != "paired_media_clip" && pattern != "bars" && pattern != "moving_stripe")) {
      return {beacon::kBadRequest, "invalid synthetic video params", "{}"};
    }
    @autoreleasepool {
      StopSyntheticVideoInternal();
      BeaconSyntheticVideoClip* clip = nil;
      if (pattern == "animated_clip" || pattern == "paired_media_clip") {
        clip = [[BeaconSyntheticVideoClip alloc]
            initWithPath:(pattern == "paired_media_clip" ? BeaconSyntheticPairedMediaClipPath()
                                                        : BeaconSyntheticVideoClipPath())];
        if (clip == nil) {
          return {beacon::kBadRequest, "synthetic video clip unavailable", "{}"};
        }
        if (width != [clip width] || height != [clip height]) {
          return {beacon::kBadRequest, "animated clip dimensions do not match request", "{}"};
        }
      }
      const int enable_code = [engine_ enableVideo];
      if (enable_code != beacon::kOk) {
        return {enable_code, "enableVideo failed", "{}"};
      }
      [engine_ setExternalVideoSource:YES useTexture:NO sourceType:AgoraExternalVideoSourceTypeVideoFrame];
      CVPixelBufferPoolRef pool = (pattern == "animated_clip" || pattern == "paired_media_clip")
          ? nullptr
          : CreateSyntheticPixelBufferPool(width, height);
      if (pattern != "animated_clip" && pattern != "paired_media_clip" && pool == nullptr) {
        [engine_ setExternalVideoSource:NO useTexture:NO sourceType:AgoraExternalVideoSourceTypeVideoFrame];
        return {beacon::kBadRequest, "synthetic video pool creation failed", "{}"};
      }
      synthetic_pool_ = pool;
      synthetic_clip_ = clip;
      synthetic_fps_ = fps;
      synthetic_moving_stripe_ = pattern == "moving_stripe";
      synthetic_active_ = true;
      synthetic_frame_index_ = 0;
      synthetic_queue_ = dispatch_queue_create("beacon.mac.synthetic-video", DISPATCH_QUEUE_SERIAL);
      dispatch_source_t timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, synthetic_queue_);
      if (timer == nullptr) {
        StopSyntheticVideoInternal();
        return {beacon::kBadRequest, "synthetic video timer creation failed", "{}"};
      }
      const int64_t interval = NSEC_PER_SEC / static_cast<int64_t>(fps);
      dispatch_source_set_timer(timer, dispatch_time(DISPATCH_TIME_NOW, interval / 10),
                                static_cast<uint64_t>(interval), static_cast<uint64_t>(interval / 10));
      dispatch_source_set_event_handler(timer, ^{
        PumpSyntheticFrame();
      });
      synthetic_timer_ = timer;
      dispatch_resume(synthetic_timer_);
      return {beacon::kOk, "synthetic video started", ResultJson("started", true)};
    }
  }

  beacon::CallResult StopSyntheticVideo() override {
    const bool was_active = synthetic_active_;
    StopSyntheticVideoInternal();
    return {beacon::kOk, "synthetic video stopped", ResultJson("stopped", was_active)};
  }

  beacon::CallResult SetDualStreamMode(const beacon::CallData& call) override {
    if (!EnsureLoaded()) return {beacon::kBadRequest, "sdk not loaded", "{}"};
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string mode_name = params.get("mode", "auto").asString();
    AgoraSimulcastStreamMode mode = AgoraAutoSimulcastStream;
    if (mode_name == "enabled") {
      mode = AgoraEnableSimulcastStream;
    } else if (mode_name == "disabled") {
      mode = AgoraDisableSimulcastStream;
    } else if (mode_name != "auto") {
      return {beacon::kBadRequest, "invalid simulcast mode", "{}"};
    }
    AgoraSimulcastStreamConfig* config = [[AgoraSimulcastStreamConfig alloc] init];
    config.dimensions = CGSizeMake(params.get("low_width", 320).asInt(), params.get("low_height", 180).asInt());
    config.kBitrate = params.get("low_bitrate", 150).asInt();
    config.framerate = params.get("low_fps", 15).asInt();
    if (config.dimensions.width <= 0 || config.dimensions.height <= 0 || config.kBitrate <= 0 || config.framerate <= 0) {
      return {beacon::kBadRequest, "invalid low stream configuration", "{}"};
    }
    const int code = [engine_ setDualStreamMode:mode streamConfig:config];
    if (code != beacon::kOk) return {code, "setDualStreamMode failed", "{}"};
    return {beacon::kOk, "dual stream mode updated", std::string("{\"mode\":\"") + mode_name + "\"}"};
  }

  beacon::CallResult SetRemoteVideoStream(const beacon::CallData& call) override {
    if (!EnsureLoaded()) return {beacon::kBadRequest, "sdk not loaded", "{}"};
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const int uid = GetInt(params, "uid", 0);
    const std::string stream_type_name = params.get("stream_type", "").asString();
    if (uid <= 0 || (stream_type_name != "high" && stream_type_name != "low")) {
      return {beacon::kBadRequest, "invalid remote video stream params", "{}"};
    }
    if (events_ != nullptr) {
      const std::string identity = ResolveEngineIdentity(call);
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
    }
    const AgoraVideoStreamType stream_type = stream_type_name == "low" ? AgoraVideoStreamTypeLow : AgoraVideoStreamTypeHigh;
    const int code = [engine_ setRemoteVideoStream:static_cast<NSUInteger>(uid) type:stream_type];
    if (code != beacon::kOk) return {code, "setRemoteVideoStream failed", "{}"};
    return {beacon::kOk, "remote video stream updated",
            std::string("{\"uid\":") + std::to_string(uid) + ",\"stream_type\":\"" + stream_type_name + "\"}"};
  }

  beacon::CallResult OpenMediaPlayer(const beacon::CallData& call) override {
    if (!EnsureLoaded()) return {beacon::kBadRequest, "sdk not loaded", "{}"};
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string source_path = GetString(params, "source_path");
    const int start_pos_ms = params.get("start_pos_ms", 0).asInt();
    if (source_path.empty() || ![[NSFileManager defaultManager] fileExistsAtPath:ToNSString(source_path)]) {
      return {beacon::kBadRequest, "media player source_path is unavailable", "{}"};
    }
    if (start_pos_ms < 0) {
      return {beacon::kBadRequest, "media player start_pos_ms must be non-negative", "{}"};
    }
    if (events_ != nullptr) {
      const std::string identity = ResolveEngineIdentity(call);
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
    }
    StopMediaPlayerInternal();
    media_player_delegate_ = [[BeaconAgoraMediaPlayerDelegate alloc] initWithBridge:events_];
    media_player_ = [engine_ createMediaPlayerWithDelegate:media_player_delegate_];
    if (media_player_ == nil) return {beacon::kBadRequest, "createMediaPlayer failed", "{}"};
    const int code = [media_player_ open:ToNSString(source_path) startPos:start_pos_ms];
    if (code != beacon::kOk) {
      StopMediaPlayerInternal();
      return {code, "open media player failed", "{}"};
    }
    if (![media_player_delegate_ waitForOpenWithTimeoutMs:15000]) {
      StopMediaPlayerInternal();
      return {beacon::kBadRequest, "media player open callback timed out", "{}"};
    }
    Json::Value result(Json::objectValue);
    result["opened"] = true;
    result["player_id"] = [media_player_ getMediaPlayerId];
    return {beacon::kOk, "media player opened", beacon::WriteJson(result)};
  }

  beacon::CallResult PlayMediaPlayer(const beacon::CallData& call) override {
    return ControlMediaPlayer(call, "play", [this] { return [media_player_ play]; });
  }
  beacon::CallResult PauseMediaPlayer(const beacon::CallData& call) override {
    return ControlMediaPlayer(call, "pause", [this] { return [media_player_ pause]; });
  }
  beacon::CallResult ResumeMediaPlayer(const beacon::CallData& call) override {
    return ControlMediaPlayer(call, "resume", [this] { return [media_player_ resume]; });
  }

  beacon::CallResult StopMediaPlayer() override {
    const bool was_active = media_player_ != nil;
    StopMediaPlayerInternal();
    return {beacon::kOk, "media player stopped", ResultJson("stopped", was_active)};
  }

  beacon::CallResult GetConnectionState(const beacon::CallData& call) override {
    if (!EnsureLoaded()) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    if (events_ != nullptr && joined_) {
      const std::string identity = ResolveEngineIdentity(call);
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
    }
    return {beacon::kOk, "ok", joined_ ? "{\"state\":\"connected\"}" : "{\"state\":\"idle\"}"};
  }

  void Reset() override {
    StopSyntheticAudioInternal();
    StopSyntheticVideoInternal();
    StopMediaPlayerInternal();
    void* local_handle = views_ == nullptr || local_view_id_.empty() ? nullptr : views_->GetHandle(local_view_id_);
    [delegate_ clearSnapshots];
    if (engine_ != nil) {
      SetupLocalVideoCanvas(engine_, nullptr);
      for (const auto& binding : remote_bindings_) {
        SetupRemoteVideoCanvas(engine_, binding.second.uid, nullptr);
      }
      [engine_ stopPreview];
      [engine_ disableVideo];
      [engine_ leaveChannel:nil];
    }
    HideWindowForHandle(local_handle);
    for (const auto& binding : remote_bindings_) {
      HideWindowForHandle(views_ == nullptr ? nullptr : views_->GetHandle(binding.first));
    }
    joined_ = false;
    previewing_ = false;
    audio_enabled_ = true;
    video_enabled_ = true;
    channel_.clear();
    local_view_id_.clear();
    remote_bindings_.clear();
    initialized_ = engine_ != nil;
    if (events_ != nullptr) {
      events_->SuppressJoinSuccessForTesting(false);
      events_->ClearActiveEngineIdentity();
    }
  }

 bool initialized() const override { return initialized_; }
 bool joined() const override { return joined_; }
 bool previewing() const override { return previewing_; }
 std::string channel() const override { return channel_; }

 private:
  bool PrepareSyntheticAudio() {
    StopSyntheticAudioInternal();
    synthetic_audio_clip_ = [[BeaconSyntheticAudioClip alloc] initWithPath:BeaconSyntheticAudioClipPath()];
    if (synthetic_audio_clip_ == nil) return false;
    AgoraAudioTrackConfig* config = [[AgoraAudioTrackConfig alloc] init];
    config.enableLocalPlayback = NO;
    synthetic_audio_track_id_ = [engine_ createCustomAudioTrack:AgoraAudioTrackTypeMixable config:config];
    if (synthetic_audio_track_id_ < 0) {
      synthetic_audio_track_id_ = -1;
      synthetic_audio_clip_ = nil;
      return false;
    }
    if ([engine_ adjustCustomAudioPublishVolume:synthetic_audio_track_id_ volume:100] != beacon::kOk) {
      StopSyntheticAudioInternal();
      return false;
    }
    return true;
  }

  void StartSyntheticAudio() {
    if (synthetic_audio_clip_ == nil || synthetic_audio_track_id_ < 0 || synthetic_audio_timer_ != nullptr) return;
    synthetic_audio_active_ = true;
    synthetic_audio_queue_ = dispatch_queue_create("beacon.mac.synthetic-audio", DISPATCH_QUEUE_SERIAL);
    synthetic_audio_timer_ = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, synthetic_audio_queue_);
    if (synthetic_audio_timer_ == nullptr) {
      StopSyntheticAudioInternal();
      return;
    }
    synthetic_audio_timestamp_ms_ = [engine_ getCurrentMonotonicTimeInMs];
    const int64_t interval = NSEC_PER_MSEC * 20;
    dispatch_source_set_timer(synthetic_audio_timer_, dispatch_time(DISPATCH_TIME_NOW, interval),
                              static_cast<uint64_t>(interval), NSEC_PER_MSEC);
    dispatch_source_set_event_handler(synthetic_audio_timer_, ^{
      PumpSyntheticAudio();
    });
    dispatch_resume(synthetic_audio_timer_);
  }

  void StopSyntheticAudioInternal() {
    if (synthetic_audio_timer_ != nullptr) {
      dispatch_source_cancel(synthetic_audio_timer_);
      if (synthetic_audio_queue_ != nullptr) dispatch_sync(synthetic_audio_queue_, ^{});
    }
    synthetic_audio_timer_ = nullptr;
    synthetic_audio_queue_ = nullptr;
    synthetic_audio_active_ = false;
    synthetic_audio_timestamp_ms_ = 0;
    if (engine_ != nil && synthetic_audio_track_id_ >= 0) {
      [engine_ destroyCustomAudioTrack:synthetic_audio_track_id_];
    }
    synthetic_audio_track_id_ = -1;
    synthetic_audio_clip_ = nil;
  }

  template <typename Control>
  beacon::CallResult ControlMediaPlayer(const beacon::CallData& call, const char* action, Control control) {
    if (!EnsureLoaded()) return {beacon::kBadRequest, "sdk not loaded", "{}"};
    if (media_player_ == nil || !media_player_published_ || !joined_) {
      return {beacon::kBadRequest, "media player is not published in a joined channel", "{}"};
    }
    if (events_ != nullptr) {
      const std::string identity = ResolveEngineIdentity(call);
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
    }
    const int code = control();
    if (code != beacon::kOk) return {code, std::string(action) + " media player failed", "{}"};
    return {beacon::kOk, std::string("media player ") + action,
            ResultJson(std::string(action) == "pause" ? "paused" : "playing", true)};
  }

  void StopMediaPlayerInternal() {
    if (media_player_ != nil) {
      [media_player_ stop];
      if (engine_ != nil) [engine_ destroyMediaPlayer:media_player_];
    }
    media_player_ = nil;
    media_player_delegate_ = nil;
    media_player_published_ = false;
  }

  void PumpSyntheticAudio() {
    if (!synthetic_audio_active_ || engine_ == nil || synthetic_audio_clip_ == nil || synthetic_audio_track_id_ < 0) {
      return;
    }
    @autoreleasepool {
      const int sample_rate = [synthetic_audio_clip_ sampleRate];
      const int channels = [synthetic_audio_clip_ channels];
      const int samples_per_channel = sample_rate / 50;
      const int samples = samples_per_channel * channels;
      NSData* pcm = [synthetic_audio_clip_ copyNextPCMFrames:static_cast<NSUInteger>(samples_per_channel)];
      const NSUInteger expected_bytes = static_cast<NSUInteger>(samples) * sizeof(int16_t);
      if (pcm == nil || pcm.length != expected_bytes) {
        synthetic_audio_active_ = false;
        if (events_ != nullptr) events_->Emit("onError", R"({"code":400,"message":"synthetic audio decode failed"})");
        return;
      }
      const int64_t monotonic_timestamp = [engine_ getCurrentMonotonicTimeInMs];
      const int64_t timestamp = monotonic_timestamp >= 0 ? monotonic_timestamp : synthetic_audio_timestamp_ms_;
      synthetic_audio_timestamp_ms_ = timestamp + 20;
      const int code = [engine_ pushExternalAudioFrameRawData:const_cast<void*>(pcm.bytes)
                                                       samples:samples
                                                    sampleRate:sample_rate
                                                      channels:channels
                                                      trackId:synthetic_audio_track_id_
                                                     timestamp:timestamp];
      if (code == beacon::kOk) synthetic_audio_push_ok_count_ += 1;
      else if (++synthetic_audio_push_failures_ == 1) {
        fprintf(stderr, "[synthetic-audio] pushExternalAudioFrameRawData failed (code=%d)\n", code);
      }
    }
  }

  int ReleaseVideoViews() {
    std::vector<std::string> roles;
    if (!local_view_id_.empty()) roles.push_back(local_view_id_);
    for (const auto& binding : remote_bindings_) roles.push_back(binding.first);
    for (const auto& role : roles) {
      beacon::CallData call;
      Json::Value params(Json::objectValue);
      params["view_role"] = role;
      call.params_json = beacon::WriteJson(params);
      const auto result = ReleaseView(call);
      if (result.error != beacon::kOk) return result.error;
    }
    [delegate_ clearSnapshots];
    return beacon::kOk;
  }

  bool EnsureLoaded() {
    return initialized_ || Load() == beacon::kOk;
  }

  bool HasMediaPermission() const {
    return !has_media_permission_ || has_media_permission_();
  }

  void EmitSnapshotRequest(NSUInteger uid, const char* view_role, NSString* file_path, NSInteger return_code) {
    if (events_ == nullptr) {
      return;
    }
    Json::Value request(Json::objectValue);
    request["uid"] = Json::UInt64(uid);
    request["view_role"] = view_role;
    request["artifact_key"] = view_role;
    request["file_path"] = file_path == nil ? "" : [file_path UTF8String];
    request["return_code"] = Json::Int64(return_code);
    events_->Emit("onSnapshotRequested", beacon::WriteJson(request));
  }

  void RequestSnapshot(NSUInteger uid, const char* artifact_key) {
    NSString* file_path = SnapshotPathForRole([[NSUUID UUID] UUIDString]);
    [delegate_ registerSnapshot:file_path role:std::string(artifact_key)];
    __block NSInteger code = beacon::kBadRequest;
    if ([NSThread isMainThread]) {
      code = [engine_ takeSnapshot:static_cast<NSInteger>(uid) filePath:file_path];
    } else {
      dispatch_sync(dispatch_get_main_queue(), ^{
        code = [engine_ takeSnapshot:static_cast<NSInteger>(uid) filePath:file_path];
      });
    }
    if (code != beacon::kOk) [delegate_ discardSnapshot:file_path];
    EmitSnapshotRequest(uid, artifact_key, file_path, code);
  }

  bool RequestVisualSnapshot(const std::string& role) {
    if (!joined_) return false;
    if (role == local_view_id_ && !role.empty()) {
      RequestSnapshot(0, role.c_str());
      return true;
    }
    const auto remote = remote_bindings_.find(role);
    if (remote != remote_bindings_.end()) {
      RequestSnapshot(remote->second.uid, role.c_str());
      return true;
    }
    return false;
  }

  void StopSyntheticVideoInternal() {
    if (synthetic_timer_ != nullptr) {
      dispatch_source_cancel(synthetic_timer_);
      if (synthetic_queue_ != nullptr) {
        dispatch_sync(synthetic_queue_, ^{});
      }
    }
    synthetic_timer_ = nullptr;
    synthetic_queue_ = nullptr;
    if (synthetic_pool_ != nullptr) {
      CFRelease(synthetic_pool_);
      synthetic_pool_ = nullptr;
    }
    synthetic_clip_ = nil;
    if (engine_ != nil) {
      [engine_ setExternalVideoSource:NO useTexture:NO sourceType:AgoraExternalVideoSourceTypeVideoFrame];
    }
    synthetic_active_ = false;
    synthetic_frame_index_ = 0;
    synthetic_push_ok_count_ = 0;
    synthetic_push_failures_ = 0;
    free(synthetic_frame_scratch_);
    synthetic_frame_scratch_ = nullptr;
    synthetic_frame_scratch_size_ = 0;
  }

  void LogSyntheticPushResult(bool pushed) {
    if (pushed) {
      synthetic_push_ok_count_ += 1;
      if (synthetic_push_ok_count_ == 1) {
        fprintf(stderr, "[synthetic-video] first frame accepted by sdk (frame_index=%lld)\n",
                static_cast<long long>(synthetic_frame_index_));
      }
      return;
    }
    synthetic_push_failures_ += 1;
    if (synthetic_push_failures_ == 1 || synthetic_push_failures_ % 100 == 0) {
      fprintf(stderr, "[synthetic-video] pushExternalVideoFrame failed (count=%lld, frame_index=%lld)\n",
              static_cast<long long>(synthetic_push_failures_),
              static_cast<long long>(synthetic_frame_index_));
    }
  }

  CVPixelBufferPoolRef CreateSyntheticPixelBufferPool(int width, int height) {
    const int even_width = width - (width % 2);
    const int even_height = height - (height % 2);
    CFMutableDictionaryRef pixel_buffer_attributes = CFDictionaryCreateMutable(
        kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    const int pixel_format = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
    CFNumberRef pixel_format_value = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &pixel_format);
    CFDictionarySetValue(pixel_buffer_attributes, kCVPixelBufferPixelFormatTypeKey, pixel_format_value);
    CFRelease(pixel_format_value);
    const int width_value = even_width;
    const int height_value = even_height;
    CFNumberRef width_number = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &width_value);
    CFNumberRef height_number = CFNumberCreate(kCFAllocatorDefault, kCFNumberIntType, &height_value);
    CFDictionarySetValue(pixel_buffer_attributes, kCVPixelBufferWidthKey, width_number);
    CFDictionarySetValue(pixel_buffer_attributes, kCVPixelBufferHeightKey, height_number);
    CFRelease(width_number);
    CFRelease(height_number);
    CVPixelBufferPoolRef pool = nullptr;
    const CVReturn status = CVPixelBufferPoolCreate(kCFAllocatorDefault, nullptr, pixel_buffer_attributes, &pool);
    CFRelease(pixel_buffer_attributes);
    return status == kCVReturnSuccess ? pool : nullptr;
  }

  // CVPixelBuffer 池缓冲由 IOSurface 承载，plane 之间存在对齐间隙，整块包装会得到错位的
  // NV12 数据；必须按 plane 复制合并为连续缓冲后再交给 SDK。
  bool MergeSyntheticFrameIntoScratch(CVPixelBufferRef buffer) {
    const size_t y_stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0);
    const size_t uv_stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 1);
    const size_t buffer_height = CVPixelBufferGetHeight(buffer);
    const size_t y_size = y_stride * buffer_height;
    const size_t uv_size = uv_stride * (buffer_height / 2);
    const size_t frame_size = y_size + uv_size;
    if (synthetic_frame_scratch_size_ < frame_size) {
      free(synthetic_frame_scratch_);
      synthetic_frame_scratch_ = static_cast<uint8_t*>(malloc(frame_size));
      synthetic_frame_scratch_size_ = synthetic_frame_scratch_ != nullptr ? frame_size : 0;
    }
    if (synthetic_frame_scratch_ == nullptr) {
      return false;
    }
    memcpy(synthetic_frame_scratch_, CVPixelBufferGetBaseAddressOfPlane(buffer, 0), y_size);
    memcpy(synthetic_frame_scratch_ + y_size, CVPixelBufferGetBaseAddressOfPlane(buffer, 1), uv_size);
    return true;
  }

  void PumpSyntheticFrame() {
    if (!synthetic_active_ || engine_ == nil || (synthetic_pool_ == nullptr && synthetic_clip_ == nil)) {
      return;
    }
    @autoreleasepool {
      CVPixelBufferRef buffer = synthetic_clip_ == nil ? nullptr : [synthetic_clip_ copyNextFrame];
      if (buffer == nullptr && synthetic_pool_ != nullptr &&
          CVPixelBufferPoolCreatePixelBuffer(kCFAllocatorDefault, synthetic_pool_, &buffer) != kCVReturnSuccess) {
        return;
      }
      if (buffer == nullptr) {
        HandleSyntheticFrameFailure();
        return;
      }
      CVPixelBufferLockBaseAddress(buffer, 0);
      if (synthetic_clip_ == nil) {
        RenderSyntheticFrame(buffer);
      }
      if (!MergeSyntheticFrameIntoScratch(buffer)) {
        CVPixelBufferUnlockBaseAddress(buffer, 0);
        CVPixelBufferRelease(buffer);
        return;
      }
      if (synthetic_frame_index_ == 0) {
        const char* dump_path = std::getenv("BEACON_SYNTHETIC_FRAME_DUMP");
        if (dump_path != nullptr && dump_path[0] != '\0') {
          FILE* dump = fopen(dump_path, "wb");
          if (dump != nullptr) {
            fwrite(synthetic_frame_scratch_, 1, synthetic_frame_scratch_size_, dump);
            fclose(dump);
          }
        }
      }
      AgoraVideoFrame* frame = [[AgoraVideoFrame alloc] init];
      frame.format = 8;  // NV12
      frame.strideInPixels = static_cast<int>(CVPixelBufferGetBytesPerRowOfPlane(buffer, 0));
      frame.height = static_cast<int>(CVPixelBufferGetHeight(buffer));
      // SDK 按绝对时间戳做帧调度，相对的小时间戳（从 0 起）会被静默丢弃，必须用主机时钟。
      frame.time = CMClockGetTime(CMClockGetHostTimeClock());
      frame.dataBuf = [NSData dataWithBytesNoCopy:synthetic_frame_scratch_
                                           length:synthetic_frame_scratch_size_
                                    freeWhenDone:NO];
      const BOOL pushed = [engine_ pushExternalVideoFrame:frame videoTrackId:0];
      CVPixelBufferUnlockBaseAddress(buffer, 0);
      CVPixelBufferRelease(buffer);
      LogSyntheticPushResult(pushed != NO);
      synthetic_frame_index_ += 1;
    }
  }

  void HandleSyntheticFrameFailure() {
    synthetic_active_ = false;
    if (engine_ != nil) {
      [engine_ setExternalVideoSource:NO useTexture:NO sourceType:AgoraExternalVideoSourceTypeVideoFrame];
    }
    // 当前在 synthetic_queue_ 的 timer handler 内；不能调用 StopSyntheticVideoInternal，
    // 否则它会 dispatch_sync 回同一队列。仅取消 source，保留同步句柄，交给随后
    // 的 StopSyntheticVideoInternal 在确认本回调退出后统一回收，避免 Reset/析构竞态。
    if (synthetic_timer_ != nullptr) {
      dispatch_source_cancel(synthetic_timer_);
    }
    if (events_ != nullptr) {
      events_->Emit("onError", R"({"code":400,"message":"synthetic video frame decode failed"})");
    }
  }

  void RenderSyntheticFrame(CVPixelBufferRef buffer) {
    const int width = static_cast<int>(CVPixelBufferGetWidth(buffer));
    const int height = static_cast<int>(CVPixelBufferGetHeight(buffer));
    uint8_t* y_plane = static_cast<uint8_t*>(CVPixelBufferGetBaseAddressOfPlane(buffer, 0));
    const size_t y_stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 0);
    uint8_t* uv_plane = static_cast<uint8_t*>(CVPixelBufferGetBaseAddressOfPlane(buffer, 1));
    const size_t uv_stride = CVPixelBufferGetBytesPerRowOfPlane(buffer, 1);
    static const uint8_t kBars[7][3] = {
        {191, 191, 191}, {191, 191, 0}, {0, 191, 191}, {0, 191, 0},
        {191, 0, 191},   {191, 0, 0},   {0, 0, 191},
    };
    const int bar_height = height * 3 / 4;
    for (int y = 0; y < bar_height; ++y) {
      uint8_t* y_row = y_plane + static_cast<size_t>(y) * y_stride;
      uint8_t* uv_row = uv_plane + static_cast<size_t>(y / 2) * uv_stride;
      for (int x = 0; x < width; x += 2) {
        const int bar = x * 7 / width;
        const uint8_t y_value = RgbToY(kBars[bar][0], kBars[bar][1], kBars[bar][2]);
        const uint8_t u_value = RgbToU(kBars[bar][0], kBars[bar][1], kBars[bar][2]);
        const uint8_t v_value = RgbToV(kBars[bar][0], kBars[bar][1], kBars[bar][2]);
        y_row[x] = y_value;
        if (x + 1 < width) {
          y_row[x + 1] = y_value;
        }
        uv_row[x] = u_value;
        uv_row[x + 1] = v_value;
      }
    }
    const int stripe_y = static_cast<int>((synthetic_frame_index_ * 4) % static_cast<int64_t>(height));
    const int stripe_band = height / 40 > 4 ? height / 40 : 4;
    for (int y = bar_height; y < height; ++y) {
      uint8_t* y_row = y_plane + static_cast<size_t>(y) * y_stride;
      uint8_t* uv_row = uv_plane + static_cast<size_t>(y / 2) * uv_stride;
      const bool stripe_row = synthetic_moving_stripe_ && y >= stripe_y && y < stripe_y + stripe_band;
      for (int x = 0; x < width; x += 2) {
        const uint8_t y_value = stripe_row ? 235 : 16;
        y_row[x] = y_value;
        if (x + 1 < width) {
          y_row[x + 1] = y_value;
        }
        uv_row[x] = 128;
        uv_row[x + 1] = 128;
      }
    }
  }

  static uint8_t RgbToY(int r, int g, int b) {
    return static_cast<uint8_t>((66 * r + 129 * g + 25 * b + 16 * 256 + 128) >> 8);
  }

  static uint8_t RgbToU(int r, int g, int b) {
    return static_cast<uint8_t>((-38 * r - 74 * g + 112 * b + 128 * 256 + 128) >> 8);
  }

  static uint8_t RgbToV(int r, int g, int b) {
    return static_cast<uint8_t>((112 * r - 94 * g - 18 * b + 128 * 256 + 128) >> 8);
  }

  SDKLoader* sdk_;
  MediaPermissionCheck has_media_permission_;
  RTCEventBridge* events_;
  ViewRegistry* views_;
  AgoraRtcEngineKit* engine_ = nil;
  BeaconAgoraDelegate* delegate_ = nil;
  BeaconAgoraMediaPlayerDelegate* media_player_delegate_ = nil;
  id<AgoraRtcMediaPlayerProtocol> media_player_ = nil;
  bool initialized_ = false;
  bool joined_ = false;
  bool previewing_ = false;
  bool audio_enabled_ = true;
  bool video_enabled_ = true;
  std::string channel_;
  std::string local_view_id_;
  struct RemoteBinding { NSUInteger uid; };
  std::map<std::string, RemoteBinding> remote_bindings_;
  dispatch_queue_t synthetic_queue_ = nullptr;
  dispatch_source_t synthetic_timer_ = nullptr;
  CVPixelBufferPoolRef synthetic_pool_ = nullptr;
  BeaconSyntheticVideoClip* synthetic_clip_ = nil;
  int synthetic_fps_ = 15;
  bool synthetic_moving_stripe_ = false;
  bool synthetic_active_ = false;
  int64_t synthetic_frame_index_ = 0;
  int64_t synthetic_push_ok_count_ = 0;
  int64_t synthetic_push_failures_ = 0;
  uint8_t* synthetic_frame_scratch_ = nullptr;
  size_t synthetic_frame_scratch_size_ = 0;
  dispatch_queue_t synthetic_audio_queue_ = nullptr;
  dispatch_source_t synthetic_audio_timer_ = nullptr;
  BeaconSyntheticAudioClip* synthetic_audio_clip_ = nil;
  NSInteger synthetic_audio_track_id_ = -1;
  bool media_player_published_ = false;
  bool synthetic_audio_active_ = false;
  int64_t synthetic_audio_push_ok_count_ = 0;
  int64_t synthetic_audio_push_failures_ = 0;
  int64_t synthetic_audio_timestamp_ms_ = 0;
};

}  // namespace

std::unique_ptr<RTCBackend> CreateRealRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission,
                                                 RTCEventBridge* events, ViewRegistry* views) {
  return std::make_unique<RealRTCBackend>(sdk, std::move(has_media_permission), events, views);
}

}  // namespace beacon::mac
