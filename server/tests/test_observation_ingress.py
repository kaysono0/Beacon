"""IR-02 现有 producer 接入 ObservationService 的兼容合同。"""

from __future__ import annotations

import pytest

from app.devices.connection_diagnostics import ConnectionEventStore
from app.reporting.artifact_runtime import ArtifactStore
from app.reporting.evidence_runtime import ResultCollector
from app.reporting.server_log_runtime import ServerLogCollector
from app.api.gateway import AgentGateway
from app.observations.observation_ingress import UNSCOPED_RUN
from app.observations.observation_models import ObservationQuery
from app.observations.observation_service import ObservationService
from app.runs.run_runtime import ServerRunRuntime


TARGET = {
    "sdk": "mock",
    "interface": "rtc_engine",
    "class_name": "MockEngine",
    "function": "onJoin",
}


def _callback_packet(*, lease_id: str = "lease-1") -> dict:
    return {
        "common": {"action": "callbackEventRequest", "op_id": "op-1", "timestamp_ms": 100},
        "data": {
            "node_id": "mac-1",
            "lease_id": lease_id,
            "event_id": "event-1",
            "run_id": "run-1",
            "case_id": "case-1",
            "device_role": "primary",
            "event_target": dict(TARGET),
            "payload": {"state": "connected", "token": "secret"},
            "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
        },
    }


@pytest.mark.anyio
async def test_IR02_callback_observation_preserves_receipt_and_legacy_projection() -> None:
    service = ObservationService(now_ms=lambda: 200)
    collector = ResultCollector()
    runtime = ServerRunRuntime(collector, observation_service=service)

    first = await runtime.ingest_callback_event(_callback_packet())
    duplicate = await runtime.ingest_callback_event(_callback_packet())
    next_lease = await runtime.ingest_callback_event(_callback_packet(lease_id="lease-2"))

    assert first["receipt"]["recorded"] is True
    assert duplicate["receipt"]["duplicate"] is True
    assert next_lease["receipt"]["recorded"] is True
    observations = await service.query(ObservationQuery(run_id="run-1", kinds=frozenset({"event"})))
    assert [record.cursor for record in observations] == [1, 2]
    assert observations[0].payload == {"state": "connected", "token": "<redacted>"}
    assert observations[0].callback_execution == {"defer_matched": False, "defer_executed": False, "call_results": []}
    assert observations[0].operation_id is None
    assert observations[0].step_id is None
    assert len(await collector.callback_events("mac-1")) == 2

    executed_packet = _callback_packet()
    executed_packet["data"]["event_id"] = "executed-event"
    executed_packet["data"]["callback_execution"] = {
        "defer_matched": True,
        "defer_executed": True,
        "call_results": [{"target": dict(TARGET), "error": 0, "message": "ok", "return_value": '{"token":"secret"}'}],
    }
    await runtime.ingest_callback_event(executed_packet)
    executed = (await service.query(ObservationQuery(run_id="run-1", kinds=frozenset({"event"}))))[-1]
    assert executed.callback_execution is not None
    assert executed.callback_execution["call_results"][0]["return_value"] == '{"token":"<redacted>"}'

    legacy_packet = _callback_packet()
    del legacy_packet["data"]["event_target"]["interface"]
    legacy_packet["data"]["event_id"] = "legacy-event"
    await runtime.ingest_callback_event(legacy_packet)
    observations = await service.query(ObservationQuery(run_id="run-1", kinds=frozenset({"event"})))
    assert observations[-1].target.interface == "legacy"

    attributed_packet = _callback_packet()
    attributed_packet["data"]["event_id"] = "agent-origin-hint"
    attributed_packet["data"]["step_id"] = "step-from-agent"
    attributed_packet["data"]["callback_context"] = {"originating_op_id": "op-hint"}
    await runtime.ingest_callback_event(attributed_packet)
    stored = await service.query(ObservationQuery(run_id="run-1", kinds=frozenset({"event"})))
    assert stored[-1].operation_id is None
    assert stored[-1].step_id is None


@pytest.mark.anyio
async def test_IR02_log_and_artifact_write_observation_before_legacy_projection() -> None:
    service = ObservationService(now_ms=lambda: 200)
    logs = ServerLogCollector(observation_service=service)
    artifacts = ArtifactStore(observation_service=service)

    stats = await logs.ingest(
        "mac-1",
        "lease-1",
        [
            {
                "event_id": "log-1",
                "timestamp_ms": 100,
                "level": "error",
                "event": "join.failed",
                "message": "Bearer secret-token",
                "run_id": "run-1",
                "case_id": "case-1",
                "step_id": "step-1",
            }
        ],
    )
    artifact_id = await artifacts.put(
        "mac-1",
        "screenshot",
        "artifact://screen.png",
        {"run_id": "run-1", "case_id": "case-1", "step_id": "step-1", "lease_id": "lease-1"},
    )

    assert stats == {"accepted": 1, "duplicates": 0, "rejected": 0}
    legacy_logs = await logs.query_by_trace("run-1")
    assert legacy_logs[0]["message"] == "<redacted>"
    assert (await artifacts.get(artifact_id))["path"] == "artifact://screen.png"
    observations = await service.query(ObservationQuery(run_id="run-1"))
    assert [record.kind for record in observations] == ["log", "artifact"]
    assert observations[0].payload["message"] == "<redacted>"
    assert observations[1].payload["metadata"]["step_id"] == "step-1"


@pytest.mark.anyio
async def test_IR02_connection_projection_and_stale_callback_behavior_are_preserved() -> None:
    service = ObservationService(now_ms=lambda: 200)
    diagnostics = ConnectionEventStore(observation_service=service)
    collector = ResultCollector(connection_diagnostics=diagnostics)
    runtime = ServerRunRuntime(collector, observation_service=service)

    class InactiveSessions:
        async def is_active_lease(self, node_id: str, lease_id: str) -> bool:
            return False

    gateway = AgentGateway(InactiveSessions(), collector, runtime)  # type: ignore[arg-type]
    response = await gateway.handle_packet(object(), _callback_packet(lease_id="stale"))

    assert response["data"]["code"] == 409
    assert response["data"]["message"] == "stale lease"
    assert [event.reason for event in await diagnostics.query(event_type="callback_event_rejected")] == ["stale lease"]
    observations = await service.query(ObservationQuery(run_id=UNSCOPED_RUN))
    assert [record.kind for record in observations] == ["connection"]
    assert observations[0].payload["reason"] == "stale lease"
