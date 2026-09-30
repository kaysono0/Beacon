#include "rtc/rtc_backend.h"

#import <AppKit/AppKit.h>
#import <CoreMedia/CoreMedia.h>
#import <ZegoExpressEngine/ZegoExpressEngine.h>

#include <atomic>
#include <climits>
#include <cstdlib>
#include <mutex>
#include <string>
#include <unordered_map>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "rtc/rtc_event_bridge.h"
#include "video/synthetic_video_clip.h"
#include "video/video_host_visibility.h"
#include "video/view_registry.h"

namespace beacon::mac {
namespace {
std::string String(NSString *s) {
  return s == nil ? "" : std::string(s.UTF8String);
}
NSString *NS(const std::string &s) {
  return [NSString stringWithUTF8String:s.c_str()];
}
std::string Param(const Json::Value &p, const char *key) {
  return p.get(key, "").asString();
}
NSString *SnapshotPath(const std::string &role) {
  NSString *dir = [NSFileManager.defaultManager.currentDirectoryPath
      stringByAppendingPathComponent:@"reports/latest/zego_visual_artifacts"];
  [NSFileManager.defaultManager createDirectoryAtPath:dir
                          withIntermediateDirectories:YES
                                           attributes:nil
                                                error:nil];
  return [dir
      stringByAppendingPathComponent:
          [NSString
              stringWithFormat:@"rendered-view-%d-%lld-%@.jpg", getpid(),
                               (long long)(NSDate.date.timeIntervalSince1970 *
                                           1000),
                               NS(role)]];
}
} // namespace
} // namespace beacon::mac

@interface BeaconZegoEventHandler : NSObject <ZegoEventHandler>
- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge *)bridge;
@end

@interface BeaconZegoCustomCaptureHandler : NSObject <ZegoCustomVideoCaptureHandler>
- (instancetype)initWithReady:(std::atomic_bool *)ready;
@end

@implementation BeaconZegoCustomCaptureHandler {
  std::atomic_bool *_ready;
}
- (instancetype)initWithReady:(std::atomic_bool *)ready {
  if ((self = [super init]))
    _ready = ready;
  return self;
}
- (void)onStart:(ZegoPublishChannel)channel {
  (void)channel;
  _ready->store(true);
}
- (void)onStop:(ZegoPublishChannel)channel {
  (void)channel;
  _ready->store(false);
}
@end
@implementation BeaconZegoEventHandler {
  beacon::mac::RTCEventBridge *_bridge;
}
- (instancetype)initWithBridge:(beacon::mac::RTCEventBridge *)bridge {
  if ((self = [super init]))
    _bridge = bridge;
  return self;
}
- (void)emit:(const char *)name payload:(Json::Value &)p {
  if (_bridge)
    _bridge->Emit(name, beacon::WriteJson(p));
}
- (void)onRoomStateUpdate:(ZegoRoomState)s
                errorCode:(int)e
             extendedData:(NSDictionary *)x
                   roomID:(NSString *)r {
  (void)x;
  Json::Value p(Json::objectValue);
  p["room_id"] = beacon::mac::String(r);
  p["state"] = (int)s;
  p["error_code"] = e;
  [self emit:"onRoomStateUpdate" payload:p];
}
- (void)onRoomStreamUpdate:(ZegoUpdateType)t
                streamList:(NSArray<ZegoStream *> *)list
              extendedData:(NSDictionary *)x
                    roomID:(NSString *)r {
  (void)x;
  for (ZegoStream *stream in list) {
    Json::Value p(Json::objectValue);
    p["room_id"] = beacon::mac::String(r);
    p["update_type"] = (int)t;
    p["stream_id"] = beacon::mac::String(stream.streamID);
    p["user_id"] = beacon::mac::String(stream.user.userID);
    [self emit:"onRoomStreamUpdate" payload:p];
  }
}
- (void)onPublisherStateUpdate:(ZegoPublisherState)s
                     errorCode:(int)e
                  extendedData:(NSDictionary *)x
                      streamID:(NSString *)id_ {
  (void)x;
  Json::Value p(Json::objectValue);
  p["stream_id"] = beacon::mac::String(id_);
  p["state"] = (int)s;
  p["error_code"] = e;
  [self emit:"onPublisherStateUpdate" payload:p];
}
- (void)onPlayerStateUpdate:(ZegoPlayerState)s
                  errorCode:(int)e
               extendedData:(NSDictionary *)x
                   streamID:(NSString *)id_ {
  (void)x;
  Json::Value p(Json::objectValue);
  p["stream_id"] = beacon::mac::String(id_);
  p["state"] = (int)s;
  p["error_code"] = e;
  [self emit:"onPlayerStateUpdate" payload:p];
}
- (void)onPlayerRenderVideoFirstFrame:(NSString *)id_ {
  Json::Value p(Json::objectValue);
  p["stream_id"] = beacon::mac::String(id_);
  [self emit:"onPlayerRenderVideoFirstFrame" payload:p];
}
@end

namespace beacon::mac {
namespace {
class ZegoBackend final : public RTCBackend {
public:
  ZegoBackend(SDKLoader *l, MediaPermissionCheck permission, RTCEventBridge *e,
              ViewRegistry *v)
      : loader_(l), permission_(std::move(permission)), events_(e), views_(v) {}
  int Load() override {
    std::lock_guard<std::mutex> g(mu_);
    if (engine_)
      return beacon::kOk;
    const char *id = getenv("ZEGO_APP_ID");
    const char *sign = getenv("ZEGO_APP_SIGN");
    if (!id || !*id || !sign || !*sign)
      return beacon::kBadRequest;
    char *end = nullptr;
    unsigned long n = strtoul(id, &end, 10);
    if (!end || *end || n > UINT_MAX)
      return beacon::kBadRequest;
    ZegoEngineProfile *p = [ZegoEngineProfile new];
    p.appID = (unsigned int)n;
    p.appSign = [NSString stringWithUTF8String:sign];
    p.scenario = ZegoScenarioStandardVideoCall;
    handler_ = [[BeaconZegoEventHandler alloc] initWithBridge:events_];
    engine_ = [ZegoExpressEngine createEngineWithProfile:p
                                            eventHandler:handler_];
    if (!engine_)
      return beacon::kBadRequest;
    if (loader_) {
      loader_->Configure(id);
      loader_->Load();
    }
    return beacon::kOk;
  }
  int Unload() override {
    Reset();
    return beacon::kOk;
  }
  beacon::CallResult JoinChannel(const beacon::CallData &call) override {
    Json::Value p;
    if (!beacon::ParseJson(call.params_json, &p))
      return {beacon::kBadRequest, "invalid ZEGO room params", "{}"};
    const auto room = Param(p, "room_id"), user = Param(p, "user_id"),
               token = Param(p, "token");
    std::lock_guard<std::mutex> g(mu_);
    if (!engine_)
      return {beacon::kBadRequest, "ZEGO engine not created", "{}"};
    if (room.empty() || user.empty())
      return {beacon::kBadRequest, "missing room_id or user_id", "{}"};
    ZegoRoomConfig *c = [ZegoRoomConfig defaultConfig];
    if (!token.empty())
      c.token = NS(token);
    [engine_ loginRoom:NS(room)
                  user:[ZegoUser userWithUserID:NS(user)]
                config:c];
    room_ = room;
    joined_ = true;
    return {beacon::kOk, "ZEGO loginRoom requested", "{\"requested\":true}"};
  }
  beacon::CallResult LeaveChannel() override {
    std::lock_guard<std::mutex> g(mu_);
    StopLocked();
    if (engine_ && !room_.empty())
      [engine_ logoutRoom:NS(room_)];
    joined_ = false;
    room_.clear();
    return {beacon::kOk, "ZEGO logoutRoom requested", "{\"requested\":true}"};
  }
  beacon::CallResult BindLocalVideo(const beacon::CallData &) override {
    return UnsupportedCapability();
  }
  beacon::CallResult BindRemoteVideo(const beacon::CallData &) override {
    return UnsupportedCapability();
  }
  beacon::CallResult StartPreview(const beacon::CallData &call) override {
    Json::Value p;
    beacon::ParseJson(call.params_json, &p);
    const auto role = Param(p, "view_role");
    if (role.empty())
      return {beacon::kBadRequest, "missing view_role", "{}"};
    if (permission_ && !permission_())
      return {kPermissionDenied, "media permission denied", "{}"};
    std::lock_guard<std::mutex> g(mu_);
    void *h = View(role);
    if (!engine_)
      return {beacon::kBadRequest, "ZEGO engine not created", "{}"};
    if (!h)
      return {403, "view handle not found", "{}"};
    local_canvas_ = [ZegoCanvas canvasWithView:(__bridge ZGView *)h];
    local_canvas_.viewMode = ZegoViewModeAspectFill;
    [engine_ startPreview:local_canvas_];
    local_view_ = role;
    previewing_ = true;
    Show(h);
    return {beacon::kOk, "ZEGO preview started", "{\"previewing\":true}"};
  }
  beacon::CallResult StopPreview() override {
    std::lock_guard<std::mutex> g(mu_);
    if (!engine_)
      return {beacon::kBadRequest, "ZEGO engine not created", "{}"};
    [engine_ stopPreview];
    void *stopped_view = View(local_view_);
    previewing_ = false;
    local_canvas_ = nil;
    local_view_.clear();
    HideIfNoActiveTilesLocked(stopped_view);
    return {beacon::kOk, "ZEGO preview stopped", "{\"previewing\":false}"};
  }
  beacon::CallResult
  StartPublishingStream(const beacon::CallData &call) override {
    Json::Value p;
    beacon::ParseJson(call.params_json, &p);
    const auto stream = Param(p, "stream_id");
    std::lock_guard<std::mutex> g(mu_);
    if (!engine_ || !joined_)
      return {beacon::kBadRequest, "ZEGO room not joined", "{}"};
    if (stream.empty())
      return {beacon::kBadRequest, "missing stream_id", "{}"};
    [engine_ startPublishingStream:NS(stream)];
    published_ = stream;
    return {beacon::kOk, "ZEGO publishing requested", "{\"requested\":true}"};
  }
  beacon::CallResult StopPublishingStream() override {
    std::lock_guard<std::mutex> g(mu_);
    if (engine_)
      [engine_ stopPublishingStream];
    published_.clear();
    return {beacon::kOk, "ZEGO publishing stopped", "{\"stopped\":true}"};
  }
  beacon::CallResult StartPlayingStream(const beacon::CallData &call) override {
    Json::Value p;
    beacon::ParseJson(call.params_json, &p);
    const auto stream = Param(p, "stream_id"), role = Param(p, "view_role");
    std::lock_guard<std::mutex> g(mu_);
    if (!engine_ || !joined_)
      return {beacon::kBadRequest, "ZEGO room not joined", "{}"};
    void *h = View(role);
    if (stream.empty() || role.empty())
      return {beacon::kBadRequest, "missing stream_id or view_role", "{}"};
    if (!h)
      return {403, "view handle not found", "{}"};
    remote_[stream] = role;
    ZegoCanvas *canvas = [ZegoCanvas canvasWithView:(__bridge ZGView *)h];
    canvas.viewMode = ZegoViewModeAspectFill;
    [engine_ startPlayingStream:NS(stream) canvas:canvas];
    Show(h);
    return {beacon::kOk, "ZEGO playing requested", "{\"requested\":true}"};
  }
  beacon::CallResult StopPlayingStream(const beacon::CallData &call) override {
    Json::Value p;
    beacon::ParseJson(call.params_json, &p);
    const auto stream = Param(p, "stream_id");
    std::lock_guard<std::mutex> g(mu_);
    if (stream.empty())
      return {beacon::kBadRequest, "missing stream_id", "{}"};
    if (engine_)
      [engine_ stopPlayingStream:NS(stream)];
    auto playing = remote_.find(stream);
    if (playing != remote_.end()) {
      void *stopped_view = View(playing->second);
      remote_.erase(playing);
      HideIfNoActiveTilesLocked(stopped_view);
    }
    return {beacon::kOk, "ZEGO playing stopped", "{\"stopped\":true}"};
  }
  beacon::CallResult CaptureSnapshot(const beacon::CallData &call) override {
    Json::Value p;
    beacon::ParseJson(call.params_json, &p);
    const auto role = Param(p, "view_role");
    void *h = View(role);
    if (role.empty())
      return {beacon::kBadRequest, "missing view_role", "{}"};
    if (!h)
      return {403, "view handle not found", "{}"};
    __block NSData *data = nil;
    __block NSInteger w = 0, hgt = 0;
    void (^capture)(void) = ^{
      NSView *v = (__bridge NSView *)h;
      NSBitmapImageRep *image =
          [v bitmapImageRepForCachingDisplayInRect:v.bounds];
      [v cacheDisplayInRect:v.bounds toBitmapImageRep:image];
      data = [image representationUsingType:NSBitmapImageFileTypeJPEG
                                 properties:@{}];
      w = image.pixelsWide;
      hgt = image.pixelsHigh;
    };
    if (NSThread.isMainThread)
      capture();
    else
      dispatch_sync(dispatch_get_main_queue(), capture);
    NSString *path = SnapshotPath(role);
    const bool ok = data && [data writeToFile:path atomically:YES];
    Json::Value out(Json::objectValue);
    out["view_role"] = role;
    out["err_code"] = ok ? 0 : -1;
    out["file_path"] = String(path);
    out["width"] = (int)w;
    out["height"] = (int)hgt;
    if (events_)
      events_->Emit("onRenderedViewSnapshot", beacon::WriteJson(out));
    return {ok ? beacon::kOk : beacon::kBadRequest,
            ok ? "rendered view snapshot captured"
               : "rendered view snapshot failed",
            beacon::WriteJson(out)};
  }
  beacon::CallResult ReleaseView(const beacon::CallData &call) override {
    Json::Value p;
    beacon::ParseJson(call.params_json, &p);
    const auto role = Param(p, "view_role");
    if (role.empty())
      return {beacon::kBadRequest, "missing view_role", "{}"};
    std::lock_guard<std::mutex> g(mu_);
    void *released_view = View(role);
    if (role == local_view_) {
      local_view_.clear();
      local_canvas_ = nil;
    }
    for (auto i = remote_.begin(); i != remote_.end();)
      i = i->second == role ? remote_.erase(i) : std::next(i);
    // local 与远端画布共用同一 Host；只有最后一个活动 tile 被释放时才隐藏窗口。
    HideIfNoActiveTilesLocked(released_view);
    return {beacon::kOk, "view released", "{\"released\":true}"};
  }
  beacon::CallResult StartSyntheticVideo(const beacon::CallData &call) override {
    Json::Value params;
    if (!beacon::ParseJson(call.params_json, &params))
      return {beacon::kBadRequest, "invalid ZEGO synthetic video params", "{}"};
    const int width = params.get("width", 0).asInt();
    const int height = params.get("height", 0).asInt();
    const int fps = params.get("fps", 0).asInt();
    const auto pattern = Param(params, "pattern");
    if (width <= 0 || height <= 0 || fps <= 0 || pattern != "animated_clip")
      return {beacon::kBadRequest, "invalid ZEGO synthetic video params", "{}"};

    std::lock_guard<std::mutex> guard(mu_);
    if (!engine_)
      return {beacon::kBadRequest, "ZEGO engine not created", "{}"};
    StopSyntheticVideoLocked();
    BeaconSyntheticVideoClip *clip = [[BeaconSyntheticVideoClip alloc]
        initWithPath:BeaconSyntheticVideoClipPath()];
    if (!clip)
      return {beacon::kBadRequest, "synthetic video clip unavailable", "{}"};
    ZegoCustomVideoCaptureConfig *config = [ZegoCustomVideoCaptureConfig new];
    config.bufferType = ZegoVideoBufferTypeCVPixelBuffer;
    capture_handler_ = [[BeaconZegoCustomCaptureHandler alloc] initWithReady:&capture_ready_];
    [engine_ setCustomVideoCaptureHandler:capture_handler_];
    [engine_ enableCustomVideoCapture:YES config:config];
    // 自定义采集接管像素帧，仍须显式允许 ZEGO 对该帧编码与发布。
    [engine_ enableCamera:YES];
    synthetic_clip_ = clip;
    synthetic_fps_ = fps;
    synthetic_frame_index_ = 0;
    synthetic_active_.store(true);
    synthetic_queue_ = dispatch_queue_create("beacon.mac.zego.synthetic-video", DISPATCH_QUEUE_SERIAL);
    synthetic_timer_ = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, synthetic_queue_);
    if (!synthetic_timer_) {
      StopSyntheticVideoLocked();
      return {beacon::kBadRequest, "synthetic video timer creation failed", "{}"};
    }
    const int64_t interval = NSEC_PER_SEC / static_cast<int64_t>(fps);
    dispatch_source_set_timer(synthetic_timer_, dispatch_time(DISPATCH_TIME_NOW, interval / 10), interval,
                              interval / 10);
    dispatch_source_set_event_handler(synthetic_timer_, ^{ SendSyntheticFrame(); });
    dispatch_resume(synthetic_timer_);
    return {beacon::kOk, "ZEGO synthetic video configured", "{\"started\":true}"};
  }
  beacon::CallResult StopSyntheticVideo() override {
    std::lock_guard<std::mutex> guard(mu_);
    const bool was_active = synthetic_active_.load();
    StopSyntheticVideoLocked();
    return {beacon::kOk, "ZEGO synthetic video stopped",
            was_active ? "{\"stopped\":true}" : "{\"stopped\":false}"};
  }
  void AttributeCallbacksTo(const beacon::CallData &c) override {
    if (events_)
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(
          c, "zego_engine", "zego_engine_1"));
  }
  void Reset() override {
    std::lock_guard<std::mutex> g(mu_);
    StopLocked();
    StopSyntheticVideoLocked();
    if (engine_ && !room_.empty())
      [engine_ logoutRoom:NS(room_)];
    if (engine_)
      [ZegoExpressEngine destroyEngine:nil];
    engine_ = nil;
    handler_ = nil;
    local_canvas_ = nil;
    joined_ = previewing_ = false;
    room_.clear();
    local_view_.clear();
    remote_.clear();
    if (loader_)
      loader_->Unload();
  }
  bool initialized() const override {
    std::lock_guard<std::mutex> g(mu_);
    return engine_ != nil;
  }
  bool joined() const override {
    std::lock_guard<std::mutex> g(mu_);
    return joined_;
  }
  bool previewing() const override {
    std::lock_guard<std::mutex> g(mu_);
    return previewing_;
  }
  std::string channel() const override {
    std::lock_guard<std::mutex> g(mu_);
    return room_;
  }

private:
  void HideIfNoActiveTilesLocked(void *released_view) {
    HideTile(released_view);
    if (local_view_.empty() && remote_.empty())
      HideWindow(released_view);
  }

  void *View(const std::string &role) const {
    return views_ ? views_->GetHandle(role) : nullptr;
  }
  void Show(void *handle) {
    if (!handle)
      return;
    dispatch_async(dispatch_get_main_queue(), ^{
      NSView *view = (__bridge NSView *)handle;
      [view setHidden:NO];
      [view.superview setNeedsLayout:YES];
      [view.superview layoutSubtreeIfNeeded];
      NSWindow *win = view.window;
      if (win && ShouldShowVideoHostFromEnvironment())
        [win orderFrontRegardless];
    });
  }
  void HideTile(void *handle) {
    if (!handle)
      return;
    void (^hide)(void) = ^{
      NSView *view = (__bridge NSView *)handle;
      [view setHidden:YES];
      [view.superview setNeedsLayout:YES];
    };
    if (NSThread.isMainThread)
      hide();
    else
      dispatch_sync(dispatch_get_main_queue(), hide);
  }
  void HideWindow(void *handle) {
    if (!handle)
      return;
    void (^hide)(void) = ^{
      NSView *view = (__bridge NSView *)handle;
      [view setHidden:YES];
      [view.superview setNeedsLayout:YES];
      NSWindow *win = view.window;
      if (win)
        [win orderOut:nil];
    };
    if (NSThread.isMainThread)
      hide();
    else
      dispatch_sync(dispatch_get_main_queue(), hide);
  }
  void StopLocked() {
    if (!engine_)
      return;
    void *video_host = View(local_view_);
    if (!video_host && !remote_.empty())
      video_host = View(remote_.begin()->second);
    for (const auto &x : remote_) {
      [engine_ stopPlayingStream:NS(x.first)];
      HideTile(View(x.second));
    }
    if (!published_.empty())
      [engine_ stopPublishingStream];
    [engine_ stopPreview];
    HideTile(View(local_view_));
    HideWindow(video_host);
    published_.clear();
    remote_.clear();
    previewing_ = false;
  }
  void SendSyntheticFrame() {
    if (!synthetic_active_.load() || !capture_ready_.load() || !engine_ || !synthetic_clip_)
      return;
    CVPixelBufferRef frame = [synthetic_clip_ copyNextFrame];
    if (!frame)
      return;
    [engine_ sendCustomVideoCapturePixelBuffer:frame
                                     timestamp:CMTimeMake(synthetic_frame_index_++, synthetic_fps_)];
    CFRelease(frame);
  }
  void StopSyntheticVideoLocked() {
    synthetic_active_.store(false);
    capture_ready_.store(false);
    if (synthetic_timer_) {
      dispatch_source_cancel(synthetic_timer_);
      if (synthetic_queue_)
        dispatch_sync(synthetic_queue_, ^{});
      synthetic_timer_ = nil;
    }
    synthetic_queue_ = nil;
    if (engine_) {
      [engine_ setCustomVideoCaptureHandler:nil];
      [engine_ enableCustomVideoCapture:NO config:nil];
    }
    capture_handler_ = nil;
    synthetic_clip_ = nil;
    synthetic_fps_ = 0;
    synthetic_frame_index_ = 0;
  }
  SDKLoader *loader_;
  MediaPermissionCheck permission_;
  RTCEventBridge *events_;
  ViewRegistry *views_;
  mutable std::mutex mu_;
  ZegoExpressEngine *engine_ = nil;
  BeaconZegoEventHandler *handler_ = nil;
  ZegoCanvas *local_canvas_ = nil;
  BeaconZegoCustomCaptureHandler *capture_handler_ = nil;
  BeaconSyntheticVideoClip *synthetic_clip_ = nil;
  bool joined_ = false, previewing_ = false;
  std::atomic_bool synthetic_active_{false};
  std::atomic_bool capture_ready_{false};
  dispatch_queue_t synthetic_queue_ = nil;
  dispatch_source_t synthetic_timer_ = nil;
  int synthetic_fps_ = 0;
  int64_t synthetic_frame_index_ = 0;
  std::string room_, local_view_, published_;
  std::unordered_map<std::string, std::string> remote_;
};
} // namespace
std::unique_ptr<RTCBackend> CreateRealRTCBackend(SDKLoader *l,
                                                 MediaPermissionCheck p,
                                                 RTCEventBridge *e,
                                                 ViewRegistry *v) {
  return std::make_unique<ZegoBackend>(l, std::move(p), e, v);
}
} // namespace beacon::mac
