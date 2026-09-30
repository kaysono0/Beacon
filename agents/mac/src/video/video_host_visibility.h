#pragma once

#include <cstdlib>
#include <string_view>

namespace beacon::mac {

// 真实 Video Host 默认只展示 primary 观察端；`all` 仅供明确要求同时观察全部 Agent 的本地验收。
inline bool ShouldShowVideoHost(std::string_view node_id, std::string_view agent_tags,
                                std::string_view mode) {
  if (mode == "all") {
    return true;
  }
  constexpr std::string_view kPrimaryRole = "role:primary";
  size_t start = 0;
  while (start <= agent_tags.size()) {
    const size_t end = agent_tags.find(',', start);
    const std::string_view tag = agent_tags.substr(start, end - start);
    if (tag == kPrimaryRole) {
      return true;
    }
    if (end == std::string_view::npos) {
      break;
    }
    start = end + 1;
  }
  // 保持未提供 role tag 的旧 Agora 启动器的默认观察端行为。
  return node_id == "mac-real-e2e-001";
}

inline bool ShouldShowVideoHostFromEnvironment() {
  const char* node_id = std::getenv("BEACON_NODE_ID");
  const char* agent_tags = std::getenv("BEACON_AGENT_TAGS");
  const char* mode = std::getenv("BEACON_SHOW_VIDEO_WINDOWS");
  return ShouldShowVideoHost(node_id == nullptr ? "" : node_id,
                             agent_tags == nullptr ? "" : agent_tags,
                             mode == nullptr ? "" : mode);
}

}  // namespace beacon::mac
