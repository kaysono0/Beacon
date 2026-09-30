#include "platform/permission_manager.h"

#include <array>
#include <iostream>
#include <utility>

namespace {

using beacon::mac::MediaPermission;
using beacon::mac::PermissionManager;
using beacon::mac::PermissionState;

bool RejectUnresolvedMediaAccess() {
  const std::array<PermissionState, 4> states = {
      PermissionState::kGranted, PermissionState::kDenied,
      PermissionState::kNotDetermined, PermissionState::kRestricted,
  };
  for (const auto camera : states) {
    for (const auto microphone : states) {
      PermissionManager permissions(
          [camera, microphone](MediaPermission permission) {
            return permission == MediaPermission::kCamera ? camera : microphone;
          },
          [](MediaPermission, PermissionManager::Completion) {});
      const bool expected = camera == PermissionState::kGranted && microphone == PermissionState::kGranted;
      if (permissions.HasMediaPermission() != expected) {
        std::cerr << "media access accepted an ungranted camera/microphone\n";
        return false;
      }
    }
  }
  return true;
}

bool RequestRemainsPendingUntilCompletion() {
  std::array<PermissionState, 3> states = {
      PermissionState::kNotDetermined, PermissionState::kGranted, PermissionState::kDenied,
  };
  PermissionManager::Completion pending;
  int requests = 0;
  bool completed = false;
  PermissionState result = PermissionState::kNotDetermined;
  PermissionManager permissions(
      [&](MediaPermission permission) { return states[static_cast<size_t>(permission)]; },
      [&](MediaPermission permission, PermissionManager::Completion completion) {
        if (permission != MediaPermission::kCamera) return;
        ++requests;
        pending = std::move(completion);
      });
  const auto immediate = permissions.RequestCamera([&](PermissionState state) {
    completed = true;
    result = state;
  });
  if (immediate != PermissionState::kNotDetermined || completed || requests != 1 ||
      permissions.HasMediaPermission() || !pending) {
    std::cerr << "pending request falsely reported authorization or completed synchronously\n";
    return false;
  }
  states[0] = PermissionState::kGranted;
  pending(PermissionState::kGranted);
  if (!completed || result != PermissionState::kGranted || !permissions.HasMediaPermission() ||
      permissions.ScreenCapture() != PermissionState::kDenied) {
    std::cerr << "completed camera authorization did not update media access independently of screen access\n";
    return false;
  }
  return true;
}

bool DeterminedStatusDoesNotPrompt() {
  int requests = 0;
  PermissionState microphone = PermissionState::kRestricted;
  PermissionManager permissions(
      [&](MediaPermission permission) {
        return permission == MediaPermission::kCamera ? PermissionState::kDenied : microphone;
      },
      [&](MediaPermission, PermissionManager::Completion) { ++requests; });
  PermissionState callback = PermissionState::kGranted;
  if (permissions.RequestCamera([&](PermissionState state) { callback = state; }) != PermissionState::kDenied ||
      callback != PermissionState::kDenied || requests != 0 || permissions.HasMediaPermission()) {
    std::cerr << "denied permission prompted again or falsely became granted\n";
    return false;
  }
  if (permissions.RequestMicrophone() != PermissionState::kRestricted || requests != 0) {
    std::cerr << "restricted microphone prompted again\n";
    return false;
  }
  microphone = PermissionState::kGranted;
  return permissions.RequestMicrophone() == PermissionState::kGranted && requests == 0;
}

}  // namespace

int main() {
  PermissionManager mock;
  if (!mock.HasMediaPermission() || mock.Camera() != PermissionState::kGranted ||
      mock.Microphone() != PermissionState::kGranted || mock.ScreenCapture() != PermissionState::kGranted) {
    std::cerr << "mock permission variant unexpectedly accessed OS status\n";
    return 1;
  }
  return RejectUnresolvedMediaAccess() && RequestRemainsPendingUntilCompletion() && DeterminedStatusDoesNotPrompt() ? 0 : 1;
}
