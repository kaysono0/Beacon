import pytest

from app.devices.device_models import DeviceSelector
from app.reporting.evidence_runtime import ResultCollector
from app.runs.run_runtime import ServerRunRuntime
from app.common.errors import RunStateTransitionError
from app.runs.test_models import StepResult, TestCase, TestRun, TestStep
from app.reporting.reporting import ReportGenerator


TARGET = {"sdk": "mock_echo", "class_name": "Echo", "function": "state"}


class FakeLogCollector:
    def __init__(self, logs: list[dict]) -> None:
        self.logs = logs
        self.queries: list[dict] = []

    async def query_by_trace(self, run_id: str, case_id: str, step_id: str, **kwargs: object) -> list[dict]:
        self.queries.append({"run_id": run_id, "case_id": case_id, "step_id": step_id, **kwargs})
        return list(self.logs)


class FakeRunReader:
    def __init__(self, run: TestRun | None) -> None:
        self.run = run

    async def get_run(self, run_id: str) -> TestRun | None:
        _ = run_id
        return self.run


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_COVERAGE_07_report_projects_blocked_scenarios_and_missing_capabilities() -> None:
    run = TestRun(
        run_id="run-blocked-report",
        status="passed",
        selector=DeviceSelector(),
        cases=[
            TestCase(
                case_id="case-runnable",
                name="runnable",
                suite="smoke_core",
                scenario_family="direct_call",
                implementation_status="runnable",
                covered_capabilities=["join_success"],
                steps=[TestStep(step_id="join")],
            ),
            TestCase(
                case_id="case-blocked",
                name="blocked",
                suite="network_resilience",
                scenario_family="failure_recovery",
                implementation_status="designed_but_blocked",
                blocked_category="missing_fault_injection_provider",
                blocked_reason="network shaping is unavailable",
                runnable_prerequisites=["fault injection provider"],
                owner_layer="platform_bridge",
                covered_capabilities=["weak_network_recovery"],
                steps=[TestStep(step_id="recover")],
            ),
        ],
        results=[StepResult(case_id="case-runnable", step_id="join", status="passed")],
    )

    report = await ReportGenerator(FakeRunReader(run)).generate(run.run_id, "json")

    assert report.capability_coverage["missing_capabilities"] == ["weak_network_recovery"]
    assert report.capability_coverage["case_count_by_layer"] == {"core": 1, "enhanced": 0, "resilience": 1}
    assert report.scenario_coverage["families"]["failure_recovery"]["designed_but_blocked"] == 1
    assert report.blocked_scenarios == [
        {
            "case_id": "case-blocked",
            "name": "blocked",
            "suite": "network_resilience",
            "scenario_family": "failure_recovery",
            "covered_capabilities": ["weak_network_recovery"],
            "implementation_status": "designed_but_blocked",
            "blocked_category": "missing_fault_injection_provider",
            "blocked_reason": "network shaping is unavailable",
            "runnable_prerequisites": ["fault injection provider"],
            "owner_layer": "platform_bridge",
        }
    ]


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_COVERAGE_08_report_uses_related_logs_for_failure_diagnostics(tmp_path) -> None:
    run = TestRun(
        run_id="run-report",
        status="failed",
        selector=DeviceSelector(),
        cases=[
            TestCase(
                case_id="case-report",
                name="report",
                suite="report_resilience",
                scenario_family="failure_recovery",
                implementation_status="runnable",
                covered_capabilities=["log-diagnostics"],
                steps=[TestStep(step_id="step-report")],
            )
        ],
        results=[
            StepResult(
                case_id="case-report",
                step_id="step-report",
                status="failed",
                node_id="device-runtime",
                lease_id="lease-runtime",
                error={"code": 500, "message": "join failed"},
                finished_at_ms=1000,
            )
        ],
    )
    logs = [
        {"timestamp_ms": 1000, "level": "error", "module": "agora", "event": "ignored", "extra": ["not", "dict"]},
        {
            "timestamp_ms": 1001,
            "level": "error",
            "node_id": "device-runtime",
            "lease_id": "lease-runtime",
            "op_id": "op-runtime",
            "module": "agora",
            "event": "join_failed",
            "message": "join failed",
            "extra": {
                "failure_category": "sdk_error",
                "failure_reason": "invalid_token",
                "owner_layer": "sdk",
                "artifact_uri": "artifact://logs/external.jsonl",
                "round_id": "round-1",
            },
        },
    ]

    generator = ReportGenerator(FakeRunReader(run), log_collector=FakeLogCollector(logs), log_artifact_dir=tmp_path)
    report = await generator.generate("run-report", "json")
    junit = await generator.generate_junit("run-report")

    diagnostics = report.summary["failure_diagnostics"]
    assert diagnostics["by_category"] == {"sdk_error": 1}
    assert diagnostics["by_reason"] == {"invalid_token": 1}
    assert diagnostics["by_owner_layer"] == {"sdk": 1}
    assert diagnostics["items"][0]["classification"]["event"] == "join_failed"
    assert diagnostics["items"][0]["classification"]["artifact_uri"] == "artifact://logs/external.jsonl"
    assert report.case_results[0]["log_artifacts"][0].startswith("artifact://logs/run-report/")
    assert '<failure message="join failed" />' in junit


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_COVERAGE_11_run_runtime_rejects_invalid_start_states() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    with pytest.raises(RunStateTransitionError):
        await runtime.create_run(TestRun(run_id="run-invalid-create", status="running", selector=DeviceSelector(), cases=[]))

    run = await runtime.create_run(TestRun(run_id="run-invalid-start", status="queued", selector=DeviceSelector(), cases=[]))
    await runtime.start_run(run.run_id, [])
    with pytest.raises(RunStateTransitionError):
        await runtime.start_run(run.run_id, [])
