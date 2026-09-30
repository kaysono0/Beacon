#pragma once

#include <string>

#include "beacon/callback_controller.h"
#include "beacon/invocation_controller.h"
#include "beacon/logging.h"
#include "beacon/protocol_validator.h"
#include "beacon/resource_vault.h"

namespace beacon {

// reset 的统一入口，清理会话相关 callback 和资源，不清除平台能力注册表。
class RuntimeCleaner {
 public:
  RuntimeCleaner(CallbackController* callbacks, ResourceVault* vault);
  void Reset();

 private:
  CallbackController* callbacks_;
  ResourceVault* vault_;
};

// 平台无关 Agent Core 门面。
// RunnerKernel 组合协议校验、调用、回调、资源和日志；连接由平台进程入口负责。
class RunnerKernel {
 public:
  int Init();
  void Clear();
  int RegisterInvocation(const std::string& key, InvocationController::Handler handler);
  void Reset();
  // 处理传入的协议请求 JSON，校验并分发接口调用或 callback 注册，返回响应 JSON。
  std::string HandleRequest(const std::string& command_json);
  // 平台 adapter 的本地 callback 入口；callbackEventRequest 只保留为 Agent 向 Server 上报的 wire action。
  CallbackExecutionResult ExecuteCallback(const CallbackEventFact& fact, const CallbackExecutionContext& context);

  InvocationController& invocations();
  CallbackController& callbacks();
  ResourceVault& vault();
  LogReporter& logs();

 private:
  ProtocolValidator validator_;
  InvocationController invocations_;
  CallbackController callbacks_{&invocations_};
  ResourceVault vault_;
  LogReporter logs_;
};

}  // namespace beacon
