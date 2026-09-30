"""Server 下行命令分发运行时。

本模块负责把 server 内部 call/defer 描述转换为 wire packet，通过当前 WebSocket
发给 Agent，并把 op_id 注册到 pending request 生命周期中。
它不解释 SDK 返回值，也不执行断言；这些由 runner/assertion 层完成。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.common import CONFIG
from app.devices.device_runtime import DeviceRegistry
from app.common.errors import CommandDispatchError, DeviceNotFoundError
from app.reporting.evidence_runtime import (
    ResultCollector,
    create_error_packet,
    dispatch_timeout_classification,
    new_op_id,
    now_ms,
    send_failure_classification,
)
from app.common.interfaces import CommandDispatcherProtocol
from app.runs.run_runtime import ServerRunRuntime

from beacon_test.wire_json import canonical_json


class PacketBuilder:
    """集中构造下行 wire packet，避免协议字段散落在业务层。"""

    def invoke_request(self, node_id: str, lease_id: str, op_id: str, calls: list[dict]) -> dict:
        """构造 invokeRequest。"""
        from app.reporting.evidence_runtime import canonical_target

        return {
            "common": {"action": "invokeRequest", "op_id": op_id, "timestamp_ms": now_ms()},
            "data": {
                "node_id": node_id,
                "lease_id": lease_id,
                "sync": all(call.get("sync", True) for call in calls),
                "list": [self._call_element(call) for call in calls],
            },
        }

    def callback_request(self, node_id: str, lease_id: str, op_id: str, defers: list[dict]) -> dict:
        """构造 callbackRequest。"""
        return {
            "common": {"action": "callbackRequest", "op_id": op_id, "timestamp_ms": now_ms()},
            "data": {
                "node_id": node_id,
                "lease_id": lease_id,
                "sync": all(call.get("sync", True) for call in defers),
                "list": [self._callback_descriptor(call) for call in defers],
            },
        }

    def _callback_descriptor(self, call: dict) -> dict:
        """把 callback rule 转成 Agent 侧 DeferDescriptor。"""
        from app.common.target_contract import normalize_event_target

        call_elements = call.get("call_elements")
        if call_elements:
            normalized_elements = [self._call_element(item) for item in call_elements]
        else:
            # 单 call 简写在 wire 层仍然规范成 call_elements 数组。
            normalized_elements = [self._call_element(call)]
        return {
            "event_target": normalize_event_target(call.get("event_target", {})),
            "repeat": call.get("repeat", 1),
            "call_elements": normalized_elements,
        }

    def _call_element(self, call: dict) -> dict:
        """把单次 SDK call 转成协议 CallData。"""
        from app.reporting.evidence_runtime import canonical_target

        element = {
            "target": canonical_target(call.get("target", {})),
            "params": canonical_json(call.get("params", {})),
            "extra": canonical_json(call.get("extra", {})),
        }
        if call.get("resource_ref"):
            element["resource_ref"] = call["resource_ref"]
        if call.get("store_as"):
            element["store_as"] = call["store_as"]
        return element


class WebSocketTransport:
    """把 packet 写入当前 WebSocket adapter。"""

    async def send(self, websocket: Any, packet: dict) -> None:
        await websocket.send_json(packet)


class CommandDispatcher(CommandDispatcherProtocol):
    """统一下发命令到设备。

    Runner 不直接写 WebSocket，所有 invokeRequest 和 callbackRequest
    都从这里创建 op_id、注册 pending request 并发送。

    Implements CommandDispatcherProtocol for dependency inversion.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        collector: ResultCollector,
        session_manager: Any = None,
        packet_builder: PacketBuilder | None = None,
        transport: WebSocketTransport | None = None,
        *,
        run_runtime: ServerRunRuntime,
        max_pending_per_device: int | None = None,
    ) -> None:
        self._registry = registry
        self._collector = collector
        self._session_manager = session_manager
        self._packet_builder = packet_builder or PacketBuilder()
        self._transport = transport or WebSocketTransport()
        self._run_runtime = run_runtime
        self._max_pending_per_device = CONFIG.max_pending_per_device if max_pending_per_device is None else max_pending_per_device

    async def send_invoke(self, node_id: str, calls: list[dict], timeout_ms: int | None = None) -> dict:
        """向设备发送 invokeRequest，并等待对应 invokeResponse。"""
        return await self._send(node_id, calls, "invokeRequest", timeout_ms or CONFIG.pending_request_ttl_ms)

    async def send_protocol_invoke(
        self,
        node_id: str,
        calls: list[dict],
        op_id: str,
        timeout_ms: int | None = None,
        *,
        expected_lease_id: str | None = None,
    ) -> dict:
        """发送 recorder-owned ID 的 invokeRequest，保持 pending/wire/response 同一 ID。"""
        if not isinstance(op_id, str) or not op_id:
            raise ValueError("protocol operation id must be non-empty")
        return await self._send(
            node_id,
            calls,
            "invokeRequest",
            timeout_ms or CONFIG.pending_request_ttl_ms,
            op_id=op_id,
            expected_lease_id=expected_lease_id,
        )

    async def install_callback(self, node_id: str, defers: list[dict], timeout_ms: int | None = None) -> dict:
        """向设备发送 callbackRequest，并等待安装结果。"""
        return await self._send(node_id, defers, "callbackRequest", timeout_ms or CONFIG.pending_request_ttl_ms)

    async def install_protocol_callback(
        self,
        node_id: str,
        defers: list[dict],
        registration_id: str,
        timeout_ms: int,
        *,
        expected_lease_id: str,
    ) -> dict:
        """按 Runner 提供的稳定 ID 安装回调规则，拒绝连接租约漂移。"""
        return await self._send(
            node_id,
            defers,
            "callbackRequest",
            timeout_ms,
            op_id=registration_id,
            expected_lease_id=expected_lease_id,
            persist_callback=False,
        )

    async def _send(
        self,
        node_id: str,
        calls: list[dict],
        action: str,
        timeout_ms: int,
        *,
        op_id: str | None = None,
        expected_lease_id: str | None = None,
        persist_callback: bool = True,
    ) -> dict:
        """发送单个协议请求，并等待 ResultCollector 给出终态。

        离线、空调用、超时都返回协议兼容 error packet，保证上层可以统一按 response 处理。
        """
        session = await self._registry.get(node_id)
        response_action = action.replace("Request", "Response")
        response_op_id = op_id or new_op_id()
        if session is None:
            return create_error_packet(response_action, response_op_id, 404, "device offline")
        if expected_lease_id is not None and session.lease_id != expected_lease_id:
            return create_error_packet(response_action, response_op_id, 409, "device lease changed")
        if not calls:
            return create_error_packet(response_action, response_op_id, 400, "missing call")
        if self._max_pending_per_device > 0 and await self._run_runtime.pending_count_for_device(node_id) >= self._max_pending_per_device:
            await self._run_runtime.record_connection_event(
                "pending_limit_rejected",
                node_id,
                reason="pending limit exceeded",
                details={"limit": self._max_pending_per_device, "action": action},
            )
            return create_error_packet(response_action, response_op_id, 429, "pending limit exceeded")
        op_id = response_op_id
        trace = self._trace_context(calls)
        pending = await self._run_runtime.create_pending(node_id, op_id, action, timeout_ms, **trace)
        payload = self._build_payload(node_id, session.lease_id, op_id, action, calls)
        try:
            try:
                await self._transport.send(session.websocket, payload)
            except Exception as exc:
                await self._run_runtime.cancel_pending(
                    op_id,
                    reason="send failure",
                    code=502,
                    failure_classification=send_failure_classification(),
                )
                await self._run_runtime.record_connection_event(
                    "send_failed",
                    node_id,
                    lease_id=session.lease_id,
                    op_id=op_id,
                    reason=str(exc),
                    **trace,
                    details={"action": action},
                )
                return create_error_packet(
                    response_action,
                    op_id,
                    502,
                    "send failure",
                    failure_classification=send_failure_classification(),
                )
            try:
                response = await asyncio.wait_for(asyncio.shield(pending.future), timeout=timeout_ms / 1000)
            except asyncio.TimeoutError:
                await self._run_runtime.timeout_pending(op_id)
                error = CommandDispatchError(
                    node_id=node_id,
                    action=action,
                    timeout_ms=timeout_ms,
                )
                return create_error_packet(
                    response_action,
                    op_id,
                    408,
                    str(error),
                    failure_classification=dispatch_timeout_classification(),
                )
        except asyncio.CancelledError:
            await self._run_runtime.cancel_pending(op_id, reason="dispatch cancelled")
            raise
        if action == "callbackRequest" and persist_callback and self._session_manager is not None and response.get("data", {}).get("code", 0) == 0:
            for index, call in enumerate(calls):
                # 只有 Agent 确认安装成功后，reconnect context 才能保存 callback 定义。
                await self._session_manager.store_callback(node_id, f"{op_id}:{index}", call)
        return response

    def _build_payload(self, node_id: str, lease_id: str, op_id: str, action: str, calls: list[dict]) -> dict:
        if action == "invokeRequest":
            return self._packet_builder.invoke_request(node_id, lease_id, op_id, calls)
        return self._packet_builder.callback_request(node_id, lease_id, op_id, calls)

    def _trace_context(self, calls: list[dict]) -> dict[str, str | None]:
        for call in calls:
            trace = self._trace_from_extra(call.get("extra"))
            if any(trace.values()):
                return trace
            for element in call.get("call_elements", []) or []:
                trace = self._trace_from_extra(element.get("extra"))
                if any(trace.values()):
                    return trace
        return {"run_id": None, "case_id": None, "step_id": None}

    def _trace_from_extra(self, extra: Any) -> dict[str, str | None]:
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except json.JSONDecodeError:
                extra = {}
        if not isinstance(extra, dict):
            extra = {}
        return {
            "run_id": extra.get("run_id") if isinstance(extra.get("run_id"), str) else None,
            "case_id": extra.get("case_id") if isinstance(extra.get("case_id"), str) else None,
            "step_id": extra.get("step_id") if isinstance(extra.get("step_id"), str) else None,
        }
