"""Target-only Runner 的 Server 编排：串行 case、隔离、回收与终态。"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from typing import Literal

from app.devices.device_models import Device, DeviceSelector
from app.reporting.evidence_runtime import now_ms
from app.common.interfaces import CommandDispatcherProtocol, DeviceRegistryProtocol
from app.observations.observation_models import ObservationInput, ObservationTarget
from app.observations.observation_service import ObservationService
from app.runs.python_native_models import NativeTestCase
from app.runs.python_native_role_resolver import RoleResolver
from app.runs.run_call_service import RunCallService
from app.runs.run_runtime import ServerRunRuntime
from app.runs.runner_case_registry import RunnerCaseContext, RunnerCaseRegistry, RunnerRoleBinding
from app.runs.runner_process import RunnerProcessManager, RunnerProcessOutcome
from app.reporting.server_log_events import record_server_log
from app.runs.test_models import CaseExecutionResult, RunTerminalStatus, TestCase, TestRun


class TargetRunSelectionError(ValueError):
    """请求包含不在隔离 target catalog 中的 case。"""


DEFAULT_CASE_TIMEOUT_MS = 180_000
DEFAULT_TOKEN_GRACE_MS = 10_000
DEFAULT_RESET_TIMEOUT_MS = 5_000


class RunnerSupervisor:
    """只为 target run 创建后台任务；Runner 不拥有 run/case 终态。"""

    def __init__(
        self,
        *,
        cases: Sequence[NativeTestCase],
        device_registry: DeviceRegistryProtocol,
        run_runtime: ServerRunRuntime,
        case_registry: RunnerCaseRegistry,
        call_service: RunCallService,
        process_manager: RunnerProcessManager,
        dispatcher: CommandDispatcherProtocol,
        observation_service: ObservationService,
        log_collector: object | None = None,
        case_timeout_ms: int = DEFAULT_CASE_TIMEOUT_MS,
        token_grace_ms: int = DEFAULT_TOKEN_GRACE_MS,
        reset_timeout_ms: int = DEFAULT_RESET_TIMEOUT_MS,
    ) -> None:
        self._cases = {case.case_id: case for case in cases}
        self._devices = device_registry
        self._resolver = RoleResolver(device_registry)
        self._runs = run_runtime
        self._case_registry = case_registry
        self._calls = call_service
        self._process = process_manager
        self._dispatcher = dispatcher
        self._observations = observation_service
        self._logs = log_collector
        self._case_timeout_ms = case_timeout_ms
        self._token_grace_ms = token_grace_ms
        self._reset_timeout_ms = reset_timeout_ms
        self._execution_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    async def create_run(self, case_ids: list[str], selector: DeviceSelector) -> TestRun:
        """验证隔离 catalog 后持久化 queued run，再交给串行后台编排。"""

        if not case_ids or len(set(case_ids)) != len(case_ids):
            raise TargetRunSelectionError("case IDs must be non-empty and unique")
        try:
            cases = [self._cases[case_id] for case_id in case_ids]
        except KeyError as exc:
            raise TargetRunSelectionError(f"case is not in target catalog: {exc.args[0]}") from exc
        run = TestRun(
            run_id=str(uuid.uuid4()),
            status="queued",
            execution_mode="target",
            selector=selector,
            cases=[
                TestCase(
                    case_id=case.case_id,
                    name=case.name,
                    platform=case.platform,
                    suite=case.suite,
                    implementation_status=case.implementation_status,
                    covered_capabilities=case.covered_capabilities,
                    scenario_family=case.scenario_family,
                    steps=[],
                )
                for case in cases
            ],
        )
        queued = await self._runs.create_run(run)
        await record_server_log(
            self._logs, event="runner.run.queued", message="target run queued",
            run_id=queued.run_id, extra={"case_ids": case_ids},
        )
        task = asyncio.create_task(self._execute(queued.run_id, cases, selector))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return queued

    async def reconcile_interrupted_runs(self) -> None:
        """仅收敛持久化 target run；重启后绝不重新下发 Native 调用。"""
        for run in await self._runs.list_runs(10_000):
            if run.execution_mode != "target" or run.status not in ("queued", "running"):
                continue
            if run.status == "queued":
                await self._runs.start_run(run.run_id, [])
            unfinished = next(
                (case for case in run.cases if case.case_id not in {item.case_id for item in run.case_results}),
                None,
            )
            if unfinished is not None:
                await self._runs.record_case_result(
                    run.run_id,
                    self._result(unfinished.case_id, "failed", "server_restarted", "Server restarted during run", now_ms()),
                )
            await self._runs.finish_run(run.run_id, "failed", now_ms())

    async def _execute(self, run_id: str, cases: list[NativeTestCase], selector: DeviceSelector) -> None:
        async with self._execution_lock:
            await self._execute_exclusive(run_id, cases, selector)

    async def _execute_exclusive(self, run_id: str, cases: list[NativeTestCase], selector: DeviceSelector) -> None:
        try:
            selected = await self._resolver.select_devices_for_cases(cases, selector)
            await self._runs.start_run(run_id, selected)
            await record_server_log(
                self._logs, event="runner.run.started", message="target run started",
                run_id=run_id, extra={"node_ids": [device.node_id for device in selected]},
            )
            failed = False
            cancelled = False
            for case in cases:
                if failed or cancelled or await self._runs.is_cancellation_requested(run_id):
                    break
                result = (
                    await self._execute_case(run_id, case, selected)
                    if selected else self._result(case.case_id, "failed", "device_selection", "no selected device", now_ms())
                )
                await self._runs.record_case_result(run_id, result)
                await record_server_log(
                    self._logs, event="runner.case.finished", message="target case finished",
                    run_id=run_id, case_id=case.case_id,
                    extra={"status": result.status, "classification": result.failure_classification,
                           "cleanup_failed": result.cleanup_failed},
                )
                failed = result.status in ("failed", "timed_out") or result.cleanup_failed
                cancelled = result.status == "cancelled"
            status: RunTerminalStatus = (
                "cancelled" if cancelled or await self._runs.is_cancellation_requested(run_id)
                else "failed" if failed else "passed"
            )
            await self._runs.finish_run(run_id, status, now_ms())
            await record_server_log(
                self._logs, event="runner.run.finished", message="target run finished",
                run_id=run_id, extra={"status": status},
            )
        except Exception as exc:
            await record_server_log(
                self._logs, event="runner.supervisor.failed", message="target run orchestration failed",
                run_id=run_id, extra={"error_type": type(exc).__name__},
            )
            run = await self._runs.get_run(run_id)
            if run is not None:
                if run.status == "queued":
                    await self._runs.start_run(run_id, [])
                if run.status in ("queued", "running"):
                    await self._runs.finish_run(run_id, "failed", now_ms())

    async def _execute_case(self, run_id: str, case: NativeTestCase, selected: list[Device]) -> CaseExecutionResult:
        started = now_ms()
        bindings: dict[str, RunnerRoleBinding] = {}
        for role in case.devices:
            device, error = self._resolver.resolve_device(selected, role)
            if error is not None or device is None:
                return self._result(case.case_id, "failed", "device_selection", "missing device role", started)
            session = await self._devices.get(device.node_id)
            if session is None:
                return self._result(case.case_id, "failed", "device_selection", "device disconnected", started)
            bindings[role] = RunnerRoleBinding.from_session(role, session)
        context = RunnerCaseContext(
            run_id=run_id,
            metadata=self._case_registry.require_metadata(case.case_id),
            bindings=bindings,
            case_timeout_ms=self._case_timeout_ms,
            token_expires_at_ms=now_ms() + self._case_timeout_ms + self._token_grace_ms,
        )
        result: CaseExecutionResult | None = None
        cleanup_failed = False
        try:
            if not await self._reset(context, "pre"):
                result = self._result(case.case_id, "failed", "pre_reset_failure", "pre reset failed", started)
            elif await self._runs.is_cancellation_requested(run_id):
                result = self._result(case.case_id, "cancelled", None, "run cancelled", started)
            else:
                result = await self._run_registered_case(context, started)
        finally:
            try:
                await self._calls.finish_case(context)
            finally:
                cleanup_failed = not await self._reset(context, "final")
        assert result is not None
        if cleanup_failed and result.status in ("passed", "unsupported"):
            result = result.model_copy(update={
                "status": "failed", "failure_classification": "final_reset_failure", "message": "final reset failed",
            })
        return result.model_copy(update={"cleanup_failed": cleanup_failed, "finished_at_ms": now_ms()})

    async def _run_registered_case(self, context: RunnerCaseContext, started: int) -> CaseExecutionResult:
        credential = await self._case_registry.register(context)
        try:
            try:
                outcome = await self._process.run(
                    context, credential,
                    cancel_requested=lambda: self._runs.is_cancellation_requested(context.run_id),
                )
                return self._from_process(context.case_id, outcome, started)
            except Exception as exc:
                return self._result(
                    context.case_id, "failed", "process_crash", f"Runner process failed: {type(exc).__name__}", started,
                )
        finally:
            await self._case_registry.finish(context.run_id, context.case_id)

    async def _reset(self, context: RunnerCaseContext, phase: str) -> bool:
        success = True
        seen: set[str] = set()
        for role, binding in context.bindings.items():
            if binding.node_id in seen:
                continue
            seen.add(binding.node_id)
            operation_id = f"reset-{context.run_id}-{context.case_id}-{phase}-{role}"
            call = {
                "target": {
                    "sdk": "beacon_system", "interface": "runtime",
                    "class_name": "AgentRuntime", "function": "resetSession",
                },
                "params": {},
                "extra": {"run_id": context.run_id, "case_id": context.case_id, "runtime_phase": phase},
            }
            try:
                response = await self._dispatcher.send_protocol_invoke(
                    binding.node_id, [call], operation_id, self._reset_timeout_ms,
                    expected_lease_id=binding.lease_id,
                )
                ok = response.get("common", {}).get("op_id") == operation_id and response.get("data", {}).get("code") == 0
            except Exception:
                ok = False
            if not ok:
                success = False
                await self._observations.ingest(ObservationInput(
                    observation_id=f"reset:{context.run_id}:{context.case_id}:{phase}:{role}",
                    kind="operation", run_id=context.run_id, case_id=context.case_id,
                    operation_id=operation_id, device_role=role, node_id=binding.node_id,
                    lease_id=binding.lease_id, source="runner_supervisor",
                    target=ObservationTarget.model_validate({
                        "sdk": "beacon_system", "interface": "runtime", "class": "AgentRuntime", "function": "resetSession",
                    }),
                    payload={"operation_type": "reset", "request_id": operation_id, "phase": phase,
                             "outcome": "failed", "failure_classification": "runtime_reset_failure"},
                    timestamp_ms=now_ms(),
                ))
                await record_server_log(
                    self._logs, event="runner.runtime_reset.failed", message="Agent runtime reset failed",
                    run_id=context.run_id, case_id=context.case_id,
                    extra={"phase": phase, "device_role": role, "node_id": binding.node_id},
                )
        return success

    @staticmethod
    def _result(
        case_id: str,
        status: Literal["passed", "failed", "unsupported", "cancelled", "timed_out"],
        classification: str | None,
        message: str,
        started: int,
    ) -> CaseExecutionResult:
        return CaseExecutionResult(
            case_id=case_id, status=status, failure_classification=classification,
            message=message, started_at_ms=started, finished_at_ms=now_ms(),
        )

    def _from_process(self, case_id: str, outcome: RunnerProcessOutcome, started: int) -> CaseExecutionResult:
        if outcome.reason == "completed" and outcome.candidate is not None:
            candidate = outcome.candidate
            return self._result(
                case_id, candidate.status, candidate.failure_classification, candidate.message, started,
            ).model_copy(update={"source": candidate.source})
        if outcome.reason == "cancelled":
            return self._result(case_id, "cancelled", None, "run cancelled", started)
        if outcome.reason == "case_timeout":
            return self._result(case_id, "timed_out", "case_timeout", "case timeout", started)
        return self._result(case_id, "failed", outcome.reason, outcome.reason, started)
