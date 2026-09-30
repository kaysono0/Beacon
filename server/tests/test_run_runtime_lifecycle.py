import asyncio
from typing import Any, cast

import pytest

from app.api.api_contracts import RunnerWaitRequest
from app.devices.device_models import Device, DeviceSelector
from app.common.errors import RunStateTransitionError
from app.reporting.evidence_runtime import ResultCollector
from app.observations.observation_models import ObservationInput, ObservationQuery
from app.observations.observation_service import ObservationService, ObservationWaitCancelledError, ObservationWaitTimeoutError
from app.runs.run_runtime import ObservationWaitConflictError, ServerRunRuntime
from app.runs.test_models import StepResult, TestCase, TestRun, TestStep
from app.runs.test_run_store import MemoryTestRunStore


def sample_run() -> TestRun:
    return TestRun(
        run_id="run-runtime-lifecycle",
        status="queued",
        selector=DeviceSelector(),
        cases=[TestCase(case_id="case-lifecycle", name="lifecycle", steps=[TestStep(step_id="step-lifecycle")])],
    )


def sample_device() -> Device:
    return Device(node_id="device-lifecycle")


def sample_result() -> StepResult:
    return StepResult(case_id="case-lifecycle", step_id="step-lifecycle", status="passed")


def wait_request(
    *,
    state: str,
    timeout_ms: int = 100,
    wait_id: str | None = None,
) -> RunnerWaitRequest:
    return RunnerWaitRequest.model_validate(
        {
            "wait_id": wait_id or f"wait-{state}",
            "device_role": "primary",
            "kind": "event",
            "target": {
                "sdk": "agora_rtc",
                "interface": "rtc_engine",
                "class": "AgoraRtcEngineDelegate",
                "function": "onConnectionStateChanged",
            },
            "match": {"state": state},
            "timeout_ms": timeout_ms,
            "source": {"path": "test_cases/python/example.py", "line": 10, "function": "test_case"},
        }
    )


def observation(observation_id: str, state: str) -> ObservationInput:
    return ObservationInput.model_validate(
        {
            "observation_id": observation_id,
            "kind": "event",
            "run_id": sample_run().run_id,
            "case_id": "case-lifecycle",
            "device_role": "primary",
            "node_id": "device-lifecycle",
            "lease_id": "lease-1",
            "source": "native_agent",
            "target": {
                "sdk": "agora_rtc",
                "interface": "rtc_engine",
                "class": "AgoraRtcEngineDelegate",
                "function": "onConnectionStateChanged",
            },
            "payload": {"state": state},
            "timestamp_ms": 100,
        }
    )


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_16_runtime_owns_run_lifecycle() -> None:
    runtime = ServerRunRuntime(ResultCollector(), MemoryTestRunStore())

    created = await runtime.create_run(sample_run())
    created.status = "failed"
    restored = await runtime.get_run(created.run_id)
    selected_device = sample_device()
    running = await runtime.start_run(created.run_id, [selected_device])
    recorded = await runtime.record_step_result(created.run_id, sample_result())
    finished = await runtime.finish_run(created.run_id, "passed", 123)

    assert restored is not None
    assert restored.status == "queued"
    assert running.status == "running"
    assert running.selected_devices == [selected_device]
    assert len(recorded.results) == 1
    assert (finished.status, finished.finished_at_ms) == ("passed", 123)


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_17_terminal_run_rejects_more_writes() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    await runtime.finish_run(run.run_id, "failed", 123)

    with pytest.raises(RunStateTransitionError) as raised:
        await runtime.record_step_result(run.run_id, sample_result())

    assert raised.value.details == {
        "run_id": run.run_id,
        "current_status": "failed",
        "requested_operation": "record_step_result",
    }


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_18_unknown_run_is_rejected() -> None:
    runtime = ServerRunRuntime(ResultCollector())

    with pytest.raises(RunStateTransitionError) as raised:
        await runtime.start_run("run-missing", [])

    assert raised.value.details == {
        "run_id": "run-missing",
        "current_status": None,
        "requested_operation": "start_run",
    }


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_19_duplicate_run_creation_is_rejected() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = sample_run()
    await runtime.create_run(run)

    with pytest.raises(RunStateTransitionError) as raised:
        await runtime.create_run(run)

    assert raised.value.details == {
        "run_id": run.run_id,
        "current_status": "queued",
        "requested_operation": "create_run",
    }


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_20_step_result_requires_running_run() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = await runtime.create_run(sample_run())

    with pytest.raises(RunStateTransitionError) as raised:
        await runtime.record_step_result(run.run_id, sample_result())

    assert raised.value.details == {
        "run_id": run.run_id,
        "current_status": "queued",
        "requested_operation": "record_step_result",
    }


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["running", "bogus"])
async def test_IT_SRV_RUNTIME_21_finish_run_rejects_non_terminal_runtime_status(status: str) -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])

    with pytest.raises(RunStateTransitionError) as raised:
        await runtime.finish_run(run.run_id, cast(Any, status), 123)

    assert raised.value.details == {
        "run_id": run.run_id,
        "current_status": "running",
        "requested_operation": "finish_run",
    }


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_22_cancellation_request_marks_active_run() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = await runtime.create_run(sample_run())
    selected_device = sample_device()
    await runtime.start_run(run.run_id, [selected_device])

    marked = await runtime.request_cancellation(run.run_id)
    unknown = await runtime.request_cancellation("run-missing")

    assert marked is not None
    assert marked.status == "running"
    assert marked.selected_devices == [selected_device]
    assert await runtime.is_cancellation_requested(run.run_id)
    assert unknown is None
    assert not await runtime.is_cancellation_requested("run-missing")

    queued_runtime = ServerRunRuntime(ResultCollector())
    queued_run = await queued_runtime.create_run(sample_run())
    assert await queued_runtime.request_cancellation(queued_run.run_id) is not None
    assert await queued_runtime.is_cancellation_requested(queued_run.run_id)


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_23_cancellation_request_is_idempotent_for_terminal_run() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    await runtime.finish_run(run.run_id, "passed", 123)

    first = await runtime.request_cancellation(run.run_id)
    second = await runtime.request_cancellation(run.run_id)

    assert first is not None
    assert second is not None
    assert (first.status, first.finished_at_ms) == ("passed", 123)
    assert second == first
    assert not await runtime.is_cancellation_requested(run.run_id)


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_24_finish_run_clears_cancellation_mark() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    await runtime.request_cancellation(run.run_id)
    assert await runtime.is_cancellation_requested(run.run_id)

    finished = await runtime.finish_run(run.run_id, "cancelled", 456)

    assert finished.status == "cancelled"
    assert not await runtime.is_cancellation_requested(run.run_id)


@pytest.mark.anyio
async def test_IR06_runtime_wait_records_operation_facts_without_steps() -> None:
    observations = ObservationService(now_ms=lambda: 200)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    await observations.ingest(observation("connected", "connected"))
    await observations.ingest(observation("failed", "failed"))

    connected, failed = await asyncio.gather(
        runtime.wait_for_observation(run.run_id, "case-lifecycle", wait_request(state="connected")),
        runtime.wait_for_observation(run.run_id, "case-lifecycle", wait_request(state="failed")),
    )
    updated = await runtime.get_run(run.run_id)

    assert {connected.observation_id, failed.observation_id} == {"connected", "failed"}
    assert updated is not None
    assert updated.results == []
    outcomes = await observations.query(ObservationQuery(run_id=run.run_id, kinds=frozenset({"operation"})))
    assert {item.payload["request_id"] for item in outcomes} == {"wait-connected", "wait-failed"}
    assert all(item.payload["outcome"] == "matched" for item in outcomes)
    assert all(item.payload["source"]["line"] == 10 for item in outcomes)

    queried = await runtime.query_observations(
        run.run_id,
        "case-lifecycle",
        ObservationQuery(run_id="caller-supplied-run", case_id="caller-supplied-case"),
    )
    unchanged = await runtime.get_run(run.run_id)
    assert {item.observation_id for item in queried if item.kind == "event"} == {"connected", "failed"}
    assert unchanged is not None
    assert unchanged.results == []


@pytest.mark.anyio
async def test_IR06_runtime_wait_records_timeout_and_cancellation_facts() -> None:
    observations = ObservationService(now_ms=lambda: 200)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])

    with pytest.raises(ObservationWaitTimeoutError):
        await runtime.wait_for_observation(
            run.run_id,
            "case-lifecycle",
            wait_request(state="missing", timeout_ms=1),
        )

    waiter = asyncio.create_task(
        runtime.wait_for_observation(
            run.run_id,
            "case-lifecycle",
            wait_request(state="cancelled", timeout_ms=1000),
        )
    )
    await asyncio.sleep(0)
    await runtime.request_cancellation(run.run_id)
    with pytest.raises(ObservationWaitCancelledError):
        await waiter

    updated = await runtime.get_run(run.run_id)
    assert updated is not None
    assert updated.results == []
    outcomes = await observations.query(ObservationQuery(run_id=run.run_id, kinds=frozenset({"operation"})))
    assert [item.payload["outcome"] for item in outcomes] == ["timed_out", "cancelled"]
    assert [item.payload["failure_classification"] for item in outcomes] == ["observation_timeout", "cancelled"]


@pytest.mark.anyio
async def test_IR06_duplicate_wait_id_reuses_one_operation_fact() -> None:
    observations = ObservationService(now_ms=lambda: 200)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    await observations.ingest(observation("connected", "connected"))
    request = wait_request(state="connected", wait_id="stable-wait-id")

    first, second = await asyncio.gather(
        runtime.wait_for_observation(run.run_id, "case-lifecycle", request),
        runtime.wait_for_observation(run.run_id, "case-lifecycle", request),
    )

    updated = await runtime.get_run(run.run_id)
    assert first == second
    assert updated is not None
    assert updated.results == []
    outcomes = await observations.query(ObservationQuery(run_id=run.run_id, kinds=frozenset({"operation"})))
    assert len(outcomes) == 1
    assert outcomes[0].payload["request_id"] == "stable-wait-id"


@pytest.mark.anyio
async def test_IR03_duplicate_wait_id_rejects_body_conflict() -> None:
    observations = ObservationService(now_ms=lambda: 200)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    await observations.ingest(observation("connected", "connected"))

    await runtime.wait_for_observation(
        run.run_id,
        "case-lifecycle",
        wait_request(state="connected", wait_id="stable-wait-id"),
    )

    with pytest.raises(ObservationWaitConflictError):
        await runtime.wait_for_observation(
            run.run_id,
            "case-lifecycle",
            wait_request(state="failed", wait_id="stable-wait-id"),
        )


@pytest.mark.anyio
async def test_IR06_finish_waits_for_cancelled_wait_fact_to_be_recorded() -> None:
    observations = ObservationService(now_ms=lambda: 200)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    waiter = asyncio.create_task(
        runtime.wait_for_observation(
            run.run_id,
            "case-lifecycle",
            wait_request(state="cancelled", timeout_ms=1000),
        )
    )
    await asyncio.sleep(0)

    await runtime.request_cancellation(run.run_id)
    finisher = asyncio.create_task(runtime.finish_run(run.run_id, "cancelled", 456))

    with pytest.raises(ObservationWaitCancelledError):
        await waiter
    finished = await finisher
    assert finished.status == "cancelled"
    assert finished.results == []
    outcomes = await observations.query(ObservationQuery(run_id=run.run_id, kinds=frozenset({"operation"})))
    assert [item.payload["outcome"] for item in outcomes] == ["cancelled"]


@pytest.mark.anyio
async def test_IR06_finish_allows_scheduled_wait_to_reserve_operation() -> None:
    observations = ObservationService(now_ms=lambda: 200)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = await runtime.create_run(sample_run())
    await runtime.start_run(run.run_id, [])
    await observations.ingest(observation("connected", "connected"))

    waiter = asyncio.create_task(
        runtime.wait_for_observation(
            run.run_id,
            "case-lifecycle",
            wait_request(state="connected"),
        )
    )
    finished = await runtime.finish_run(run.run_id, "passed", 456)

    assert (await waiter).observation_id == "connected"
    assert finished.results == []
    outcomes = await observations.query(ObservationQuery(run_id=run.run_id, kinds=frozenset({"operation"})))
    assert [item.payload["outcome"] for item in outcomes] == ["matched"]
