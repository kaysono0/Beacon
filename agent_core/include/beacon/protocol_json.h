#pragma once

#include <string>
#include <vector>

#include <json/json.h>

#include "beacon/models.h"

namespace beacon {

bool ParseJson(const std::string& json_text, Json::Value* output);
std::string WriteJson(const Json::Value& value);
std::string PacketAction(const Json::Value& packet);
std::string PacketOpId(const Json::Value& packet);
Json::Value PacketData(const Json::Value& packet);
EventTarget EventTargetFromValue(const Json::Value& value);
Json::Value TargetToJson(const EventTarget& target);
std::string TargetKey(const EventTarget& target);
std::string TargetKey(const CallData& call);
CallData CallDataFromPacket(const Json::Value& packet);
CallData CallDataFromItem(const Json::Value& item, const std::string& op_id);
std::vector<CallData> CallDataListFromPacket(const Json::Value& packet);
std::string MakeCallResultJson(const CallResult& result, const std::string& action, const std::string& op_id);
std::string MakeCallResultsJson(const std::vector<CallResult>& results, const std::string& action,
                                const std::string& op_id);
std::string LogEventToJson(const LogEvent& event);

}  // namespace beacon
