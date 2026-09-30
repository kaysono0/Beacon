#pragma once

#include <map>
#include <string>
#include <utility>
#include <vector>

#include <json/json.h>

namespace beacon {

// 协议错误码的最小公共集合，必须和工程合同保持一致。
constexpr int kOk = 0;
constexpr int kBadRequest = 400;
constexpr int kUnauthorized = 401;
constexpr int kTimeout = 408;
constexpr int kInternalError = -100;

// 下行调用的标准数据模型，params_json 在 wire 上保持 JSON 字符串。
struct CallData {
  CallData() = default;
  CallData(std::string op, std::string sdk_name, std::string class_name_value, std::string function_name_value,
           std::string overload_value, std::string params)
      : op_id(std::move(op)),
        sdk(std::move(sdk_name)),
        class_name(std::move(class_name_value)),
        function_name(std::move(function_name_value)),
        overload(std::move(overload_value)),
        params_json(std::move(params)) {}

  std::string op_id;
  std::string sdk;
  std::string interface_name;
  std::string class_name;
  std::string function_name;
  std::string overload;
  std::string resource_ref;
  std::string store_as;
  std::string params_json = "{}";
  std::string extra_json = "{}";
  std::string callback_context_json = "{}";
  bool sync = true;
};

struct EventTarget {
  EventTarget() = default;
  EventTarget(std::string sdk_name, std::string class_name_value, std::string function_name_value,
              std::string overload_value = "")
      : sdk(std::move(sdk_name)),
        class_name(std::move(class_name_value)),
        function_name(std::move(function_name_value)),
        overload(std::move(overload_value)) {}

  std::string sdk;
  std::string interface_name;
  std::string class_name;
  std::string function_name;
  std::string overload;
};

// callbackEventRequest 上报的最小事件事实，保持纯协议字段，不序列化 native 对象。
struct CallbackEventFact {
  std::string node_id;
  std::string run_id;
  std::string case_id;
  std::string step_id;
  std::string event_id;
  EventTarget event_target;
  std::string payload_json;
  uint64_t timestamp_ms = 0;
};

// callback 执行上下文只承载 callback-specific 字段，trace 字段由事件事实单独携带。
struct CallbackExecutionContext {
  std::string provider;
  std::string originating_op_id;
  std::string resource_ref;
  std::string instance_id;
  std::string subscription_id;
  std::string rule_id;
  uint64_t sequence = 0;
};

// 调用、ack、错误路径统一返回该结构，result_json 在 wire 上保持 JSON 字符串。
struct CallResult {
  int error = kOk;
  std::string message = "ok";
  std::string result_json = "{}";

  bool ok() const { return error == kOk; }
};

// 日志和报告的追踪上下文，用于把 run、case、step、op_id 串起来。
struct TraceContext {
  std::string node_id;
  std::string lease_id;
  std::string run_id;
  std::string case_id;
  std::string step_id;
  std::string op_id;
};

// Agent Core 内部统一日志事件，写出前必须经过 Redactor。
struct LogEvent {
  std::string event_id;
  long long timestamp_ms = 0;
  std::string level;
  TraceContext trace;
  std::string module;
  std::string event;
  std::string message;
  int error = 0;
  Json::Value extra = Json::Value(Json::objectValue);
};

}  // namespace beacon
