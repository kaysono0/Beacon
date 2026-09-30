#include "platform/permission_manager_real.h"

#import <CoreGraphics/CoreGraphics.h>

namespace beacon::mac {

PermissionState PermissionStateFromAVAuthorizationStatus(AVAuthorizationStatus status) {
  switch (status) {
    case AVAuthorizationStatusAuthorized: return PermissionState::kGranted;
    case AVAuthorizationStatusDenied: return PermissionState::kDenied;
    case AVAuthorizationStatusNotDetermined: return PermissionState::kNotDetermined;
    case AVAuthorizationStatusRestricted: return PermissionState::kRestricted;
  }
  return PermissionState::kDenied;
}

namespace {

AVMediaType MediaType(MediaPermission permission) {
  return permission == MediaPermission::kCamera ? AVMediaTypeVideo : AVMediaTypeAudio;
}

PermissionState ReadPermission(MediaPermission permission) {
  if (permission == MediaPermission::kScreenCapture) {
    // 只查询录屏权限，不调用会弹窗的 CGRequestScreenCaptureAccess。
    if (@available(macOS 10.15, *)) {
      return CGPreflightScreenCaptureAccess() ? PermissionState::kGranted : PermissionState::kDenied;
    }
    return PermissionState::kGranted;
  }
  return PermissionStateFromAVAuthorizationStatus([AVCaptureDevice authorizationStatusForMediaType:MediaType(permission)]);
}

void RequestPermission(MediaPermission permission, PermissionManager::Completion completion) {
  [AVCaptureDevice requestAccessForMediaType:MediaType(permission) completionHandler:^(BOOL granted) {
    if (completion) completion(granted ? PermissionState::kGranted : PermissionState::kDenied);
  }];
}

}  // namespace

PermissionManager::PermissionManager() : PermissionManager(ReadPermission, RequestPermission) {}

}  // namespace beacon::mac
