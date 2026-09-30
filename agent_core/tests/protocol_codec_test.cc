#include "beacon/protocol_codec.h"

#include <iostream>
#include <string>

int main() {
  beacon::ProtocolCodec codec;
  const std::string packet = R"({"common":{"action":"registerRequest"},"data":{}})";
  std::string decoded;
  if (codec.Encode(packet) != packet) {
    std::cerr << "UT-PC-01 encode smoke failed\n";
    return 1;
  }
  if (!codec.Decode(packet, &decoded) || decoded != packet) {
    std::cerr << "UT-PC-01 decode smoke failed\n";
    return 1;
  }
  if (codec.Decode("", &decoded) || codec.Decode(packet, nullptr)) {
    std::cerr << "UT-PC-02 invalid decode inputs were accepted\n";
    return 1;
  }
  return 0;
}
