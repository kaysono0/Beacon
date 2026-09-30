#pragma once

#include <string>

namespace beacon {

// 协议编解码边界。当前实现保持透明传递，后续可接入压缩或封包格式。
class ProtocolCodec {
 public:
  std::string Encode(const std::string& packet_json) const;
  bool Decode(const std::string& packet_json, std::string* output) const;
};

}  // namespace beacon
