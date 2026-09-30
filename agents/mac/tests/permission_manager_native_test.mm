#include "platform/permission_manager_real.h"

#include <iostream>

int main() {
  using beacon::mac::MediaPermission;
  using beacon::mac::PermissionManager;
  using beacon::mac::PermissionState;
  using beacon::mac::PermissionStateFromAVAuthorizationStatus;

  if (PermissionStateFromAVAuthorizationStatus(AVAuthorizationStatusAuthorized) != PermissionState::kGranted ||
      PermissionStateFromAVAuthorizationStatus(AVAuthorizationStatusDenied) != PermissionState::kDenied ||
      PermissionStateFromAVAuthorizationStatus(AVAuthorizationStatusNotDetermined) != PermissionState::kNotDetermined ||
      PermissionStateFromAVAuthorizationStatus(AVAuthorizationStatusRestricted) != PermissionState::kRestricted ||
      PermissionStateFromAVAuthorizationStatus(static_cast<AVAuthorizationStatus>(-1)) != PermissionState::kDenied) {
    std::cerr << "native authorization status mapping falsely granted or conflated unresolved access\n";
    return 1;
  }
  // 链接 real 实现但只注入状态，不构造默认系统 reader，也不请求用户机器权限。
  PermissionManager permissions(
      [](MediaPermission permission) {
        return PermissionStateFromAVAuthorizationStatus(permission == MediaPermission::kCamera
                                                          ? AVAuthorizationStatusNotDetermined
                                                          : AVAuthorizationStatusAuthorized);
      },
      [](MediaPermission, PermissionManager::Completion) {});
  if (permissions.HasMediaPermission() || permissions.RequestCamera() != PermissionState::kNotDetermined) {
    std::cerr << "real linked permission path falsely accepted pending camera access\n";
    return 1;
  }
  return 0;
}
