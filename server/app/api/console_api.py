"""Mac Test Console 查询与运行控制 API。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.reporting.reporting import ReportGenerator
from app.reporting.server_log_runtime import ServerLogCollector
from app.common.interfaces import TestRunReaderProtocol
from app.observations.observation_models import ObservationQuery
from app.observations.observation_service import ObservationService
from app.runs.python_native_models import NativeTestCase
from app.runs.python_native_registry import PythonNativeRegistry
from app.runs.run_runtime import ACTIVE_RUN_STATUSES, ServerRunRuntime
from app.sdk.sdk_extensions import case_requires_runtime_isolation
from app.sdk.sdk_registry import SDKRegistry
from app.reporting.server_log_events import record_server_log



def sdk_capabilities_payload(sdk_registry: SDKRegistry) -> dict[str, Any]:
    sdks = []
    for sdk_name, artifact in sorted(sdk_registry.artifacts.items()):
        grouped: dict[str, dict[str, Any]] = {}
        for item in artifact.get("interfaces", []):
            target = item.get("target", {})
            interface = target.get("interface", "")
            if not interface:
                continue
            view = grouped.setdefault(
                interface,
                {"interface": interface, "methods": [], "callbacks": [], "metrics": [], "states": []},
            )
            if item.get("kind") == "call":
                view["methods"].append(target)
            elif item.get("kind") == "callback":
                view["callbacks"].append(
                    {
                        "target": target,
                        "filterable_fields": item.get("filterable_fields", []),
                        "evidence_summary_fields": item.get("evidence_summary_fields", []),
                        "payload_schema": item.get("payload_schema", {}),
                    }
                )
        sdks.append({"sdk": sdk_name, "interfaces": list(grouped.values())})
    return {"sdks": sdks}


def test_cases_payload(root: Path) -> dict[str, Any]:
    registry = PythonNativeRegistry.discover(root / "test_cases/python", repo_root=root)
    return {"cases": [_native_case_summary(case) for case in registry.cases]}


async def run_detail_payload(
    run_id: str,
    run_reader: TestRunReaderProtocol,
    report_generator: ReportGenerator,
    log_collector: ServerLogCollector,
    observation_service: ObservationService | None = None,
) -> dict[str, Any]:
    await record_server_log(
        log_collector,
        event="console.run_detail.requested",
        message="console requested run detail and report projection",
        run_id=run_id,
    )
    run = await run_reader.get_run(run_id)
    if run is None:
        raise KeyError(run_id)
    report = await report_generator.generate(run_id, "json")
    if run.execution_mode == "target":
        if observation_service is None:
            raise RuntimeError("target console detail requires ObservationService")
        records = await observation_service.query(ObservationQuery(run_id=run_id, kinds=frozenset({"log"})))
        logs = [record.payload for record in records]
    else:
        logs = await log_collector.query_by_trace(run_id)
    return {
        "run": run.model_dump(), "report": report.model_dump(), "logs": logs,
        "observation_cursor_enabled": run.execution_mode == "target",
    }


async def run_history_payload(
    run_runtime: ServerRunRuntime,
    limit: int,
    log_collector: ServerLogCollector,
) -> dict[str, Any]:
    """Console 运行历史摘要：倒序、限量，只投影列表需要的字段。"""
    await record_server_log(
        log_collector,
        event="console.run_history.requested",
        message="console requested the run history summary list",
        extra={"limit": limit},
    )
    runs = await run_runtime.list_runs(limit)
    return {
        "runs": [
            {
                "run_id": run.run_id,
                "status": run.status,
                "case_ids": [case.case_id for case in run.cases],
                "created_at_ms": run.created_at_ms,
                "finished_at_ms": run.finished_at_ms,
                "duration_ms": (run.finished_at_ms - run.created_at_ms)
                if run.finished_at_ms is not None
                else None,
            }
            for run in runs
        ]
    }


async def cancel_run_payload(
    run_id: str,
    run_runtime: ServerRunRuntime,
    log_collector: ServerLogCollector,
    dispatcher: Any,
) -> dict[str, Any]:
    """取消活动 run，并立即请求每个已选 Agent 回收其运行时会话。"""
    run = await run_runtime.request_cancellation(run_id)
    if run is None:
        raise KeyError(run_id)
    await record_server_log(
        log_collector,
        event="console.run.cancellation_requested",
        message="console requested cooperative run cancellation",
        run_id=run_id,
        extra={"run_status": run.status, "cancellation_marked": run.status in ACTIVE_RUN_STATUSES},
    )
    if run.status in ACTIVE_RUN_STATUSES:
        await _reset_selected_agent_sessions(run, dispatcher, log_collector)
    return run.model_dump()


async def _reset_selected_agent_sessions(run: Any, dispatcher: Any, log_collector: ServerLogCollector) -> None:
    """用通用 runtime reset 落实取消后的 SDK stop/leave/destroy，不在 Server 分支厂商接口。"""
    reset_nodes: set[str] = set()
    for device in run.selected_devices:
        if device.node_id in reset_nodes:
            continue
        reset_nodes.add(device.node_id)
        op_id = f"op-{run.run_id}-runtime-reset-cancel-{len(reset_nodes)}"
        call = {
            "target": {
                "sdk": "beacon_system",
                "interface": "runtime",
                "class_name": "AgentRuntime",
                "function": "resetSession",
            },
            "params": {},
            "extra": {
                "run_id": run.run_id,
                "step_id": "runtime-reset-cancel",
                "runtime_phase": "cancel",
            },
        }
        try:
            response = await dispatcher.send_protocol_invoke(device.node_id, [call], op_id)
            response_code = response.get("data", {}).get("code", 500)
            code = response_code if isinstance(response_code, int) else 500
        except Exception as exc:  # pragma: no cover - concrete dispatchers normalize ordinary transport failures
            code = 502
            response = {"error": str(exc)}
        await record_server_log(
            log_collector,
            event="console.run.cancellation_reset",
            message="requested agent runtime reset for cancelled run",
            run_id=run.run_id,
            level="error" if code != 0 else "info",
            error_code=code,
            extra={"node_id": device.node_id, "op_id": op_id, "response": response},
        )


def _native_case_summary(case: NativeTestCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "name": case.name,
        "platform": case.platform,
        "suite": case.suite,
        "tags": case.tags,
        "covered_capabilities": case.covered_capabilities,
        "scenario_family": case.scenario_family,
        "implementation_status": case.implementation_status,
        "blocked_category": case.blocked_category,
        "blocked_reason": case.blocked_reason,
        "runnable_prerequisites": case.runnable_prerequisites,
        "owner_layer": case.owner_layer,
        "sdk_names": case.sdk_names,
        "steps": [],
        "requires_runtime_isolation": case_requires_runtime_isolation(case.tags, case.sdk_names),
        "source": case.source_path,
    }
