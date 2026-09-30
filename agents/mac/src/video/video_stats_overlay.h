#pragma once

#include <string>

namespace beacon::mac {

// 仅格式化已经由 SDK callback 确认的渲染事实；未知字段必须保留为未知，不能用请求参数补写。
struct VideoRenderOverlay {
  std::string case_id;
  std::string publisher;
  std::string state;
  std::string layer;
  int width = 0;
  int height = 0;
  int frame_rate = 0;
  std::string bitrate_direction;
  int bitrate = 0;
  std::string updated_at;
};

inline std::string FormatVideoRenderOverlay(const VideoRenderOverlay& overlay) {
  const std::string case_id = overlay.case_id.empty() ? "Not reported" : overlay.case_id;
  const std::string frame = overlay.width > 0 && overlay.height > 0
                                ? std::to_string(overlay.width) + " x " + std::to_string(overlay.height)
                                : "Not reported";
  const std::string fps = overlay.frame_rate > 0 ? std::to_string(overlay.frame_rate) : "Not reported";
  const std::string bitrate = overlay.bitrate > 0 ? std::to_string(overlay.bitrate) + " kbps" : "Not reported";
  return "Case: " + case_id + "\nPublisher: " + overlay.publisher + " · State: " + overlay.state +
         "\nLayer: " + overlay.layer + " · Frame: " + frame + " · " + fps + " fps\nBitrate: " +
         overlay.bitrate_direction + " " + bitrate + " · Updated: " + overlay.updated_at;
}

}  // namespace beacon::mac
