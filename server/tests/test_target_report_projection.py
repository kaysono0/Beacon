"""IR-08 target 报告只从 case 终态和 Observation 读取事实。"""

import pytest

from app.devices.device_models import DeviceSelector
from app.reporting.evidence_runtime import ResultCollector
from app.observations.observation_models import ObservationInput, ObservationQuery
from app.observations.observation_service import ObservationService
from app.runs.run_runtime import ServerRunRuntime
from app.runs.test_models import CaseExecutionResult, StepResult, TestCase, TestRun
from app.reporting.reporting import ReportGenerator


@pytest.mark.anyio
async def test_IR09_legacy_report_projection_keeps_step_fixture():
    run = TestRun(
        run_id="legacy-report", status="passed", selector=DeviceSelector(),
        cases=[TestCase(case_id="case-1", name="legacy", steps=[])],
        results=[StepResult(
            case_id="case-1", step_id="step-1", status="passed",
            artifacts=["artifact://legacy.png"],
        )],
    )

    class RunReader:
        async def get_run(self, run_id: str) -> TestRun | None:
            return run if run_id == run.run_id else None

    generator = ReportGenerator(RunReader())
    report = await generator.generate(run.run_id, "json")
    assert report.summary["total_steps"] == 1
    assert report.summary["passed"] == 1
    assert [(item["case_id"], item["step_id"], item["status"]) for item in report.case_results] == [
        ("case-1", "step-1", "passed")
    ]
    assert "operations" not in report.case_results[0]
    assert report.artifact_urls == ["artifact://legacy.png"]
    assert 'tests="1" failures="0"' in await generator.generate_junit(run.run_id)


@pytest.mark.anyio
async def test_IR08_target_report_projects_case_and_observation_without_legacy_steps():
    observations = ObservationService()
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(TestRun(
        run_id="target-report", status="queued", execution_mode="target", selector=DeviceSelector(),
        cases=[TestCase(case_id="case-1", name="target", steps=[])],
    ))
    await runtime.start_run(run.run_id, [])
    await observations.ingest(ObservationInput.model_validate({
        "observation_id": "call-1", "kind": "operation", "run_id": run.run_id, "case_id": "case-1",
        "operation_id": "op-1", "device_role": "primary", "node_id": "node-1", "lease_id": "lease-1",
        "source": "run_call_service", "target": {"sdk": "mock_echo", "interface": "echo", "function": "echo"},
        "payload": {"operation_type": "call", "request_id": "op-1", "outcome": "succeeded"},
        "timestamp_ms": 1,
    }))
    await observations.ingest(ObservationInput.model_validate({
        "observation_id": "artifact-1", "kind": "artifact", "run_id": run.run_id, "case_id": "case-1",
        "device_role": "primary", "node_id": "node-1", "lease_id": "lease-1",
        "source": "artifact_ingress", "target": {"sdk": "beacon", "interface": "artifact", "name": "screenshot"},
        "payload": {"path": "artifact://screen.png"}, "timestamp_ms": 2,
    }))
    await runtime.record_case_result(run.run_id, CaseExecutionResult(
        case_id="case-1", status="passed", started_at_ms=1, finished_at_ms=2,
    ))
    await runtime.finish_run(run.run_id, "passed", 2)

    report = await ReportGenerator(runtime, observation_service=observations).generate(run.run_id, "json")
    assert report.summary["passed"] == 1
    assert report.case_results[0]["status"] == "passed"
    assert report.case_results[0]["observations"][0]["payload"]["request_id"] == "op-1"
    assert report.case_results[0]["operations"] == report.case_results[0]["observations"][:1]
    assert report.artifact_urls == ["artifact://screen.png"]
    assert (await runtime.get_run(run.run_id)).results == []


@pytest.mark.anyio
async def test_IR09_report_keeps_callback_separate_from_operations_and_handles_timeout():
    observations = ObservationService()
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(TestRun(
        run_id="target-timeout", status="queued", execution_mode="target", selector=DeviceSelector(),
        cases=[TestCase(case_id="case-1", name="target", steps=[])],
    ))
    await runtime.start_run(run.run_id, [])
    common = {
        "run_id": run.run_id, "case_id": "case-1", "device_role": "primary",
        "node_id": "node-1", "lease_id": "lease-1", "timestamp_ms": 1,
    }
    await observations.ingest(ObservationInput.model_validate({
        **common, "observation_id": "callback-1", "kind": "event", "source": "native_agent",
        "target": {"sdk": "mock_echo", "interface": "echo", "name": "completed"}, "payload": {"value": 0},
    }))
    await observations.ingest(ObservationInput.model_validate({
        **common, "observation_id": "wait-1", "kind": "operation", "source": "observation_wait",
        "target": {"sdk": "mock_echo", "interface": "echo", "name": "completed"},
        "payload": {"operation_type": "wait", "request_id": "wait-1", "outcome": "timed_out"},
    }))
    await runtime.record_case_result(run.run_id, CaseExecutionResult(
        case_id="case-1", status="timed_out", message="wait timed out", started_at_ms=1, finished_at_ms=2,
    ))
    await runtime.finish_run(run.run_id, "failed", 2)

    generator = ReportGenerator(runtime, observation_service=observations)
    report = await generator.generate(run.run_id, "json")
    facts = await observations.query(ObservationQuery(run_id=run.run_id))
    assert report.case_results[0]["observations"] == [
        fact.model_dump(mode="json", by_alias=True) for fact in facts
    ]
    assert [item["observation_id"] for item in report.case_results[0]["operations"]] == ["wait-1"]
    assert "failures=\"1\"" in await generator.generate_junit(run.run_id)
    assert "wait timed out" in await generator.generate_junit(run.run_id)
