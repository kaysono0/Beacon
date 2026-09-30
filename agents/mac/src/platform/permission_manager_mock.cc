#include "platform/permission_manager.h"

namespace beacon::mac {

// 固定授权只用于 mock 编译变体，不进入真实 SDK 进程。
PermissionManager::PermissionManager()
    : PermissionManager([](MediaPermission) { return PermissionState::kGranted; },
                        [](MediaPermission, Completion completion) {
                          if (completion) completion(PermissionState::kGranted);
                        }) {}

}  // namespace beacon::mac
