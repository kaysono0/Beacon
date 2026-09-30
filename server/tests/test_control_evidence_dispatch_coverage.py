import json
from pathlib import Path

import pytest

from app.devices.connection_diagnostics import ConnectionEventStore
from app.reporting.artifact_runtime import JsonlArtifactStore
from app.reporting.server_log_runtime import JsonlServerLogStore, ServerLogCollector
from app.devices.device_models import Device, DeviceSession
from app.devices.device_runtime import DeviceRegistry
from app.devices.dispatch_runtime import CommandDispatcher, PacketBuilder
from app.reporting.evidence_runtime import (
    AckTracker,
    EvidenceStore,
    connection_failure_classification,
    now_ms,
)
from app.runs.run_runtime import ServerRunRuntime
from app.reporting.evidence_runtime import ResultCollector

from beacon_test.wire_json import canonical_json


TARGET = {"sdk": "mock_echo", "class_name": "Echo", "function": "onMessage"}
CALLBACK_TARGET = {"sdk": "mock_echo", "interface": "events", "class_name": "Echo", "function": "onMessage"}


class FakeWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []

    async def send_json(self, packet: dict) -> None:
        if self.fail:
            raise RuntimeError("transport closed")
        self.sent.append(packet)


@pytest.mark.anyio
async def test_IT_EVIDENCE_RUNTIME_01_ack_rejects_mismatched_responses_and_records_diagnostics() -> None:
    diagnostics = ConnectionEventStore()
    tracker = AckTracker(connection_diagnostics=diagnostics)
    pending = await tracker.create_pending(
        "device-ack",
        "op-ack",
        "invokeRequest",
        5000,
        run_id="run-ack",
        case_id="case-ack",
        step_id="step-ack",
    )

    assert await tracker.resolve("other-device", "op-ack", {"common": {"action": "invokeResponse"}}) is False
    assert await tracker.resolve("device-ack", "missing-op", {"common": {"action": "invokeResponse"}}) is False
    assert await tracker.resolve("device-ack", "op-ack", {"common": {"action": "callbackResponse"}}) is False
    assert pending.future.done() is False
    assert await tracker.timeout("missing-op") is False

    events = await diagnostics.summaries(node_id="device-ack", event_type="pending_response_rejected")
    assert len(events) == 1
    assert events[0]["details"]["expected_response_action"] == "invokeResponse"
    assert events[0]["details"]["actual_response_action"] == "callbackResponse"


@pytest.mark.anyio
async def test_IT_EVIDENCE_RUNTIME_02_callback_projection_accepts_only_complete_execution_receipts() -> None:
    assert connection_failure_classification("disconnect") == {
        "category": "dispatch_failure",
        "source": "connection",
        "reason": "disconnect",
    }
    with pytest.raises(ValueError, match="unsupported connection failure reason"):
        connection_failure_classification("network")
    with pytest.raises(json.JSONDecodeError):
        canonical_json("{bad-json")
    assert canonical_json('{"ok":true}') == '{"ok":true}'

    store = EvidenceStore()
    valid_packet = {
        "common": {"timestamp_ms": now_ms()},
        "data": {
            "node_id": "device-evidence",
            "run_id": "run-evidence",
            "case_id": "case-evidence",
            "step_id": "step-evidence",
            "event_target": TARGET,
            "payload": "{bad-json",
            "callback_context": '{"resource_ref":"res-1"}',
            "callback_execution": {
                "defer_matched": True,
                "defer_executed": True,
                "call_results": [
                    {
                        "target": TARGET,
                        "resource_ref": "res-1",
                        "error": 0,
                        "message": "ok",
                        "return_value": "{}",
                    }
                ],
            },
        },
    }
    event = await store.record_callback_event(valid_packet)
    assert event.data["node_id"] == "device-evidence"

    evidence = await store.evidence_events(
        "device-evidence",
        TARGET,
        run_id="run-evidence",
        case_id="case-evidence",
        step_id="step-evidence",
    )
    assert evidence[0].payload == "{bad-json"
    assert evidence[0].callback_context == {"resource_ref": "res-1"}
    assert evidence[0].callback_execution == {
        "defer_matched": True,
        "defer_executed": True,
        "call_results": [
            {"target": TARGET, "resource_ref": "res-1", "error": 0, "message": "ok", "has_return_value": True}
        ],
    }

    invalid_packets = [
        {**valid_packet, "data": {**valid_packet["data"], "callback_context": "{bad-json"}},
        {**valid_packet, "data": {**valid_packet["data"], "callback_context": []}},
        {**valid_packet, "data": {**valid_packet["data"], "callback_execution": {"bad": "shape"}}},
        {
            **valid_packet,
            "data": {
                **valid_packet["data"],
                "callback_execution": {"defer_matched": "yes", "defer_executed": True, "call_results": []},
            },
        },
        {
            **valid_packet,
            "data": {
                **valid_packet["data"],
                "callback_execution": {"defer_matched": True, "defer_executed": "yes", "call_results": []},
            },
        },
        {
            **valid_packet,
            "data": {
                **valid_packet["data"],
                "callback_execution": {"defer_matched": True, "defer_executed": True, "call_results": "bad"},
            },
        },
        {
            **valid_packet,
            "data": {
                **valid_packet["data"],
                "callback_execution": {"defer_matched": True, "defer_executed": True, "call_results": ["bad"]},
            },
        },
        {
            **valid_packet,
            "data": {
                **valid_packet["data"],
                "callback_execution": {
                    "defer_matched": True,
                    "defer_executed": True,
                    "call_results": [{"target": TARGET, "unexpected": True}],
                },
            },
        },
    ]
    for packet in invalid_packets:
        await store.record_callback_event(packet)

    projected = await store.evidence_events("device-evidence", TARGET, run_id="run-evidence")
    assert projected[1].callback_context is None
    assert projected[1].callback_execution == evidence[0].callback_execution
    assert projected[2].callback_context is None
    assert projected[2].callback_execution == evidence[0].callback_execution
    assert [item.callback_execution for item in projected[3:]] == [None] * (len(invalid_packets) - 2)


@pytest.mark.anyio
async def test_IT_CONTROL_PLANE_01_jsonl_log_store_rebuilds_quarantines_and_rotates(tmp_path) -> None:
    log_path = tmp_path / "server-logs.jsonl"
    log_path.write_text(
        "\n".join(
            [
                "",
                "{bad-json",
                json.dumps(["not", "dict"]),
                json.dumps({"event_id": "missing-fields"}),
                json.dumps(
                    {
                        "event_id": "expired",
                        "timestamp_ms": 1,
                        "level": "info",
                        "event": "old",
                        "message": "old",
                        "node_id": "device-log",
                        "lease_id": "lease-log",
                    }
                ),
                json.dumps(
                    {
                        "event_id": "current",
                        "timestamp_ms": 100,
                        "level": "info",
                        "event": "current",
                        "message": "current",
                        "node_id": "device-log",
                        "lease_id": "lease-log",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    store = JsonlServerLogStore(log_path, retention_ms=50, quarantine_corrupt_lines=True, now_ms=120)

    assert [event["event_id"] for event in await store.list_events()] == ["current"]
    corrupt = log_path.with_suffix(".jsonl.corrupt").read_text(encoding="utf-8")
    assert "{bad-json" in corrupt
    assert '["not", "dict"]' in corrupt
    assert '"missing-fields"' in corrupt

    await store.append(
        {
            "event_id": "rotate",
            "timestamp_ms": 121,
            "level": "info",
            "event": "rotate",
            "message": "x" * 80,
            "node_id": "device-log",
            "lease_id": "lease-log",
        },
        ("rotate", "device-log", "lease-log"),
    )
    assert log_path.exists()

    delete_path = tmp_path / "delete-logs.jsonl"
    delete_path.write_text("x" * 20, encoding="utf-8")
    delete_store = JsonlServerLogStore(delete_path, max_bytes=1, max_rotated_files=0)
    await delete_store.append(
        {
            "event_id": "delete",
            "timestamp_ms": 1,
            "level": "info",
            "event": "delete",
            "message": "delete",
            "node_id": "device-log",
            "lease_id": "lease-log",
        },
        ("delete", "device-log", "lease-log"),
    )
    assert delete_path.exists()


@pytest.mark.anyio
async def test_IT_CONTROL_PLANE_02_log_collector_redacts_filters_and_deduplicates() -> None:
    collector = ServerLogCollector()
    stats = await collector.ingest(
        "device-log",
        "lease-log",
        [
            "bad-event",
            {"event_id": "bad-timestamp", "timestamp_ms": "1", "level": "info", "event": "bad", "message": "bad"},
            {
                "event_id": "event-1",
                "timestamp_ms": 10,
                "level": "error",
                "event": "join",
                "message": "Bearer secret-token",
                "run_id": "run-log",
                "case_id": "case-log",
                "step_id": "step-log",
                "op_id": "op-log",
                "extra": {"api_key": "secret", "nested": ["authorization header"]},
            },
            {
                "event_id": "event-1",
                "timestamp_ms": 11,
                "level": "error",
                "event": "join",
                "message": "duplicate",
            },
        ],
    )

    assert stats == {"accepted": 1, "duplicates": 1, "rejected": 2}
    events = await collector.query_by_trace(
        "run-log",
        case_id="case-log",
        step_id="step-log",
        op_id="op-log",
        node_id="device-log",
        lease_id="lease-log",
        start_ms=1,
        end_ms=20,
    )
    assert len(events) == 1
    assert events[0]["message"] == "<redacted>"
    assert events[0]["extra"]["api_key"] == "<redacted>"
    assert events[0]["extra"]["nested"] == ["<redacted>"]
    assert await collector.query_window("device-log", 1, 20) == events
    assert await collector.query_window("missing-device", 1, 20) == []


@pytest.mark.anyio
async def test_IT_CONTROL_PLANE_03_jsonl_artifact_store_rebuilds_and_quarantines_bad_lines(tmp_path) -> None:
    path = tmp_path / "artifacts.jsonl"
    path.write_text(
        "\n".join(
            [
                "",
                "{bad-json",
                json.dumps({"artifact_id": "bad"}),
                json.dumps(
                    {
                        "artifact_id": "artifact-loaded",
                        "node_id": "device-artifact",
                        "artifact_type": "log",
                        "path": "artifact://loaded",
                        "metadata": {"run_id": "run-artifact", "case_id": "case-artifact", "step_id": "step-artifact"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    store = JsonlArtifactStore(path)

    assert [item["artifact_id"] for item in await store.query(run_id="run-artifact")] == ["artifact-loaded"]
    assert "bad" in Path(f"{path}.corrupt").read_text(encoding="utf-8")
    new_id = await store.put(
        "device-artifact",
        "screenshot",
        "artifact://new",
        {"run_id": "run-artifact", "case_id": "case-new", "step_id": "step-new"},
    )
    assert (await store.get(new_id))["path"] == "artifact://new"
    assert await store.query(case_id="missing") == []


@pytest.mark.anyio
async def test_IT_DISPATCH_RUNTIME_01_dispatcher_rejects_bad_ids_limits_and_send_failures() -> None:
    registry = DeviceRegistry()
    collector = ResultCollector(connection_diagnostics=ConnectionEventStore())
    runtime = ServerRunRuntime(collector)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=runtime, max_pending_per_device=1)
    with pytest.raises(ValueError, match="protocol operation id must be non-empty"):
        await dispatcher.send_protocol_invoke("device-dispatch", [{"target": TARGET}], "")

    offline = await dispatcher.send_invoke("device-dispatch", [{"target": TARGET}], timeout_ms=1)
    assert offline["data"]["code"] == 404
    await registry.upsert(
        DeviceSession(
            device=Device(node_id="device-dispatch", platform="mac"),
            websocket=FakeWebSocket(fail=True),
            lease_id="lease-dispatch",
        )
    )
    missing_call = await dispatcher.send_invoke("device-dispatch", [], timeout_ms=1)
    assert missing_call["data"]["code"] == 400

    await runtime.create_pending("device-dispatch", "op-existing", "invokeRequest", 1000)
    limited = await dispatcher.send_invoke("device-dispatch", [{"target": TARGET}], timeout_ms=1)
    assert limited["data"]["code"] == 429

    await runtime.timeout_pending("op-existing")
    send_failed = await dispatcher.send_invoke(
        "device-dispatch",
        [{"target": TARGET, "extra": '{"run_id":"run-dispatch","case_id":"case-dispatch","step_id":"step-dispatch"}'}],
        timeout_ms=1,
    )
    assert send_failed["data"]["code"] == 502
    events = await collector.connection_events(node_id="device-dispatch", event_type="send_failed")
    assert events[0]["run_id"] == "run-dispatch"
