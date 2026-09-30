#pragma once

namespace beacon {
namespace protocol {

inline constexpr const char* kCommon = "common";
inline constexpr const char* kData = "data";
inline constexpr const char* kAction = "action";
inline constexpr const char* kOpId = "op_id";
inline constexpr const char* kParams = "params";
inline constexpr const char* kExtra = "extra";
inline constexpr const char* kPayload = "payload";
inline constexpr const char* kTarget = "target";
inline constexpr const char* kEventTarget = "event_target";
inline constexpr const char* kSdk = "sdk";
inline constexpr const char* kInterface = "interface";
inline constexpr const char* kClassName = "class_name";
inline constexpr const char* kFunction = "function";
inline constexpr const char* kOverload = "overload";
inline constexpr const char* kResourceRef = "resource_ref";
inline constexpr const char* kStoreAs = "store_as";
inline constexpr const char* kRepeat = "repeat";
inline constexpr const char* kSync = "sync";
inline constexpr const char* kCode = "code";
inline constexpr const char* kMessage = "message";
inline constexpr const char* kResult = "result";
inline constexpr const char* kError = "error";
inline constexpr const char* kReturnValue = "return_value";
inline constexpr const char* kTimestampMs = "timestamp_ms";
inline constexpr const char* kList = "list";
inline constexpr const char* kCallElements = "call_elements";
inline constexpr const char* kState = "state";
inline constexpr const char* kCallbackContext = "callback_context";
inline constexpr const char* kOriginatingOpId = "originating_op_id";
inline constexpr const char* kRunId = "run_id";
inline constexpr const char* kCaseId = "case_id";
inline constexpr const char* kStepId = "step_id";

inline constexpr const char* kRegisterRequest = "registerRequest";
inline constexpr const char* kRegisterResponse = "registerResponse";
inline constexpr const char* kInvokeRequest = "invokeRequest";
inline constexpr const char* kInvokeResponse = "invokeResponse";
inline constexpr const char* kCallbackRequest = "callbackRequest";
inline constexpr const char* kCallbackResponse = "callbackResponse";
inline constexpr const char* kCallbackEventRequest = "callbackEventRequest";
inline constexpr const char* kCallbackEventResponse = "callbackEventResponse";
inline constexpr const char* kReconnectRequest = "reconnectRequest";
inline constexpr const char* kReconnectResponse = "reconnectResponse";
inline constexpr const char* kUnregisterRequest = "unregisterRequest";
inline constexpr const char* kUnregisterResponse = "unregisterResponse";
inline constexpr const char* kHeartbeatRequest = "heartbeatRequest";
inline constexpr const char* kHeartbeatResponse = "heartbeatResponse";
inline constexpr const char* kLogReportRequest = "logReportRequest";
inline constexpr const char* kLogReportResponse = "logReportResponse";
inline constexpr const char* kErrorResponse = "errorResponse";

}  // namespace protocol
}  // namespace beacon
