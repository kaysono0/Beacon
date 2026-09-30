import pytest

from app.devices.device_runtime import DeviceRegistry, SessionManager
from app.common.errors import (
    BeaconErrorCode,
    DeviceNotFoundError,
    EvidenceStoreError,
    RunStateTransitionError,
    ValidationError,
)
from app.reporting.evidence_runtime import AckTracker, Evidence, EvidenceStore, ResultCollector, now_ms
from app.runs.run_runtime import ServerRunRuntime
from app.runs.test_models import TestCase, TestRun, TestStep


class FakeWebSocket:
    async def send_json(self, packet: dict) -> None:
        _ = packet


def _sample_run() -> TestRun:
    return TestRun(
        run_id="run-errors",
        status="queued",
        selector={},
        cases=[TestCase(case_id="case-errors", name="errors", steps=[TestStep(step_id="step-errors")])],
    )


@pytest.mark.anyio
async def test_UT_SRV_ERRORS_01_registry_missing_device_raises_structured_not_found() -> None:
    registry = DeviceRegistry()

    with pytest.raises(DeviceNotFoundError) as raised:
        await registry.get_or_raise("device-missing")

    assert raised.value.to_dict() == {
        "code": int(BeaconErrorCode.NOT_FOUND),
        "message": "Device not found: device-missing",
        "details": {"node_id": "device-missing"},
    }


@pytest.mark.anyio
async def test_UT_SRV_ERRORS_02_register_requires_node_id_with_structured_validation_error() -> None:
    collector = ResultCollector()
    manager = SessionManager(DeviceRegistry(), ServerRunRuntime(collector))

    with pytest.raises(ValidationError) as raised:
        await manager.handle_register(
            FakeWebSocket(),
            {"common": {"action": "registerRequest", "op_id": "op-register"}, "data": {}},
        )

    assert raised.value.to_dict() == {
        "code": int(BeaconErrorCode.BAD_REQUEST),
        "message": "Validation failed for node_id: must be provided in registerRequest",
        "details": {"field": "node_id", "reason": "must be provided in registerRequest"},
    }


@pytest.mark.anyio
async def test_UT_SRV_ERRORS_03_runtime_rejects_terminal_writes_with_serializable_context() -> None:
    runtime = ServerRunRuntime(ResultCollector())
    run = await runtime.create_run(_sample_run())
    await runtime.start_run(run.run_id, [])
    await runtime.finish_run(run.run_id, "failed", now_ms())

    with pytest.raises(RunStateTransitionError) as raised:
        await runtime.finish_run(run.run_id, "passed", now_ms())

    assert raised.value.to_dict() == {
        "code": int(BeaconErrorCode.BAD_REQUEST),
        "message": "Run state transition rejected: finish_run",
        "details": {
            "run_id": run.run_id,
            "current_status": "failed",
            "requested_operation": "finish_run",
        },
    }


@pytest.mark.anyio
async def test_UT_SRV_ERRORS_04_ack_timeout_returns_error_packet_with_dispatch_classification() -> None:
    tracker = AckTracker()
    pending = await tracker.create_pending("device-timeout", "op-timeout", "invokeRequest", 5000)

    assert await tracker.timeout("op-timeout") is True

    packet = pending.future.result()
    assert packet["common"]["action"] == "invokeResponse"
    assert packet["common"]["op_id"] == "op-timeout"
    assert packet["data"]["code"] == 408
    assert packet["data"]["message"] == "request timeout"
    assert packet["data"]["failure_classification"] == {
        "source": "dispatch",
        "category": "timeout",
        "reason": "dispatch_timeout",
    }


@pytest.mark.anyio
async def test_UT_SRV_ERRORS_05_evidence_store_wraps_target_contract_failures() -> None:
    store = EvidenceStore()

    with pytest.raises(EvidenceStoreError) as raised:
        await store.record_evidence(
            Evidence(
                type="event",
                source="callback",
                node_id="device-evidence",
                target={"sdk": "mock", "class_name": "Mock"},
                payload={"event": "joined"},
                timestamp_ms=now_ms(),
            )
        )

    assert raised.value.to_dict() == {
        "code": int(BeaconErrorCode.INTERNAL_ERROR),
        "message": "Evidence store normalize failed for event",
        "details": {"operation": "normalize", "evidence_type": "event"},
    }
