#pragma once

#include <string>

#include "beacon/invocation_controller.h"
#include "beacon/models.h"

namespace beacon::mac {

class InterfaceProvider {
 public:
  virtual ~InterfaceProvider() = default;
  virtual std::string sdk() const = 0;
  virtual std::string interface_name() const = 0;
  virtual bool Supports(const beacon::CallData& call) const = 0;
  virtual void RegisterInvocations(beacon::InvocationController& controller) = 0;
};

}  // namespace beacon::mac
