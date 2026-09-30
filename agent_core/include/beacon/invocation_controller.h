#pragma once

#include <functional>
#include <map>
#include <string>
#include <vector>

#include "beacon/models.h"

namespace beacon {

// 管理可调用能力的注册表。
// 平台 adapter 只注册 handler，协议解析和批量聚合由本类统一处理。
class InvocationController {
 public:
  using Handler = std::function<CallResult(const CallData&)>;

  int Init();
  void Clear();
  int RegisterInvocation(const std::string& key, Handler handler);
  void UnregisterInvocation(const std::string& key);
  // 未知 key 和 handler 异常必须稳定转换为协议错误。
  CallResult CallInvocation(const CallData& info) const;
  // 批量调用保持输入顺序，方便服务端把结果映射回步骤证据。
  std::vector<CallResult> InvokeBatch(const std::vector<CallData>& calls) const;
  std::vector<CallResult> OnInvokeRequestBatch(const std::string& packet_json) const;
  CallResult OnInvokeRequest(const std::string& packet_json) const;
  // 供一致性门禁核对平台 adapter 是否注册了 canonical target，不暴露 handler 实现。
  bool HasInvocation(const std::string& key) const;
  size_t size() const;

 private:
  std::map<std::string, Handler> handlers_;
};

}  // namespace beacon
