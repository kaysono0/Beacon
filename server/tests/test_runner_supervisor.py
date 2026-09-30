"""IR-07 target-only run 编排与 Server 终态测试。"""

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app import main
from app.api.api_contracts import RunnerCallRequest, RunnerCaseResultRequest
from app.devices.device_models import Device, DeviceSelector, DeviceSession
from app.devices.device_runtime import DeviceRegistry
from app.reporting.evidence_runtime import ResultCollector
from app.observations.observation_models import ObservationQuery
from app.observations.observation_service import ObservationService
from app.runs.python_native_models import NativeTestCase
from app.runs.python_native_runtime import RuntimeParamResolver
from app.runs.run_call_service import RunCallService
from app.runs.run_runtime import ServerRunRuntime
from app.runs.runner_case_registry import RunnerAuthorizationError, RunnerCaseRegistry
from app.runs.runner_process import RunnerProcessOutcome
from app.runs.runner_supervisor import RunnerSupervisor, TargetRunSelectionError
from app.sdk.sdk_registry import SDKRegistry
from app.runs.test_models import TestCase, TestRun
from app.runs.test_run_store import JsonlTestRunStore

from beacon_test.registry_paths import registry_dir


def _unused_case(_):
    raise AssertionError("case must execute only in Runner")


def _case(case_id="TC-TARGET"):
    return NativeTestCase(
        case_id=case_id, name="target", platform="macos", devices=["primary"],
        suite="target", scenario_family="test", implementation_status="runnable",
        covered_capabilities=[], tags=[], source_path="test_cases/target_runtime/case.py",
        function_name="test_case", function=_unused_case,
    )


class FakeDispatcher:
    def __init__(self):
        self.phases = []
        self.fail_phase = None

    async def send_protocol_invoke(self, node_id, calls, op_id, timeout_ms, *, expected_lease_id=None):
        phase = calls[0]["extra"]["runtime_phase"]
        self.phases.append((phase, node_id, expected_lease_id))
        return {"common": {"op_id": op_id}, "data": {"code": 500 if phase == self.fail_phase else 0}}


class FakeCalls:
    def __init__(self):
        self.finished = []

    async def finish_case(self, context):
        self.finished.append(context.case_id)


class FakeProcess:
    def __init__(self, outcome=None):
        self.outcome = outcome or RunnerProcessOutcome(
            "completed", 0, RunnerCaseResultRequest(status="passed"),
        )
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.contexts = []
        self.credentials = []

    async def run(self, context, credential, *, cancel_requested):
        self.contexts.append(context)
        self.credentials.append(credential)
        self.entered.set()
        await self.release.wait()
        if await cancel_requested():
            return RunnerProcessOutcome("cancelled", -15, None)
        return self.outcome


class InFlightCallDispatcher:
    def __init__(self):
        self.phases = []
        self.call_entered = asyncio.Event()
        self.release_call = asyncio.Event()

    async def send_protocol_invoke(self, node_id, calls, op_id, timeout_ms, *, expected_lease_id=None):
        assert node_id == "node-1" and expected_lease_id == "lease-1"
        phase = calls[0]["extra"].get("runtime_phase")
        if phase:
            self.phases.append(phase)
            return {"common": {"op_id": op_id}, "data": {"code": 0}}
        self.call_entered.set()
        await self.release_call.wait()
        return {"common": {"op_id": op_id}, "data": {"code": 0, "result": '{"echo":"ok"}'}}


class InFlightCallProcess:
    def __init__(self, calls, case, dispatcher):
        self.calls = calls
        self.case = case
        self.dispatcher = dispatcher
        self.call_task = None
        self.context = None

    async def run(self, context, credential, *, cancel_requested):
        self.context = context
        request = RunnerCallRequest.model_validate({
            "operation_id": "op-create-resource", "device_role": "primary",
            "target": {"sdk": "mock_echo", "interface": "echo", "class": "EchoService", "function": "echo"},
            "params": {"message": "hello"}, "create_resource": True,
            "source": {"path": self.case.source_path, "line": 1, "function": self.case.function_name},
        })
        self.call_task = asyncio.create_task(self.calls.execute(context, request))
        await self.dispatcher.call_entered.wait()
        return RunnerProcessOutcome("completed", 0, RunnerCaseResultRequest(status="passed"))


async def _harness(*, outcome=None, two_cases=False, run_store=None):
    cases = [_case()] + ([_case("TC-TARGET-2")] if two_cases else [])
    devices = DeviceRegistry()
    await devices.upsert(DeviceSession(Device(node_id="node-1", platform="macos"), object(), "lease-1"))
    runtime = ServerRunRuntime(ResultCollector(), run_store)
    registry = RunnerCaseRegistry(cases, now_ms=lambda: 1_000)
    dispatcher = FakeDispatcher()
    calls = FakeCalls()
    process = FakeProcess(outcome)
    observations = ObservationService()
    supervisor = RunnerSupervisor(
        cases=cases, device_registry=devices, run_runtime=runtime,
        case_registry=registry, call_service=calls, process_manager=process,
        dispatcher=dispatcher, observation_service=observations,
    )
    return supervisor, runtime, registry, dispatcher, calls, process


async def _terminal(runtime, run_id):
    for _ in range(200):
        run = await runtime.get_run(run_id)
        if run.status in ("passed", "failed", "cancelled"):
            return run
        await asyncio.sleep(0.001)
    raise AssertionError("run did not terminate")


@pytest.mark.anyio
async def test_IR07_create_returns_queued_then_serial_cases_reset_and_revoke():
    supervisor, runtime, registry, dispatcher, calls, process = await _harness(two_cases=True)
    process.outcome = RunnerProcessOutcome("completed", 0, RunnerCaseResultRequest.model_validate({
        "status": "passed",
        "source": {"path": "test_cases/target_runtime/case.py", "line": 3, "function": "test_case"},
    }))
    process.release.clear()
    run = await supervisor.create_run(["TC-TARGET", "TC-TARGET-2"], DeviceSelector())
    assert run.status == "queued"
    await process.entered.wait()
    assert len(process.contexts) == 1
    process.release.set()
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "passed"
    assert [case.status for case in finished.case_results] == ["passed", "passed"]
    assert finished.case_results[0].source.line == 3
    assert finished.results == []
    assert [phase for phase, _, _ in dispatcher.phases] == ["pre", "final", "pre", "final"]
    assert calls.finished == ["TC-TARGET", "TC-TARGET-2"]
    assert all(lease == "lease-1" for _, _, lease in dispatcher.phases)
    with pytest.raises(RunnerAuthorizationError, match="revoked_token"):
        await registry.authorize(process.credentials[0].token, run.run_id, "TC-TARGET")


@pytest.mark.anyio
async def test_IR07_separate_runs_do_not_execute_cases_concurrently():
    supervisor, runtime, _, _, _, process = await _harness()
    process.release.clear()
    first = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    await process.entered.wait()
    second = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    await asyncio.sleep(0)
    assert len(process.contexts) == 1
    assert (await runtime.get_run(second.run_id)).status == "queued"

    process.release.set()
    assert (await _terminal(runtime, first.run_id)).status == "passed"
    assert (await _terminal(runtime, second.run_id)).status == "passed"
    assert len(process.contexts) == 2


@pytest.mark.anyio
async def test_IR07_pre_reset_failure_skips_process_but_runs_final_reset():
    supervisor, runtime, _, dispatcher, calls, process = await _harness()
    dispatcher.fail_phase = "pre"
    run = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "failed"
    assert finished.case_results[0].failure_classification == "pre_reset_failure"
    assert process.contexts == []
    assert [phase for phase, _, _ in dispatcher.phases] == ["pre", "final"]
    assert calls.finished == ["TC-TARGET"]


@pytest.mark.anyio
@pytest.mark.parametrize("candidate_status", ["passed", "unsupported"])
async def test_IR07_final_reset_failure_overrides_success(candidate_status):
    outcome = RunnerProcessOutcome(
        "completed", 0, RunnerCaseResultRequest(status=candidate_status),
    )
    supervisor, runtime, _, dispatcher, _, _ = await _harness(outcome=outcome)
    dispatcher.fail_phase = "final"
    run = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "failed"
    assert finished.case_results[0].failure_classification == "final_reset_failure"
    assert finished.case_results[0].cleanup_failed
    observations = await supervisor._observations.query(ObservationQuery(run_id=run.run_id))
    assert len(observations) == 1
    assert observations[0].payload["phase"] == "final"


@pytest.mark.anyio
async def test_IR07_cancel_terminates_case_and_final_reset_remains_required():
    supervisor, runtime, _, dispatcher, _, process = await _harness()
    process.release.clear()
    run = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    await process.entered.wait()
    await runtime.request_cancellation(run.run_id)
    process.release.set()
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "cancelled"
    assert finished.case_results[0].status == "cancelled"
    assert [phase for phase, _, _ in dispatcher.phases] == ["pre", "final"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_classification"),
    [
        (RunnerProcessOutcome("completed", 1, RunnerCaseResultRequest(
            status="failed", failure_classification="python_assertion", message="assertion failed")),
         "failed", "python_assertion"),
        (RunnerProcessOutcome("completed", 1, RunnerCaseResultRequest(
            status="failed", failure_classification="import_error")), "failed", "import_error"),
        (RunnerProcessOutcome("completed", 1, RunnerCaseResultRequest(
            status="failed", failure_classification="python_exception")), "failed", "python_exception"),
        (RunnerProcessOutcome("process_crash", 9, None), "failed", "process_crash"),
        (RunnerProcessOutcome("runner_startup_failure", -15, None), "failed", "runner_startup_failure"),
        (RunnerProcessOutcome("case_timeout", -15, None), "timed_out", "case_timeout"),
    ],
)
async def test_IR07_process_outcomes_are_server_owned_and_still_reset(
    outcome, expected_status, expected_classification,
):
    supervisor, runtime, _, dispatcher, _, _ = await _harness(outcome=outcome)
    run = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "failed"
    assert finished.case_results[0].status == expected_status
    assert finished.case_results[0].failure_classification == expected_classification
    assert [phase for phase, _, _ in dispatcher.phases] == ["pre", "final"]


@pytest.mark.anyio
async def test_IR07_runner_cancel_candidate_cannot_turn_run_passed():
    outcome = RunnerProcessOutcome("completed", 1, RunnerCaseResultRequest(status="cancelled"))
    supervisor, runtime, _, _, _, _ = await _harness(outcome=outcome)
    run = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "cancelled"
    assert finished.case_results[0].status == "cancelled"


@pytest.mark.anyio
async def test_IR07_target_catalog_rejects_production_case():
    supervisor, _, _, _, _, _ = await _harness()
    with pytest.raises(TargetRunSelectionError, match="not in target catalog"):
        await supervisor.create_run(["TC-PRODUCTION"], DeviceSelector())


@pytest.mark.anyio
async def test_IR07_target_only_http_create_returns_queued(monkeypatch):
    supervisor, runtime, _, _, _, process = await _harness()
    process.release.clear()
    monkeypatch.setattr(main, "runner_supervisor", supervisor)
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        path = "/api/v1/test-runs"
        assert (await client.post(path, json={"case_ids": ["TC-TARGET"]})).status_code == 401
        headers = {"Authorization": "Bearer local-test-token"}
        assert (await client.post(path, headers=headers, json={"case_ids": ["TC-PRODUCTION"]})).status_code == 400
        response = await client.post(path, headers=headers, json={"case_ids": ["TC-TARGET"]})
    assert response.status_code == 200 and response.json()["status"] == "queued"
    process.release.set()
    assert (await _terminal(runtime, response.json()["run_id"])).status == "passed"


@pytest.mark.anyio
async def test_IR07_final_reset_failure_blocks_second_case_and_cancellation_stays_cancelled():
    supervisor, runtime, _, dispatcher, _, process = await _harness(two_cases=True)
    dispatcher.fail_phase = "final"
    run = await supervisor.create_run(["TC-TARGET", "TC-TARGET-2"], DeviceSelector())
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "failed"
    assert [item.case_id for item in finished.case_results] == ["TC-TARGET"]
    assert [context.case_id for context in process.contexts] == ["TC-TARGET"]

    supervisor, runtime, _, dispatcher, _, process = await _harness()
    dispatcher.fail_phase = "final"
    process.release.clear()
    run = await supervisor.create_run(["TC-TARGET"], DeviceSelector())
    await process.entered.wait()
    await runtime.request_cancellation(run.run_id)
    process.release.set()
    finished = await _terminal(runtime, run.run_id)
    assert finished.status == "cancelled"
    assert finished.case_results[0].cleanup_failed


@pytest.mark.anyio
async def test_IR07_restart_reconciliation_fails_target_run_without_reexecution():
    supervisor, runtime, _, dispatcher, _, process = await _harness()
    run = TestRun(
        run_id="persisted-target-run", status="queued", execution_mode="target",
        selector=DeviceSelector(), cases=[TestCase(case_id="TC-TARGET", name="target", steps=[])],
    )
    await runtime.create_run(run)
    await supervisor.reconcile_interrupted_runs()
    finished = await runtime.get_run(run.run_id)
    assert finished.status == "failed"
    assert finished.case_results[0].failure_classification == "server_restarted"
    assert dispatcher.phases == [] and process.contexts == []


@pytest.mark.anyio
async def test_IR07_jsonl_restart_reconciles_only_active_target_runs(tmp_path):
    path = tmp_path / "test-runs.jsonl"
    before = ServerRunRuntime(ResultCollector(), JsonlTestRunStore(path))
    cases = [TestCase(case_id="TC-TARGET", name="target", steps=[])]
    for run_id, mode, running in [
        ("target-queued", "target", False),
        ("target-running", "target", True),
        ("legacy-queued", "legacy", False),
    ]:
        await before.create_run(TestRun(
            run_id=run_id, status="queued", execution_mode=mode,
            selector=DeviceSelector(), cases=cases,
        ))
        if running:
            await before.start_run(run_id, [Device(node_id="old-node")])

    supervisor, _, _, dispatcher, _, process = await _harness(run_store=JsonlTestRunStore(path))
    await supervisor.reconcile_interrupted_runs()
    reloaded = JsonlTestRunStore(path)
    for run_id in ("target-queued", "target-running"):
        run = await reloaded.get(run_id)
        assert run.status == "failed"
        assert run.case_results[0].failure_classification == "server_restarted"
    assert (await reloaded.get("legacy-queued")).status == "queued"
    assert dispatcher.phases == [] and process.contexts == []


@pytest.mark.anyio
async def test_IR07_supervisor_drains_real_call_service_before_final_reset():
    case = _case()
    devices = DeviceRegistry()
    await devices.upsert(DeviceSession(Device(node_id="node-1", platform="macos"), object(), "lease-1"))
    observations = ObservationService()
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    registry = RunnerCaseRegistry([case], now_ms=lambda: 1_000)

    dispatcher = InFlightCallDispatcher()
    calls = RunCallService(
        dispatcher, SDKRegistry.load_from(registry_dir()), RuntimeParamResolver(), runtime, observations,
    )

    process = InFlightCallProcess(calls, case, dispatcher)
    supervisor = RunnerSupervisor(
        cases=[case], device_registry=devices, run_runtime=runtime,
        case_registry=registry, call_service=calls, process_manager=process,
        dispatcher=dispatcher, observation_service=observations,
    )
    run = await supervisor.create_run([case.case_id], DeviceSelector())
    await dispatcher.call_entered.wait()
    await asyncio.sleep(0)
    assert dispatcher.phases == ["pre"]
    dispatcher.release_call.set()
    finished = await _terminal(runtime, run.run_id)
    response = await process.call_task
    assert response.resource_ref is not None
    assert finished.status == "passed" and dispatcher.phases == ["pre", "final"]
    assert calls._operations == {} and calls._resources == {}
    with pytest.raises(RunnerAuthorizationError, match="case_scope_closed"):
        await calls.execute(process.context, RunnerCallRequest.model_validate({
            "operation_id": "op-after-close", "device_role": "primary",
            "target": {"sdk": "mock_echo", "interface": "echo", "class": "EchoService", "function": "echo"},
            "params": {"message": "hello"},
            "source": {"path": case.source_path, "line": 2, "function": case.function_name},
        }))
