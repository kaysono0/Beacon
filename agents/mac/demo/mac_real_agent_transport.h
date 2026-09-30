#pragma once

#include <memory>
#include <string>

namespace beacon::mac::agent_runtime {

class DirectWebSocketTransport {
 public:
  DirectWebSocketTransport();
  ~DirectWebSocketTransport();

  DirectWebSocketTransport(const DirectWebSocketTransport&) = delete;
  DirectWebSocketTransport& operator=(const DirectWebSocketTransport&) = delete;

  bool Connect(const std::string& url, std::string* error_message);
  bool Send(const std::string& text, std::string* error_message = nullptr);
  bool Receive(std::string* text, std::string* error_message = nullptr);
  void Close();

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace beacon::mac::agent_runtime
