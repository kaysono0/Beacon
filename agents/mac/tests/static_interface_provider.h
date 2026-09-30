#pragma once

#include <string>
#include <utility>

#include "platform/interface_provider.h"

namespace beacon::mac::testing {

// 只声明身份的测试替身，不安装生产 invocation handler。
class StaticInterfaceProvider final : public InterfaceProvider {
 public:
  StaticInterfaceProvider(std::string sdk, std::string interface_name)
      : sdk_(std::move(sdk)), interface_name_(std::move(interface_name)) {}
  std::string sdk() const override { return sdk_; }
  std::string interface_name() const override { return interface_name_; }
  bool Supports(const beacon::CallData& call) const override {
    return call.sdk == sdk_ && call.interface_name == interface_name_;
  }
  void RegisterInvocations(beacon::InvocationController&) override {}

 private:
  std::string sdk_;
  std::string interface_name_;
};

}  // namespace beacon::mac::testing
