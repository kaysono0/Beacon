#include "beacon/resource_vault.h"
#include "beacon/models.h"

#include <iostream>
#include <memory>
#include <string>
#include <vector>

class TestResource : public beacon::VaultResource {
 public:
  TestResource(int order, std::string name, std::vector<std::string>* destroyed)
      : order_(order), name_(std::move(name)), destroyed_(destroyed) {}
  int DestroyOrder() const override { return order_; }
  void Destroy() override { destroyed_->push_back(name_); }

 private:
  int order_;
  std::string name_;
  std::vector<std::string>* destroyed_;
};

int main() {
  beacon::ResourceVault vault;
  std::vector<std::string> destroyed;
  if (vault.Set("", std::make_shared<TestResource>(1, "invalid-key", &destroyed)) != beacon::kBadRequest ||
      vault.Set("invalid-object", nullptr) != beacon::kBadRequest ||
      vault.Get("missing") != nullptr) {
    std::cerr << "UT-MODEL-03 invalid resource operations were accepted\n";
    return 1;
  }
  vault.Set("single", std::make_shared<TestResource>(3, "single", &destroyed));
  if (vault.Get("single") == nullptr || vault.size() != 1) {
    std::cerr << "UT-MODEL-04 resource lookup failed\n";
    return 1;
  }
  vault.Remove("missing");
  vault.Remove("single");
  if ((destroyed != std::vector<std::string>{"single"}) || vault.size() != 0) {
    std::cerr << "UT-MODEL-05 remove did not destroy resource\n";
    return 1;
  }
  destroyed.clear();
  vault.Set("low", std::make_shared<TestResource>(1, "low", &destroyed));
  vault.Set("high-old", std::make_shared<TestResource>(10, "high-old", &destroyed));
  vault.Set("high-new", std::make_shared<TestResource>(10, "high-new", &destroyed));
  vault.Reset();
  if ((destroyed != std::vector<std::string>{"high-new", "high-old", "low"})) {
    std::cerr << "UT-MODEL-01 resource destroy order failed\n";
    return 1;
  }
  if (vault.size() != 0) {
    std::cerr << "UT-MODEL-02 reset did not clear vault\n";
    return 1;
  }
  return 0;
}
