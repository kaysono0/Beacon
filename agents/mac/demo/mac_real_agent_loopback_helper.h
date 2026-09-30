#pragma once

#include <optional>
#include <string>

#include <json/json.h>

namespace beacon::mac::agent_runtime {

struct LoopbackHelperConfig {
  std::string channel;
  std::string token;
  int uid = 2001;
};

std::optional<LoopbackHelperConfig> ExtractLoopbackHelperConfig(const Json::Value& packet);
bool HelperModeEnabled();
int RunLoopbackHelperMode();

class LoopbackHelperManager {
 public:
  explicit LoopbackHelperManager(std::string executable_path);
  ~LoopbackHelperManager();

  bool EnsureStarted(const LoopbackHelperConfig& config, std::string* error_message);
  void Stop();

 private:
  bool BuildHelperToken(const std::string& channel, int uid, std::string* token, std::string* error_message);
  bool WaitForHandshake(std::string* message);

  std::string executable_path_;
  void* task_ = nullptr;
  void* stdin_pipe_ = nullptr;
  void* stdout_pipe_ = nullptr;
};

}  // namespace beacon::mac::agent_runtime
