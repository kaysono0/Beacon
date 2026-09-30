// 火山引擎真实 RTC 后端（Objective-C++）。
//
// 实现 Adapter Source 中 mac/supported 的 op：控制面（createRTCEngine / destroyRTCEngine / joinRoom /
// leaveRoom）与画面能力面（startVideoCapture / stopVideoCapture / startSyntheticVideo / stopSyntheticVideo /
// bindLocalVideo / bindRemoteVideo / captureSnapshot / releaseView）；未声明能力显式返回「不支持」，
// 避免"看似可用"的假象。
//
// 职责边界（B-009 标准 / ADR-041）：桥层只把火山原生回调翻译成标准画面证据事件
// （onSnapshotRequested / onSnapshotTaken / onFirstRemoteVideoFrame / onLocalVideoStats /
// onRemoteVideoStats / onRtcStats），判定逻辑不属于这里；事件 payload 带原生函数名与 stream_id 以便溯源。
// 回调按声明的 interface/class 发事件：房间级走 ByteRTCRoomDelegate，引擎级走 ByteRTCEngineDelegate。
//
// 火山远端身份是 stream_id 字符串而非整数 uid：canvas / 快照用 stream_id，
// 证据层 uid 用房间内用户 id 字符串（onRemoteStreamStats.uid / StreamInfo.userId），两者解耦。
#include "rtc/rtc_backend.h"

// 火山 SDK 的头文件按 umbrella 暴露（objc/ 下），只引 umbrella 即可拿到引擎/房间与委托协议。
#import <VolcEngineRTC/VolcEngineRTC.h>

#import <CoreVideo/CoreVideo.h>
#import <Foundation/Foundation.h>

#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <map>
#include <mutex>
#include <string>
#include <utility>
#include <vector>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "rtc/rtc_command_vocabulary.h"
#include "rtc/rtc_event_bridge.h"
#include "video/synthetic_video_clip.h"
#include "video/video_host_visibility.h"
#include "video/view_registry.h"

namespace beacon::mac {

namespace {

NSString* ToNSString(const std::string& value) {
  return [NSString stringWithUTF8String:value.c_str()];
}

std::string ToStdString(NSString* value) {
  return value == nil ? std::string() : std::string([value UTF8String]);
}

// SDK 的 leaveRoom 是异步的：官方要求在收到房间态回调后才能销毁房间或引擎。
// 该信号由房间委托在「离开完成」时触发，供 LeaveChannel/Reset 等待。
struct RoomLeaveSignal {
  std::mutex mutex;
  std::condition_variable cv;
  bool left = false;

  void ResetSignal() {
    std::lock_guard<std::mutex> lock(mutex);
    left = false;
  }

  void Signal() {
    std::lock_guard<std::mutex> lock(mutex);
    left = true;
    cv.notify_all();
  }

  bool WaitFor(int timeout_ms) {
    std::unique_lock<std::mutex> lock(mutex);
    return cv.wait_for(lock, std::chrono::milliseconds(timeout_ms), [this]() { return left; });
  }
};

// 一次快照请求的归属信息：唯一落盘路径在调用前登记，保留原始调用身份。
struct SnapshotRequest {
  std::string view_role;
  std::string artifact_key;
  std::string uid;
  std::string file_path;
  RTCEventBridge::ActiveEngineIdentity origin;
};

struct RemoteBinding {
  std::string uid;
  std::string stream_id;
  bool snapshot_requested = false;
};

// 后端与委托共享的可变状态。委托回调在 SDK 自己的线程执行、op 在调用线程执行，
// 跨线程读写一律经 mutex；on_stream_published 由后端在构造时注入。
struct SharedState {
  mutable std::mutex mutex;  // const 查询方法也要加锁，故为 mutable
  std::string local_uid;  // SDK 的本地流统计没有 uid，桥层补本地用户 id 供证据层对齐
  bool synthetic_active = false;  // 画面来源归一化：0=摄像头，4=合成（与标准模块 source_type 编码一致）
  std::map<std::string, SnapshotRequest> snapshot_requests;  // 唯一文件路径 → 请求信息
  std::map<std::string, std::string> stream_by_uid;      // 远端 publish 通知维护：uid → stream_id
  float tx_video_kbitrate = 0;  // onRtcStats 聚合：最近一次本地发送速率
  float rx_video_kbitrate = 0;  // onRtcStats 聚合：最近一次远端接收速率
  std::map<std::string, RemoteBinding> remote_bindings;  // view_role → 独立发布者画布
  std::function<void(const std::string&)> on_stream_published;
};

std::string GetViewId(const Json::Value& params) {
  const std::string view_id = params.get("view_id", "").asString();
  return view_id.empty() ? params.get("view", "").asString() : view_id;
}

// 火山用户 id 是字符串；兼容测试用例写成数字的情况。
std::string GetUidString(const Json::Value& params) {
  const Json::Value& uid = params["uid"];
  if (uid.isString()) {
    return uid.asString();
  }
  if (uid.isNumeric()) {
    return std::to_string(uid.asUInt64());
  }
  return "";
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

NSString* SnapshotPathForRole(NSString* role) {
  NSString* directory = [[[NSFileManager defaultManager] currentDirectoryPath]
      stringByAppendingPathComponent:@"reports/latest/volcengine_visual_artifacts"];
  [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
  long long timestamp_ms = static_cast<long long>([[NSDate date] timeIntervalSince1970] * 1000.0);
  NSString* file_name = [NSString stringWithFormat:@"sdk-snapshot-%d-%lld-%@.jpg", getpid(), timestamp_ms, role];
  return [directory stringByAppendingPathComponent:file_name];
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

// ByteRTCView 在 macOS 上就是 NSView；SDK 要求画布操作在主线程执行。
int SetupLocalVideoCanvas(ByteRTCEngine* engine, void* handle) {
  __block int code = beacon::kBadRequest;
  void (^setup_block)(void) = ^{
    ByteRTCVideoCanvas* canvas = [[ByteRTCVideoCanvas alloc] init];
    canvas.view = (__bridge NSView*)handle;
    canvas.renderMode = ByteRTCRenderModeHidden;
    code = [engine setLocalVideoCanvas:canvas];
  };
  if ([NSThread isMainThread]) {
    setup_block();
  } else {
    dispatch_sync(dispatch_get_main_queue(), setup_block);
  }
  return code;
}

int SetupRemoteVideoCanvas(ByteRTCEngine* engine, const std::string& stream_id, void* handle) {
  __block int code = beacon::kBadRequest;
  NSString* stream = ToNSString(stream_id);
  void (^setup_block)(void) = ^{
    ByteRTCVideoCanvas* canvas = [[ByteRTCVideoCanvas alloc] init];
    canvas.view = (__bridge NSView*)handle;
    canvas.renderMode = ByteRTCRenderModeHidden;
    code = [engine setRemoteVideoCanvas:stream withCanvas:canvas];
  };
  if ([NSThread isMainThread]) {
    setup_block();
  } else {
    dispatch_sync(dispatch_get_main_queue(), setup_block);
  }
  return code;
}

}  // namespace
}  // namespace beacon::mac

// 引擎级回调：连接态、错误、远端首帧与本地/远端快照结果。事件目标与 sdk_adapters/volcengine_rtc 声明一致。
@interface BeaconVolcengineEngineDelegate : NSObject <ByteRTCEngineDelegate>
- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge
                        shared:(beacon::mac::SharedState*)shared;
@end

// 房间级回调：房间态（加入成功 state=0、离开完成 state=2）、离开、远端流发布通知与音视频流统计。
@interface BeaconVolcengineRoomDelegate : NSObject <ByteRTCRoomDelegate>
- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge
                        signal:(beacon::mac::RoomLeaveSignal*)signal
                        shared:(beacon::mac::SharedState*)shared;
@end

@implementation BeaconVolcengineEngineDelegate {
  beacon::mac::RTCEventBridge* _bridge;
  beacon::mac::SharedState* _shared;
}

- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge
                        shared:(beacon::mac::SharedState*)shared {
  self = [super init];
  if (self) {
    _bridge = bridge;
    _shared = shared;
  }
  return self;
}

- (void)emit:(const std::string&)function payload:(const std::string&)payload {
  if (_bridge != nullptr) {
    _bridge->Emit(function, payload);
  }
}

- (void)rtcEngine:(ByteRTCEngine*)engine onConnectionStateChanged:(ByteRTCConnectionState)state {
  (void)engine;
  if (_bridge == nullptr) {
    return;
  }
  Json::Value payload(Json::objectValue);
  payload["state"] = static_cast<int>(state);
  _bridge->Emit(std::string("onConnectionStateChanged"), beacon::WriteJson(payload));
}

- (void)rtcEngine:(ByteRTCEngine*)engine onError:(ByteRTCErrorCode)errorCode {
  (void)engine;
  if (_bridge == nullptr) {
    return;
  }
  Json::Value payload(Json::objectValue);
  payload["code"] = static_cast<int>(errorCode);
  _bridge->Emit(std::string("onError"), beacon::WriteJson(payload));
}

// 首帧证据：Decoded 与 Rendered 都会到达，任一到达即满足「远端视频收到」；uid 用房间内用户 id。
- (void)emitFirstRemoteVideoFrame:(NSString*)streamId
                             info:(ByteRTCStreamInfo*)info
                    withFrameInfo:(ByteRTCVideoFrameInfo*)frameInfo
                      sdkFunction:(const char*)sdk_function {
  if (_bridge == nullptr) {
    return;
  }
  Json::Value payload(Json::objectValue);
  payload["uid"] = beacon::mac::ToStdString(info.userId);
  payload["stream_id"] = beacon::mac::ToStdString(streamId);
  payload["width"] = Json::Int64(frameInfo.width);
  payload["height"] = Json::Int64(frameInfo.height);
  payload["sdk_function"] = sdk_function;
  [self emit:std::string(beacon::mac::rtc_commands::kFirstRemoteVideoFrameEvent)
     payload:beacon::WriteJson(payload)];
}

- (void)rtcEngine:(ByteRTCEngine*)engine
    onFirstRemoteVideoFrameDecoded:(NSString*)streamId
                              info:(ByteRTCStreamInfo*)info
                     withFrameInfo:(ByteRTCVideoFrameInfo*)frameInfo {
  (void)engine;
  [self emitFirstRemoteVideoFrame:streamId
                             info:info
                    withFrameInfo:frameInfo
                      sdkFunction:"onFirstRemoteVideoFrameDecoded"];
}

- (void)rtcEngine:(ByteRTCEngine*)engine
    onFirstRemoteVideoFrameRendered:(NSString*)streamId
                               info:(ByteRTCStreamInfo*)info
                      withFrameInfo:(ByteRTCVideoFrameInfo*)frameInfo {
  (void)engine;
  [self emitFirstRemoteVideoFrame:streamId
                             info:info
                    withFrameInfo:frameInfo
                      sdkFunction:"onFirstRemoteVideoFrameRendered"];
}

// 快照结果：本地回调没有 streamId/info；按本次唯一路径取得角色与调用身份。
- (void)emitSnapshotTaken:(NSString*)streamId
                     info:(ByteRTCStreamInfo*)info
                 filePath:(NSString*)filePath
                    width:(NSInteger)width
                   height:(NSInteger)height
                errorCode:(ByteRTCSnapshotErrorCode)errorCode
                   taskId:(NSInteger)taskId
              sdkFunction:(const char*)sdk_function {
  if (_bridge == nullptr) {
    return;
  }
  beacon::mac::SnapshotRequest request;
  bool found = false;
  if (_shared != nullptr) {
    std::lock_guard<std::mutex> lock(_shared->mutex);
    const auto it = _shared->snapshot_requests.find(beacon::mac::ToStdString(filePath));
    if (it != _shared->snapshot_requests.end()) {
      request = it->second;
      _shared->snapshot_requests.erase(it);
      found = true;
    }
  }
  if (!found) return;  // reset 后的迟到回调不归入新一轮调用。
  Json::Value payload(Json::objectValue);
  payload["uid"] = found ? request.uid : (info != nil ? beacon::mac::ToStdString(info.userId) : std::string());
  payload["view_role"] = found ? request.view_role : std::string();
  payload["artifact_key"] = found ? request.artifact_key : std::string();
  payload["file_path"] = beacon::mac::ToStdString(filePath);
  payload["width"] = Json::Int64(width);
  payload["height"] = Json::Int64(height);
  payload["err_code"] = static_cast<int>(errorCode);
  payload["task_id"] = Json::Int64(taskId);
  if (streamId != nil) {
    payload["stream_id"] = beacon::mac::ToStdString(streamId);
  }
  payload["sdk_function"] = sdk_function;
  _bridge->Emit(std::string(beacon::mac::rtc_commands::kSnapshotTakenEvent), beacon::WriteJson(payload), request.origin);
}

- (void)rtcEngine:(ByteRTCEngine*)engine
    onLocalSnapshotTakenToFile:(ByteRTCVideoSource*)videoSource
                      filePath:(NSString*)filePath
                         width:(NSInteger)width
                        height:(NSInteger)height
                     errorCode:(ByteRTCSnapshotErrorCode)errorCode
                        taskId:(NSInteger)taskId {
  (void)engine;
  (void)videoSource;
  [self emitSnapshotTaken:nil
                     info:nil
                 filePath:filePath
                    width:width
                   height:height
                errorCode:errorCode
                   taskId:taskId
              sdkFunction:"onLocalSnapshotTakenToFile"];
}

- (void)rtcEngine:(ByteRTCEngine*)engine
    onRemoteSnapshotTakenToFile:(NSString*)streamId
                          info:(ByteRTCStreamInfo*)info
                      filePath:(NSString*)filePath
                         width:(NSInteger)width
                        height:(NSInteger)height
                     errorCode:(ByteRTCSnapshotErrorCode)errorCode
                        taskId:(NSInteger)taskId {
  (void)engine;
  [self emitSnapshotTaken:streamId
                     info:info
                 filePath:filePath
                    width:width
                   height:height
                errorCode:errorCode
                   taskId:taskId
              sdkFunction:"onRemoteSnapshotTakenToFile"];
}

@end

@implementation BeaconVolcengineRoomDelegate {
  beacon::mac::RTCEventBridge* _bridge;
  beacon::mac::RoomLeaveSignal* _leave_signal;
  beacon::mac::SharedState* _shared;
}

- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge*)bridge
                        signal:(beacon::mac::RoomLeaveSignal*)signal
                        shared:(beacon::mac::SharedState*)shared {
  self = [super init];
  if (self) {
    _bridge = bridge;
    _leave_signal = signal;
    _shared = shared;
  }
  return self;
}

- (void)emit:(const std::string&)function payload:(const std::string&)payload {
  if (_bridge != nullptr) {
    _bridge->Emit(function, payload);
  }
}

- (void)rtcRoom:(ByteRTCRoom*)rtcRoom
    onRoomStateChanged:(NSString*)roomId
               withUid:(NSString*)uid
                 state:(NSInteger)state
             extraInfo:(NSString*)extraInfo {
  (void)rtcRoom;
  if (_bridge != nullptr) {
    Json::Value payload(Json::objectValue);
    payload["room_id"] = beacon::mac::ToStdString(roomId);
    payload["uid"] = beacon::mac::ToStdString(uid);
    payload["state"] = static_cast<int>(state);
    // extraInfo 形如 {"elapsed":1187,"join_type":0}；能解析出 elapsed 就带上，作为加入耗时证据。
    Json::Value extra;
    if (beacon::ParseJson(beacon::mac::ToStdString(extraInfo), &extra) && extra.isObject()) {
      payload["elapsed_ms"] = extra.get("elapsed", 0).asInt();
    }
    _bridge->Emit(std::string(beacon::mac::rtc_commands::kJoinChannelSuccessEvent), beacon::WriteJson(payload));
  }
  // state 2 = 离开房间：官方语义下这代表 leaveRoom 真正完成，此后才允许销毁房间/引擎。
  if (_leave_signal != nullptr && state == 2) {
    _leave_signal->Signal();
  }
}

- (void)rtcRoom:(ByteRTCRoom*)rtcRoom onLeaveRoom:(ByteRTCRoomStats*)stats {
  (void)stats;
  if (_bridge != nullptr) {
    Json::Value payload(Json::objectValue);
    payload["room_id"] = beacon::mac::ToStdString([rtcRoom getRoomId]);
    _bridge->Emit(std::string(beacon::mac::rtc_commands::kLeaveRoomEvent), beacon::WriteJson(payload));
  }
  if (_leave_signal != nullptr) {
    _leave_signal->Signal();
  }
}

// 远端流发布通知：维护 uid → stream_id 映射（画布与远端快照需要 stream_id），
// 并通知后端：若绑定早于发布，此刻把等待中的远端画布补上。
- (void)rtcRoom:(ByteRTCRoom*)rtcRoom
    onUserPublishStreamVideo:(NSString*)streamId
                        info:(ByteRTCStreamInfo*)info
                   isPublish:(BOOL)isPublish {
  (void)rtcRoom;
  if (_shared == nullptr || info.isScreen) {
    return;
  }
  const std::string uid = beacon::mac::ToStdString(info.userId);
  std::function<void(const std::string&)> handler;
  {
    std::lock_guard<std::mutex> lock(_shared->mutex);
    if (isPublish) {
      _shared->stream_by_uid[uid] = beacon::mac::ToStdString(streamId);
    } else {
      _shared->stream_by_uid.erase(uid);
    }
    handler = _shared->on_stream_published;
  }
  if (isPublish && handler) {
    handler(uid);
  }
}

// 本地视频统计：SDK 结构里没有 uid，用共享状态里的本地用户 id 补齐；
// source_type 火山无此字段，桥层按当前采集源归一化（0=摄像头，4=合成）。
// 注意 ObjC selector 必须与 SDK 头文件逐参数一致（streamId + info + stats），
// 少一个参数 respondsToSelector 会静默不命中，统计事件会整类消失。
- (void)rtcRoom:(ByteRTCRoom*)rtcRoom
    onLocalStreamStats:(NSString*)streamId
                  info:(ByteRTCStreamInfo*)info
                 stats:(ByteRTCLocalStreamStats*)stats {
  (void)rtcRoom;
  (void)info;
  if (_bridge == nullptr || _shared == nullptr || stats.isScreen) {
    return;
  }
  std::string uid;
  bool synthetic = false;
  {
    std::lock_guard<std::mutex> lock(_shared->mutex);
    uid = _shared->local_uid;
    synthetic = _shared->synthetic_active;
    _shared->tx_video_kbitrate = stats.videoStats.sentKBitrate;
  }
  Json::Value payload(Json::objectValue);
  payload["uid"] = uid;
  payload["sent_bitrate"] = stats.videoStats.sentKBitrate;
  payload["sent_frame_rate"] = Json::Int64(stats.videoStats.sentFrameRate);
  payload["width"] = Json::Int64(stats.videoStats.encodedFrameWidth);
  payload["height"] = Json::Int64(stats.videoStats.encodedFrameHeight);
  payload["source_type"] = synthetic ? 4 : 0;
  payload["stream_id"] = beacon::mac::ToStdString(streamId);
  payload["sdk_function"] = "onLocalStreamStats";
  [self emit:std::string(beacon::mac::rtc_commands::kLocalVideoStatsEvent) payload:beacon::WriteJson(payload)];
  [self emitRtcStatsAggregate];
}

// 远端流统计：selector 与 SDK 一致需带 info 参数，见 onLocalStreamStats 注释。
- (void)rtcRoom:(ByteRTCRoom*)rtcRoom
    onRemoteStreamStats:(NSString*)streamId
                   info:(ByteRTCStreamInfo*)info
                  stats:(ByteRTCRemoteStreamStats*)stats {
  (void)rtcRoom;
  (void)info;
  if (_bridge == nullptr || _shared == nullptr || stats.isScreen) {
    return;
  }
  {
    std::lock_guard<std::mutex> lock(_shared->mutex);
    _shared->rx_video_kbitrate = stats.videoStats.receivedKBitrate;
  }
  Json::Value payload(Json::objectValue);
  payload["uid"] = beacon::mac::ToStdString(stats.uid);
  payload["received_bitrate"] = stats.videoStats.receivedKBitrate;
  payload["decoder_output_frame_rate"] = Json::Int64(stats.videoStats.decoderOutputFrameRate);
  // 火山侧叫 renderOutputFrameRate，标准词汇用 renderer_output_frame_rate。
  payload["renderer_output_frame_rate"] = Json::Int64(stats.videoStats.renderOutputFrameRate);
  payload["width"] = Json::Int64(stats.videoStats.width);
  payload["height"] = Json::Int64(stats.videoStats.height);
  payload["stream_id"] = beacon::mac::ToStdString(streamId);
  payload["sdk_function"] = "onRemoteStreamStats";
  [self emit:std::string(beacon::mac::rtc_commands::kRemoteVideoStatsEvent) payload:beacon::WriteJson(payload)];
  [self emitRtcStatsAggregate];
}

// 会话级收发速率聚合：本地/远端流统计到达时各发一次，供标准模块的 rx/tx 兜底判定。
- (void)emitRtcStatsAggregate {
  if (_bridge == nullptr || _shared == nullptr) {
    return;
  }
  float tx = 0;
  float rx = 0;
  {
    std::lock_guard<std::mutex> lock(_shared->mutex);
    tx = _shared->tx_video_kbitrate;
    rx = _shared->rx_video_kbitrate;
  }
  Json::Value payload(Json::objectValue);
  payload["tx_video_kbitrate"] = tx;
  payload["rx_video_kbitrate"] = rx;
  payload["sdk_function"] = "streamStatsAggregate";
  [self emit:std::string(beacon::mac::rtc_commands::kRtcStatsEvent) payload:beacon::WriteJson(payload)];
}

@end

namespace beacon::mac {

namespace {

class RealVolcengineRTCBackend final : public RTCBackend {
 public:
  RealVolcengineRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission, RTCEventBridge* events,
                           ViewRegistry* views)
      : sdk_(sdk), has_media_permission_(std::move(has_media_permission)), events_(events), views_(views) {
    shared_.on_stream_published = [this](const std::string& uid) { ApplyPendingRemoteCanvas(uid); };
  }

  ~RealVolcengineRTCBackend() override { Unload(); }

  int Load() override {
    @autoreleasepool {
      const char* app_id = std::getenv("VOLCENGINE_RTC_ID");
      if (app_id == nullptr || app_id[0] == '\0' || sdk_ == nullptr || !sdk_->Load()) {
        return beacon::kBadRequest;
      }
      if (engine_ == nil) {
        engine_delegate_ = [[BeaconVolcengineEngineDelegate alloc] initWithBridge:events_ shared:&shared_];
        ByteRTCEngineConfig* config = [[ByteRTCEngineConfig alloc] init];
        config.appID = ToNSString(app_id);
        engine_ = [ByteRTCEngine createRTCEngine:config delegate:engine_delegate_];
        if (engine_ == nil) {
          return beacon::kBadRequest;
        }
        sdk_->Configure(app_id);
      }
      return engine_ != nil ? beacon::kOk : beacon::kBadRequest;
    }
  }

  int Unload() override {
    Reset();
    @autoreleasepool {
      room_ = nil;
      room_delegate_ = nil;
      if (engine_ != nil) {
        engine_.delegate = nil;
        [ByteRTCEngine destroyRTCEngine];
        engine_ = nil;
      }
      // 引擎销毁后才释放 handler（SDK 明确要求 handler 生命周期不短于引擎）。
      engine_delegate_ = nil;
      room_delegate_ = nil;
    }
    if (sdk_ != nullptr) {
      sdk_->Unload();
    }
    return beacon::kOk;
  }

  beacon::CallResult JoinChannel(const beacon::CallData& call) override {
    if (ShouldDenyMediaPermissionForTesting(call) || !HasMediaPermission()) {
      return {kPermissionDenied, "media permission denied", "{}"};
    }
    if (engine_ == nil && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    @autoreleasepool {
      Json::Value params;
      beacon::ParseJson(call.params_json, &params);
      const std::string room_id = params.get("room_id", "").asString();
      const std::string user_id = params.get("user_id", "").asString();
      const std::string token = params.get("token", "").asString();
      if (room_id.empty() || user_id.empty()) {
        return {beacon::kBadRequest, "missing room_id or user_id", "{}"};
      }
      if (ShouldRejectTokenForTesting(call)) {
        return {beacon::kUnauthorized, "invalid token", "{}"};
      }
      if (room_ == nil) {
        room_ = [engine_ createRTCRoom:ToNSString(room_id)];
        if (room_ == nil) {
          return {beacon::kBadRequest, "createRTCRoom failed", "{}"};
        }
        room_delegate_ = [[BeaconVolcengineRoomDelegate alloc] initWithBridge:events_
                                                                       signal:&leave_signal_
                                                                       shared:&shared_];
        room_.delegate = room_delegate_;
      }
      ByteRTCUserInfo* user_info = [[ByteRTCUserInfo alloc] init];
      user_info.userId = ToNSString(user_id);
      ByteRTCRoomConfig* room_config = [[ByteRTCRoomConfig alloc] init];
      // 默认保持 L1 行为（发布音频、不发布视频），画面用例按参数显式打开视频发布/订阅。
      room_config.isPublishAudio = params.get("publish_audio", true).asBool();
      room_config.isPublishVideo = params.get("publish_video", false).asBool();
      room_config.isAutoSubscribeAudio = params.get("auto_subscribe_audio", true).asBool();
      room_config.isAutoSubscribeVideo = params.get("auto_subscribe_video", false).asBool();
      const int join_code = [room_ joinRoom:ToNSString(token)
                                   userInfo:user_info
                             userVisibility:YES
                                 roomConfig:room_config];
      if (join_code != 0) {
        return {join_code, "joinRoom failed", "{}"};
      }
      joined_ = true;
      room_id_ = room_id;
      {
        std::lock_guard<std::mutex> lock(shared_.mutex);
        shared_.local_uid = user_id;
      }
      // 事件必须绑定到发起调用的 run/case/step，否则服务端按 trace 查不到该 callback 证据。
      if (events_ != nullptr) {
        const std::string identity = ResolveEngineIdentity(call);
        events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
      }
      return {beacon::kOk, "joined", "{\"joined\":true}"};
    }
  }

  beacon::CallResult LeaveChannel(const beacon::CallData& call) override {
    // 离开期间 SDK 会回调 onLeaveRoom / 房间态 state=2，事件必须携带**本次调用**的
    // run/case/step，否则会被归因到 join 步骤、在 leave 步骤里查不到证据。
    StopSyntheticVideoInternal();
    const int release_code = ReleaseVideoViews();
    if (release_code != beacon::kOk) return {release_code, "video cleanup failed", "{}"};
    ReleaseRoom(&call);
    joined_ = false;
    room_id_.clear();
    return {beacon::kOk, "left", "{\"left\":true}"};
  }

  beacon::CallResult LeaveChannel() override {
    StopSyntheticVideoInternal();
    const int release_code = ReleaseVideoViews();
    if (release_code != beacon::kOk) return {release_code, "video cleanup failed", "{}"};
    ReleaseRoom(nullptr);
    joined_ = false;
    room_id_.clear();
    return {beacon::kOk, "left", "{\"left\":true}"};
  }

  // 把随后的回调事件归因到本次调用：创建引擎时的连接态、join/leave 时的房间态都依赖它。
  void AttributeCallbacksTo(const beacon::CallData& call) override {
    if (events_ == nullptr) {
      return;
    }
    const std::string identity = ResolveEngineIdentity(call);
    events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
  }

  // startVideoCapture / stopVideoCapture：火山原生采集开关（等价 Agora 的 preview 控制）。
  beacon::CallResult StartPreview(const beacon::CallData& call) override {
    if (ShouldDenyMediaPermissionForTesting(call) || !HasMediaPermission()) {
      return {kPermissionDenied, "media permission denied", "{}"};
    }
    if (engine_ == nil && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    const int code = [engine_ startVideoCapture];
    if (code != 0) {
      return {code, "startVideoCapture failed", "{}"};
    }
    previewing_ = true;
    return {beacon::kOk, "video capture started", ResultJson("capturing", true)};
  }

  beacon::CallResult StopPreview() override {
    if (engine_ == nil && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    const int code = [engine_ stopVideoCapture];
    if (code != 0) {
      return {code, "stopVideoCapture failed", "{}"};
    }
    previewing_ = false;
    return {beacon::kOk, "video capture stopped", ResultJson("capturing", false)};
  }

  beacon::CallResult BindLocalVideo(const beacon::CallData& call) override {
    if (engine_ == nil && Load() != beacon::kOk) {
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
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      for (const auto& binding : shared_.remote_bindings) {
        if (views_->GetHandle(binding.first) == handle) {
          return {beacon::kBadRequest, "view already bound remotely", "{}"};
        }
      }
    }
    const int code = SetupLocalVideoCanvas(engine_, handle);
    if (code != 0) {
      return {code, "setLocalVideoCanvas failed", "{}"};
    }
    local_view_id_ = view_id;
    ShowWindowForHandle(handle);
    Json::Value result(Json::objectValue);
    result["configured"] = true;
    result["view_id"] = view_id;
    return {beacon::kOk, "local video configured", beacon::WriteJson(result)};
  }

  beacon::CallResult BindRemoteVideo(const beacon::CallData& call) override {
    if (engine_ == nil && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_id = GetViewId(params);
    const std::string uid = GetUidString(params);
    if (uid.empty()) {
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
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      for (const auto& binding : shared_.remote_bindings) {
        if (binding.first == view_id && binding.second.uid == uid) continue;
        if (binding.first == view_id || binding.second.uid == uid ||
            views_->GetHandle(binding.first) == handle) {
          return {beacon::kBadRequest, "release remote publisher or view before rebinding", "{}"};
        }
      }
    }
    if (views_->GetHandle(local_view_id_) == handle) {
      return {beacon::kBadRequest, "view already bound locally", "{}"};
    }
    const std::string stream_id = ResolveStreamId(uid);
    if (!stream_id.empty()) {
      const int code = SetupRemoteVideoCanvas(engine_, stream_id, handle);
      if (code != 0) {
        return {code, "setRemoteVideoCanvas failed", "{}"};
      }
    }
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      shared_.remote_bindings[view_id] = RemoteBinding{uid, stream_id, false};
    }
    ApplyPendingRemoteCanvas(uid);
    ShowWindowForHandle(handle);
    Json::Value result(Json::objectValue);
    result["configured"] = true;
    result["view_id"] = view_id;
    result["uid"] = uid;
    if (!stream_id.empty()) {
      result["stream_id"] = stream_id;
    }
    return {beacon::kOk, "remote video configured", beacon::WriteJson(result)};
  }

  beacon::CallResult CaptureSnapshot(const beacon::CallData& call) override {
    if (engine_ == nil && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_role = params.get("view_role", "").asString();
    if (view_role.empty()) {
      return {beacon::kBadRequest, "missing view_role", "{}"};
    }
    // 快照回调是异步的：先归因到本次调用，否则 onSnapshotRequested/Taken 没有 trace。
    RTCEventBridge::ActiveEngineIdentity previous_origin;
    if (events_ != nullptr) {
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
    if (!local_view_id_.empty() && view_role == local_view_id_) {
      void* handle = views_ == nullptr ? nullptr : views_->GetHandle(view_role);
      if (engine_ != nil) {
        const int code = SetupLocalVideoCanvas(engine_, nullptr);
        if (code != 0) return {code, "local canvas release failed", "{}"};
      }
      local_view_id_.clear();
      local_snapshot_requested_ = false;
      HideTileForHandle(handle);
      if (RemoteBindingsEmpty()) {
        HideWindowForHandle(handle);
      }
      released = true;
    }
    RemoteBinding remote;
    bool found = false;
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      const auto it = shared_.remote_bindings.find(view_role);
      if (it != shared_.remote_bindings.end()) {
        remote = it->second;
        shared_.remote_bindings.erase(it);
        found = true;
      }
    }
    if (found) {
      void* handle = views_ == nullptr ? nullptr : views_->GetHandle(view_role);
      if (engine_ != nil && !remote.stream_id.empty()) {
        const int code = SetupRemoteVideoCanvas(engine_, remote.stream_id, nullptr);
        if (code != 0) {
          std::lock_guard<std::mutex> lock(shared_.mutex);
          shared_.remote_bindings[view_role] = remote;
          return {code, "remote canvas release failed", "{}"};
        }
      }
      HideTileForHandle(handle);
      if (local_view_id_.empty() && RemoteBindingsEmpty()) HideWindowForHandle(handle);
      released = true;
    }
    if (released) {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      for (auto it = shared_.snapshot_requests.begin(); it != shared_.snapshot_requests.end();) {
        if (it->second.view_role == view_role) it = shared_.snapshot_requests.erase(it);
        else ++it;
      }
    }
    Json::Value result(Json::objectValue);
    result["released"] = released;
    result["view_role"] = view_role;
    return {beacon::kOk, "view released", beacon::WriteJson(result)};
  }

  // 合成画面源：setVideoSourceType(External) + 固定 fps 推送 NV12 帧（ADR-037 的 SDK 级合成源思路）。
  beacon::CallResult StartSyntheticVideo(const beacon::CallData& call) override {
    if (engine_ == nil && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const int width = params.get("width", 640).asInt();
    const int height = params.get("height", 480).asInt();
    const int fps = params.get("fps", 15).asInt();
    const std::string pattern = params.get("pattern", "animated_clip").asString();
    if (width <= 0 || height <= 0 || fps <= 0 ||
        (pattern != "animated_clip" && pattern != "bars" && pattern != "moving_stripe")) {
      return {beacon::kBadRequest, "invalid synthetic video params", "{}"};
    }
    @autoreleasepool {
      StopSyntheticVideoInternal();
      BeaconSyntheticVideoClip* clip = nil;
      if (pattern == "animated_clip") {
        clip = [[BeaconSyntheticVideoClip alloc] initWithPath:BeaconSyntheticVideoClipPath()];
        if (clip == nil) {
          return {beacon::kBadRequest, "synthetic video clip unavailable", "{}"};
        }
        if (width != [clip width] || height != [clip height]) {
          return {beacon::kBadRequest, "animated clip dimensions do not match request", "{}"};
        }
      }
      const int source_code = [engine_ setVideoSourceType:ByteRTCVideoSourceTypeExternal];
      if (source_code != 0) {
        return {source_code, "setVideoSourceType failed", "{}"};
      }
      CVPixelBufferPoolRef pool = pattern == "animated_clip" ? nullptr : CreateSyntheticPixelBufferPool(width, height);
      if (pattern != "animated_clip" && pool == nullptr) {
        [engine_ setVideoSourceType:ByteRTCVideoSourceTypeInternal];
        return {beacon::kBadRequest, "synthetic video pool creation failed", "{}"};
      }
      synthetic_pool_ = pool;
      synthetic_clip_ = clip;
      synthetic_fps_ = fps;
      synthetic_moving_stripe_ = pattern == "moving_stripe";
      synthetic_active_ = true;
      {
        std::lock_guard<std::mutex> lock(shared_.mutex);
        shared_.synthetic_active = true;
      }
      synthetic_frame_index_ = 0;
      synthetic_queue_ = dispatch_queue_create("beacon.mac.volcengine-synthetic-video", DISPATCH_QUEUE_SERIAL);
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

  void Reset() override {
    StopSyntheticVideoInternal();
    std::map<std::string, RemoteBinding> remote_bindings;
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      remote_bindings.swap(shared_.remote_bindings);
      shared_.stream_by_uid.clear();
      shared_.snapshot_requests.clear();
      shared_.local_uid.clear();
      shared_.tx_video_kbitrate = 0;
      shared_.rx_video_kbitrate = 0;
    }
    void* local_handle = views_ == nullptr || local_view_id_.empty() ? nullptr : views_->GetHandle(local_view_id_);

    if (engine_ != nil) {
      SetupLocalVideoCanvas(engine_, nullptr);
      for (const auto& binding : remote_bindings) {
        if (!binding.second.stream_id.empty()) SetupRemoteVideoCanvas(engine_, binding.second.stream_id, nullptr);
      }
      [engine_ stopVideoCapture];
    }
    HideWindowForHandle(local_handle);
    for (const auto& binding : remote_bindings) {
      HideWindowForHandle(views_ == nullptr ? nullptr : views_->GetHandle(binding.first));
    }
    previewing_ = false;
    local_view_id_.clear();
    local_snapshot_requested_ = false;
    // 不依赖本地 joined_ 标志：只要房间对象存在就按官方时序释放，避免 SDK 实际状态与本地标志失配。
    ReleaseRoom(nullptr);
    joined_ = false;
    room_id_.clear();
    if (events_ != nullptr) {
      events_->ClearActiveEngineIdentity();
    }
  }

  // 由引擎对象派生，不维护本地标志：Unload/Reset 后不会残留过期的「已初始化」状态。
  bool initialized() const override { return engine_ != nil; }
  bool joined() const override { return joined_; }
  bool previewing() const override { return previewing_; }
  std::string channel() const override { return room_id_; }

 private:
  int ReleaseVideoViews() {
    std::vector<std::string> roles;
    if (!local_view_id_.empty()) roles.push_back(local_view_id_);
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      for (const auto& binding : shared_.remote_bindings) roles.push_back(binding.first);
    }
    for (const auto& role : roles) {
      beacon::CallData call;
      Json::Value params(Json::objectValue);
      params["view_role"] = role;
      call.params_json = beacon::WriteJson(params);
      const auto result = ReleaseView(call);
      if (result.error != beacon::kOk) return result.error;
    }
    std::lock_guard<std::mutex> lock(shared_.mutex);
    shared_.snapshot_requests.clear();
    shared_.stream_by_uid.clear();
    return beacon::kOk;
  }

  static constexpr int kLeaveTimeoutMs = 5000;

  bool HasMediaPermission() const {
    return !has_media_permission_ || has_media_permission_();
  }

  std::string LocalUid() const {
    std::lock_guard<std::mutex> lock(shared_.mutex);
    return shared_.local_uid;
  }

  bool RemoteBindingsEmpty() const {
    std::lock_guard<std::mutex> lock(shared_.mutex);
    return shared_.remote_bindings.empty();
  }

  std::string ResolveStreamId(const std::string& uid) const {
    std::lock_guard<std::mutex> lock(shared_.mutex);
    const auto it = shared_.stream_by_uid.find(uid);
    return it == shared_.stream_by_uid.end() ? std::string() : it->second;
  }

  // 远端发布晚于绑定：SDK 回调线程上补画布（画布设置内部切主线程）。
  void ApplyPendingRemoteCanvas(const std::string& uid) {
    if (engine_ == nil) {
      return;
    }
    std::string view_id;
    std::string stream_id;
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      const auto stream = shared_.stream_by_uid.find(uid);
      if (stream == shared_.stream_by_uid.end()) return;
      stream_id = stream->second;
      for (const auto& binding : shared_.remote_bindings) {
        if (binding.second.uid == uid && binding.second.stream_id.empty()) {
          view_id = binding.first;
          break;
        }
      }
    }
    if (view_id.empty() || stream_id.empty()) return;
    // 主线程执行前再核对绑定；reset/release 已删除的 tile 不得被迟到发布重新激活。
    void (^apply)(void) = ^{
      std::lock_guard<std::mutex> lock(shared_.mutex);
      const auto binding = shared_.remote_bindings.find(view_id);
      if (binding == shared_.remote_bindings.end() || binding->second.uid != uid ||
          !binding->second.stream_id.empty()) return;
      void* handle = views_ == nullptr ? nullptr : views_->GetHandle(view_id);
      if (engine_ != nil && handle != nullptr && SetupRemoteVideoCanvas(engine_, stream_id, handle) == 0) {
        binding->second.stream_id = stream_id;
      }
    };
    if ([NSThread isMainThread]) apply();
    else dispatch_sync(dispatch_get_main_queue(), apply);
  }

  // 按官方生命周期释放房间：leaveRoom 是异步的，必须等房间态回调（state 2）或 onLeaveRoom
  // 到达后才能 destroy，否则 SDK 会在自己的消息队列上访问正在拆解的对象（间歇性段错误）。
  // `call` 非空时先把事件身份切到本次调用，使离开回调归因到 leave 步骤。
  void ReleaseRoom(const beacon::CallData* call) {
    if (room_ == nil) {
      return;
    }
    @autoreleasepool {
      if (call != nullptr && events_ != nullptr) {
        const std::string identity = ResolveEngineIdentity(*call);
        events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(*call, identity, identity));
      }
      leave_signal_.ResetSignal();
      [room_ leaveRoom];
      if (!leave_signal_.WaitFor(kLeaveTimeoutMs)) {
        std::cerr << "volcengine backend: leaveRoom did not complete within " << kLeaveTimeoutMs
                  << "ms; destroying the room anyway\n";
      }
      room_.delegate = nil;
      [room_ destroy];
      room_ = nil;
      // room_delegate_ 保持存活到 Unload：SDK 要求 handler 生命周期不短于引擎。
    }
  }

  void EmitSnapshotRequest(const std::string& uid, const std::string& view_role, const std::string& file_path,
                           int return_code, int64_t task_id, const std::string& stream_id,
                           const char* sdk_function) {
    if (events_ == nullptr) {
      return;
    }
    Json::Value request(Json::objectValue);
    request["uid"] = uid;
    request["view_role"] = view_role;
    request["artifact_key"] = view_role;
    request["file_path"] = file_path;
    request["return_code"] = return_code;
    request["task_id"] = Json::Int64(task_id);
    if (!stream_id.empty()) {
      request["stream_id"] = stream_id;
    }
    request["sdk_function"] = sdk_function;
    events_->Emit(std::string(rtc_commands::kSnapshotRequestedEvent), beacon::WriteJson(request));
  }

  void RequestLocalSnapshot(const std::string& view_role) {
    NSString* file_path = SnapshotPathForRole([[NSUUID UUID] UUIDString]);
    RegisterSnapshotRequest(view_role, LocalUid(), file_path);
    __block NSInteger task_id = -1;
    if ([NSThread isMainThread]) {
      task_id = [engine_ takeLocalSnapshotToFile:file_path];
    } else {
      dispatch_sync(dispatch_get_main_queue(), ^{
        task_id = [engine_ takeLocalSnapshotToFile:file_path];
      });
    }
    // 火山返回的是任务编号（从 1 起）：证据层的 return_code 语义是「调用是否被受理」，成功归一化为 0。
    if (task_id < 1) {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      shared_.snapshot_requests.erase(ToStdString(file_path));
    }
    const int return_code = task_id >= 1 ? 0 : static_cast<int>(task_id);
    EmitSnapshotRequest(LocalUid(), view_role, ToStdString(file_path), return_code, static_cast<int64_t>(task_id),
                        std::string(), "takeLocalSnapshotToFile");
  }

  void RequestRemoteSnapshot(const std::string& view_role, const std::string& uid, const std::string& stream_id) {
    NSString* file_path = SnapshotPathForRole([[NSUUID UUID] UUIDString]);
    RegisterSnapshotRequest(view_role, uid, file_path);
    __block NSInteger task_id = -1;
    NSString* stream = ToNSString(stream_id);
    if ([NSThread isMainThread]) {
      task_id = [engine_ takeRemoteSnapshotToFile:stream filePath:file_path];
    } else {
      dispatch_sync(dispatch_get_main_queue(), ^{
        task_id = [engine_ takeRemoteSnapshotToFile:stream filePath:file_path];
      });
    }
    if (task_id < 1) {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      shared_.snapshot_requests.erase(ToStdString(file_path));
    }
    const int return_code = task_id >= 1 ? 0 : static_cast<int>(task_id);
    EmitSnapshotRequest(uid, view_role, ToStdString(file_path), return_code, static_cast<int64_t>(task_id), stream_id,
                        "takeRemoteSnapshotToFile");
  }

  void RegisterSnapshotRequest(const std::string& view_role, const std::string& uid,
                               NSString* file_path) {
    const auto origin = events_ == nullptr ? RTCEventBridge::ActiveEngineIdentity{} : events_->active_engine_identity();
    std::lock_guard<std::mutex> lock(shared_.mutex);
    shared_.snapshot_requests[ToStdString(file_path)] =
        SnapshotRequest{view_role, view_role, uid, ToStdString(file_path), origin};
  }

  bool RequestVisualSnapshot(const std::string& role) {
    if (!joined_) {
      return false;
    }
    if (!local_view_id_.empty() && role == local_view_id_ && !local_snapshot_requested_) {
      local_snapshot_requested_ = true;
      RequestLocalSnapshot(role);
      return true;
    }
    RemoteBinding remote;
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      const auto it = shared_.remote_bindings.find(role);
      if (it == shared_.remote_bindings.end() || it->second.snapshot_requested || it->second.stream_id.empty()) {
        return false;
      }
      it->second.snapshot_requested = true;
      remote = it->second;
    }
    RequestRemoteSnapshot(role, remote.uid, remote.stream_id);
    return true;
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
    if (engine_ != nil && synthetic_active_) {
      [engine_ setVideoSourceType:ByteRTCVideoSourceTypeInternal];
    }
    synthetic_active_ = false;
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      shared_.synthetic_active = false;
    }
    synthetic_frame_index_ = 0;
    synthetic_push_ok_count_ = 0;
    synthetic_push_failures_ = 0;
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
      const int width = static_cast<int>(CVPixelBufferGetWidth(buffer));
      const int height = static_cast<int>(CVPixelBufferGetHeight(buffer));
      ByteRTCVideoFrameData* frame = [[ByteRTCVideoFrameData alloc] init];
      frame.bufferType = ByteRTCVideoBufferTypeCVPixelBuffer;
      frame.pixelFormat = ByteRTCVideoPixelFormatNV12;
      frame.width = width;
      frame.height = height;
      // SDK 按绝对时间戳做帧调度，相对的小时间戳（从 0 起）会被静默丢弃，必须用主机时钟。
      frame.timestamp = CMClockGetTime(CMClockGetHostTimeClock());
      frame.cvpixelbuffer = buffer;
      const int code = [engine_ pushExternalVideoFrame:frame];
      CVPixelBufferUnlockBaseAddress(buffer, 0);
      CVPixelBufferRelease(buffer);
      LogSyntheticPushResult(code == 0);
      synthetic_frame_index_ += 1;
    }
  }

  void HandleSyntheticFrameFailure() {
    synthetic_active_ = false;
    {
      std::lock_guard<std::mutex> lock(shared_.mutex);
      shared_.synthetic_active = false;
    }
    if (engine_ != nil) {
      [engine_ setVideoSourceType:ByteRTCVideoSourceTypeInternal];
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

  bool ShouldDenyMediaPermissionForTesting(const beacon::CallData& call) const {
    Json::Value extra;
    if (!beacon::ParseJson(call.extra_json, &extra) || !extra.isObject()) {
      return false;
    }
    return extra.get("permission_fixture", "").asString() == "deny_media_for_testing";
  }

  bool ShouldRejectTokenForTesting(const beacon::CallData& call) const {
    Json::Value extra;
    if (!beacon::ParseJson(call.extra_json, &extra) || !extra.isObject()) {
      return false;
    }
    return extra.get("token_fixture", "").asString() == "invalid_for_testing";
  }

  SDKLoader* sdk_;
  MediaPermissionCheck has_media_permission_;
  RTCEventBridge* events_;
  ViewRegistry* views_;
  ByteRTCEngine* engine_ = nil;
  ByteRTCRoom* room_ = nil;
  BeaconVolcengineEngineDelegate* engine_delegate_ = nil;
  BeaconVolcengineRoomDelegate* room_delegate_ = nil;
  RoomLeaveSignal leave_signal_;
  SharedState shared_;
  bool joined_ = false;
  bool previewing_ = false;
  std::string room_id_;
  std::string local_view_id_;
  bool local_snapshot_requested_ = false;
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
};

}  // namespace

std::unique_ptr<RTCBackend> CreateRealRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission,
                                                 RTCEventBridge* events, ViewRegistry* views) {
  return std::make_unique<RealVolcengineRTCBackend>(sdk, std::move(has_media_permission), events, views);
}

}  // namespace beacon::mac
