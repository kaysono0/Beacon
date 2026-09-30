#pragma once

#import <AVFoundation/AVFoundation.h>

#include "platform/permission_manager.h"

namespace beacon::mac {

// 将系统授权枚举映射为平台状态；未知值按拒绝处理。
PermissionState PermissionStateFromAVAuthorizationStatus(AVAuthorizationStatus status);

}  // namespace beacon::mac
