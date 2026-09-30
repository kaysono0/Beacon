#include "beacon/protocol_codec.h"

namespace beacon {

std::string ProtocolCodec::Encode(const std::string& packet_json) const {
  return packet_json;
}

bool ProtocolCodec::Decode(const std::string& packet_json, std::string* output) const {
  if (packet_json.empty() || output == nullptr) {
    return false;
  }
  *output = packet_json;
  return true;
}

}  // namespace beacon
