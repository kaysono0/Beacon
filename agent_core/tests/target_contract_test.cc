#include "beacon/target_contract.h"

#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#include "beacon/protocol_json.h"

namespace {

// 与 server/tests/test_phase1_components.py 的 fixtures 门共用同一份样例文件（ADR-020）。
const char* kFixturesPath = "test_cases/target_contract/targets.json";

bool ProfileFromName(const std::string& name, beacon::TargetProfile* profile) {
  if (name == "call") {
    *profile = beacon::TargetProfile::kCall;
  } else if (name == "callback") {
    *profile = beacon::TargetProfile::kCallback;
  } else if (name == "registry") {
    *profile = beacon::TargetProfile::kRegistry;
  } else if (name == "assertion") {
    *profile = beacon::TargetProfile::kAssertion;
  } else if (name == "evidence") {
    *profile = beacon::TargetProfile::kEvidence;
  } else if (name == "system") {
    *profile = beacon::TargetProfile::kSystem;
  } else if (name == "wire_compat") {
    *profile = beacon::TargetProfile::kWireCompat;
  } else {
    return false;
  }
  return true;
}

int RunFixtures(const Json::Value& cases) {
  for (const auto& item : cases) {
    const std::string id = item["id"].asString();
    beacon::TargetProfile profile = beacon::TargetProfile::kWireCompat;
    if (!ProfileFromName(item["profile"].asString(), &profile)) {
      std::cerr << "UT-TC-01 " << id << " has unknown profile\n";
      return 1;
    }
    const auto result = beacon::NormalizeTargetValue(item["input"], profile);
    if (item["valid"].asBool()) {
      if (!result.ok) {
        std::cerr << "UT-TC-01 " << id << " was rejected: " << result.error << "\n";
        return 1;
      }
      if (beacon::TargetToJson(result.target) != item["normalized"]) {
        std::cerr << "UT-TC-01 " << id << " normalized target mismatch\n";
        return 1;
      }
      if (beacon::TargetKey(result.target) != item["key"].asString()) {
        std::cerr << "UT-TC-01 " << id << " canonical key mismatch\n";
        return 1;
      }
      continue;
    }
    if (result.ok) {
      std::cerr << "UT-TC-01 " << id << " should have failed\n";
      return 1;
    }
    if (result.error != item["error"].asString()) {
      std::cerr << "UT-TC-01 " << id << " error mismatch: " << result.error << "\n";
      return 1;
    }
  }
  return 0;
}

}  // namespace

int main() {
  std::ifstream file(kFixturesPath);
  if (!file) {
    std::cerr << "UT-TC-01 cannot open " << kFixturesPath << "\n";
    return 1;
  }
  std::stringstream buffer;
  buffer << file.rdbuf();
  Json::Value cases;
  if (!beacon::ParseJson(buffer.str(), &cases) || !cases.isArray() || cases.empty()) {
    std::cerr << "UT-TC-01 fixtures must be a non-empty array\n";
    return 1;
  }
  return RunFixtures(cases);
}
