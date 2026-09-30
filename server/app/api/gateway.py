"""Agent WebSocket Gateway 的协议分派模块。"""

import time
from typing import Any

from app.reporting.evidence_runtime import ResultCollector
from app.reporting.server_log_runtime import ServerLogCollector
from app.devices.device_runtime import SessionManager
from app.runs.run_runtime import ServerRunRuntime
from app.common.target_contract import TargetContractError, normalize_wire_target


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _valid_target(target: Any) -> bool:
    # target 校验只有 Target Contract 一份实现；网关不得再自带字段清单，否则会与 Agent 判定分叉。
    try:
        normalize_wire_target(target)
    except TargetContractError:
        return False
    return True


def _valid_callback_context(context: Any) -> bool:
    allowed = {
        "provider",
        "originating_op_id",
        "resource_ref",
        "instance_id",
        "subscription_id",
        "rule_id",
        "sequence",
    }
    if not isinstance(context, dict) or set(context) - allowed:
        return False
    if not _nonempty_string(context.get("resource_ref")) or not _nonempty_string(context.get("instance_id")):
        return False
    sequence = context.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        return False
    return all(
        field not in context or _nonempty_string(context[field])
        for field in ("provider", "originating_op_id", "subscription_id", "rule_id")
    )


def _valid_callback_call_result(result: Any) -> bool:
    allowed = {"target", "resource_ref", "error", "message", "return_value"}
    if not isinstance(result, dict) or set(result) - allowed or not _valid_target(result.get("target")):
        return False
    error = result.get("error")
    if not isinstance(error, int) or isinstance(error, bool):
        return False
    if not isinstance(result.get("message"), str) or not isinstance(result.get("return_value"), str):
        return False
    return "resource_ref" not in result or _nonempty_string(result["resource_ref"])


def _valid_callback_execution(execution: Any) -> bool:
    if not isinstance(execution, dict) or set(execution) != {"defer_matched", "defer_executed", "call_results"}:
        return False
    if not isinstance(execution["defer_matched"], bool) or not isinstance(execution["defer_executed"], bool):
        return False
    call_results = execution["call_results"]
    return isinstance(call_results, list) and all(_valid_callback_call_result(item) for item in call_results)


def _callback_event_validation_error(data: Any) -> str | None:
    if not isinstance(data, dict):
        return "data"
    if not _nonempty_string(data.get("event_id")):
        return "event_id"
    if not _valid_target(data.get("event_target")):
        return "event_target"
    if not isinstance(data.get("payload"), dict):
        return "payload"
    if "callback_execution" in data and not _valid_callback_execution(data["callback_execution"]):
        return "callback_execution"
    if "callback_context" in data and not _valid_callback_context(data["callback_context"]):
        return "callback_context"
    return None


class AgentGateway:
    """处理 Agent 上行协议包。

    FastAPI route 只负责鉴权和 WebSocket 生命周期；action 分派集中在这里。
    """

    def __init__(
        self,
        session_manager: SessionManager,
        collector: ResultCollector,
        run_runtime: ServerRunRuntime,
        log_collector: ServerLogCollector | None = None,
    ) -> None:
        self._session_manager = session_manager
        self._collector = collector
        self._run_runtime = run_runtime
        self._log_collector = log_collector

    async def handle_packet(self, websocket: Any, packet: dict) -> dict | None:
        action = packet.get("common", {}).get("action")
        if action == "registerRequest":
            return await self._session_manager.handle_register(websocket, packet)
        if action == "reconnectRequest":
            return await self._session_manager.handle_reconnect(websocket, packet)
        if action == "unregisterRequest":
            return await self._session_manager.handle_unregister(websocket, packet)
        if action == "heartbeatRequest":
            return await self._handle_heartbeat(packet)
        if action in {"invokeResponse", "callbackResponse"}:
            node_id = packet.get("data", {}).get("node_id", "")
            lease_id = packet.get("data", {}).get("lease_id", "")
            if not node_id or not lease_id or not await self._session_manager.is_active_lease(node_id, lease_id):
                reason = "missing lease" if not node_id or not lease_id else "stale lease"
                await self._run_runtime.record_connection_event(
                    "upstream_response_rejected",
                    node_id,
                    lease_id=lease_id,
                    op_id=packet.get("common", {}).get("op_id", ""),
                    reason=reason,
                    details={"action": action},
                )
                return None
            op_id = packet.get("common", {}).get("op_id", "")
            await self._run_runtime.resolve_pending(node_id, op_id, packet)
            return None
        if action == "callbackEventRequest":
            data = packet.get("data", {})
            validation_error = _callback_event_validation_error(data)
            node_id = data.get("node_id", "") if isinstance(data, dict) else ""
            lease_id = data.get("lease_id", "") if isinstance(data, dict) else ""
            if validation_error is not None:
                await self._run_runtime.record_connection_event(
                    "callback_event_rejected",
                    node_id,
                    lease_id=lease_id,
                    op_id=packet.get("common", {}).get("op_id", ""),
                    reason="invalid callback event",
                    details={
                        "event_id": data.get("event_id", "") if isinstance(data, dict) else "",
                        "validation_error": validation_error,
                    },
                )
                return self._callback_event_response(
                    packet,
                    self._rejected_callback_event_receipt(
                        data if isinstance(data, dict) else {},
                        400,
                        f"invalid callback event: {validation_error}",
                    ),
                )
            if not node_id or not lease_id:
                await self._run_runtime.record_connection_event(
                    "callback_event_rejected",
                    node_id,
                    lease_id=lease_id,
                    op_id=packet.get("common", {}).get("op_id", ""),
                    reason="missing lease",
                    details={"event_id": data.get("event_id", "")},
                )
                return self._callback_event_response(packet, self._rejected_callback_event_receipt(data, 400, "missing lease"))
            if not await self._session_manager.is_active_lease(node_id, lease_id):
                await self._run_runtime.record_connection_event(
                    "callback_event_rejected",
                    node_id,
                    lease_id=lease_id,
                    op_id=packet.get("common", {}).get("op_id", ""),
                    reason="stale lease",
                    details={"event_id": data.get("event_id", "")},
                )
                return self._callback_event_response(packet, self._rejected_callback_event_receipt(data, 409, "stale lease"))
            receipt = await self._run_runtime.ingest_callback_event(packet)
            return self._callback_event_response(packet, receipt)
        if action == "logReportRequest" and self._log_collector is not None:
            data = packet.get("data", {})
            node_id = data.get("node_id")
            lease_id = data.get("lease_id")
            events = data.get("events", [])
            if not node_id or not lease_id or not isinstance(events, list):
                stats = {"accepted": 0, "duplicates": 0, "rejected": len(events) if isinstance(events, list) else 1}
            else:
                stats = await self._log_collector.ingest(node_id, lease_id, events)
            return self._log_report_response(packet, stats)
        return {
            "common": {"action": "errorResponse", "op_id": packet.get("common", {}).get("op_id", "")},
            "data": {"code": 400, "message": "unknown action", "result": "{}"},
        }

    async def _handle_heartbeat(self, packet: dict) -> dict:
        data = packet.get("data", {})
        node_id = data.get("node_id", "")
        lease_id = data.get("lease_id", "")
        active = bool(node_id and lease_id and await self._session_manager.is_active_lease(node_id, lease_id))
        if active:
            code = 0
            message = "ok"
        else:
            reason = "missing lease" if not node_id or not lease_id else "stale lease"
            await self._run_runtime.record_connection_event(
                "heartbeat_missed",
                node_id,
                lease_id=lease_id,
                reason=reason,
            )
            code = 409
            message = reason
        return {
            "common": {
                "action": "heartbeatResponse",
                "op_id": packet.get("common", {}).get("op_id", ""),
                "timestamp_ms": int(time.time() * 1000),
            },
            "data": {"code": code, "message": message, "server_time_ms": int(time.time() * 1000)},
        }

    def _callback_event_response(self, packet: dict, receipt: dict) -> dict:
        return {
            "common": {
                "action": "callbackEventResponse",
                "op_id": packet.get("common", {}).get("op_id", ""),
                "timestamp_ms": int(time.time() * 1000),
            },
            "data": receipt,
        }

    def _rejected_callback_event_receipt(self, data: dict, code: int, message: str) -> dict:
        event_id = str(data.get("event_id", ""))
        return {
            "code": code,
            "message": message,
            "event_id": event_id,
            "receipt": {
                "received": True,
                "recorded": False,
                "duplicate": False,
                "evidence_id": "",
            },
        }

    def _log_report_response(self, packet: dict, stats: dict) -> dict:
        return {
            "common": {
                "action": "logReportResponse",
                "op_id": packet.get("common", {}).get("op_id", ""),
                "timestamp_ms": int(time.time() * 1000),
            },
            "data": {"code": 0, "message": "ok", **stats},
        }
