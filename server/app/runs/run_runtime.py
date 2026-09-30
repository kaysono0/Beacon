"""Server 运行时事实写入 facade。

Phase 5: ServerRunRuntime 作为运行时事实的唯一写入边界，统一管理：
- callback event 摄入和去重
- Evidence 写入（event/metric/state/artifact/log）
- Step result 记录
- Pending request 生命周期管理（resolve/timeout/fail）

所有写操作必须通过此facade，不得直接调用 ResultCollector 或 EvidenceStore。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from app.api.api_contracts import RunnerWaitRequest
from app.devices.device_models import Device
from app.reporting.evidence_runtime import Evidence, PendingRequest, ResultCollector, now_ms
from app.common.errors import RunStateTransitionError
from app.common.interfaces import TestRunStoreProtocol
from app.observations.observation_ingress import callback_observation
from app.observations.observation_models import ObservationInput, ObservationQuery, ObservationRecord, ObservationTarget
from app.observations.observation_service import (
    ObservationService,
    ObservationWaitCancelledError,
    ObservationWaitTimeoutError,
)
from app.runs.test_models import CaseExecutionResult, RunTerminalStatus, StepResult, TestRun
from app.runs.test_run_store import MemoryTestRunStore

# 只有非终态 run 还存在未完成的执行；终态 run 的取消请求必须幂等地返回当前快照。
ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})


class ObservationWaitConflictError(ValueError):
    """同一 wait ID 被不同请求体重复使用。"""


class ServerRunRuntime:
    """运行时事实写入边界。

    封装 ResultCollector 和 EvidenceStore，提供统一的写入口。
    确保所有事实写入都经过此层，便于后续迁移到持久化存储。
    """

    def __init__(
        self,
        collector: ResultCollector,
        run_store: TestRunStoreProtocol | None = None,
        observation_service: ObservationService | None = None,
    ) -> None:
        self._collector = collector
        self._observation_service = observation_service
        self._seen_events: set[tuple[str, str, str]] = set()
        self._run_store = run_store or MemoryTestRunStore()
        self._run_lock = asyncio.Lock()
        self._cancellation_requests: set[str] = set()
        self._active_operations: dict[str, int] = {}
        self._operation_condition = asyncio.Condition(self._run_lock)
        self._wait_lock = asyncio.Lock()
        self._wait_operations: dict[
            tuple[str, str, str],
            tuple[str, asyncio.Task[ObservationRecord]],
        ] = {}

    async def create_run(self, run: TestRun) -> TestRun:
        """注册初始 queued run 快照。"""
        async with self._run_lock:
            existing = await self._run_store.get(run.run_id)
            if existing is not None:
                raise RunStateTransitionError(run.run_id, existing.status, "create_run")
            if run.status != "queued":
                raise RunStateTransitionError(run.run_id, run.status, "create_run")
            return await self._persist_run(run.model_copy(deep=True))

    async def get_run(self, run_id: str) -> TestRun | None:
        """返回隔离的 run 快照。"""
        run = await self._run_store.get(run_id)
        return run.model_copy(deep=True) if run is not None else None

    async def list_runs(self, limit: int) -> list[TestRun]:
        """按创建时间倒序返回隔离的 run 快照清单，供 Console 运行历史使用。"""
        return await self._run_store.list_runs(limit)

    async def request_cancellation(self, run_id: str) -> TestRun | None:
        """登记协作取消请求并返回当前 run 快照；run 不存在时返回 None。

        这里只写请求标记、不落终态：进行中的执行器仍持有后续 step/case 写入，
        提前终态化会让它的下一次写入撞上 RunStateTransitionError。
        终态由执行器在用例/步骤边界调用 finish_run 写 cancelled。
        已终态 run 不登记标记，直接返回快照，使重复取消请求幂等。
        """
        should_wake_waits = False
        async with self._run_lock:
            run = await self._run_store.get(run_id)
            if run is None:
                return None
            if run.status in ACTIVE_RUN_STATUSES:
                self._cancellation_requests.add(run_id)
                should_wake_waits = True
            snapshot = run.model_copy(deep=True)
        if should_wake_waits and self._observation_service is not None:
            await self._observation_service.cancel_waits(run_id)
        return snapshot

    async def is_cancellation_requested(self, run_id: str) -> bool:
        """执行器边界检查点读取取消请求；集合成员判断本身原子，不需要持锁。"""
        return run_id in self._cancellation_requests

    async def start_run(self, run_id: str, selected_devices: list[Device]) -> TestRun:
        """将 queued run 转换为 running 并固化选中的设备。"""
        async with self._run_lock:
            run = await self._run_for_operation(run_id, "start_run")
            if run.status != "queued":
                raise RunStateTransitionError(run_id, run.status, "start_run")
            updated = run.model_copy(deep=True)
            updated.status = "running"
            updated.selected_devices = [device.model_copy(deep=True) for device in selected_devices]
            return await self._persist_run(updated)

    async def record_step_result(self, run_id: str, result: StepResult) -> TestRun:
        """向 running run 追加一个步骤结果。"""
        async with self._run_lock:
            run = await self._run_for_operation(run_id, "record_step_result")
            if run.status != "running":
                raise RunStateTransitionError(run_id, run.status, "record_step_result")
            updated = run.model_copy(deep=True)
            updated.results.append(result.model_copy(deep=True))
            return await self._persist_run(updated)

    async def record_case_result(self, run_id: str, result: CaseExecutionResult) -> TestRun:
        """向 running run 追加目标 case 终态，不创建逐操作 StepResult。"""
        async with self._run_lock:
            run = await self._run_for_operation(run_id, "record_case_result")
            if run.status != "running":
                raise RunStateTransitionError(run_id, run.status, "record_case_result")
            if result.case_id not in {case.case_id for case in run.cases}:
                raise ValueError("case does not belong to run")
            if any(item.case_id == result.case_id for item in run.case_results):
                raise ValueError("case result already recorded")
            updated = run.model_copy(deep=True)
            updated.case_results.append(result.model_copy(deep=True))
            return await self._persist_run(updated)

    async def query_observations(
        self,
        run_id: str,
        case_id: str,
        query: ObservationQuery,
        *,
        node_id: str | None = None,
        lease_id: str | None = None,
    ) -> list[ObservationRecord]:
        """按 endpoint path 强制收窄 Runner 只读查询，不创建 step。"""

        if self._observation_service is None:
            raise RuntimeError("observation service is not configured")
        scoped_query = query.model_copy(
            update={"run_id": run_id, "case_id": case_id, "node_id": node_id, "lease_id": lease_id}
        )
        return await self._observation_service.query(scoped_query)

    async def wait_for_observation(
        self,
        run_id: str,
        case_id: str,
        request: RunnerWaitRequest,
        *,
        node_id: str | None = None,
        lease_id: str | None = None,
    ) -> ObservationRecord:
        """执行一个 Runner wait，并保存独立的操作结果事实。"""

        if self._observation_service is None:
            raise RuntimeError("observation service is not configured")
        body = json.dumps(request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
        key = (run_id, case_id, request.wait_id)
        async with self._wait_lock:
            existing = self._wait_operations.get(key)
            if existing is not None:
                if existing[0] != body:
                    raise ObservationWaitConflictError(
                        f"observation wait {request.wait_id!r} conflicts within run {run_id!r} case {case_id!r}"
                    )
                task = existing[1]
            else:
                await self._reserve_operation(run_id, "reserve_wait")
                task = asyncio.create_task(
                    self._execute_observation_wait(
                        run_id,
                        case_id,
                        request,
                        node_id=node_id,
                        lease_id=lease_id,
                        started_at_ms=now_ms(),
                    )
                )
                self._wait_operations[key] = (body, task)
        return await asyncio.shield(task)

    async def _execute_observation_wait(
        self,
        run_id: str,
        case_id: str,
        request: RunnerWaitRequest,
        *,
        node_id: str | None,
        lease_id: str | None,
        started_at_ms: int,
    ) -> ObservationRecord:
        if self._observation_service is None:
            raise RuntimeError("observation service is not configured")
        query = ObservationQuery(
            run_id=run_id,
            case_id=case_id,
            device_role=request.device_role,
            node_id=node_id,
            lease_id=lease_id,
            kinds=frozenset({request.kind}),
            target=ObservationTarget.model_validate(
                request.target.model_dump(mode="python", by_alias=True, exclude_none=True)
            ),
            match=request.match,
            after_cursor=request.after_cursor or 0,
        )
        try:
            record = await self._observation_service.wait(query, request.timeout_ms)
        except ObservationWaitTimeoutError as error:
            await self._record_wait_result(
                run_id, case_id, request, started_at_ms, "timed_out", "observation_timeout", str(error),
                node_id=node_id, lease_id=lease_id,
            )
            raise
        except ObservationWaitCancelledError as error:
            await self._record_wait_result(
                run_id, case_id, request, started_at_ms, "cancelled", "cancelled", str(error),
                node_id=node_id, lease_id=lease_id,
            )
            raise
        else:
            await self._record_wait_result(
                run_id,
                case_id,
                request,
                started_at_ms,
                "matched",
                None,
                "",
                node_id=record.node_id,
                lease_id=record.lease_id,
                matched_observation_id=record.observation_id,
            )
            return record
        finally:
            await self._release_operation(run_id)

    async def _reserve_operation(self, run_id: str, requested_operation: str) -> None:
        async with self._operation_condition:
            run = await self._run_for_operation(run_id, requested_operation)
            if run.status != "running" or run_id in self._cancellation_requests:
                raise RunStateTransitionError(run_id, run.status, requested_operation)
            self._active_operations[run_id] = self._active_operations.get(run_id, 0) + 1

    async def reserve_call(self, run_id: str) -> None:
        """在 run 收尾前预留一个在途 Runner call。"""

        await self._reserve_operation(run_id, "reserve_call")

    async def release_call(self, run_id: str) -> None:
        """call 结果事实写完后释放预留。"""

        await self._release_operation(run_id)

    async def _release_operation(self, run_id: str) -> None:
        async with self._operation_condition:
            active = self._active_operations.get(run_id, 0)
            if active <= 1:
                self._active_operations.pop(run_id, None)
            else:
                self._active_operations[run_id] = active - 1
            self._operation_condition.notify_all()

    async def _record_wait_result(
        self,
        run_id: str,
        case_id: str,
        request: RunnerWaitRequest,
        started_at_ms: int,
        status: str,
        classification: str | None,
        message: str,
        *,
        node_id: str | None = None,
        lease_id: str | None = None,
        matched_observation_id: str | None = None,
    ) -> None:
        if self._observation_service is None:
            raise RuntimeError("observation service is not configured")
        finished_at_ms = now_ms()
        observation_id = "wait:" + hashlib.sha256(
            json.dumps([case_id, request.wait_id], separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        await self._observation_service.ingest(
            ObservationInput.model_validate(
                {
                    "observation_id": observation_id,
                    "kind": "operation",
                    "run_id": run_id,
                    "case_id": case_id,
                    "device_role": request.device_role,
                    "node_id": node_id or "unknown",
                    "lease_id": lease_id or "unscoped",
                    "source": "observation_wait",
                    "target": request.target.model_dump(mode="python", by_alias=True, exclude_none=True),
                    "payload": {
                        "operation_type": "wait",
                        "request_id": request.wait_id,
                        "outcome": status,
                        "failure_classification": classification,
                        "message": message,
                        "matched_observation_id": matched_observation_id,
                        "source": request.source.model_dump(mode="python"),
                        "started_at_ms": started_at_ms,
                        "finished_at_ms": finished_at_ms,
                        "duration_ms": max(0, finished_at_ms - started_at_ms),
                    },
                    "timestamp_ms": finished_at_ms,
                }
            )
        )

    async def finish_run(self, run_id: str, status: RunTerminalStatus, finished_at_ms: int) -> TestRun:
        """将 running run 转换为指定终态并记录完成时间。"""
        # 让已由调用方调度的 wait 先完成 admission 和在途登记。
        await asyncio.sleep(0)
        async with self._operation_condition:
            while self._active_operations.get(run_id, 0) > 0:
                await self._operation_condition.wait()
            run = await self._run_for_operation(run_id, "finish_run")
            if run.status != "running":
                raise RunStateTransitionError(run_id, run.status, "finish_run")
            if status not in ("passed", "failed", "cancelled"):
                raise RunStateTransitionError(run_id, run.status, "finish_run")
            updated = run.model_copy(deep=True)
            updated.status = status
            updated.finished_at_ms = finished_at_ms
            self._cancellation_requests.discard(run_id)
            return await self._persist_run(updated)

    async def _run_for_operation(self, run_id: str, requested_operation: str) -> TestRun:
        run = await self._run_store.get(run_id)
        if run is None:
            raise RunStateTransitionError(run_id, None, requested_operation)
        return run

    async def _persist_run(self, run: TestRun) -> TestRun:
        await self._run_store.put(run)
        return run.model_copy(deep=True)

    async def ingest_callback_event(self, packet: dict[str, Any]) -> dict[str, Any]:
        """摄入 callback event，执行去重并写入 Evidence。

        Args:
            packet: callbackEventRequest 数据包

        Returns:
            receipt 字典，包含 received/recorded/duplicate/evidence_id
        """
        data = packet.get("data", {})
        node_id = str(data.get("node_id", ""))
        lease_id = str(data.get("lease_id", ""))
        event_id = str(data["event_id"])
        key = (node_id, lease_id, event_id)
        duplicate = key in self._seen_events
        if not duplicate:
            self._seen_events.add(key)
            if self._observation_service is not None:
                await self._observation_service.ingest(callback_observation(packet))
            await self._collector.record_callback_event(packet)
        return {
            "code": 0,
            "message": "ok",
            "event_id": event_id,
            "receipt": {
                "received": True,
                "recorded": not duplicate,
                "duplicate": duplicate,
                "evidence_id": event_id if not duplicate else "",
            },
        }

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
        """创建待处理请求，统一交由运行时边界管理。"""
        return await self._collector.create_pending(
            node_id,
            op_id,
            action,
            timeout_ms,
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
        )

    async def pending_count_for_device(self, node_id: str) -> int:
        """返回指定设备当前 in-flight pending 数。"""
        return await self._collector.pending_count(node_id=node_id)

    async def record_evidence(self, evidence: Evidence) -> Evidence:
        """写入标准 Evidence（event/metric/state/artifact/log）。

        Args:
            evidence: Evidence 对象

        Returns:
            写入后的 Evidence 对象
        """
        return await self._collector.record_evidence(evidence)

    async def resolve_pending(self, node_id: str, op_id: str, packet: dict[str, Any]) -> bool:
        """完成待处理请求，写入响应 Evidence。

        Args:
            node_id: 设备ID
            op_id: 操作ID
            packet: 响应数据包

        Returns:
            是否成功resolve
        """
        return await self._collector.resolve(node_id, op_id, packet)

    async def timeout_pending(self, op_id: str) -> bool:
        """标记待处理请求超时。

        Args:
            op_id: 操作ID
        """
        return await self._collector.timeout(op_id)

    async def fail_pending_for_device(
        self,
        node_id: str,
        reason: str,
        *,
        failure_classification: dict[str, Any] | None = None,
    ) -> None:
        """失败指定设备的所有待处理请求。

        Args:
            node_id: 设备ID
            reason: 失败原因
        """
        await self._collector.fail_all_for_device(
            node_id,
            reason,
            failure_classification=failure_classification,
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
        """记录连接诊断事件。"""
        await self._collector.record_connection_event(
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

    async def cancel_pending(
        self,
        op_id: str,
        *,
        reason: str = "request cancelled",
        code: int = 499,
        failure_classification: dict[str, Any] | None = None,
    ) -> bool:
        """取消待处理请求。

        Args:
            op_id: 操作ID

        Returns:
            是否成功取消
        """
        return await self._collector.cancel(
            op_id,
            reason=reason,
            code=code,
            failure_classification=failure_classification,
        )
