#pragma once

#include <functional>

namespace beacon::mac {

enum class PermissionState {
  kGranted,
  kDenied,
  kNotDetermined,
  kRestricted,
};

enum class MediaPermission {
  kCamera,
  kMicrophone,
  kScreenCapture,
};

// 查询平台权限；请求异步完成，不在主线程等待系统授权弹窗。
// mock 与 real 分别装配固定测试权限和真实系统权限边界。
class PermissionManager {
 public:
  using Completion = std::function<void(PermissionState)>;
  using StatusReader = std::function<PermissionState(MediaPermission)>;
  using AccessRequester = std::function<void(MediaPermission, Completion)>;

  PermissionManager();
  // 注入系统查询/请求边界，测试可验证拒绝与待授权而不触发真实弹窗。
  PermissionManager(StatusReader reader, AccessRequester requester);
  bool HasMediaPermission() const;
  PermissionState Camera() const;
  PermissionState Microphone() const;
  PermissionState ScreenCapture() const;
  // 返回当前状态；未决定时发起异步请求，completion 接收最终状态。
  // completion 可在系统任意回调队列执行，调用方负责其线程与对象生命周期。
  PermissionState RequestCamera(Completion completion = {});
  PermissionState RequestMicrophone(Completion completion = {});

 private:
  PermissionState Request(MediaPermission permission, Completion completion);
  StatusReader reader_;
  AccessRequester requester_;
};

// 结构化日志中的平台权限状态名。
const char* PermissionStateName(PermissionState state);

}  // namespace beacon::mac
