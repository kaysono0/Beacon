#pragma once

#include <cstdint>
#include <functional>
#include <mutex>
#include <string>

#include "beacon/models.h"
#include "beacon/runner_kernel.h"

namespace beacon::mac {

// 将 SDK 回调交给 RunnerKernel，并通知 observer 组装上行事件。
// 持有 active/pending 上下文、本地执行回执和事件序号；上下文仅供关联，不证明调用因果。
// mutex_ 只保护桥内状态；kernel 和 observer 在锁外调用，不由此保证它们自身的线程安全。
class RTCEventBridge {
 public:
  struct ActiveEngineIdentity {
    std::string resource_ref;
    std::string instance_id;
    std::string originating_op_id;
    std::string run_id;
    std::string case_id;
    std::string device_role;
    std::string step_id;
    uint64_t sequence = 0;
  };

  using EventObserver = std::function<void(const std::string&,
                                           const std::string&,
                                           const beacon::CallbackExecutionResult&,
                                           const ActiveEngineIdentity&)>;

  explicit RTCEventBridge(beacon::RunnerKernel* kernel);
  // kernel 为借用指针；调用方需保证它在进行中的 Emit 返回前仍有效。
  void Bind(beacon::RunnerKernel* kernel);
  void SetNodeId(std::string node_id);
  void Suppress(bool suppressed);
  void SetObserver(EventObserver observer);
  void SuppressJoinSuccessForTesting(bool suppressed);
  // 替换默认回调上下文并重置序号；Restore 则恢复捕获时的序号。
  void SetActiveEngineIdentity(std::string resource_ref, std::string instance_id);
  void SetActiveEngineIdentity(ActiveEngineIdentity identity);
  void RestoreActiveEngineIdentity(ActiveEngineIdentity identity);
  // SDK 请求发起前记录 pending；成功时仅激活同一操作，失败时仅取消同一操作。
  // 激活不移除 pending；新请求可覆盖它，Clear 会同时清除 active/pending。
  void TrackPendingEngineIdentity(ActiveEngineIdentity identity);
  void ActivatePendingEngineIdentity(const ActiveEngineIdentity& identity);
  void CancelPendingEngineIdentity(const ActiveEngineIdentity& identity);
  // 从 call 构造上下文副本，不修改桥内的 active/pending 状态。
  ActiveEngineIdentity CaptureActiveEngineIdentity(const beacon::CallData& call,
                                                   std::string resource_ref,
                                                   std::string instance_id) const;
  void ClearActiveEngineIdentity();
  ActiveEngineIdentity active_engine_identity() const;
  // 无显式上下文时优先用 active，active 无来源时才回退到 pending。
  // 返回本地执行回执；上行事件由 observer 负责，回执不代表 Server 已接收或记录事件。
  std::string Emit(const std::string& function_name, const std::string& payload_json);
  std::string Emit(const std::string& function_name,
                   const std::string& payload_json,
                   const ActiveEngineIdentity& identity);
  // 一旦已有 matched 回执，后续未匹配的回调不会覆盖它。
  std::string last_response() const;
  bool has_matched_callback() const;

 private:
  beacon::RunnerKernel* kernel_;
  bool suppressed_ = false;
  bool suppress_join_success_for_testing_ = false;
  std::string node_id_ = "mac-mock-001";
  std::string last_response_;
  bool has_matched_callback_ = false;
  ActiveEngineIdentity active_engine_identity_;
  ActiveEngineIdentity pending_engine_identity_;
  uint64_t sequence_ = 0;
  EventObserver observer_;
  mutable std::mutex mutex_;
};

}  // namespace beacon::mac
