#pragma once

#include <map>
#include <string>
#include <vector>

#include "beacon/invocation_controller.h"
#include "beacon/models.h"

namespace beacon {

// defer 定义的运行态副本，保留原始调用链和 repeat 策略。
struct DeferInfo {
  EventTarget event_target;
  int repeat = 1;
  std::vector<CallData> calls;
};

struct CallbackCallResult {
  CallData call;
  CallResult result;
};

struct CallbackExecutionResult {
  bool matched = false;
  CallbackEventFact fact;
  CallbackExecutionContext context;
  std::vector<CallbackCallResult> call_results;
};

// 管理 callbackRequest 安装的 defer，并在运行期事件到达时触发命令链。
// callbackRequest 只表示安装结果，真正的 SDK 事件由 OnCallback 处理。
class CallbackController {
 public:
  explicit CallbackController(InvocationController* invocation_controller = nullptr);
  int Init();
  void Clear();
  void BindInvocationController(InvocationController* invocation_controller);
  CallResult OnCallbackRequest(const std::string& packet_json);
  // 运行期 callback event 会消费 repeat 次数，并按 defer 定义调用 InvocationController。
  CallbackExecutionResult OnCallback(const CallbackEventFact& fact, const CallbackExecutionContext& context);
  const CallbackExecutionResult& last_execution_result() const;
  const CallbackExecutionResult& last_matched_execution_result() const;
  void Reset();
  size_t size() const;

 private:
  InvocationController* invocation_controller_ = nullptr;
  std::map<std::string, std::vector<DeferInfo>> defers_;
  CallbackExecutionResult last_execution_result_;
  CallbackExecutionResult last_matched_execution_result_;
};

}  // namespace beacon
