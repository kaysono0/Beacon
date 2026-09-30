#include "platform/network_condition_provider.h"

#include <cstdlib>
#include <string_view>
#include <utility>
#include <vector>

#include <json/json.h>

#include "beacon/protocol_json.h"
#include "beacon/target_contract.h"

namespace beacon::mac {
namespace {

inline constexpr std::string_view kSdk = "beacon_system";
inline constexpr std::string_view kInterface = "network_condition";
inline constexpr std::string_view kClass = "NetworkCondition";
inline constexpr std::string_view kApplyImpairment = "applyImpairment";
inline constexpr std::string_view kGetConditionState = "getConditionState";
inline constexpr std::string_view kResetImpairment = "resetImpairment";
inline constexpr std::string_view kMacosPf = "macos_pf";
inline constexpr std::string_view kWeakNetwork = "weak_network";

std::string CanonicalKey(std::string_view function_name) {
  beacon::TargetData target;
  target.sdk = std::string(kSdk);
  target.interface_name = std::string(kInterface);
  target.class_name = std::string(kClass);
  target.function_name = std::string(function_name);
  return beacon::TargetKey(target);
}

bool IsTruthyEnv(const char* value) {
  return value != nullptr && (std::string_view(value) == "1" || std::string_view(value) == "true");
}

NetworkConditionProvider::Config LoadConfigFromEnvironment() {
  NetworkConditionProvider::Config config;
  if (const char* backend = std::getenv("BEACON_NETWORK_CONDITION_BACKEND")) {
    config.backend = backend;
  }
  config.allow_privileged = IsTruthyEnv(std::getenv("BEACON_NETWORK_CONDITION_ALLOW_PRIVILEGED"));
  return config;
}

Json::Value BuildProof(const std::string& backend, const std::string& anchor, int pipe_number,
                       const std::vector<std::string>& commands, const std::vector<int>& exit_codes) {
  Json::Value proof(Json::objectValue);
  proof["backend"] = backend;
  proof["anchor"] = anchor;
  proof["pipe"] = pipe_number;
  for (const auto& command : commands) {
    proof["commands"].append(command);
  }
  for (const int exit_code : exit_codes) {
    proof["exit_codes"].append(exit_code);
  }
  return proof;
}

std::string StateJson(bool active, const std::string& profile, int duration_ms, const std::string& backend,
                      const std::string& anchor, int pipe_number, const Json::Value& proof = Json::Value()) {
  Json::Value result(Json::objectValue);
  result["active"] = active;
  result["profile"] = profile;
  result["duration_ms"] = duration_ms;
  result["backend"] = backend;
  if (backend == kMacosPf) {
    result["anchor"] = anchor;
    result["pipe"] = pipe_number;
  }
  if (!proof.isNull()) {
    result["proof"] = proof;
  }
  return beacon::WriteJson(result);
}

}  // namespace

NetworkConditionProvider::NetworkConditionProvider()
    : NetworkConditionProvider(LoadConfigFromEnvironment(),
                               [](const std::string& command) { return std::system(command.c_str()); }) {}

NetworkConditionProvider::NetworkConditionProvider(Config config, CommandRunner command_runner)
    : config_(std::move(config)),
      command_runner_(std::move(command_runner)),
      backend_(config_.backend.empty() ? "fixture" : config_.backend) {}

std::string NetworkConditionProvider::sdk() const {
  return std::string(kSdk);
}

std::string NetworkConditionProvider::interface_name() const {
  return std::string(kInterface);
}

bool NetworkConditionProvider::Supports(const beacon::CallData& call) const {
  return call.sdk == kSdk && call.interface_name == kInterface;
}

void NetworkConditionProvider::RegisterInvocations(beacon::InvocationController& controller) {
  controller.RegisterInvocation(CanonicalKey(kApplyImpairment),
                                [this](const beacon::CallData& call) { return ApplyImpairment(call); });
  controller.RegisterInvocation(CanonicalKey(kGetConditionState),
                                [this](const beacon::CallData&) { return GetConditionState(); });
  controller.RegisterInvocation(CanonicalKey(kResetImpairment),
                                [this](const beacon::CallData&) { return ResetImpairment(); });
}

void NetworkConditionProvider::Reset() {
  if (backend_ == kMacosPf && active_ && config_.allow_privileged) {
    ResetMacosPf();
  }
  active_ = false;
  profile_.clear();
  duration_ms_ = 0;
}

beacon::CallResult NetworkConditionProvider::ApplyForTesting(const beacon::CallData& call) {
  return ApplyImpairment(call);
}

beacon::CallResult NetworkConditionProvider::ResetForTesting() {
  return ResetImpairment();
}

beacon::CallResult NetworkConditionProvider::ApplyImpairment(const beacon::CallData& call) {
  Json::Value params;
  beacon::ParseJson(call.params_json, &params);
  const std::string profile = params.get("profile", "").asString();
  if (profile.empty()) {
    return {beacon::kBadRequest, "missing network profile", "{}"};
  }
  const int duration_ms = params.get("duration_ms", 0).asInt();
  if (backend_ == kMacosPf) {
    return ApplyMacosPf(profile, duration_ms);
  }
  return ApplyFixture(profile, duration_ms);
}

beacon::CallResult NetworkConditionProvider::GetConditionState() const {
  return {beacon::kOk, "network condition state",
          StateJson(active_, profile_, duration_ms_, backend_, anchor_, pipe_number_)};
}

beacon::CallResult NetworkConditionProvider::ResetImpairment() {
  if (backend_ == kMacosPf) {
    if (!config_.allow_privileged) {
      Json::Value result(Json::objectValue);
      result["active"] = active_;
      result["backend"] = backend_;
      result["privileged_required"] = true;
      return {403, "macOS network impairment reset requires explicit privileged opt-in", beacon::WriteJson(result)};
    }
    return ResetMacosPf();
  }
  Reset();
  return {beacon::kOk, "network impairment reset",
          StateJson(active_, profile_, duration_ms_, backend_, anchor_, pipe_number_)};
}

beacon::CallResult NetworkConditionProvider::ApplyFixture(const std::string& profile, int duration_ms) {
  active_ = true;
  profile_ = profile;
  duration_ms_ = duration_ms;
  Json::Value proof(Json::objectValue);
  proof["mode"] = "deterministic_fixture";
  return {beacon::kOk, "network impairment applied",
          StateJson(active_, profile_, duration_ms_, backend_, anchor_, pipe_number_, proof)};
}

beacon::CallResult NetworkConditionProvider::ApplyMacosPf(const std::string& profile, int duration_ms) {
  if (profile != kWeakNetwork) {
    return {beacon::kBadRequest, "unsupported macOS network profile", "{}"};
  }
  if (!config_.allow_privileged) {
    Json::Value result(Json::objectValue);
    result["active"] = false;
    result["backend"] = backend_;
    result["profile"] = profile;
    result["duration_ms"] = duration_ms;
    result["privileged_required"] = true;
    result["anchor"] = anchor_;
    result["pipe"] = pipe_number_;
    return {403, "macOS network impairment requires explicit privileged opt-in", beacon::WriteJson(result)};
  }

  const std::vector<std::string> commands = {
      "/usr/sbin/dnctl pipe 9001 config bw 512Kbit/s delay 250ms plr 0.05",
      "printf 'dummynet out proto udp from any to any pipe 9001\\n' | /sbin/pfctl -a com.beacon.network_condition -f -",
      "/sbin/pfctl -E",
  };
  std::vector<int> exit_codes;
  for (const auto& command : commands) {
    const int exit_code = command_runner_ ? command_runner_(command) : 1;
    exit_codes.push_back(exit_code);
    if (exit_code != 0) {
      return {exit_code, "macOS network impairment command failed",
              StateJson(false, profile, duration_ms, backend_, anchor_, pipe_number_,
                        BuildProof(backend_, anchor_, pipe_number_, commands, exit_codes))};
    }
  }

  active_ = true;
  profile_ = profile;
  duration_ms_ = duration_ms;
  return {beacon::kOk, "network impairment applied",
          StateJson(active_, profile_, duration_ms_, backend_, anchor_, pipe_number_,
                    BuildProof(backend_, anchor_, pipe_number_, commands, exit_codes))};
}

beacon::CallResult NetworkConditionProvider::ResetMacosPf() {
  const std::vector<std::string> commands = {
      "/sbin/pfctl -a com.beacon.network_condition -F all",
      "/usr/sbin/dnctl delete 9001",
  };
  std::vector<int> exit_codes;
  for (const auto& command : commands) {
    const int exit_code = command_runner_ ? command_runner_(command) : 1;
    exit_codes.push_back(exit_code);
    if (exit_code != 0) {
      return {exit_code, "macOS network impairment reset command failed",
              StateJson(active_, profile_, duration_ms_, backend_, anchor_, pipe_number_,
                        BuildProof(backend_, anchor_, pipe_number_, commands, exit_codes))};
    }
  }

  active_ = false;
  profile_.clear();
  duration_ms_ = 0;
  return {beacon::kOk, "network impairment reset",
          StateJson(active_, profile_, duration_ms_, backend_, anchor_, pipe_number_,
                    BuildProof(backend_, anchor_, pipe_number_, commands, exit_codes))};
}

}  // namespace beacon::mac
