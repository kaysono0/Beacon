"""Server evidence 和 pending request 运行时。

本模块有两条相互独立但经常一起出现的链路：
- `AckTracker` 管理下行请求的 complete-once 终态，resolve/timeout/cancel/disconnect 只能赢一次。
- `EvidenceStore` 保存 callback/state/metric evidence，供断言按 node/run/case/step/target 查询。

`ResultCollector` 是对外 facade；业务层应该通过它访问 ack 和 evidence，不直接越过内部存储。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from app.common.errors import CommandDispatchError, EvidenceStoreError
from app.common.interfaces import EvidenceStoreProtocol
from app.devices.connection_diagnostics import ConnectionEventStore
from app.common.target_contract import normalize_wire_target


def now_ms() -> int:
    """返回协议和报告统一使用的毫秒时间戳。"""
    return int(time.time() * 1000)


def new_op_id() -> str:
    """生成 server 下行请求的 op_id。"""
    return f"op-{uuid.uuid4().hex}"


def create_error_packet(
    action: str,
    op_id: str,
    code: int,
    message: str,
    *,
    failure_classification: dict[str, Any] | None = None,
) -> dict:
    """构造协议兼容的错误 response packet。"""
    packet = {
        "common": {"action": action, "op_id": op_id, "timestamp_ms": now_ms()},
        "data": {"code": code, "message": message, "result": "{}"},
    }
    if failure_classification is not None:
        packet["data"]["failure_classification"] = deepcopy(failure_classification)
    return packet


def dispatch_timeout_classification() -> dict[str, str]:
    return {"category": "timeout", "source": "dispatch", "reason": "dispatch_timeout"}


def send_failure_classification() -> dict[str, str]:
    return {"category": "dispatch_failure", "source": "transport", "reason": "send_failure"}


def connection_failure_classification(reason: str) -> dict[str, str]:
    if reason not in {"disconnect", "stale_lease"}:
        raise ValueError(f"unsupported connection failure reason: {reason}")
    return {"category": "dispatch_failure", "source": "connection", "reason": reason}


def canonical_target(target: dict[str, Any]) -> dict[str, Any]:
    return normalize_wire_target(target)


@dataclass
class PendingRequest:
    """等待 Agent 响应的下行请求。

    ResultCollector 独占它的终态写入，避免 resolve、timeout、disconnect、
    cancel 之间出现多次完成。
    """

    node_id: str
    op_id: str
    action: str
    future: asyncio.Future
    run_id: str | None = None
    case_id: str | None = None
    step_id: str | None = None
    created_at_ms: int = field(default_factory=now_ms)


@dataclass
class StoredEvent:
    """保留 callbackEventRequest 的原始 common/data 视图。"""

    common: dict
    data: dict


@dataclass(frozen=True)
class Evidence:
    """通用运行期证据。"""

    type: str
    source: str
    node_id: str
    target: dict
    payload: Any
    timestamp_ms: int
    run_id: str | None = None
    case_id: str | None = None
    step_id: str | None = None
    callback_context: dict[str, Any] | None = None
    callback_execution: dict[str, Any] | None = None
    raw: dict = field(default_factory=dict)


class AckTracker:
    """持有 pending request，并独占终态写入。

    resolve、timeout、disconnect、cancel 都必须经过本类，
    保证每个 pending request 只完成一次。
    """

    def __init__(self, connection_diagnostics: ConnectionEventStore | None = None) -> None:
        self._pending: dict[str, PendingRequest] = {}
        self._lock = asyncio.Lock()
        self._connection_diagnostics = connection_diagnostics

    async def create_pending(
        self,
        node_id: str,
        op_id: str,
        action: str,
        timeout_ms: int,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> PendingRequest:
        """登记等待 Agent response 的 pending request。"""
        loop = asyncio.get_running_loop()
        pending = PendingRequest(
            node_id=node_id,
            op_id=op_id,
            action=action,
            future=loop.create_future(),
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
        )
        async with self._lock:
            self._pending[op_id] = pending
        return pending

    async def resolve(self, node_id: str, op_id: str, packet: dict) -> bool:
        """按 op_id 和成对的 response action 完成 pending request。

        Agent 响应可能不包含 node_id，因此 op_id 是主匹配键。请求不存在、已完成、
        node_id 不匹配或 response action 不匹配时返回 False，并保留 pending 给正确
        响应或 timeout 收尾。
        """
        action_mismatch: tuple[PendingRequest, str, str] | None = None
        async with self._lock:
            pending = self._pending.get(op_id)
            if pending is None or pending.future.done():
                return False
            if node_id and pending.node_id != node_id:
                return False
            expected_action = pending.action.replace("Request", "Response")
            actual_action = str(packet.get("common", {}).get("action", ""))
            if actual_action != expected_action:
                action_mismatch = (pending, expected_action, actual_action)
            else:
                self._pending.pop(op_id, None)
                pending.future.set_result(packet)
        if action_mismatch is not None:
            await self._record_pending_response_rejected(*action_mismatch)
            return False
        return True

    async def timeout(self, op_id: str) -> bool:
        """把指定 pending request 收敛为 timeout 终态。

        Raises CommandDispatchError for logging and diagnostics,
        but still completes the pending request with error packet.
        """
        pending: PendingRequest | None = None
        async with self._lock:
            pending = self._pending.pop(op_id, None)
            if pending is None or pending.future.done():
                return False
            # Create structured error for diagnostics
            error = CommandDispatchError(
                node_id=pending.node_id,
                action=pending.action,
                timeout_ms=5000  # Default timeout
            )
            # Log error details (in production, use proper logger)
            # logger.warning(f"Request timeout: {error}")
            pending.future.set_result(create_error_packet(
                pending.action.replace("Request", "Response"),
                op_id,
                408,
                "request timeout",
                failure_classification=dispatch_timeout_classification(),
            ))
        await self._record_pending_terminal(pending, "request timeout")
        return True

    async def cancel(
        self,
        op_id: str,
        *,
        reason: str = "request cancelled",
        code: int = 499,
        failure_classification: dict[str, Any] | None = None,
    ) -> bool:
        """把指定 pending request 收敛为 cancel 终态。"""
        pending: PendingRequest | None = None
        async with self._lock:
            pending = self._pending.pop(op_id, None)
            if pending is None or pending.future.done():
                return False
            pending.future.set_result(
                create_error_packet(
                    pending.action.replace("Request", "Response"),
                    op_id,
                    code,
                    reason,
                    failure_classification=failure_classification,
                )
            )
        await self._record_pending_terminal(pending, reason)
        return True

    async def fail_all_for_device(
        self,
        node_id: str,
        reason: str,
        *,
        failure_classification: dict[str, Any] | None = None,
    ) -> None:
        """断连、注销、重复注册时终结该设备名下所有 pending request。"""
        terminals: list[PendingRequest] = []
        async with self._lock:
            matches = [pending for pending in self._pending.values() if pending.node_id == node_id]
            for pending in matches:
                self._pending.pop(pending.op_id, None)
                if not pending.future.done():
                    pending.future.set_result(
                        create_error_packet(
                            pending.action.replace("Request", "Response"),
                            pending.op_id,
                            408,
                            reason,
                            failure_classification=failure_classification,
                        )
                    )
                    terminals.append(pending)
        for pending in terminals:
            await self._record_pending_terminal(pending, reason)

    async def pending_count(self, node_id: str | None = None) -> int:
        async with self._lock:
            if node_id is not None:
                return sum(1 for pending in self._pending.values() if pending.node_id == node_id)
            return len(self._pending)

    async def _record_pending_terminal(self, pending: PendingRequest, reason: str) -> None:
        if self._connection_diagnostics is None:
            return
        await self._connection_diagnostics.record(
            "pending_terminal",
            pending.node_id,
            op_id=pending.op_id,
            reason=reason,
            run_id=pending.run_id,
            case_id=pending.case_id,
            step_id=pending.step_id,
            details={"action": pending.action},
        )

    async def _record_pending_response_rejected(
        self,
        pending: PendingRequest,
        expected_action: str,
        actual_action: str,
    ) -> None:
        if self._connection_diagnostics is None:
            return
        await self._connection_diagnostics.record(
            "pending_response_rejected",
            pending.node_id,
            op_id=pending.op_id,
            reason="response action mismatch",
            run_id=pending.run_id,
            case_id=pending.case_id,
            step_id=pending.step_id,
            details={
                "request_action": pending.action,
                "expected_response_action": expected_action,
                "actual_response_action": actual_action,
            },
        )


class EvidenceStore(EvidenceStoreProtocol):
    """保存通用运行期 Evidence。

    Implements EvidenceStoreProtocol for dependency inversion.
    Supports normalized event, metric, state, artifact, and log evidence with query filters.
    """

    def __init__(self) -> None:
        self._callback_events: dict[str, list[StoredEvent]] = {}
        self._evidence: dict[str, list[Evidence]] = {}
        # Secondary indexes for fast trace-context queries
        self._by_run: dict[str, list[Evidence]] = {}  # run_id -> evidences
        self._by_case: dict[str, list[Evidence]] = {}  # case_id -> evidences
        self._by_step: dict[str, list[Evidence]] = {}  # step_id -> evidences
        self._lock = asyncio.Lock()

    async def record_callback_event(self, packet: dict) -> StoredEvent:
        """记录 Agent 上报的运行期 callback event。

        callbackEventRequest 是事件证据，不表示 defer 安装结果。
        """
        event = StoredEvent(common=packet.get("common", {}), data=packet.get("data", {}))
        node_id = event.data.get("node_id", "")
        evidence = self._callback_event_to_evidence(packet)
        async with self._lock:
            self._callback_events.setdefault(node_id, []).append(event)
            self._evidence.setdefault(node_id, []).append(evidence)
            if evidence.run_id:
                self._by_run.setdefault(evidence.run_id, []).append(evidence)
            if evidence.case_id:
                self._by_case.setdefault(evidence.case_id, []).append(evidence)
            if evidence.step_id:
                self._by_step.setdefault(evidence.step_id, []).append(evidence)
        return event

    async def callback_events(self, node_id: str) -> list[StoredEvent]:
        async with self._lock:
            return list(self._callback_events.get(node_id, []))

    async def record_evidence(self, evidence: Evidence) -> Evidence:
        """写入通用 Evidence，并同步维护 trace 上下文索引。

        target 在写入前会规范化，避免查询端因为 wire target 形状差异漏匹配。
        """
        try:
            normalized = Evidence(
                type=evidence.type,
                source=evidence.source,
                run_id=evidence.run_id,
                case_id=evidence.case_id,
                step_id=evidence.step_id,
                node_id=evidence.node_id,
                target=canonical_target(evidence.target),
                payload=evidence.payload,
                timestamp_ms=evidence.timestamp_ms,
                callback_context=evidence.callback_context,
                callback_execution=evidence.callback_execution,
                raw=evidence.raw,
            )
        except Exception as exc:
            raise EvidenceStoreError(
                operation="normalize",
                evidence_type=evidence.type
            ) from exc

        async with self._lock:
            # Primary index by node_id
            self._evidence.setdefault(normalized.node_id, []).append(normalized)

            # Secondary indexes for trace-context queries
            if normalized.run_id:
                self._by_run.setdefault(normalized.run_id, []).append(normalized)
            if normalized.case_id:
                self._by_case.setdefault(normalized.case_id, []).append(normalized)
            if normalized.step_id:
                self._by_step.setdefault(normalized.step_id, []).append(normalized)

        return normalized

    async def evidence_events(
        self,
        node_id: str,
        target: dict | None = None,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[Evidence]:
        return await self.evidence_by_type(node_id, "event", target, run_id=run_id, case_id=case_id, step_id=step_id)

    async def evidence_by_type(
        self,
        node_id: str,
        evidence_type: str,
        target: dict | None = None,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[Evidence]:
        """按类型、target 和 trace 上下文查询 Evidence。

        step/case/run 索引用来先收窄候选集；最终仍会检查 node_id、target 和 trace 条件。
        """
        expected = canonical_target(target) if target is not None else None

        # Use secondary index if available and selective
        candidates: list[Evidence] | None = None
        async with self._lock:
            # Try most selective index first
            if step_id and step_id in self._by_step:
                candidates = [e for e in self._by_step[step_id] if e.type == evidence_type and e.node_id == node_id]
            elif case_id and case_id in self._by_case:
                candidates = [e for e in self._by_case[case_id] if e.type == evidence_type and e.node_id == node_id]
            elif run_id and run_id in self._by_run:
                candidates = [e for e in self._by_run[run_id] if e.type == evidence_type and e.node_id == node_id]

            # If no selective index, fall back to node_id scan
            if candidates is None:
                candidates = [item for item in self._evidence.get(node_id, []) if item.type == evidence_type]

        # Apply remaining filters
        result = []
        for item in candidates:
            # Check target match
            if expected is not None and item.target != expected:
                continue
            # Check trace context
            if not self._matches_trace(item, run_id=run_id, case_id=case_id, step_id=step_id):
                continue
            result.append(item)

        return result

    async def evidence_for_step(self, run_id: str, case_id: str, step_id: str) -> list[Evidence]:
        """返回一个 step 下所有类型的 Evidence。"""
        async with self._lock:
            evidence = [item for items in self._evidence.values() for item in items]
        return [item for item in evidence if self._matches_trace(item, run_id=run_id, case_id=case_id, step_id=step_id)]

    def _callback_event_to_evidence(self, packet: dict) -> Evidence:
        common = packet.get("common", {})
        data = packet.get("data", {})
        return Evidence(
            type="event",
            source="callback",
            run_id=data.get("run_id"),
            case_id=data.get("case_id"),
            step_id=data.get("step_id"),
            node_id=data.get("node_id", ""),
            target=canonical_target(data.get("event_target", {})),
            payload=self._decode_payload(data.get("payload", "{}")),
            timestamp_ms=common.get("timestamp_ms", now_ms()),
            callback_context=self._decode_callback_context(data.get("callback_context")),
            callback_execution=self._decode_callback_execution(data.get("callback_execution")),
            raw=packet,
        )

    def _decode_payload(self, payload: Any) -> Any:
        if not isinstance(payload, str):
            return payload
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

    def _decode_callback_context(self, callback_context: Any) -> dict[str, Any] | None:
        if callback_context in (None, ""):
            return None
        if isinstance(callback_context, str):
            try:
                decoded = json.loads(callback_context)
            except json.JSONDecodeError:
                return None
            return decoded if isinstance(decoded, dict) and decoded else None
        if isinstance(callback_context, dict):
            return callback_context or None
        return None

    def _decode_callback_execution(self, callback_execution: Any) -> dict[str, Any] | None:
        """投影 callback defer 执行回执，避免报告读取原始协议包。"""
        if not isinstance(callback_execution, dict):
            return None
        if set(callback_execution) != {"defer_matched", "defer_executed", "call_results"}:
            return None
        if not isinstance(callback_execution["defer_matched"], bool):
            return None
        if not isinstance(callback_execution["defer_executed"], bool):
            return None
        call_results = callback_execution["call_results"]
        if not isinstance(call_results, list):
            return None
        if not callback_execution["defer_matched"] and not callback_execution["defer_executed"] and not call_results:
            return None
        projected_results: list[dict[str, Any]] = []
        for result in call_results:
            if not isinstance(result, dict):
                return None
            if set(result) - {"target", "resource_ref", "error", "message", "return_value"}:
                return None
            projected = {
                key: result[key]
                for key in ("target", "resource_ref", "error", "message")
                if key in result
            }
            if "return_value" in result:
                projected["has_return_value"] = True
            projected_results.append(projected)
        return {
            "defer_matched": callback_execution["defer_matched"],
            "defer_executed": callback_execution["defer_executed"],
            "call_results": projected_results,
        }

    def _matches_trace(
        self,
        evidence: Evidence,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> bool:
        if run_id is not None and evidence.run_id != run_id:
            return False
        if case_id is not None and evidence.case_id != case_id:
            return False
        if step_id is not None and evidence.step_id != step_id:
            return False
        return True


class ResultCollector:
    """结果收集 facade。

    Ack lifecycle 和 runtime event evidence 分别由内部组件管理。
    上层通过这个 facade 共享同一套 pending/evidence 语义。
    """

    def __init__(
        self,
        ack_tracker: AckTracker | None = None,
        event_store: EvidenceStore | None = None,
        connection_diagnostics: ConnectionEventStore | None = None,
    ) -> None:
        self._connection_diagnostics = connection_diagnostics
        self._ack_tracker = ack_tracker or AckTracker(connection_diagnostics=connection_diagnostics)
        self._event_store = event_store or EvidenceStore()

    async def create_pending(
        self,
        node_id: str,
        op_id: str,
        action: str,
        timeout_ms: int,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> PendingRequest:
        return await self._ack_tracker.create_pending(
            node_id,
            op_id,
            action,
            timeout_ms,
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
        )

    async def resolve(self, node_id: str, op_id: str, packet: dict) -> bool:
        return await self._ack_tracker.resolve(node_id, op_id, packet)

    async def timeout(self, op_id: str) -> bool:
        return await self._ack_tracker.timeout(op_id)

    async def cancel(
        self,
        op_id: str,
        *,
        reason: str = "request cancelled",
        code: int = 499,
        failure_classification: dict[str, Any] | None = None,
    ) -> bool:
        return await self._ack_tracker.cancel(
            op_id,
            reason=reason,
            code=code,
            failure_classification=failure_classification,
        )

    async def fail_all_for_device(
        self,
        node_id: str,
        reason: str,
        *,
        failure_classification: dict[str, Any] | None = None,
    ) -> None:
        await self._ack_tracker.fail_all_for_device(
            node_id,
            reason,
            failure_classification=failure_classification,
        )

    async def pending_count(self, node_id: str | None = None) -> int:
        return await self._ack_tracker.pending_count(node_id=node_id)

    async def record_callback_event(self, packet: dict) -> StoredEvent:
        return await self._event_store.record_callback_event(packet)

    async def record_evidence(self, evidence: Evidence) -> Evidence:
        return await self._event_store.record_evidence(evidence)

    async def callback_events(self, node_id: str) -> list[StoredEvent]:
        return await self._event_store.callback_events(node_id)

    async def evidence_events(
        self,
        node_id: str,
        target: dict | None = None,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[Evidence]:
        return await self._event_store.evidence_events(node_id, target, run_id=run_id, case_id=case_id, step_id=step_id)

    async def evidence_by_type(
        self,
        node_id: str,
        evidence_type: str,
        target: dict | None = None,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[Evidence]:
        return await self._event_store.evidence_by_type(
            node_id,
            evidence_type,
            target,
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
        )

    async def evidence_for_step(self, run_id: str, case_id: str, step_id: str) -> list[Evidence]:
        return await self._event_store.evidence_for_step(run_id, case_id, step_id)

    async def connection_events(
        self,
        *,
        node_id: str | None = None,
        event_type: str | None = None,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._connection_diagnostics is None:
            return []
        return await self._connection_diagnostics.summaries(
            node_id=node_id,
            event_type=event_type,
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
        )

    async def record_connection_event(
        self,
        event_type: str,
        node_id: str,
        *,
        lease_id: str = "",
        op_id: str = "",
        reason: str = "",
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if self._connection_diagnostics is None:
            return
        await self._connection_diagnostics.record(
            event_type,
            node_id,
            lease_id=lease_id,
            op_id=op_id,
            reason=reason,
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
            details=details,
        )
