#pragma once

#include <algorithm>
#include <array>
#include <functional>
#include <string>

namespace beacon::mac {

struct VideoHostRect {
  double x;
  double y;
  double width;
  double height;
};

inline bool VideoHostRectsOverlap(const VideoHostRect& left, const VideoHostRect& right) {
  return left.x < right.x + right.width && right.x < left.x + left.width &&
         left.y < right.y + right.height && right.y < left.y + left.height;
}

// 每个 Agent 独立进程也能复现同一布局：primary 固定中央，已知观察端固定角落。
// 3×3 网格会把所有 Host 裁在可见屏幕内，且保留 16:9 的内容比例。
inline VideoHostRect VideoHostFrameForRole(const std::string& role, const VideoHostRect& visible) {
  constexpr double kPreferredWidth = 660.0;
  constexpr double kAspectHeight = 9.0 / 16.0;
  constexpr int kColumns = 3;
  constexpr int kRows = 3;
  const double width = std::min(kPreferredWidth, std::max(1.0, visible.width / kColumns));
  const double height = std::min(width * kAspectHeight, std::max(1.0, visible.height / kRows));
  const double cell_width = visible.width / kColumns;
  const double cell_height = visible.height / kRows;
  int slot = 4;
  if (role == "peer") {
    slot = 0;
  } else if (role == "peer-b") {
    slot = 2;
  } else if (role != "primary") {
    constexpr std::array<int, 8> kObserverSlots = {0, 2, 6, 8, 1, 3, 5, 7};
    slot = kObserverSlots[std::hash<std::string>{}(role) % kObserverSlots.size()];
  }
  const int column = slot % kColumns;
  const int row = slot / kColumns;
  const double x = visible.x + column * cell_width + (cell_width - width) / 2.0;
  const double y = visible.y + (kRows - row - 1) * cell_height + (cell_height - height) / 2.0;
  return {std::max(visible.x, std::min(x, visible.x + visible.width - width)),
          std::max(visible.y, std::min(y, visible.y + visible.height - height)), width, height};
}

}  // namespace beacon::mac
