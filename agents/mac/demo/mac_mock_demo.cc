#include <iostream>

#include "platform/platform_adapter.h"

int main() {
  beacon::mac::PlatformAdapter adapter;
  if (adapter.Bind() != beacon::kOk) {
    std::cerr << "mac mock init failed\n";
    return 1;
  }
  const auto response = adapter.kernel().HandleRequest(
      R"({"common":{"action":"invokeRequest","op_id":"op-demo","timestamp_ms":1},"data":{"node_id":"mac-demo-001","sync":true,"list":[{"target":{"sdk":"agora_rtc","interface":"rtc_engine","class_name":"AgoraRtcEngineKit","function":"joinChannel"},"params":"{\"channel\":\"demo\"}"}]}})");
  std::cout << response << "\n";
  return response.find("\"code\":0") == std::string::npos ? 1 : 0;
}
