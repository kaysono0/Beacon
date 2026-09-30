#include "beacon/protocol_validator.h"

#include <iostream>

int main() {
  beacon::ProtocolValidator validator;
  if (!validator.ValidatePacket(R"({"common":{"action":"registerRequest","op_id":"op","timestamp_ms":1},"data":{"node_id":"n1","capabilities":["rtc.mock"]}})")) {
    std::cerr << "UT-PV-01 valid packet smoke failed\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"data":{}})")) {
    std::cerr << "UT-PV-01 invalid packet smoke failed\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op"},"data":{"sync":false,"params":"{}"}})")) {
    std::cerr << "UT-PV-02 sync=false was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackRequest","op_id":"op"},"data":{"sync":true,"repeat":0,"params":"{}"}})")) {
    std::cerr << "UT-PV-03 repeat=0 was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params": { "uid": 1001 }}]}})")) {
    std::cerr << "UT-PV-04 object params with whitespace was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"unknownRequest","op_id":"op","timestamp_ms":1},"data":{}})")) {
    std::cerr << "UT-PV-05 unknown action was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"registerRequest","op_id":"op"},"data":{"node_id":"n1","capabilities":[]}})")) {
    std::cerr << "UT-PV-06 missing timestamp was accepted\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op-extra","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params":"{}","extra":"{\"lang_name\":\"cpp\"}"}]}})")) {
    std::cerr << "UT-PV-07 valid extra JSON string was rejected\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op-bad-extra","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params":"{}","extra":"{"}]}})")) {
    std::cerr << "UT-PV-08 invalid extra JSON string was accepted\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-event","timestamp_ms":1},"data":{"node_id":"n1","event_id":"evt-1","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":{"uid":1001},"callback_execution":{"defer_matched":false,"defer_executed":false,"call_results":[]}}})")) {
    std::cerr << "UT-PV-09 canonical callbackEventRequest was rejected\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-event-local","timestamp_ms":1},"data":{"node_id":"n1","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":{"uid":1001}}})")) {
    std::cerr << "UT-PV-09 schema-incomplete callbackEventRequest was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-event","timestamp_ms":1},"data":{"node_id":"n1","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":"{}"}})")) {
    std::cerr << "UT-PV-10 string payload was accepted\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"unregisterRequest","op_id":"op-unreg","timestamp_ms":1},"data":{"node_id":"n1"}})")) {
    std::cerr << "UT-PV-11 documented unregisterRequest action was rejected\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"logReportRequest","op_id":"op-log","timestamp_ms":1},"data":{"node_id":"n1"}})")) {
    std::cerr << "UT-PV-12 documented logReportRequest action was rejected\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"artifactUploadReq","op_id":"op-artifact","timestamp_ms":1},"data":{"node_id":"n1"}})")) {
    std::cerr << "UT-PV-13 documented artifactUploadReq action was rejected\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op-list","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params":"{}","extra":"{\"lang_name\":\"cpp\"}"}]}})")) {
    std::cerr << "UT-PV-14 invokeRequest list was rejected\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"callbackRequest","op_id":"op-defer","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"repeat":-1,"call_elements":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"params":"{}","extra":"{}"}]}]}})")) {
    std::cerr << "UT-PV-15 callbackRequest list was rejected\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-event","timestamp_ms":1},"data":{"node_id":"n1","event_id":"evt-1","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":{},"callback_context":{"provider":"agora_rtc/rtc_engine","originating_op_id":"op-join","resource_ref":"engine_1","instance_id":"engine_1","sequence":7},"callback_execution":{"defer_matched":true,"defer_executed":true,"call_results":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"resource_ref":"engine_1","error":0,"message":"ok","return_value":"{}"}]}}})")) {
    std::cerr << "UT-PV-16 callbackEventRequest origin context was rejected\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-event-invalid-context","timestamp_ms":1},"data":{"node_id":"n1","event_id":"evt-invalid","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":{},"callback_context":{"originating_op_id":"op-join"},"callback_execution":{"defer_matched":false,"defer_executed":false,"call_results":[]}}})")) {
    std::cerr << "UT-PV-17 incomplete callback context was accepted\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"callbackEventResponse","op_id":"op-event-response","timestamp_ms":1},"data":{"code":0,"message":"ok","event_id":"evt-1","receipt":{"received":true,"recorded":true,"duplicate":false,"evidence_id":"evt-1"}}})")) {
    std::cerr << "UT-PV-18 callbackEventResponse receipt was rejected\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"invokeResponse","op_id":"op-response","timestamp_ms":1},"data":{"code":0,"message":"ok","result":"{}","list":[]}})")) {
    std::cerr << "UT-PV-18B invokeResponse result was rejected\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"invokeResponse","op_id":"op-response","timestamp_ms":1},"data":{"code":0,"message":"ok","result":{},"list":[]}})")) {
    std::cerr << "UT-PV-18C invokeResponse object result was accepted\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"callbackResponse","op_id":"op-callback-response","timestamp_ms":1},"data":{"code":0,"message":"installed"}})")) {
    std::cerr << "UT-PV-18D callbackResponse was rejected\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventResponse","op_id":"op-event-response","timestamp_ms":1},"data":{"code":0,"message":"ok","event_id":"evt-1","receipt":{"received":true,"recorded":true,"duplicate":false,"unexpected":true}}})")) {
    std::cerr << "UT-PV-18E callbackEventResponse receipt with extra field was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-event-bad-execution","timestamp_ms":1},"data":{"node_id":"n1","event_id":"evt-1","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":{},"callback_execution":{"defer_matched":false,"defer_executed":false,"call_results":"[]"}}})")) {
    std::cerr << "UT-PV-18F callback execution with string call_results was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-event-bad-call-result","timestamp_ms":1},"data":{"node_id":"n1","event_id":"evt-1","event_target":{"sdk":"mock","class_name":"MockDelegate","function":"onJoin"},"payload":{},"callback_execution":{"defer_matched":true,"defer_executed":true,"call_results":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"error":0,"message":"ok","return_value":{}}]}}})")) {
    std::cerr << "UT-PV-18G callback execution with object return_value was accepted\n";
    return 1;
  }
  if (!validator.ValidatePacket(R"({"common":{"action":"reconnectResponse","op_id":"op-reconnect-ok","timestamp_ms":1},"data":{"code":0,"message":"ok","state":1}})")) {
    std::cerr << "UT-PV-18H valid reconnectResponse was rejected\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventResponse","op_id":"op-event-response","timestamp_ms":1},"data":{"code":0,"message":"ok","defer_matched":true,"defer_executed":true,"call_results":[{"target":{"sdk":"mock","class_name":"Mock","function":"join"},"error":0,"message":"ok","return_value":"{}"}]}})")) {
    std::cerr << "UT-PV-19 callbackEventResponse evidence fields were accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"reconnectResponse","op_id":"op-reconnect","timestamp_ms":1},"data":{"code":0,"message":"ok","state":2}})")) {
    std::cerr << "UT-PV-20 invalid reconnect state was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op-old","timestamp_ms":1},"data":{"node_id":"n1","method":"mock.join","sync":true,"params":"{}"}})")) {
    std::cerr << "UT-PV-21 legacy invokeRequest shape was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"callbackEventRequest","op_id":"op-old-event","timestamp_ms":1},"data":{"node_id":"n1","event":"onJoin","payload":"{}"}})")) {
    std::cerr << "UT-PV-22 legacy callbackEventRequest shape was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op-extra-field","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","class_name":"Mock","function":"join","params":"{}"},"params":"{}"}]}})")) {
    std::cerr << "UT-PV-23 target with unknown field was accepted\n";
    return 1;
  }
  if (validator.ValidatePacket(R"({"common":{"action":"invokeRequest","op_id":"op-empty-interface","timestamp_ms":1},"data":{"node_id":"n1","sync":true,"list":[{"target":{"sdk":"mock","interface":"","class_name":"Mock","function":"join"},"params":"{}"}]}})")) {
    std::cerr << "UT-PV-24 target with empty interface was accepted\n";
    return 1;
  }
  return 0;
}
