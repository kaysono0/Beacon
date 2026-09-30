// 火山变体的 mock RTC backend。实现声明中 mac/supported 的 op：控制面
// （createRTCEngine / destroyRTCEngine / joinRoom / leaveRoom）与画面能力面
// （bindLocalVideo / bindRemoteVideo / captureSnapshot / releaseView /
// startVideoCapture / stopVideoCapture / startSyntheticVideo / stopSyntheticVideo）；
// 其余 RTCBackend 方法属于未声明能力，返回不支持，避免"看似可用"的假象。
// mock 只做确定性状态与参数校验，不伪造 SDK 回调证据事件（真实 SDK 才会发快照/统计证据）。
#include "rtc/rtc_backend.h"

#include <string>
#include <utility>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "rtc/rtc_command_vocabulary.h"
#include "rtc/rtc_event_bridge.h"
#include "video/view_registry.h"

namespace beacon::mac {

namespace {

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

bool ShouldRejectTokenForTesting(const beacon::CallData& call) {
  Json::Value extra;
  if (!beacon::ParseJson(call.extra_json, &extra) || !extra.isObject()) {
    return false;
  }
  return extra.get("token_fixture", "").asString() == "invalid_for_testing";
}

std::string GetViewId(const Json::Value& params) {
  const std::string view_id = params.get("view_id", "").asString();
  return view_id.empty() ? params.get("view", "").asString() : view_id;
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

class MockVolcengineRTCBackend final : public RTCBackend {
 public:
  MockVolcengineRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission, RTCEventBridge* events,
                           ViewRegistry* views)
      : sdk_(sdk), has_media_permission_(std::move(has_media_permission)), events_(events), views_(views) {}

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

  beacon::CallResult JoinChannel(const beacon::CallData& call) override {
    if (ShouldDenyMediaPermissionForTesting(call) || !HasMediaPermission()) {
      return {kPermissionDenied, "media permission denied", "{}"};
    }
    if (!initialized_ && Load() != beacon::kOk) {
      return {beacon::kBadRequest, "sdk not loaded", "{}"};
    }
    if (ShouldRejectTokenForTesting(call)) {
      return {beacon::kUnauthorized, "invalid token", "{}"};
    }
    Json::Value params;
    beacon::ParseJson(call.params_json, &params);
    const std::string room_id = params.get("room_id", "").asString();
    const std::string user_id = params.get("user_id", "").asString();
    if (room_id.empty() || user_id.empty()) {
      return {beacon::kBadRequest, "missing room_id or user_id", "{}"};
    }
    joined_ = true;
    room_id_ = room_id;
    user_id_ = user_id;
    if (events_ != nullptr) {
      events_->SuppressJoinSuccessForTesting(ShouldSuppressJoinSuccessForTesting(call));
      if (!ShouldSuppressJoinSuccessForTesting(call)) {
        // 与真实 SDK 一致：只报房间态（0 = 加入成功）。连接态回调在火山侧记为 unsupported，
        // 真实 SDK 在该路径不发出，mock 不得伪造。
        Json::Value payload(Json::objectValue);
        payload["room_id"] = room_id_;
        payload["uid"] = user_id_;
        payload["state"] = 0;
        payload["elapsed_ms"] = 0;
        events_->Emit(std::string(rtc_commands::kJoinChannelSuccessEvent), beacon::WriteJson(payload));
      }
    }
    return {beacon::kOk, "joined", "{\"joined\":true}"};
  }

  beacon::CallResult LeaveChannel() override {
    const std::string room_id = room_id_;
    const std::string user_id = user_id_;
    joined_ = false;
    room_id_.clear();
    user_id_.clear();
    if (events_ != nullptr) {
      events_->SuppressJoinSuccessForTesting(false);
      if (!room_id.empty()) {
        // 与真实 SDK 一致：leaveRoom 返回后 onLeaveRoom 与房间态 state=2 都会到达。
        Json::Value leave_payload(Json::objectValue);
        leave_payload["room_id"] = room_id;
        events_->Emit(std::string(rtc_commands::kLeaveRoomEvent), beacon::WriteJson(leave_payload));
        Json::Value room_state(Json::objectValue);
        room_state["room_id"] = room_id;
        room_state["uid"] = user_id;
        room_state["state"] = 2;
        events_->Emit(std::string(rtc_commands::kJoinChannelSuccessEvent), beacon::WriteJson(room_state));
      }
    }
    return {beacon::kOk, "left", "{\"left\":true}"};
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
    const std::string uid = GetUidString(params);
    if (uid.empty()) {
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
      remote_uid_.clear();
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
    return {beacon::kOk, "video capture started", "{\"capturing\":true}"};
  }

  beacon::CallResult StopPreview() override {
    previewing_ = false;
    return {beacon::kOk, "video capture stopped", "{\"capturing\":false}"};
  }

  beacon::CallResult StartSyntheticVideo(const beacon::CallData& call) override {
    if (!initialized_ && Load() != beacon::kOk) {
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
    synthetic_active_ = true;
    return {beacon::kOk, "synthetic video started", "{\"started\":true}"};
  }

  beacon::CallResult StopSyntheticVideo() override {
    const bool was_active = synthetic_active_;
    synthetic_active_ = false;
    return {beacon::kOk, "synthetic video stopped",
            std::string("{\"stopped\":") + (was_active ? "true}" : "false}")};
  }

  beacon::CallResult GetConnectionState(const beacon::CallData&) override {
    return {beacon::kOk, "ok", joined_ ? "{\"state\":1}" : "{\"state\":0}"};
  }

  void Reset() override {
    initialized_ = false;
    joined_ = false;
    previewing_ = false;
    synthetic_active_ = false;
    local_view_id_.clear();
    remote_view_id_.clear();
    remote_uid_.clear();
    room_id_.clear();
    user_id_.clear();
    if (events_ != nullptr) {
      events_->SuppressJoinSuccessForTesting(false);
      events_->ClearActiveEngineIdentity();
    }
  }

  bool initialized() const override { return initialized_; }
  bool joined() const override { return joined_; }
  bool previewing() const override { return previewing_; }
  std::string channel() const override { return room_id_; }

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
  std::string room_id_;
  std::string user_id_;
  std::string local_view_id_;
  std::string remote_view_id_;
  std::string remote_uid_;
};

}  // namespace

std::unique_ptr<RTCBackend> CreateMockRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission,
                                                 RTCEventBridge* events, ViewRegistry* views) {
  return std::make_unique<MockVolcengineRTCBackend>(sdk, std::move(has_media_permission), events, views);
}

#ifndef BEACON_MAC_REAL_BACKEND
std::unique_ptr<RTCBackend> CreateRealRTCBackend(SDKLoader* sdk, MediaPermissionCheck has_media_permission,
                                                 RTCEventBridge* events, ViewRegistry* views) {
  return CreateMockRTCBackend(sdk, std::move(has_media_permission), events, views);
}
#endif

}  // namespace beacon::mac
