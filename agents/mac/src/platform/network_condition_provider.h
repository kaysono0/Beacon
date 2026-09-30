#pragma once

#include <functional>
#include <string>

#include "beacon/invocation_controller.h"
#include "platform/interface_provider.h"

namespace beacon::mac {

class NetworkConditionProvider final : public InterfaceProvider {
 public:
  struct Config {
    std::string backend = "fixture";
    bool allow_privileged = false;
  };
  using CommandRunner = std::function<int(const std::string&)>;

  NetworkConditionProvider();
  NetworkConditionProvider(Config config, CommandRunner command_runner);

  std::string sdk() const override;
  std::string interface_name() const override;
  bool Supports(const beacon::CallData& call) const override;
  void RegisterInvocations(beacon::InvocationController& controller) override;
  void Reset();
  beacon::CallResult ApplyForTesting(const beacon::CallData& call);
  beacon::CallResult ResetForTesting();

 private:
  beacon::CallResult ApplyImpairment(const beacon::CallData& call);
  beacon::CallResult GetConditionState() const;
  beacon::CallResult ResetImpairment();
  beacon::CallResult ApplyFixture(const std::string& profile, int duration_ms);
  beacon::CallResult ApplyMacosPf(const std::string& profile, int duration_ms);
  beacon::CallResult ResetMacosPf();

  bool active_ = false;
  std::string profile_;
  int duration_ms_ = 0;
  Config config_;
  CommandRunner command_runner_;
  std::string backend_ = "fixture";
  int pipe_number_ = 9001;
  std::string anchor_ = "com.beacon.network_condition";
};

}  // namespace beacon::mac
