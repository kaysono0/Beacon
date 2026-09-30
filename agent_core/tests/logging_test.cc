#include "beacon/logging.h"
#include "beacon/platform_log_bridge.h"
#include "beacon/protocol_json.h"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {

class FailingSink : public beacon::LogSink {
 public:
  void Write(const beacon::LogEvent&) override { throw std::runtime_error("sink unavailable"); }
};

class UnknownFailingSink : public beacon::LogSink {
 public:
  void Write(const beacon::LogEvent&) override { throw 7; }
};

bool ParseLine(const std::filesystem::path& path, Json::Value* value) {
  std::ifstream in(path);
  std::string line;
  return std::getline(in, line) && beacon::ParseJson(line, value);
}

}  // namespace

int main() {
  const std::filesystem::path temp_dir = std::filesystem::temp_directory_path() / "beacon-agent-core-logging-test";
  std::filesystem::create_directories(temp_dir);
  const std::filesystem::path log_file = temp_dir / "agent_core_logging_test.jsonl";
  std::filesystem::remove(log_file);
  for (const auto& entry : std::filesystem::directory_iterator(temp_dir)) {
    if (entry.path().filename().string().find("agent_core_logging_test") != std::string::npos) {
      std::filesystem::remove(entry.path());
    }
  }

  auto ring = std::make_shared<beacon::RingBufferLogSink>(2);
  beacon::LogReporter reporter;
  reporter.Init({ring, std::make_shared<beacon::FileLogSink>(log_file.string())});
  // core 不内置任何 SDK/OS 专有脱敏知识；测试以 fixture 身份注入 macOS/Agora 扩展来验证注入机制。
  reporter.RegisterPlatformRedaction({{"AGORA_APP_CERT", "AGORA_APP_ID"},
                                      {"/Users/[^\\s,:;\"']+(?:/[^\\s,:;\"']*)?", "\\$HOME(?:/[^\\s,:;\"']*)?"}});
  reporter.SetTraceContext({"node", "lease", "run", "case", "step", "op-log"});

  Json::Value path_extra(Json::objectValue);
  path_extra["file_uri"] = "file:///Users/example/Library/Logs/Beacon/agora.log";
  path_extra["home_path"] = "$HOME/Library/Logs/Beacon/agora.log";
  path_extra["AGORA_APP_CERT"] = "cert-value";
  path_extra["AGORA_APP_ID"] = "app-id-value";
  Json::Value attempt(Json::objectValue);
  attempt["token"] = "secret-array-token";
  attempt["dump_path"] = "/Users/example/Library/Logs/Beacon/attempt.log";
  path_extra["attempts"] = Json::Value(Json::arrayValue);
  path_extra["attempts"].append(attempt);
  auto first = reporter.Log("Info", "invocation", "invoke.start",
                            "token=abc Authorization Bearer secret AGORA_APP_CERT=cert-value "
                            "AGORA_APP_ID=app-id-value /Users/example/Library/Logs/Beacon/agora.log",
                            0, path_extra);
  if (first.event_id.empty() || first.trace.op_id != "op-log") {
    std::cerr << "UT-LOG-01 structured event failed\n";
    return 1;
  }
  if (first.message.find("abc") != std::string::npos || first.message.find("example") != std::string::npos ||
      first.message.find("Library/Logs/Beacon") != std::string::npos ||
      first.message.find("cert-value") != std::string::npos ||
      first.message.find("app-id-value") != std::string::npos ||
      first.message.find("secret") != std::string::npos ||
      first.extra["file_uri"].asString().find("Library/Logs/Beacon") != std::string::npos ||
      first.extra["home_path"].asString().find("Library/Logs/Beacon") != std::string::npos ||
      first.extra["AGORA_APP_CERT"].asString() != "<redacted>" ||
      first.extra["AGORA_APP_ID"].asString() != "<redacted>" ||
      first.extra["attempts"][0]["token"].asString() != "<redacted>" ||
      first.extra["attempts"][0]["dump_path"].asString().find("Library/Logs/Beacon") != std::string::npos) {
    std::cerr << "UT-LOG-02 redaction failed\n";
    return 1;
  }
  reporter.Log("Warn", "callback", "callback.defer.install", "second");
  reporter.Log("Error", "callback", "callback.defer.trigger", "third");
  if (ring->Events().size() != 2) {
    std::cerr << "UT-LOG-05 ring buffer capacity failed\n";
    return 1;
  }
  if (reporter.QueryByOpId("op-log").size() != 2) {
    std::cerr << "UT-LOG-06 trace query failed\n";
    return 1;
  }
  reporter.Flush();
  Json::Value first_json;
  if (!ParseLine(log_file, &first_json) || first_json["event_id"].asString().empty()) {
    std::cerr << "UT-LOG-03 file JSONL failed\n";
    return 1;
  }
  if (first_json["node_id"].asString() != "node" || first_json["lease_id"].asString() != "lease" ||
      first_json["run_id"].asString() != "run" || first_json["case_id"].asString() != "case" ||
      first_json["step_id"].asString() != "step" || first_json["op_id"].asString() != "op-log") {
    std::cerr << "UT-LOG-09 flat trace projection failed\n";
    return 1;
  }
  Json::Value extra(Json::objectValue);
  extra["failure_category"] = "sdk_error";
  extra["token"] = "secret-token";
  auto with_extra = reporter.Log("Error", "agora", "agora.join.failed", "failed", 109, extra);
  if (with_extra.extra["failure_category"].asString() != "sdk_error" ||
      with_extra.extra["token"].asString() != "<redacted>") {
    std::cerr << "UT-LOG-10 structured extra redaction failed\n";
    return 1;
  }
  beacon::LogQuery step_query;
  step_query.node_id = "node";
  step_query.lease_id = "lease";
  step_query.step_id = "step";
  step_query.start_ms = first.timestamp_ms;
  step_query.end_ms = with_extra.timestamp_ms;
  if (reporter.Query(step_query).empty()) {
    std::cerr << "UT-LOG-11 ring query by node/lease/step/window failed\n";
    return 1;
  }
  step_query.node_id = "other-node";
  if (!reporter.Query(step_query).empty()) {
    std::cerr << "UT-LOG-14 ring query node filter isolation failed\n";
    return 1;
  }
  auto artifact = reporter.RecordArtifact("dump", (temp_dir / "a.txt").string());
  if (artifact.find("artifact://dump/") != 0) {
    std::cerr << "UT-LOG-04 artifact ref failed\n";
    return 1;
  }
  if (reporter.QueryByOpId("op-log").back().extra["artifact_type"].asString() != "dump") {
    std::cerr << "UT-LOG-12 artifact metadata failed\n";
    return 1;
  }

  auto failure_ring = std::make_shared<beacon::RingBufferLogSink>(4);
  beacon::LogReporter failure_reporter;
  failure_reporter.Init({std::make_shared<FailingSink>(), failure_ring});
  failure_reporter.SetTraceContext({"node", "lease", "run", "case", "step", "op-failing-sink"});
  failure_reporter.Log("Info", "invocation", "invoke.start", "sink failure must not escape");
  if (failure_ring->Events().empty() || failure_ring->Events().back().event != "logging.sink.failed") {
    std::cerr << "UT-LOG-13 sink failure downgrade failed\n";
    return 1;
  }
  auto unknown_failure_ring = std::make_shared<beacon::RingBufferLogSink>(4);
  beacon::LogReporter unknown_failure_reporter;
  unknown_failure_reporter.Init({std::make_shared<UnknownFailingSink>(), unknown_failure_ring});
  unknown_failure_reporter.Log("Info", "invocation", "invoke.start", "unknown sink failure must not escape");
  if (unknown_failure_ring->Events().empty() ||
      unknown_failure_ring->Events().back().message.find("unknown sink failure") == std::string::npos) {
    std::cerr << "UT-LOG-16 unknown sink failure downgrade failed\n";
    return 1;
  }

  auto zero_ring = std::make_shared<beacon::RingBufferLogSink>(0);
  zero_ring->Write(first);
  if (!zero_ring->Events().empty() || !zero_ring->QueryByOpId("op-log").empty()) {
    std::cerr << "UT-LOG-17 zero-capacity ring retained events\n";
    return 1;
  }

  beacon::LogReporter console_reporter;
  console_reporter.Init({std::make_shared<beacon::ConsoleLogSink>()});
  console_reporter.Log("Info", "console", "console.stdout", "console info path");
  console_reporter.Log("Error", "console", "console.stderr", "console error path");
  console_reporter.Flush();

  auto platform_ring = std::make_shared<beacon::RingBufferLogSink>(4);
  beacon::LogReporter platform_reporter;
  platform_reporter.Init({platform_ring});
  platform_reporter.SetTraceContext(
      {"mock-node", "mock-lease", "run-platform", "case-platform", "step-platform", "op-platform"});
  beacon::PlatformLogBridge platform_bridge(&platform_reporter, "mock");
  const auto platform_event = platform_bridge.Record(beacon::PlatformLogEntry{
      .level = "error",
      .subsystem = "beacon.mock.media",
      .category = "capture",
      .source = "mock_log",
      .permission_state = "granted",
      .collector = "mock_platform_log",
      .relative_path = "platform/mock/mock-node/platform.jsonl",
      .message = "camera token=secret",
      .error = 5601,
  });
  const auto platform_logs = platform_reporter.QueryByOpId("op-platform");
  if (platform_event.module != "platform" || platform_event.event != "platform.system.log" || platform_logs.size() != 1U) {
    std::cerr << "UT-LOG-15 platform log bridge event shape failed\n";
    return 1;
  }
  const auto& platform_log = platform_logs[0];
  if (platform_log.extra.get("platform", "").asString() != "mock" ||
      platform_log.extra.get("subsystem", "").asString() != "beacon.mock.media" ||
      platform_log.extra.get("category", "").asString() != "capture" ||
      platform_log.extra.get("source", "").asString() != "mock_log" ||
      platform_log.extra.get("permission_state", "").asString() != "granted" ||
      platform_log.extra.get("collector", "").asString() != "mock_platform_log" ||
      platform_log.extra.get("relative_path", "").asString() != "platform/mock/mock-node/platform.jsonl") {
    std::cerr << "UT-LOG-15 platform log bridge structured fields failed\n";
    return 1;
  }
  if (platform_log.message.find("secret") != std::string::npos ||
      platform_log.message.find("<redacted>") == std::string::npos) {
    std::cerr << "UT-LOG-15 platform log bridge redaction failed\n";
    return 1;
  }

  // 平台纯度守卫：未注入任何平台扩展时，core 只应用平台无关基线，
  // 不得内置 Agora 凭证键或 macOS 本机路径形态（ADR-002）。
  auto bare_ring = std::make_shared<beacon::RingBufferLogSink>(4);
  beacon::LogReporter bare_reporter;
  bare_reporter.Init({bare_ring});
  bare_reporter.SetTraceContext({"node", "lease", "run", "case", "step", "op-bare"});
  const auto bare_event = bare_reporter.Log(
      "Error", "invocation", "invoke.failed",
      "token=abc Bearer secret AGORA_APP_CERT=cert-value /Users/example/Library/Logs/Beacon/agora.log", 0);
  if (bare_event.message.find("abc") != std::string::npos ||
      bare_event.message.find("secret") != std::string::npos ||
      bare_event.message.find("<redacted>") == std::string::npos) {
    std::cerr << "UT-LOG-18 baseline redaction regressed\n";
    return 1;
  }
  if (bare_event.message.find("cert-value") == std::string::npos ||
      bare_event.message.find("Library/Logs/Beacon") == std::string::npos) {
    std::cerr << "UT-LOG-18 core still carries built-in platform redaction knowledge\n";
    return 1;
  }

  // 平台 pattern 在注册期编译：无效 pattern 必须立即失败，不得推迟到首条日志。
  auto invalid_pattern_ring = std::make_shared<beacon::RingBufferLogSink>(4);
  beacon::LogReporter invalid_pattern_reporter;
  invalid_pattern_reporter.Init({invalid_pattern_ring});
  bool registration_failed = false;
  try {
    invalid_pattern_reporter.RegisterPlatformRedaction({{"MOCK_KEY"}, {"([invalid"}});
  } catch (const std::regex_error&) {
    registration_failed = true;
  }
  if (!registration_failed) {
    std::cerr << "UT-LOG-19 invalid platform pattern must fail at registration\n";
    return 1;
  }
  const auto after_invalid = invalid_pattern_reporter.Log("Info", "invocation", "invoke.start", "token=abc", 0);
  if (after_invalid.message.find("abc") != std::string::npos) {
    std::cerr << "UT-LOG-19 reporter unusable after failed registration\n";
    return 1;
  }

  // 重复注册同一 profile 不改变脱敏行为，也不得产生重复 alternation。
  auto duplicate_ring = std::make_shared<beacon::RingBufferLogSink>(4);
  beacon::LogReporter duplicate_reporter;
  duplicate_reporter.Init({duplicate_ring});
  const beacon::PlatformRedactionProfile duplicate_profile{
      {"AGORA_APP_CERT"}, {"/Users/[^\\s,:;\"']+(?:/[^\\s,:;\"']*)?"}};
  duplicate_reporter.RegisterPlatformRedaction(duplicate_profile);
  duplicate_reporter.RegisterPlatformRedaction(duplicate_profile);
  const auto duplicate_event = duplicate_reporter.Log(
      "Info", "invocation", "invoke.start",
      "AGORA_APP_CERT=cert-value /Users/example/Library/Logs/Beacon/dup.log", 0);
  if (duplicate_event.message.find("cert-value") != std::string::npos ||
      duplicate_event.message.find("example") != std::string::npos ||
      duplicate_event.message.find("<redacted>") == std::string::npos) {
    std::cerr << "UT-LOG-20 duplicate platform registration changed redaction\n";
    return 1;
  }

  const std::filesystem::path rotated_log_file = temp_dir / "agent_core_logging_test_rotate.jsonl";
  for (const auto& entry : std::filesystem::directory_iterator(temp_dir)) {
    if (entry.path().filename().string().find("agent_core_logging_test_rotate") != std::string::npos) {
      std::filesystem::remove(entry.path());
    }
  }
  beacon::LogReporter rotating_reporter;
  rotating_reporter.Init({std::make_shared<beacon::FileLogSink>(rotated_log_file.string(), 180, 2)});
  rotating_reporter.SetTraceContext({"node", "lease", "run", "case", "step", "op-rotate"});
  for (int i = 0; i < 20; ++i) {
    rotating_reporter.Log("Info", "invocation", "invoke.rotate", "rotation-payload-abcdefghijklmnopqrstuvwxyz");
  }
  rotating_reporter.Flush();
  bool found_rotated_file = false;
  for (const auto& entry : std::filesystem::directory_iterator(temp_dir)) {
    const auto filename = entry.path().filename().string();
    if (filename.find("agent_core_logging_test_rotate") != std::string::npos && entry.path() != rotated_log_file) {
      found_rotated_file = true;
    }
  }
  if (!found_rotated_file) {
    std::cerr << "UT-LOG-04 file rotation failed\n";
    return 1;
  }
  return 0;
}
