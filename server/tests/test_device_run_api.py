"""Server Phase 1 HTTP 与 WebSocket 入口测试。

本文件覆盖认证、故障注入开关、test run、报告、日志、artifact 和 Gateway 行为。
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.common.config import ServerConfig
from app.devices.device_models import DeviceSelector
from app.main import app
from app.observations.observation_models import ObservationPage
from app.runs.test_models import StepResult, TestCase, TestRun, TestStep


AUTH = {"Authorization": "Bearer local-test-token"}


def target(function: str, *, sdk: str = "test_sdk", class_name: str = "TestClass", interface: str | None = None) -> dict:
    data = {"sdk": sdk, "class_name": class_name, "function": function}
    if interface:
        data["interface"] = interface
    return data


def event_target(function: str, *, sdk: str = "test_sdk", class_name: str = "TestDelegate", interface: str | None = None) -> dict:
    return target(function, sdk=sdk, class_name=class_name, interface=interface)


def test_IT_SRV_AUTH_01_http_phase1_routes_require_authorization(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/devices")

    assert response.status_code == 401


def test_IR03_console_observation_page_parses_cursor_limit_and_kinds(monkeypatch):
    captured: dict[str, object] = {}

    class FakeObservationService:
        async def page(self, **kwargs: object) -> ObservationPage:
            captured.update(kwargs)
            return ObservationPage(items=[], next_cursor=int(kwargs["after_cursor"]), has_more=False)

    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setattr(main_module, "observation_service", FakeObservationService())
    client = TestClient(app)

    response = client.get(
        "/api/v1/test-runs/run-1/observations?after_cursor=4&limit=20&kinds=event,state",
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": 4, "has_more": False}
    assert captured == {
        "run_id": "run-1",
        "after_cursor": 4,
        "limit": 20,
        "kinds": frozenset({"event", "state"}),
    }
    assert client.get(
        "/api/v1/test-runs/run-1/observations?kinds=unknown",
        headers=AUTH,
    ).status_code == 422


def test_IT_SRV_FAULT_01_fault_api_is_hidden_when_test_mode_disabled(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.delenv("BEACON_ENABLE_TEST_ENDPOINTS", raising=False)
    client = TestClient(app)

    response = client.post("/api/v1/test/faults/disconnect", headers=AUTH, json={"node_id": "mac-1"})

    assert response.status_code == 404


def test_IT_SRV_FAULT_02_fault_api_requires_auth_when_test_mode_enabled(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    client = TestClient(app)

    response = client.post("/api/v1/test/faults/disconnect", json={"node_id": "mac-1"})

    assert response.status_code == 401


def test_IT_SRV_AUTH_02_websocket_rejects_missing_token(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    try:
        with client.websocket_connect("/api/v1/agent/ws"):
            assert False, "websocket should reject missing auth"
    except Exception:
        response = client.get("/api/v1/devices", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["devices"] == []


def test_IT_SRV_REG_01_websocket_register_response_and_device_listing(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    with client.websocket_connect("/api/v1/agent/ws?token=local-test-token") as websocket:
        websocket.send_json(
            {
                "common": {"action": "registerRequest", "op_id": "op-register"},
                "data": {"node_id": "mac-ws-1", "platform": "mac", "tags": ["ws"], "capabilities": ["rtc.mock"]},
            }
        )
        response = websocket.receive_json()
        devices = client.get("/api/v1/devices", headers=AUTH).json()["devices"]

    assert response["common"]["action"] == "registerResponse"
    assert response["data"]["lease_id"].startswith("lease-")
    assert any(device["node_id"] == "mac-ws-1" for device in devices)


def test_IT_SRV_CBEVT_01_websocket_callback_event_is_acknowledged(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    with client.websocket_connect("/api/v1/agent/ws?token=local-test-token") as websocket:
        websocket.send_json(
            {
                "common": {"action": "registerRequest", "op_id": "op-register-callback"},
                "data": {"node_id": "mac-ws-1", "platform": "mac", "tags": ["ws"], "capabilities": ["rtc.mock"]},
            }
        )
        register_response = websocket.receive_json()
        lease_id = register_response["data"]["lease_id"]
        websocket.send_json(
            {
                "common": {"action": "callbackEventRequest", "op_id": "op-callback"},
                "data": {
                    "node_id": "mac-ws-1",
                    "lease_id": lease_id,
                    "event_id": "evt-op-callback",
                    "event_target": event_target("onJoin"),
                    "payload": {"uid": 1001},
                    "callback_context": {
                        "provider": "agora_rtc/rtc_engine",
                        "resource_ref": "engine_1",
                        "instance_id": "engine_1",
                        "sequence": 7,
                    },
                },
            }
        )
        response = websocket.receive_json()

    assert response["common"]["action"] == "callbackEventResponse"
    assert "timestamp_ms" in response["common"]
    assert response["data"]["code"] == 0
    assert response["data"]["event_id"] == "evt-op-callback"
    assert response["data"]["receipt"] == {
        "received": True,
        "recorded": True,
        "duplicate": False,
        "evidence_id": "evt-op-callback",
    }
    assert "callback_context" not in response["data"]
    assert "callback_execution" not in response["data"]


def test_IT_SRV_DIAG_01_app_records_websocket_connection_diagnostics(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)
    node_id = "mac-ws-diag"

    with client.websocket_connect("/api/v1/agent/ws?token=local-test-token") as first:
        first.send_json(
            {
                "common": {"action": "registerRequest", "op_id": "op-register-diag-1"},
                "data": {"node_id": node_id, "platform": "mac", "tags": ["ws"], "capabilities": ["rtc.mock"]},
            }
        )
        stale_lease = first.receive_json()["data"]["lease_id"]
        with client.websocket_connect("/api/v1/agent/ws?token=local-test-token") as second:
            second.send_json(
                {
                    "common": {"action": "registerRequest", "op_id": "op-register-diag-2"},
                    "data": {"node_id": node_id, "platform": "mac", "tags": ["ws"], "capabilities": ["rtc.mock"]},
                }
            )
            second.receive_json()
            first.send_json(
                {
                    "common": {"action": "callbackEventRequest", "op_id": "op-stale-diag"},
                    "data": {
                        "node_id": node_id,
                        "lease_id": stale_lease,
                        "event_id": "evt-stale-diag",
                        "event_target": event_target("onJoin"),
                        "payload": {"uid": 1001},
                        "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
                    },
                }
            )
            first.receive_json()

    diagnostics = main_module.collector._connection_diagnostics  # noqa: SLF001
    assert diagnostics is not None
    events = asyncio.run(diagnostics.query(node_id=node_id, event_type="callback_event_rejected"))
    assert [event.reason for event in events] == ["stale lease"]


def test_IT_SRV_LOG_02_websocket_log_report_enters_server_log_collector(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    with client.websocket_connect("/api/v1/agent/ws?token=local-test-token") as websocket:
        websocket.send_json(
            {
                "common": {"action": "logReportRequest", "op_id": "op-ws-log-report"},
                "data": {
                    "node_id": "mac-ws-log",
                    "lease_id": "lease-ws-log",
                    "events": [
                        {
                            "event_id": "log-ws-1",
                            "timestamp_ms": 400,
                            "level": "error",
                            "run_id": "run-ws-log",
                            "case_id": "case-ws-log",
                            "step_id": "step-ws-log",
                            "op_id": "op-ws-log",
                            "event": "agora.join.failed",
                            "message": "join failed",
                        }
                    ],
                },
            }
        )
        response = websocket.receive_json()

    assert response["common"]["action"] == "logReportResponse"
    assert response["data"] == {"code": 0, "message": "ok", "accepted": 1, "duplicates": 0, "rejected": 0}
    logs = client.get(
        "/api/v1/test-runs/run-ws-log/logs",
        headers=AUTH,
        params={"op_id": "op-ws-log"},
    ).json()["events"]
    assert [event["event_id"] for event in logs] == ["log-ws-1"]


def test_IT_SRV_OPENAPI_01_exposes_only_runner_call_and_test_run_contracts(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    document = client.get("/openapi.json").json()
    schema = document["components"]["schemas"]

    assert client.post("/api/v1/sdk/call", headers=AUTH, json={}).status_code == 404
    assert client.get("/api/v1/sdk/callback-events", headers=AUTH).status_code == 404
    assert "/api/v1/sdk/call" not in document["paths"]
    assert "/api/v1/sdk/callback-events" not in document["paths"]
    for endpoint in ("commands", "callbacks"):
        assert client.post(f"/api/v1/devices/mac-1/{endpoint}", headers=AUTH, json={}).status_code == 404
        assert f"/api/v1/devices/{{node_id}}/{endpoint}" not in document["paths"]
    assert "SDKCallRequest" not in schema
    assert "SDKCallResponse" not in schema
    assert "/api/v1/runner/runs/{run_id}/cases/{case_id}/calls" in document["paths"]
    test_run = schema["TestRunCreateRequest"]["properties"]
    assert {"selector", "case_ids"}.issubset(test_run)
    assert "cases" not in test_run

    # SDK 专有端点改为声明式装配后，operationId 与 summary 仍须是重构前公开的值。
    agora_token = document["paths"]["/api/v1/agora/token"]["post"]
    assert agora_token["operationId"] == "agora_token_api_v1_agora_token_post"
    assert agora_token["summary"] == "Agora Token"


def test_IT_SRV_LOG_ARTIFACT_server_log_collector_and_artifact_store_endpoints(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    ingest = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-1",
            "lease_id": "lease-1",
            "events": [
                {
                    "event_id": "log-artifact-1",
                    "timestamp_ms": 10,
                    "level": "info",
                    "run_id": "run-log",
                    "case_id": "case-1",
                    "step_id": "step-1",
                    "event": "artifact.fixture",
                    "message": "artifact fixture",
                }
            ],
        },
    )
    artifact = client.post(
        "/api/v1/artifacts",
        headers=AUTH,
        json={"node_id": "mac-log-1", "artifact_type": "log", "path": "logs/a.jsonl", "metadata": {"run_id": "run-log"}},
    )

    assert ingest.status_code == 200
    assert artifact.status_code == 200
    artifact_id = artifact.json()["artifact_id"]
    logs = client.get("/api/v1/test-runs/run-log/logs", headers=AUTH).json()["events"]
    fetched = client.get(f"/api/v1/artifacts/{artifact_id}", headers=AUTH).json()
    assert logs[0]["step_id"] == "step-1"
    assert fetched["path"] == "logs/a.jsonl"


def test_IT_SRV_LOG_ARTIFACT_query_filters_log_artifacts_by_trace(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    matching = client.post(
        "/api/v1/artifacts",
        headers=AUTH,
        json={
            "node_id": "mac-log-query-1",
            "artifact_type": "log",
            "path": "reports/latest/logs/run-query/case-a.step-a.jsonl",
            "metadata": {"run_id": "run-query", "case_id": "case-a", "step_id": "step-a"},
        },
    )
    client.post(
        "/api/v1/artifacts",
        headers=AUTH,
        json={
            "node_id": "mac-log-query-2",
            "artifact_type": "log",
            "path": "reports/latest/logs/run-query/case-b.step-b.jsonl",
            "metadata": {"run_id": "run-query", "case_id": "case-b", "step_id": "step-b"},
        },
    )
    client.post(
        "/api/v1/artifacts",
        headers=AUTH,
        json={
            "node_id": "mac-log-query-1",
            "artifact_type": "screenshot",
            "path": "reports/latest/screenshots/run-query/case-a.step-a.png",
            "metadata": {"run_id": "run-query", "case_id": "case-a", "step_id": "step-a"},
        },
    )

    response = client.get(
        "/api/v1/artifacts",
        headers=AUTH,
        params={
            "run_id": "run-query",
            "case_id": "case-a",
            "step_id": "step-a",
            "node_id": "mac-log-query-1",
            "artifact_type": "log",
        },
    )

    assert matching.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "artifacts": [
            {
                "artifact_id": matching.json()["artifact_id"],
                "node_id": "mac-log-query-1",
                "artifact_type": "log",
                "path": "reports/latest/logs/run-query/case-a.step-a.jsonl",
                "metadata": {"run_id": "run-query", "case_id": "case-a", "step_id": "step-a"},
            }
        ]
    }


def test_IT_SRV_LOG_ARTIFACT_report_generated_jsonl_is_queryable(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)
    run_id = "run-log-artifact-report-query"
    case_id = "case-log-artifact-report-query"
    step_id = "step-log-artifact-report-query"

    async def create_failed_run() -> None:
        await main_module.run_runtime.create_run(
            TestRun(
                run_id=run_id,
                status="queued",
                selector=DeviceSelector(),
                cases=[TestCase(case_id=case_id, name="log artifact report query", steps=[TestStep(step_id=step_id)])],
            )
        )
        await main_module.run_runtime.start_run(run_id, [])
        await main_module.run_runtime.record_step_result(
            run_id,
            StepResult(
                case_id=case_id,
                step_id=step_id,
                status="failed",
                node_id="mac-log-artifact-report",
                lease_id="lease-log-artifact-report",
                error={"code": 109, "message": "join failed"},
                finished_at_ms=10_000,
            ),
        )
        await main_module.run_runtime.finish_run(run_id, "failed", 10_000)

    asyncio.run(create_failed_run())
    ingest = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-artifact-report",
            "lease_id": "lease-log-artifact-report",
            "events": [
                {
                    "event_id": "log-artifact-report-1",
                    "timestamp_ms": 10_000,
                    "level": "error",
                    "run_id": run_id,
                    "case_id": case_id,
                    "step_id": step_id,
                    "module": "agora",
                    "event": "agora.join.failed",
                    "message": "join failed",
                    "error": 109,
                }
            ],
        },
    )

    report = client.get(f"/api/v1/test-runs/{run_id}/report", headers=AUTH)
    artifacts = client.get(
        "/api/v1/artifacts",
        headers=AUTH,
        params={
            "run_id": run_id,
            "case_id": case_id,
            "step_id": step_id,
            "node_id": "mac-log-artifact-report",
            "artifact_type": "log",
        },
    )

    assert ingest.status_code == 200
    assert report.status_code == 200
    assert report.json()["case_results"][0]["log_artifacts"] == [
        f"artifact://logs/{run_id}/{case_id}.{step_id}.jsonl"
    ]
    assert artifacts.status_code == 200
    artifact_items = artifacts.json()["artifacts"]
    assert len(artifact_items) == 1
    assert artifact_items == [
        {
            "artifact_id": artifact_items[0]["artifact_id"],
            "node_id": "mac-log-artifact-report",
            "artifact_type": "log",
            "path": f"reports/latest/logs/{run_id}/{case_id}.{step_id}.jsonl",
            "metadata": {"run_id": run_id, "case_id": case_id, "step_id": step_id},
        }
    ]


def test_IT_SRV_LOG_ARTIFACT_report_path_follows_report_dir_config(tmp_path):
    config = ServerConfig(report_dir=str(tmp_path / "custom-report-root"))

    path = main_module._report_log_artifact_path("artifact://logs/run-custom/case.step.jsonl", config)

    assert path == str(tmp_path / "custom-report-root/logs/run-custom/case.step.jsonl")


@pytest.mark.anyio
async def test_IT_SRV_LOG_03E_configured_jsonl_log_store_survives_runtime_factory_rebuild(tmp_path):
    log_path = tmp_path / "server-runtime-logs.jsonl"
    config = ServerConfig(server_log_store="jsonl", server_log_jsonl_path=str(log_path))
    first_collector = main_module.create_server_log_collector(config)

    stats = await first_collector.ingest(
        "mac-runtime-jsonl",
        "lease-runtime-jsonl",
        [
            {
                "event_id": "log-runtime-jsonl-1",
                "timestamp_ms": 1400,
                "level": "error",
                "run_id": "run-runtime-jsonl",
                "case_id": "case-runtime-jsonl",
                "step_id": "step-runtime-jsonl",
                "op_id": "op-runtime-jsonl",
                "module": "agora",
                "event": "agora.join.failed",
                "message": "join failed",
                "error": 109,
                "extra": {"failure_category": "sdk_error"},
            }
        ],
    )

    rebuilt_collector = main_module.create_server_log_collector(config)
    events = await rebuilt_collector.query_by_trace(
        "run-runtime-jsonl",
        case_id="case-runtime-jsonl",
        step_id="step-runtime-jsonl",
        op_id="op-runtime-jsonl",
        node_id="mac-runtime-jsonl",
        lease_id="lease-runtime-jsonl",
    )

    assert stats == {"accepted": 1, "duplicates": 0, "rejected": 0}
    assert log_path.exists()
    assert [event["event_id"] for event in events] == ["log-runtime-jsonl-1"]
    assert events[0]["extra"] == {"failure_category": "sdk_error"}


def test_IT_SRV_LOG_03J_config_loads_jsonl_lifecycle_options_from_env(monkeypatch):
    monkeypatch.setenv("BEACON_SERVER_LOG_STORE", "jsonl")
    monkeypatch.setenv("BEACON_SERVER_LOG_JSONL_PATH", "reports/latest/runtime-logs.jsonl")
    monkeypatch.setenv("BEACON_SERVER_LOG_JSONL_MAX_BYTES", "4096")
    monkeypatch.setenv("BEACON_SERVER_LOG_JSONL_MAX_FILES", "3")
    monkeypatch.setenv("BEACON_SERVER_LOG_JSONL_RETENTION_MS", "86400000")
    monkeypatch.setenv("BEACON_SERVER_LOG_JSONL_QUARANTINE_CORRUPT", "false")

    config = ServerConfig.from_env()

    assert config.server_log_store == "jsonl"
    assert config.server_log_jsonl_path == "reports/latest/runtime-logs.jsonl"
    assert config.server_log_jsonl_max_bytes == 4096
    assert config.server_log_jsonl_max_files == 3
    assert config.server_log_jsonl_retention_ms == 86400000
    assert config.server_log_jsonl_quarantine_corrupt is False


def test_IT_SRV_RUNTIME_13_config_loads_jsonl_runtime_store_options_from_env(monkeypatch):
    monkeypatch.setenv("BEACON_SERVER_RUNTIME_STORE", "jsonl")
    monkeypatch.setenv("BEACON_SERVER_RUNTIME_JSONL_DIR", "reports/latest/runtime-state")

    config = ServerConfig.from_env()

    assert config.server_runtime_store == "jsonl"
    assert config.server_runtime_jsonl_dir == "reports/latest/runtime-state"


def test_IT_SRV_RUNTIME_14_runtime_store_factory_uses_jsonl_dir(tmp_path):
    config = ServerConfig(server_runtime_store="jsonl", server_runtime_jsonl_dir=str(tmp_path / "runtime-state"))

    device_store, run_store, artifact_store = main_module.create_runtime_stores(config)

    assert device_store is not None
    assert run_store is not None
    assert artifact_store.__class__.__name__ == "JsonlArtifactStore"


def test_IT_SRV_RUNTIME_15_main_injects_jsonl_test_run_store_into_runtime(tmp_path):
    env = os.environ.copy()
    env["BEACON_SERVER_RUNTIME_STORE"] = "jsonl"
    env["BEACON_SERVER_RUNTIME_JSONL_DIR"] = str(tmp_path / "runtime-state")
    server_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import app.main as main; "
                "assert main.test_run_store is not None; "
                "assert main.run_runtime._run_store is main.test_run_store"
            ),
        ],
        cwd=server_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_IT_SRV_LOG_03_http_ingest_deduplicates_and_filters_by_op_id(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-l2",
            "lease_id": "lease-l2",
            "events": [
                {
                    "event_id": "log-l2-1",
                    "timestamp_ms": 100,
                    "level": "error",
                    "run_id": "run-log-l2",
                    "case_id": "case-l2",
                    "step_id": "step-l2",
                    "op_id": "op-keep",
                    "module": "agora",
                    "event": "agora.join.failed",
                    "message": "join failed",
                    "error": 109,
                    "extra": {"failure_category": "sdk_error"},
                },
                {
                    "event_id": "log-l2-1",
                    "timestamp_ms": 100,
                    "level": "error",
                    "run_id": "run-log-l2",
                    "case_id": "case-l2",
                    "step_id": "step-l2",
                    "op_id": "op-keep",
                    "module": "agora",
                    "event": "agora.join.failed",
                    "message": "duplicate",
                    "error": 109,
                    "extra": {},
                },
                {
                    "event_id": "log-l2-2",
                    "timestamp_ms": 101,
                    "level": "info",
                    "run_id": "run-log-l2",
                    "case_id": "case-l2",
                    "step_id": "step-l2",
                    "op_id": "op-drop",
                    "module": "agora",
                    "event": "agora.join.retry",
                    "message": "retry",
                    "error": 0,
                    "extra": {},
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "accepted": 2, "duplicates": 1, "rejected": 0}
    logs = client.get(
        "/api/v1/test-runs/run-log-l2/logs",
        headers=AUTH,
        params={"case_id": "case-l2", "step_id": "step-l2", "op_id": "op-keep"},
    ).json()["events"]
    assert [event["event_id"] for event in logs] == ["log-l2-1"]
    assert logs[0]["message"] == "join failed"


def test_IT_SRV_LOG_03A_run_log_query_filters_by_node_and_lease(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-node-a",
            "lease_id": "lease-a",
            "events": [
                {
                    "event_id": "log-node-a-1",
                    "timestamp_ms": 110,
                    "level": "error",
                    "run_id": "run-log-scope",
                    "case_id": "case-scope",
                    "step_id": "step-scope",
                    "op_id": "op-scope",
                    "module": "agora",
                    "event": "agora.join.failed",
                    "message": "node a failed",
                    "error": 109,
                    "extra": {},
                },
                {
                    "event_id": "log-node-b-1",
                    "timestamp_ms": 111,
                    "level": "error",
                    "node_id": "mac-log-node-b",
                    "lease_id": "lease-b",
                    "run_id": "run-log-scope",
                    "case_id": "case-scope",
                    "step_id": "step-scope",
                    "op_id": "op-scope",
                    "module": "agora",
                    "event": "agora.join.failed",
                    "message": "node b failed",
                    "error": 109,
                    "extra": {},
                },
            ],
        },
    )

    assert response.status_code == 200
    unscoped = client.get(
        "/api/v1/test-runs/run-log-scope/logs",
        headers=AUTH,
        params={"case_id": "case-scope", "step_id": "step-scope", "op_id": "op-scope"},
    ).json()["events"]
    node_scoped = client.get(
        "/api/v1/test-runs/run-log-scope/logs",
        headers=AUTH,
        params={
            "case_id": "case-scope",
            "step_id": "step-scope",
            "op_id": "op-scope",
            "node_id": "mac-log-node-b",
            "lease_id": "lease-b",
        },
    ).json()["events"]

    assert [event["event_id"] for event in unscoped] == ["log-node-a-1", "log-node-b-1"]
    assert [event["event_id"] for event in node_scoped] == ["log-node-b-1"]


def test_IT_SRV_LOG_03B_run_log_query_filters_by_time_window(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-window",
            "lease_id": "lease-window",
            "events": [
                {
                    "event_id": "log-window-before",
                    "timestamp_ms": 1000,
                    "level": "info",
                    "run_id": "run-log-window",
                    "case_id": "case-window",
                    "step_id": "step-window",
                    "op_id": "op-window",
                    "module": "agora",
                    "event": "agora.join.start",
                    "message": "before window",
                },
                {
                    "event_id": "log-window-hit",
                    "timestamp_ms": 1500,
                    "level": "error",
                    "run_id": "run-log-window",
                    "case_id": "case-window",
                    "step_id": "step-window",
                    "op_id": "op-window",
                    "module": "agora",
                    "event": "agora.join.failed",
                    "message": "inside window",
                },
                {
                    "event_id": "log-window-after",
                    "timestamp_ms": 2000,
                    "level": "info",
                    "run_id": "run-log-window",
                    "case_id": "case-window",
                    "step_id": "step-window",
                    "op_id": "op-window",
                    "module": "agora",
                    "event": "agora.cleanup",
                    "message": "after window",
                },
            ],
        },
    )

    assert response.status_code == 200
    logs = client.get(
        "/api/v1/test-runs/run-log-window/logs",
        headers=AUTH,
        params={
            "case_id": "case-window",
            "step_id": "step-window",
            "op_id": "op-window",
            "node_id": "mac-log-window",
            "lease_id": "lease-window",
            "start_ms": 1200,
            "end_ms": 1800,
        },
    ).json()["events"]

    assert [event["event_id"] for event in logs] == ["log-window-hit"]


def test_IT_SRV_LOG_04_http_ingest_rejects_invalid_events(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-invalid",
            "lease_id": "lease-invalid",
            "events": [
                {
                    "timestamp_ms": 200,
                    "level": "error",
                    "run_id": "run-log-invalid",
                    "event": "missing.event_id",
                    "message": "must not enter logs",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "accepted": 0, "duplicates": 0, "rejected": 1}
    logs = client.get("/api/v1/test-runs/run-log-invalid/logs", headers=AUTH).json()["events"]
    assert logs == []


def test_IT_SRV_LOG_05_http_ingest_redacts_sensitive_extra_fields(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-redact",
            "lease_id": "lease-redact",
            "events": [
                {
                    "event_id": "log-redact-1",
                    "timestamp_ms": 300,
                    "level": "error",
                    "run_id": "run-log-redact",
                    "event": "agora.join.failed",
                    "message": "failed with token=secret-token",
                    "extra": {
                        "token": "secret-token",
                        "target": {"authorization": "Bearer secret-token"},
                        "attempts": [{"api_key": "secret-key"}],
                    },
                },
                {
                    "event_id": "log-redact-2",
                    "timestamp_ms": 301,
                    "level": "error",
                    "run_id": "run-log-redact-agora",
                    "event": "agora.token.build_failed",
                    "message": "build failed AGORA_APP_CERT=cert-value AGORA_APP_ID=app-id-value",
                    "extra": {
                        "app_cert": "cert-value",
                        "AGORA_APP_ID": "app-id-value",
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    logs = client.get("/api/v1/test-runs/run-log-redact/logs", headers=AUTH).json()["events"]
    assert logs[0]["message"] == "<redacted>"
    assert logs[0]["extra"]["token"] == "<redacted>"
    assert logs[0]["extra"]["target"]["authorization"] == "<redacted>"
    assert logs[0]["extra"]["attempts"][0]["api_key"] == "<redacted>"

    agora_logs = client.get("/api/v1/test-runs/run-log-redact-agora/logs", headers=AUTH).json()["events"]
    assert agora_logs[0]["message"] == "<redacted>"
    assert agora_logs[0]["extra"]["app_cert"] == "<redacted>"
    assert agora_logs[0]["extra"]["AGORA_APP_ID"] == "<redacted>"
    assert "cert-value" not in json.dumps(agora_logs[0], sort_keys=True)
    assert "app-id-value" not in json.dumps(agora_logs[0], sort_keys=True)


def test_IT_SRV_LOG_05A_http_ingest_redacts_local_user_paths(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.post(
        "/api/v1/logs/ingest",
        headers=AUTH,
        json={
            "node_id": "mac-log-path-redact",
            "lease_id": "lease-path-redact",
            "events": [
                {
                    "event_id": "log-path-redact-1",
                    "timestamp_ms": 310,
                    "level": "error",
                    "run_id": "run-log-path-redact",
                    "event": "agora.dump.created",
                    "message": "dump at /Users/example/Library/Logs/Beacon/agora.log",
                    "extra": {
                        "file_uri": "file:///Users/example/Library/Logs/Beacon/agora.log",
                        "home_path": "$HOME/Library/Logs/Beacon/agora.log",
                        "nested": ["see /Users/example/tmp/beacon.log"],
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    logs = client.get("/api/v1/test-runs/run-log-path-redact/logs", headers=AUTH).json()["events"]
    assert "/Users/example" not in json.dumps(logs[0], sort_keys=True)
    assert "file:///Users/example" not in logs[0]["extra"]["file_uri"]
    assert logs[0]["message"] == "dump at <redacted>"
    assert logs[0]["extra"]["file_uri"] == "file://<redacted>"
    assert logs[0]["extra"]["home_path"] == "<redacted>"
    assert logs[0]["extra"]["nested"] == ["see <redacted>"]
