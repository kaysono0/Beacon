#include "rtc/rtc_backend.h"

#include <utility>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "rtc/rtc_event_bridge.h"
#include "video/view_registry.h"

namespace beacon::mac {

namespace {

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

std::string GetViewId(const Json::Value& params) {
  const std::string view_id = params.get("view_id", "").asString();
  return view_id.empty() ? params.get("view", "").asString() : view_id;
}

int GetUid(const Json::Value& params) {
  return params.get("uid", 0).asInt();
}

class MockRTCBackend final : public RTCBackend {
 public:
  MockRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission, RTCEventBridge* events, ViewRegistry* views)
      : sdk_(sdk),
        has_media_permission_(std::move(has_media_permission)),
        events_(events),
        views_(views) {}

  int Load() override {
    if (sdk_ == nullptr || !sdk_->Load()) {
      return beacon::kBadRequest;
    }
    initialized_ = true;
    return beacon::kOk;
  }

  int Unload() override {
    Reset();
    if (sdk_ != nullptr) {
      sdk_->Unload();
    }
    return beacon::kOk;
  }

  beacon::CallResult EnableLocalAudio(bool enabled) override {
    audio_enabled_ = enabled;
    return {beacon::kOk, "audio updated", std::string("{\"audio\":") + (enabled ? "true}" : "false}")};
  }

  beacon::CallResult EnableLocalVideo(bool enabled) override {
    video_enabled_ = enabled;
    return {beacon::kOk, "video updated", std::string("{\"video\":") + (enabled ? "true}" : "false}")};
  }

  beacon::CallResult JoinChannel(const beacon::CallData& call) override {
    if (ShouldDenyMediaPermissionForTesting(call) || !HasMediaPermission()) {
      return {kPermissionDenied, "media permission denied", "{}"};
    }
    if (!initialized_ && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    joined_ = true;
    channel_ = params.get("channel", "mock").asString();
    const std::string identity = ResolveEngineIdentity(call);
    if (events_ != nullptr) {
      events_->SuppressJoinSuccessForTesting(ShouldSuppressJoinSuccessForTesting(call));
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
    }
    return {beacon::kOk, "joined", "{\"joined\":true}"};
  }

  beacon::CallResult LeaveChannel() override {
    joined_ = false;
    channel_.clear();
    if (events_ != nullptr) {
      events_->SuppressJoinSuccessForTesting(false);
      events_->ClearActiveEngineIdentity();
    }
    return {beacon::kOk, "left", "{\"left\":true}"};
  }

  beacon::CallResult RenewToken(const beacon::CallData& call) override {
    if (!initialized_) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    if (params.get("token", "").asString().empty()) {
      return {beacon::kBadRequest, "missing token", "{}"};
    }
    return {beacon::kOk, "token renewed", "{\"renewed\":true}"};
  }

  beacon::CallResult BindLocalVideo(const beacon::CallData& call) override {
    if (!initialized_ && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_id = GetViewId(params);
    if (view_id.empty()) {
      return {beacon::kBadRequest, "missing view_id", "{}"};
    }
    if (views_ == nullptr || views_->GetHandle(view_id) == nullptr) {
      return {403, "view handle not found", "{}"};
    }
    local_view_id_ = view_id;
    return {beacon::kOk, "local video configured",
            std::string("{\"configured\":true,\"view_id\":\"") + view_id + "\"}"};
  }

  beacon::CallResult BindRemoteVideo(const beacon::CallData& call) override {
    if (!initialized_ && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_id = GetViewId(params);
    const int uid = GetUid(params);
    if (uid <= 0) {
      return {beacon::kBadRequest, "missing uid", "{}"};
    }
    if (view_id.empty()) {
      return {beacon::kBadRequest, "missing view_id", "{}"};
    }
    if (views_ == nullptr || views_->GetHandle(view_id) == nullptr) {
      return {403, "view handle not found", "{}"};
    }
    remote_view_id_ = view_id;
    remote_uid_ = uid;
    Json::Value result(Json::objectValue);
    result["configured"] = true;
    result["view_id"] = view_id;
    result["uid"] = uid;
    return {beacon::kOk, "remote video configured", beacon::WriteJson(result)};
  }

  beacon::CallResult CaptureSnapshot(const beacon::CallData& call) override {
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string view_role = params.get("view_role", "").asString();
    if (view_role.empty()) {
      return {beacon::kBadRequest, "missing view_role", "{}"};
    }
    if (view_role != local_view_id_ && view_role != remote_view_id_) {
      return {403, "view role not bound", "{}"};
    }
    if (events_ != nullptr) {
      const std::string identity = ResolveEngineIdentity(call);
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
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
      local_view_id_.clear();
      released = true;
    }
    if (view_role == remote_view_id_) {
      remote_view_id_.clear();
      remote_uid_ = 0;
      released = true;
    }
    Json::Value result(Json::objectValue);
    result["released"] = released;
    result["view_role"] = view_role;
    return {beacon::kOk, "view released", beacon::WriteJson(result)};
  }

  beacon::CallResult StartPreview(const beacon::CallData& call) override {
    if (ShouldDenyMediaPermissionForTesting(call) || !HasMediaPermission()) {
      return {kPermissionDenied, "media permission denied", "{}"};
    }
    if (!initialized_ && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    previewing_ = true;
    return {beacon::kOk, "preview started", "{\"previewing\":true}"};
  }

  beacon::CallResult StopPreview() override {
    previewing_ = false;
    return {beacon::kOk, "preview stopped", "{\"previewing\":false}"};
  }

  beacon::CallResult StartSyntheticVideo(const beacon::CallData& call) override {
    if (!initialized_) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const int width = params.get("width", 640).asInt();
    const int height = params.get("height", 480).asInt();
    const int fps = params.get("fps", 15).asInt();
    const std::string pattern = params.get("pattern", "animated_clip").asString();
    if (width <= 0 || height <= 0 || fps <= 0 ||
        (pattern != "animated_clip" && pattern != "paired_media_clip" && pattern != "bars" &&
         pattern != "moving_stripe")) {
      return {beacon::kBadRequest, "invalid synthetic video params", "{}"};
    }
    synthetic_active_ = true;
    return {beacon::kOk, "synthetic video started", "{\"started\":true}"};
  }

  beacon::CallResult StopSyntheticVideo() override {
    const bool was_active = synthetic_active_;
    synthetic_active_ = false;
    return {beacon::kOk, "synthetic video stopped",
            std::string("{\"stopped\":") + (was_active ? "true}" : "false}")};
  }

  beacon::CallResult SetDualStreamMode(const beacon::CallData& call) override {
    if (!initialized_) return {beacon::kBadRequest, "sdk not loaded", "{}"};
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string mode = params.get("mode", "auto").asString();
    if (mode != "auto" && mode != "enabled" && mode != "disabled") {
      return {beacon::kBadRequest, "invalid simulcast mode", "{}"};
    }
    return {beacon::kOk, "dual stream mode updated", std::string("{\"mode\":\"") + mode + "\"}"};
  }

  beacon::CallResult SetRemoteVideoStream(const beacon::CallData& call) override {
    if (!initialized_) return {beacon::kBadRequest, "sdk not loaded", "{}"};
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const int uid = GetUid(params);
    const std::string stream_type = params.get("stream_type", "").asString();
    if (uid <= 0 || (stream_type != "high" && stream_type != "low")) {
      return {beacon::kBadRequest, "invalid remote video stream params", "{}"};
    }
    return {beacon::kOk, "remote video stream updated",
            std::string("{\"uid\":") + std::to_string(uid) + ",\"stream_type\":\"" + stream_type + "\"}"};
  }

  beacon::CallResult GetConnectionState(const beacon::CallData& call) override {
    if (events_ != nullptr && joined_) {
      const std::string identity = ResolveEngineIdentity(call);
      events_->SetActiveEngineIdentity(events_->CaptureActiveEngineIdentity(call, identity, identity));
    }
    return {beacon::kOk, "ok", joined_ ? "{\"state\":\"connected\"}" : "{\"state\":\"idle\"}"};
  }

  void Reset() override {
    initialized_ = false;
    joined_ = false;
    previewing_ = false;
    synthetic_active_ = false;
    audio_enabled_ = true;
    video_enabled_ = true;
    channel_.clear();
    local_view_id_.clear();
    remote_view_id_.clear();
    remote_uid_ = 0;
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
  bool HasMediaPermission() const {
    return !has_media_permission_ || has_media_permission_();
  }

  SDKLoader* sdk_;
  MediaPermissionCheck has_media_permission_;
  RTCEventBridge* events_;
  ViewRegistry* views_;
  bool initialized_ = false;
  bool joined_ = false;
  bool previewing_ = false;
  bool synthetic_active_ = false;
  bool audio_enabled_ = true;
  bool video_enabled_ = true;
  std::string channel_;
  std::string local_view_id_;
  std::string remote_view_id_;
  int remote_uid_ = 0;
};

}  // namespace

std::unique_ptr<RTCBackend> CreateMockRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission,
                                                 RTCEventBridge* events, ViewRegistry* views) {
  return std::make_unique<MockRTCBackend>(sdk, std::move(has_media_permission), events, views);
}

#ifndef BEACON_MAC_REAL_BACKEND
std::unique_ptr<RTCBackend> CreateRealRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission,
                                                 RTCEventBridge* events, ViewRegistry* views) {
  return CreateMockRTCBackend(sdk, std::move(has_media_permission), events, views);
}
#endif

}  // namespace beacon::mac
