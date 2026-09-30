#pragma once

#include <deque>
#include <limits>
#include <memory>
#include <optional>
#include <regex>
#include <string>
#include <utility>
#include <vector>

#include "beacon/models.h"

namespace spdlog {
class logger;
}

namespace beacon {

// 日志查询条件。空字段表示不按该字段过滤。
struct LogQuery {
  std::string node_id;
  std::string lease_id;
  std::string run_id;
  std::string case_id;
  std::string step_id;
  std::string op_id;
  long long start_ms = 0;
  long long end_ms = std::numeric_limits<long long>::max();
};

// 平台/SDK 专有的脱敏扩展，由 adapter 在初始化时注入。
// Agent Core 只保留平台无关基线：token、app_cert、authorization 字段名和 Bearer 文本形态。
// 专有敏感键与本机路径形态属于适配层知识，按 ADR-002 不得下沉到 core。
struct PlatformRedactionProfile {
  // 结构化字段名命中即整值抹除，同时参与自由文本 `key=value` 形态匹配。
  std::vector<std::string> sensitive_keys;
  // 每项作为 ECMAScript 正则执行，命中片段替换为脱敏占位符，按注入顺序生效。
  std::vector<std::string> path_patterns;
};

// 日志脱敏器，负责在写入 sink 前移除敏感字段。
class Redactor {
 public:
  void RegisterPlatformProfile(const PlatformRedactionProfile& profile);
  std::string RedactText(const std::string& input) const;
  LogEvent Redact(const LogEvent& event) const;

 private:
  void RedactJson(Json::Value* value) const;
  bool IsSensitiveKey(const std::string& key) const;
  std::string SecretKeyAlternation() const;

  std::vector<std::string> platform_sensitive_keys_;
  // 注册期完成编译与去重：无效 pattern 在注册时立即失败，不推迟到首条日志。
  std::vector<std::pair<std::string, std::regex>> platform_path_patterns_;
  // key=value 形态的脱敏正则按需重建；注册新键后失效。
  mutable std::optional<std::regex> secret_key_pattern_;
};

// 日志输出目标接口。业务模块只写 LogReporter，不直接选择 sink。
class LogSink {
 public:
  virtual ~LogSink() = default;
  virtual void Write(const LogEvent& event) = 0;
  virtual void Flush() {}
};

// 内存环形缓冲，用于本地调试和按 op_id 查询最近日志。
class RingBufferLogSink : public LogSink {
 public:
  explicit RingBufferLogSink(size_t capacity);
  void Write(const LogEvent& event) override;
  std::vector<LogEvent> Query(const LogQuery& query) const;
  std::vector<LogEvent> QueryByOpId(const std::string& op_id) const;
  std::vector<LogEvent> Events() const;

 private:
  size_t capacity_;
  std::deque<LogEvent> events_;
};

// 文件日志输出，负责把脱敏后的事件写到本地文件。
class FileLogSink : public LogSink {
 public:
  explicit FileLogSink(std::string path);
  FileLogSink(std::string path, size_t max_size_bytes, size_t max_files);
  void Write(const LogEvent& event) override;
  void Flush() override;

 private:
  std::string path_;
  std::shared_ptr<spdlog::logger> logger_;
};

// 控制台日志输出，适合 smoke 和本地调试。
class ConsoleLogSink : public LogSink {
 public:
  ConsoleLogSink();
  void Write(const LogEvent& event) override;

 private:
  std::shared_ptr<spdlog::logger> stdout_logger_;
  std::shared_ptr<spdlog::logger> stderr_logger_;
};

// 日志门面，统一注入 trace、脱敏并分发到多个 sink。
class LogReporter {
 public:
  void Init(std::vector<std::shared_ptr<LogSink>> sinks);
  // adapter 通过这里注入平台专有脱敏扩展；必须在写第一条日志前调用。
  void RegisterPlatformRedaction(const PlatformRedactionProfile& profile);
  void SetTraceContext(const TraceContext& trace);
  LogEvent Log(const std::string& level, const std::string& module, const std::string& event,
               const std::string& message, int error = 0);
  LogEvent Log(const std::string& level, const std::string& module, const std::string& event,
               const std::string& message, int error, const Json::Value& extra);
  // artifact 只记录引用，不把大文件或敏感内容写入日志正文。
  std::string RecordArtifact(const std::string& artifact_type, const std::string& path);
  std::vector<LogEvent> Query(const LogQuery& query) const;
  std::vector<LogEvent> QueryByOpId(const std::string& op_id) const;
  void Flush();
  void ResetSession();
  void Clear();

 private:
  TraceContext trace_;
  Redactor redactor_;
  std::vector<std::shared_ptr<LogSink>> sinks_;
  long long next_event_id_ = 1;
};

}  // namespace beacon
