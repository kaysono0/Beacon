#include "platform/permission_manager.h"

#include <utility>

namespace beacon::mac {

PermissionManager::PermissionManager(StatusReader reader, AccessRequester requester)
    : reader_(std::move(reader)), requester_(std::move(requester)) {}

bool PermissionManager::HasMediaPermission() const {
  return Camera() == PermissionState::kGranted && Microphone() == PermissionState::kGranted;
}

PermissionState PermissionManager::Camera() const {
  return reader_(MediaPermission::kCamera);
}

PermissionState PermissionManager::Microphone() const {
  return reader_(MediaPermission::kMicrophone);
}

PermissionState PermissionManager::ScreenCapture() const {
  return reader_(MediaPermission::kScreenCapture);
}

PermissionState PermissionManager::RequestCamera(Completion completion) {
  return Request(MediaPermission::kCamera, std::move(completion));
}

PermissionState PermissionManager::RequestMicrophone(Completion completion) {
  return Request(MediaPermission::kMicrophone, std::move(completion));
}

PermissionState PermissionManager::Request(MediaPermission permission, Completion completion) {
  const auto state = reader_(permission);
  if (state == PermissionState::kNotDetermined) {
    requester_(permission, std::move(completion));
    return reader_(permission);
  }
  if (completion) {
    completion(state);
  }
  return state;
}

const char* PermissionStateName(PermissionState state) {
  switch (state) {
    case PermissionState::kGranted: return "granted";
    case PermissionState::kDenied: return "denied";
    case PermissionState::kNotDetermined: return "not_determined";
    case PermissionState::kRestricted: return "restricted";
  }
  return "unknown";
}

}  // namespace beacon::mac
