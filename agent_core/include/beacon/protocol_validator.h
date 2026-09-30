#pragma once

#include <string>

namespace beacon {

// 协议结构校验入口。业务控制器应在处理 packet 前先经过这里。
class ProtocolValidator {
 public:
  bool ValidatePacket(const std::string& packet_json) const;
};

}  // namespace beacon
