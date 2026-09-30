import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.sdk.agora_token as agora_token_module
import app.main as main_module
from app.sdk.agora_token import AgoraTokenRequest, create_agora_token
from app.api.auth import require_auth
from app.common.config import ServerConfig
from app.devices.device_models import DeviceSession
from app.api.gateway import AgentGateway
from app.main import (
    _index_report_log_artifacts,
    create_runtime_stores,
    create_server_log_collector,
    inject_disconnect_fault,
)


TARGET = {"sdk": "mock_echo", "class_name": "Echo", "function": "onMessage"}


class FakeSessionManager:
    def __init__(self, active: bool = True) -> None:
        self.active = active
        self.calls: list[str] = []

    async def handle_register(self, websocket: object, packet: dict) -> dict:
        _ = (websocket, packet)
        self.calls.append("register")
        return {"registered": True}

    async def handle_reconnect(self, websocket: object, packet: dict) -> dict:
        _ = (websocket, packet)
        self.calls.append("reconnect")
        return {"reconnected": True}

    async def handle_unregister(self, websocket: object, packet: dict) -> dict:
        _ = (websocket, packet)
        self.calls.append("unregister")
        return {"unregistered": True}

    async def is_active_lease(self, node_id: str, lease_id: str) -> bool:
        _ = (node_id, lease_id)
        return self.active


class FakeRunRuntime:
    def __init__(self) -> None:
        self.connection_events: list[dict] = []
        self.resolved: list[tuple[str, str, dict]] = []
        self.removed_pending: list[tuple[str, str]] = []

    async def record_connection_event(self, event_type: str, node_id: str, **kwargs: object) -> None:
        self.connection_events.append({"event_type": event_type, "node_id": node_id, **kwargs})

    async def resolve_pending(self, node_id: str, op_id: str, packet: dict) -> None:
        self.resolved.append((node_id, op_id, packet))

    async def ingest_callback_event(self, packet: dict) -> dict:
        return {
            "code": 0,
            "message": "ok",
            "event_id": packet["data"]["event_id"],
            "receipt": {"received": True, "recorded": True, "duplicate": False, "evidence_id": "evidence-1"},
        }

    async def fail_pending_for_device(self, node_id: str, reason: str) -> None:
        self.removed_pending.append((node_id, reason))


class FakeLogCollector:
    def __init__(self) -> None:
        self.ingested: list[tuple[str, str, list[dict]]] = []

    async def ingest(self, node_id: str, lease_id: str, events: list[dict]) -> dict:
        self.ingested.append((node_id, lease_id, events))
        return {"accepted": len(events), "duplicates": 0, "rejected": 0}

    async def query_by_trace(self, run_id: str, *args: object, **kwargs: object) -> list[dict]:
        _ = (run_id, args, kwargs)
        return []

    async def query_window(self, node_id: str, start_ms: int, end_ms: int) -> list[dict]:
        return [{"node_id": node_id, "start_ms": start_ms, "end_ms": end_ms}]


class FakeRegistry:
    def __init__(self, sessions: list[DeviceSession] | None = None) -> None:
        self.sessions = sessions or []
        self.removed: list[str] = []

    async def list(self, selector: object) -> list[DeviceSession]:
        _ = selector
        return list(self.sessions)

    async def remove(self, node_id: str) -> None:
        self.removed.append(node_id)


class FakeArtifactStore:
    def __init__(self) -> None:
        self.existing_paths: set[str] = set()
        self.puts: list[dict] = []

    async def query(self, **kwargs: object) -> list[dict]:
        _ = kwargs
        return [{"path": path} for path in self.existing_paths]

    async def put(self, node_id: str, artifact_type: str, path: str, metadata: dict) -> str:
        self.puts.append({"node_id": node_id, "artifact_type": artifact_type, "path": path, "metadata": metadata})
        return "artifact-indexed"

    async def get(self, artifact_id: str) -> dict:
        _ = artifact_id
        raise KeyError(artifact_id)


class FakeLoadRegistry:
    def __init__(self) -> None:
        self.loaded = False

    async def load_from_store(self) -> None:
        self.loaded = True


class FakeLoadSessionManager:
    def __init__(self) -> None:
        self.loaded = False

    async def load_contexts_from_store(self) -> None:
        self.loaded = True


@pytest.mark.anyio
async def test_IT_GATEWAY_01_dispatches_session_log_and_unknown_packets() -> None:
    sessions = FakeSessionManager(active=False)
    runtime = FakeRunRuntime()
    log_collector = FakeLogCollector()
    gateway = AgentGateway(sessions, object(), runtime, log_collector)  # type: ignore[arg-type]

    assert await gateway.handle_packet(object(), {"common": {"action": "reconnectRequest"}}) == {"reconnected": True}
    assert await gateway.handle_packet(object(), {"common": {"action": "unregisterRequest"}}) == {"unregistered": True}
    assert sessions.calls == ["reconnect", "unregister"]

    assert await gateway.handle_packet(
        object(),
        {"common": {"action": "invokeResponse", "op_id": "op-1"}, "data": {"node_id": "", "lease_id": ""}},
    ) is None
    assert runtime.connection_events[-1]["reason"] == "missing lease"

    stale_callback = await gateway.handle_packet(
        object(),
        {
            "common": {"action": "callbackEventRequest", "op_id": "op-callback"},
            "data": {
                "event_id": "event-1",
                "node_id": "device-1",
                "lease_id": "lease-stale",
                "event_target": TARGET,
                "payload": {},
                "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
            },
        },
    )
    assert stale_callback["data"]["code"] == 409
    assert stale_callback["data"]["message"] == "stale lease"

    invalid_log = await gateway.handle_packet(
        object(),
        {"common": {"action": "logReportRequest", "op_id": "op-log"}, "data": {"node_id": "", "events": "bad"}},
    )
    assert invalid_log["data"] == {"code": 0, "message": "ok", "accepted": 0, "duplicates": 0, "rejected": 1}

    unknown = await gateway.handle_packet(object(), {"common": {"action": "unknown", "op_id": "op-unknown"}})
    assert unknown["common"]["action"] == "errorResponse"
    assert unknown["data"]["message"] == "unknown action"


@pytest.mark.anyio
async def test_IT_GATEWAY_02_callback_event_entrypoint_validates_and_receipts_packets() -> None:
    sessions = FakeSessionManager(active=True)
    runtime = FakeRunRuntime()
    gateway = AgentGateway(sessions, object(), runtime)  # type: ignore[arg-type]
    base_data = {
        "event_id": "event-1",
        "node_id": "device-1",
        "lease_id": "lease-1",
        "event_target": TARGET,
        "payload": {"uid": 7},
        "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
    }

    valid = await gateway.handle_packet(
        object(),
        {"common": {"action": "callbackEventRequest", "op_id": "op-callback"}, "data": base_data},
    )
    assert valid["data"]["code"] == 0
    assert valid["data"]["event_id"] == "event-1"

    invalid_packets = [
        ("data", "not-a-data-object"),
        ("event_target", {**base_data, "event_target": {**TARGET, "class_name": ""}}),
        ("event_target", {**base_data, "event_target": {**TARGET, "bad": "field"}}),
        ("payload", {**base_data, "payload": "bad"}),
        ("callback_execution", {**base_data, "callback_execution": {"defer_matched": True}}),
        (
            "callback_execution",
            {**base_data, "callback_execution": {"defer_matched": 1, "defer_executed": True, "call_results": []}},
        ),
        (
            "callback_execution",
            {
                **base_data,
                "callback_execution": {
                    "defer_matched": True,
                    "defer_executed": True,
                    "call_results": [
                        {"target": {**TARGET, "bad": "field"}, "resource_ref": "res", "error": 0, "message": "ok", "return_value": "{}"}
                    ],
                },
            },
        ),
        (
            "callback_execution",
            {
                **base_data,
                "callback_execution": {
                    "defer_matched": True,
                    "defer_executed": True,
                    "call_results": [
                        {"target": TARGET, "resource_ref": "res", "error": True, "message": "ok", "return_value": "{}"}
                    ],
                },
            },
        ),
        (
            "callback_execution",
            {
                **base_data,
                "callback_execution": {
                    "defer_matched": True,
                    "defer_executed": True,
                    "call_results": [
                        {"target": TARGET, "resource_ref": "res", "error": 0, "message": 1, "return_value": "{}"}
                    ],
                },
            },
        ),
        ("callback_context", {**base_data, "callback_context": {"resource_ref": ""}}),
        (
            "callback_context",
            {
                **base_data,
                "callback_context": {"resource_ref": "res", "instance_id": "instance", "sequence": True},
            },
        ),
    ]
    for expected_field, data in invalid_packets:
        response = await gateway.handle_packet(
            object(),
            {"common": {"action": "callbackEventRequest", "op_id": f"op-{expected_field}"}, "data": data},
        )
        assert response["data"]["code"] == 400
        assert response["data"]["message"] == f"invalid callback event: {expected_field}"

    assert [event["details"]["validation_error"] for event in runtime.connection_events[-len(invalid_packets) :]] == [
        expected_field for expected_field, _ in invalid_packets
    ]


def test_UT_MAIN_01_config_helpers_reject_unknown_store_backends(tmp_path) -> None:
    jsonl_log = create_server_log_collector(
        ServerConfig(server_log_store="jsonl", server_log_jsonl_path=str(tmp_path / "server-logs.jsonl"))
    )
    assert jsonl_log.__class__.__name__ == "ServerLogCollector"
    assert create_runtime_stores(ServerConfig(server_runtime_store="memory"))[0:2] == (None, None)
    runtime_stores = create_runtime_stores(
        ServerConfig(server_runtime_store="jsonl", server_runtime_jsonl_dir=str(tmp_path / "runtime"))
    )
    assert runtime_stores[0].__class__.__name__ == "JsonlDeviceSessionStore"
    assert runtime_stores[1].__class__.__name__ == "JsonlTestRunStore"
    assert runtime_stores[2].__class__.__name__ == "JsonlArtifactStore"

    with pytest.raises(ValueError, match="unsupported server log store"):
        create_server_log_collector(ServerConfig(server_log_store="sqlite"))
    with pytest.raises(ValueError, match="unsupported server runtime store"):
        create_runtime_stores(ServerConfig(server_runtime_store="sqlite"))


@pytest.mark.anyio
async def test_IT_MAIN_03_indexes_report_log_artifacts_and_guards_fault_endpoint(monkeypatch) -> None:
    artifacts = FakeArtifactStore()
    monkeypatch.setattr("app.main.artifact_store", artifacts)
    report = {
        "run_id": "run-report",
        "case_results": [
            "not-a-case-result",
            {"case_id": 1, "step_id": "step", "log_artifacts": ["artifact://logs/run-report/ignored.jsonl"]},
            {"case_id": "case", "step_id": "step", "node_id": "device", "log_artifacts": ["artifact://other"]},
            {
                "case_id": "case",
                "step_id": "step",
                "node_id": "device",
                "log_artifacts": ["artifact://logs/run-report/case.step.jsonl"],
            },
        ],
    }

    await _index_report_log_artifacts({"run_id": 1, "case_results": []})
    await _index_report_log_artifacts(report)
    assert len(artifacts.puts) == 1
    assert artifacts.puts[0]["artifact_type"] == "log"
    assert artifacts.puts[0]["metadata"] == {"run_id": "run-report", "case_id": "case", "step_id": "step"}

    artifacts.existing_paths.add(artifacts.puts[0]["path"])
    await _index_report_log_artifacts(report)
    assert len(artifacts.puts) == 1

    registry = FakeRegistry()
    runtime = FakeRunRuntime()
    monkeypatch.setattr("app.main.registry", registry)
    monkeypatch.setattr("app.main.run_runtime", runtime)
    monkeypatch.delenv("BEACON_ENABLE_TEST_ENDPOINTS", raising=False)
    with pytest.raises(HTTPException) as disabled:
        await inject_disconnect_fault({"node_id": "device-fault"})
    assert disabled.value.status_code == 404

    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    assert await inject_disconnect_fault({"node_id": "device-fault"}) == {"status": "ok"}
    assert registry.removed == ["device-fault"]
    assert runtime.removed_pending == [("device-fault", "fault disconnect")]
    assert await inject_disconnect_fault({}) == {"status": "ok"}


@pytest.mark.anyio
async def test_IT_MAIN_04_endpoint_helpers_translate_missing_resources(monkeypatch) -> None:
    async def missing_run_detail(*args: object, **kwargs: object) -> dict:
        _ = (args, kwargs)
        raise KeyError("missing")

    class MissingReportGenerator:
        async def generate(self, run_id: str, format: str) -> object:
            _ = (run_id, format)
            raise KeyError(run_id)

        async def generate_junit(self, run_id: str) -> str:
            _ = run_id
            raise KeyError(run_id)

    monkeypatch.setattr(main_module, "run_detail_payload", missing_run_detail)
    monkeypatch.setattr(main_module, "report_generator", MissingReportGenerator())
    monkeypatch.setattr(main_module, "log_collector", FakeLogCollector())
    monkeypatch.setattr(main_module, "artifact_store", FakeArtifactStore())

    with pytest.raises(HTTPException) as console_missing:
        await main_module.console_run_detail("missing-run")
    assert console_missing.value.status_code == 404

    with pytest.raises(HTTPException) as report_missing:
        await main_module.get_run_report("missing-run")
    assert report_missing.value.status_code == 404

    with pytest.raises(HTTPException) as junit_missing:
        await main_module.get_run_junit("missing-run")
    assert junit_missing.value.status_code == 404

    assert await main_module.get_device_logs("device-log", start_ms=1, end_ms=2) == {
        "events": [{"node_id": "device-log", "start_ms": 1, "end_ms": 2}]
    }
    with pytest.raises(HTTPException) as artifact_missing:
        await main_module.get_artifact("missing-artifact")
    assert artifact_missing.value.status_code == 404


@pytest.mark.anyio
async def test_IT_MAIN_05_lifespan_and_auth_configuration_guards(monkeypatch) -> None:
    registry = FakeLoadRegistry()
    session_manager = FakeLoadSessionManager()
    monkeypatch.setattr(main_module, "registry", registry)
    monkeypatch.setattr(main_module, "session_manager", session_manager)

    async with main_module.lifespan(main_module.app):
        assert registry.loaded is True
        assert session_manager.loaded is True

    monkeypatch.delenv("BEACON_AUTH_TOKEN", raising=False)
    with pytest.raises(HTTPException) as missing_token:
        require_auth(None)
    assert missing_token.value.status_code == 401

    monkeypatch.setenv("BEACON_AUTH_TOKEN", "secret")
    with pytest.raises(HTTPException) as invalid_auth:
        require_auth("Bearer wrong")
    assert invalid_auth.value.status_code == 401
    assert require_auth("Bearer secret") is None

    monkeypatch.delenv("BEACON_ENABLE_TEST_ENDPOINTS", raising=False)
    with pytest.raises(HTTPException) as token_disabled:
        create_agora_token(AgoraTokenRequest(channel="room", uid=7))
    assert token_disabled.value.status_code == 404

    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    monkeypatch.delenv("AGORA_APP_ID", raising=False)
    monkeypatch.delenv("AGORA_APP_CERT", raising=False)
    with pytest.raises(HTTPException) as missing_credentials:
        create_agora_token(AgoraTokenRequest(channel="room", uid=7))
    assert missing_credentials.value.status_code == 500

    class FailingSigner:
        def build_rtc_token(self, *args: object) -> str:
            _ = args
            raise RuntimeError("missing token signer")

    monkeypatch.setattr(agora_token_module, "token_signer", FailingSigner())
    monkeypatch.setenv("AGORA_APP_ID", "app-id")
    monkeypatch.setenv("AGORA_APP_CERT", "app-cert")
    client = TestClient(main_module.app)
    response = client.post(
        "/api/v1/agora/token",
        headers={"Authorization": "Bearer secret"},
        json={"channel": "room", "uid": 7},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "missing token signer"
