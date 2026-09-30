#include "beacon/logging.h"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <filesystem>
#include <regex>
#include <stdexcept>

#include "beacon/logging_constants.h"
#include "beacon/protocol_json.h"
#include "spdlog/logger.h"
#include "spdlog/sinks/rotating_file_sink.h"
#include "spdlog/sinks/stdout_sinks.h"

namespace beacon {

namespace {

long long NowMs() {
  using namespace std::chrono;
  return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

std::string LoggerName(const std::string& prefix) {
  static long long next_logger_id = 1;
  return prefix + "-" + std::to_string(next_logger_id++);
}

std::string Lowercase(std::string value) {
  for (auto& ch : value) {
    ch = static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
  }
  return value;
}

bool MatchesField(const std::string& actual, const std::string& expected) {
  return expected.empty() || actual == expected;
}

bool MatchesQuery(const LogEvent& event, const LogQuery& query) {
  return event.timestamp_ms >= query.start_ms && event.timestamp_ms <= query.end_ms &&
         MatchesField(event.trace.node_id, query.node_id) && MatchesField(event.trace.lease_id, query.lease_id) &&
         MatchesField(event.trace.run_id, query.run_id) && MatchesField(event.trace.case_id, query.case_id) &&
         MatchesField(event.trace.step_id, query.step_id) && MatchesField(event.trace.op_id, query.op_id);
}

LogEvent MakeLoggingFailureEvent(const LogEvent& source, const std::string& suffix, const std::string& event_name,
                                 const std::exception& error) {
  LogEvent failure;
  failure.event_id = source.event_id + suffix;
  failure.timestamp_ms = NowMs();
  failure.level = logging::kLevelError;
  failure.trace = source.trace;
  failure.module = "logging";
  failure.event = event_name;
  failure.message = error.what();
  failure.error = kInternalError;
  failure.extra["source_event_id"] = source.event_id;
  return failure;
}

void WriteFailureToRemainingSinks(const std::vector<std::shared_ptr<LogSink>>& sinks, size_t start_index,
                                  const LogEvent& failure) {
  for (size_t index = start_index; index < sinks.size(); ++index) {
    try {
      sinks[index]->Write(failure);
    } catch (...) {
    }
  }
}

void WriteToSinks(const std::vector<std::shared_ptr<LogSink>>& sinks, const LogEvent& event) {
  for (size_t index = 0; index < sinks.size(); ++index) {
    try {
      sinks[index]->Write(event);
    } catch (const std::exception& error) {
      WriteFailureToRemainingSinks(sinks, index + 1,
                                   MakeLoggingFailureEvent(event, "-sink-failed", "logging.sink.failed", error));
      return;
    } catch (...) {
      const std::runtime_error unknown_error("unknown sink failure");
      WriteFailureToRemainingSinks(sinks, index + 1,
                                   MakeLoggingFailureEvent(event, "-sink-failed", "logging.sink.failed", unknown_error));
      return;
    }
  }
}

// 平台注入的敏感键是字段名而不是 pattern，参与自由文本匹配前必须转义元字符。
std::string EscapeRegex(const std::string& value) {
  static const std::regex kSpecial(R"([\]\[\\.^$|()*+?{}])");
  return std::regex_replace(value, kSpecial, "\\$&");
}

}  // namespace

void Redactor::RegisterPlatformProfile(const PlatformRedactionProfile& profile) {
  for (const auto& key : profile.sensitive_keys) {
    if (std::find(platform_sensitive_keys_.begin(), platform_sensitive_keys_.end(), key) ==
        platform_sensitive_keys_.end()) {
      platform_sensitive_keys_.push_back(key);
    }
  }
  for (const auto& pattern : profile.path_patterns) {
    if (std::find_if(platform_path_patterns_.begin(), platform_path_patterns_.end(),
                     [&](const auto& compiled) { return compiled.first == pattern; }) != platform_path_patterns_.end()) {
      continue;
    }
    // 注册期编译：无效 pattern 立即失败，不推迟到首条日志。
    platform_path_patterns_.emplace_back(pattern, pattern);
  }
  secret_key_pattern_.reset();
}

bool Redactor::IsSensitiveKey(const std::string& key) const {
  if (key == logging::kSensitiveToken || key == logging::kSensitiveAppCert ||
      key == logging::kSensitiveAuthorization) {
    return true;
  }
  return std::find(platform_sensitive_keys_.begin(), platform_sensitive_keys_.end(), key) !=
         platform_sensitive_keys_.end();
}

// 基线键在前、注入键在后，保持迁移前的 alternation 顺序与匹配优先级不变。
std::string Redactor::SecretKeyAlternation() const {
  std::string alternation = std::string(logging::kSensitiveToken) + "|" + logging::kSensitiveAppCert + "|" +
                            logging::kSensitiveAuthorization;
  for (const auto& key : platform_sensitive_keys_) {
    alternation += "|" + EscapeRegex(key);
  }
  return alternation;
}

std::string Redactor::RedactText(const std::string& input) const {
  static const std::regex kAuthorizationPattern(std::string(logging::kAuthorizationPrefix) + "[A-Za-z0-9._~+/-]+");
  std::string out = std::regex_replace(input, kAuthorizationPattern,
                                       std::string(logging::kAuthorizationPrefix) + logging::kRedactedValue);
  if (!secret_key_pattern_.has_value()) {
    secret_key_pattern_.emplace("(" + SecretKeyAlternation() + ")=([^\\s,}]+)");
  }
  out = std::regex_replace(out, *secret_key_pattern_, "$1=" + std::string(logging::kRedactedValue));
  for (const auto& compiled : platform_path_patterns_) {
    out = std::regex_replace(out, compiled.second, logging::kRedactedValue);
  }
  return out;
}

void Redactor::RedactJson(Json::Value* value) const {
  if (value == nullptr) {
    return;
  }
  if (value->isArray()) {
    for (Json::ArrayIndex index = 0; index < value->size(); ++index) {
      Json::Value& item = (*value)[index];
      if (item.isString()) {
        item = RedactText(item.asString());
      } else if (item.isObject() || item.isArray()) {
        RedactJson(&item);
      }
    }
    return;
  }
  if (!value->isObject()) {
    return;
  }
  for (const auto& key : value->getMemberNames()) {
    Json::Value& item = (*value)[key];
    if (IsSensitiveKey(key)) {
      item = logging::kRedactedValue;
    } else if (item.isString()) {
      item = RedactText(item.asString());
    } else if (item.isObject() || item.isArray()) {
      RedactJson(&item);
    }
  }
}

LogEvent Redactor::Redact(const LogEvent& event) const {
  LogEvent redacted = event;
  redacted.message = RedactText(redacted.message);
  RedactJson(&redacted.extra);
  return redacted;
}

RingBufferLogSink::RingBufferLogSink(size_t capacity) : capacity_(capacity) {}

void RingBufferLogSink::Write(const LogEvent& event) {
  if (capacity_ == 0) {
    return;
  }
  events_.push_back(event);
  while (events_.size() > capacity_) {
    events_.pop_front();
  }
}

std::vector<LogEvent> RingBufferLogSink::Query(const LogQuery& query) const {
  std::vector<LogEvent> out;
  for (const auto& event : events_) {
    if (MatchesQuery(event, query)) {
      out.push_back(event);
    }
  }
  return out;
}

std::vector<LogEvent> RingBufferLogSink::QueryByOpId(const std::string& op_id) const {
  LogQuery query;
  query.op_id = op_id;
  return Query(query);
}

std::vector<LogEvent> RingBufferLogSink::Events() const {
  return {events_.begin(), events_.end()};
}

FileLogSink::FileLogSink(std::string path) : FileLogSink(std::move(path), 50 * 1024 * 1024, 5) {}

FileLogSink::FileLogSink(std::string path, size_t max_size_bytes, size_t max_files) : path_(std::move(path)) {
  auto parent = std::filesystem::path(path_).parent_path();
  if (!parent.empty()) {
    std::filesystem::create_directories(parent);
  }
  auto sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(path_, max_size_bytes, max_files);
  logger_ = std::make_shared<spdlog::logger>(LoggerName("beacon-file"), sink);
  logger_->set_pattern("%v");
  logger_->set_level(spdlog::level::trace);
}

void FileLogSink::Write(const LogEvent& event) {
  logger_->info("{}", LogEventToJson(event));
}

void FileLogSink::Flush() {
  logger_->flush();
}

ConsoleLogSink::ConsoleLogSink() {
  auto stdout_sink = std::make_shared<spdlog::sinks::stdout_sink_mt>();
  stdout_logger_ = std::make_shared<spdlog::logger>(LoggerName("beacon-stdout"), stdout_sink);
  stdout_logger_->set_pattern("%v");
  stdout_logger_->set_level(spdlog::level::trace);

  auto stderr_sink = std::make_shared<spdlog::sinks::stderr_sink_mt>();
  stderr_logger_ = std::make_shared<spdlog::logger>(LoggerName("beacon-stderr"), stderr_sink);
  stderr_logger_->set_pattern("%v");
  stderr_logger_->set_level(spdlog::level::trace);
}

void ConsoleLogSink::Write(const LogEvent& event) {
  if (event.level == logging::kLevelWarn || event.level == logging::kLevelError ||
      event.level == logging::kLevelFatal) {
    stderr_logger_->info("{}", LogEventToJson(event));
  } else {
    stdout_logger_->info("{}", LogEventToJson(event));
  }
}

void LogReporter::Init(std::vector<std::shared_ptr<LogSink>> sinks) {
  sinks_ = std::move(sinks);
}

void LogReporter::RegisterPlatformRedaction(const PlatformRedactionProfile& profile) {
  redactor_.RegisterPlatformProfile(profile);
}

void LogReporter::SetTraceContext(const TraceContext& trace) {
  trace_ = trace;
}

LogEvent LogReporter::Log(const std::string& level, const std::string& module, const std::string& event,
                          const std::string& message, int error) {
  return Log(level, module, event, message, error, Json::Value(Json::objectValue));
}

LogEvent LogReporter::Log(const std::string& level, const std::string& module, const std::string& event,
                          const std::string& message, int error, const Json::Value& extra) {
  LogEvent log;
  log.event_id = "log-" + std::to_string(next_event_id_++);
  log.timestamp_ms = NowMs();
  log.level = Lowercase(level);
  log.trace = trace_;
  log.module = module;
  log.event = event;
  log.message = message;
  log.error = error;
  log.extra = extra.isObject() ? extra : Json::Value(Json::objectValue);
  // 脱敏失败必须 fail closed：原文绝不进 sink，只降级写入不含原始内容的失败事件。
  try {
    log = redactor_.Redact(log);
  } catch (const std::exception& redaction_error) {
    const LogEvent failure =
        MakeLoggingFailureEvent(log, "-redaction-failed", "logging.redaction.failed", redaction_error);
    WriteToSinks(sinks_, failure);
    return failure;
  } catch (...) {
    const std::runtime_error unknown_error("unknown redaction failure");
    const LogEvent failure =
        MakeLoggingFailureEvent(log, "-redaction-failed", "logging.redaction.failed", unknown_error);
    WriteToSinks(sinks_, failure);
    return failure;
  }
  WriteToSinks(sinks_, log);
  return log;
}

std::string LogReporter::RecordArtifact(const std::string& artifact_type, const std::string& path) {
  Json::Value extra(Json::objectValue);
  extra["artifact_type"] = artifact_type;
  extra["artifact_path"] = path;
  Log(logging::kLevelInfo, logging::kModuleArtifact, logging::kArtifactRecorded, "artifact recorded", 0, extra);
  return std::string(logging::kArtifactScheme) + artifact_type + "/" + path;
}

std::vector<LogEvent> LogReporter::Query(const LogQuery& query) const {
  std::vector<LogEvent> out;
  for (const auto& sink : sinks_) {
    auto ring = std::dynamic_pointer_cast<RingBufferLogSink>(sink);
    if (!ring) {
      continue;
    }
    auto events = ring->Query(query);
    out.insert(out.end(), events.begin(), events.end());
  }
  return out;
}

std::vector<LogEvent> LogReporter::QueryByOpId(const std::string& op_id) const {
  LogQuery query;
  query.op_id = op_id;
  return Query(query);
}

void LogReporter::Flush() {
  for (const auto& sink : sinks_) {
    sink->Flush();
  }
}

void LogReporter::ResetSession() {
  trace_.run_id.clear();
  trace_.case_id.clear();
  trace_.step_id.clear();
  trace_.op_id.clear();
}

void LogReporter::Clear() {
  Flush();
  sinks_.clear();
}

}  // namespace beacon
