"""IR-04 Runner HTTP 鉴权、binding 和 Observation route 合同。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

import anyio
import httpx
import pytest
from fastapi import FastAPI

from app import main
from app.api.api_contracts import RunnerCallRequest
from app.devices.device_models import Device, DeviceSelector, DeviceSession
from app.reporting.evidence_runtime import ResultCollector
from app.observations.observation_models import ObservationInput, ObservationQuery
from app.observations.observation_service import ObservationService
from app.runs.python_native_models import NativeTestCase
from app.runs.python_native_runtime import RuntimeParamResolver
from app.runs.run_call_service import RunCallService
from app.runs.run_runtime import ServerRunRuntime
from app.runs.runner_case_registry import RunnerCaseContext, RunnerCaseMetadata, RunnerCaseRegistry, RunnerRoleBinding
from app.sdk.sdk_registry import SDKRegistry
from app.runs.test_models import TestCase, TestRun

from beacon_test import BeaconSession
from beacon_test.registry_paths import registry_dir


def _case_function(_: object) -> None:
    raise AssertionError("Runner API tests must not execute case functions")


def _case() -> NativeTestCase:
    return NativeTestCase(
        case_id="TC-RUNNER-API",
        name="runner api",
        platform="macos",
        devices=["primary"],
        suite="target-runtime",
        scenario_family="runner",
        implementation_status="runnable",
        covered_capabilities=[],
        tags=[],
        source_path="test_cases/python/runner_api.py",
        function_name="test_runner_api",
        function=_case_function,
    )


class RunnerApiHarness:
    def __init__(
        self,
        credential: str,
        runtime: ServerRunRuntime,
        observations: ObservationService,
        case_registry: RunnerCaseRegistry,
        context: RunnerCaseContext,
        clock: list[int],
        dispatcher: CountingDispatcher,
    ) -> None:
        self.credential = credential
        self.runtime = runtime
        self.observations = observations
        self.case_registry = case_registry
        self.context = context
        self.clock = clock
        self.dispatcher = dispatcher

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.credential}"}


class CountingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict], str, int, str | None]] = []
        self.callbacks: list[tuple[str, list[dict], str, int, str]] = []
        self.release = asyncio.Event()
        self.release.set()
        self.response_code = 0
        self.response_message: str | None = None
        self.raise_transport_error = False

    async def send_protocol_invoke(
        self, node_id: str, calls: list[dict], op_id: str, timeout_ms: int, *, expected_lease_id: str | None = None
    ) -> dict:
        self.calls.append((node_id, calls, op_id, timeout_ms, expected_lease_id))
        await self.release.wait()
        if self.raise_transport_error:
            raise ConnectionError("Bearer private-transport-token")
        data = {
            "code": self.response_code,
            "message": self.response_message or ("ok" if self.response_code == 0 else "native failure"),
            "result": '{"echo":"ok"}',
            "failure_classification": {"category": "native_failure"} if self.response_code else None,
        }
        return {
            "common": {"op_id": op_id},
            "data": data,
        }

    async def install_protocol_callback(
        self, node_id: str, defers: list[dict], registration_id: str, timeout_ms: int, *, expected_lease_id: str
    ) -> dict:
        self.callbacks.append((node_id, defers, registration_id, timeout_ms, expected_lease_id))
        await self.release.wait()
        return {"common": {"op_id": registration_id}, "data": {"code": self.response_code, "message": "installed"}}


@pytest.mark.anyio
async def test_IR10_runner_callback_registration_is_scoped_and_idempotent(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/callbacks"
    body = {
        "registration_id": "callback-1",
        "device_role": "primary",
        "event_target": {"sdk": "mock_echo", "interface": "echo", "class": "EchoDelegate", "function": "onEchoReceived"},
        "calls": [
            {"target": {"sdk": "mock_echo", "interface": "echo", "class": "EchoService", "function": "getLastEcho"}, "params": {}}
        ],
        "repeat": 1,
        "timeout_ms": 1000,
        "source": {"path": "test_cases/python/runner_api.py", "line": 12, "function": "test_runner_api"},
    }
    headers = {**harness.auth, "Idempotency-Key": "callback-1"}

    first = await client.post(path, headers=headers, json=body)
    duplicate = await client.post(path, headers=headers, json=body)
    conflict = await client.post(path, headers=headers, json={**body, "repeat": 2})
    wrong_role = await client.post(path, headers=headers, json={**body, "device_role": "peer"})
    bad_repeat = await client.post(path, headers=headers, json={**body, "repeat": 0})
    bad_call = await client.post(path, headers={**harness.auth, "Idempotency-Key": "callback-2"}, json={**body, "registration_id": "callback-2", "calls": [{"target": body["event_target"], "params": {}}]})

    assert first.status_code == 200 and first.json()["code"] == 0
    assert duplicate.json() == first.json()
    assert conflict.status_code == 409
    assert wrong_role.status_code == 403
    assert bad_repeat.status_code == 422
    assert bad_call.status_code == 200 and bad_call.json()["code"] == 422
    assert len(harness.dispatcher.callbacks) == 1
    node_id, defers, registration_id, timeout_ms, lease_id = harness.dispatcher.callbacks[0]
    assert (node_id, registration_id, timeout_ms, lease_id) == ("node-bound", "callback-1", 1000, "lease-bound")
    assert defers[0]["repeat"] == 1
    assert defers[0]["call_elements"][0]["target"]["function"] == "getLastEcho"


@pytest.mark.anyio
async def test_IR10_runner_routes_are_production_only() -> None:
    path = "/api/v1/runner/runs/run-1/cases/case-1/started"
    enabled_app = FastAPI()
    enabled_app.include_router(main.runner_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=enabled_app), base_url="http://test") as client:
        assert (await client.post(path, json={})).status_code == 401
        assert (await client.post("/api/v1/internal/target-test-runs", json={"case_ids": ["x"]})).status_code == 404


@pytest.fixture
async def runner_api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[httpx.AsyncClient, RunnerApiHarness]]:
    case = _case()
    clock = [1_000]
    case_registry = RunnerCaseRegistry([case], now_ms=lambda: clock[0], token_factory=lambda: b"r" * 32)
    binding = RunnerRoleBinding.from_session(
        "primary",
        DeviceSession(
            device=Device(node_id="node-bound", platform="macos", tags=["role:primary"]),
            websocket=object(),
            lease_id="lease-bound",
        ),
    )
    context = RunnerCaseContext(
        run_id="run-runner-api",
        metadata=RunnerCaseMetadata.from_native_case(case),
        bindings={"primary": binding},
        case_timeout_ms=10_000,
        token_expires_at_ms=2_000,
    )
    credential = await case_registry.register(context)
    observations = ObservationService(now_ms=lambda: 1_000)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    run = TestRun(
        run_id=context.run_id,
        status="queued",
        selector=DeviceSelector(),
        cases=[TestCase(case_id=context.case_id, name=case.name, steps=[])],
    )
    await runtime.create_run(run)
    await runtime.start_run(run.run_id, [Device(node_id=binding.node_id)])
    monkeypatch.setattr(main, "runner_case_registry", case_registry)
    monkeypatch.setattr(main, "run_runtime", runtime)
    monkeypatch.setattr(main, "observation_service", observations)
    monkeypatch.setattr(main, "sdk_registry", SDKRegistry.load_from(registry_dir()))
    fake_dispatcher = CountingDispatcher()
    monkeypatch.setattr(
        main,
        "run_call_service",
        RunCallService(fake_dispatcher, main.sdk_registry, RuntimeParamResolver(), runtime, observations),
    )
    target_app = FastAPI()
    target_app.include_router(main.runner_router)
    transport = httpx.ASGITransport(app=target_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, RunnerApiHarness(credential.token, runtime, observations, case_registry, context, clock, fake_dispatcher)


@pytest.mark.anyio
async def test_IR04_runner_routes_reject_missing_server_and_cross_scope_tokens(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/started"
    body = {"runner_protocol_version": 1, "python_version": "3.11", "pid": 42}

    missing = await client.post(path, json=body)
    server_token = await client.post(path, headers={"Authorization": "Bearer local-test-token"}, json=body)
    wrong_scope = await client.post(
        "/api/v1/runner/runs/run-other/cases/TC-RUNNER-API/started",
        headers=harness.auth,
        json=body,
    )
    accepted = await client.post(path, headers=harness.auth, json=body)
    conflict = await client.post(path, headers=harness.auth, json={**body, "pid": 43})
    harness.clock[0] = 2_001
    expired = await client.post(path, headers=harness.auth, json=body)

    assert missing.status_code == 401
    assert server_token.status_code == 403
    assert wrong_scope.status_code == 403
    assert accepted.status_code == 200
    assert conflict.status_code == 409
    assert expired.status_code == 403
    assert harness.credential not in accepted.text


@pytest.mark.anyio
async def test_IR04_wait_and_query_use_binding_and_registry_filters(runner_api) -> None:
    client, harness = runner_api
    target = {
        "sdk": "mock_complex_sdk",
        "interface": "session",
        "class": "MockComplexSessionObserver",
        "function": "onValueApplied",
    }
    source = {"path": "test_cases/python/runner_api.py", "line": 12, "function": "test_runner_api"}
    for observation_id, node_id, lease_id in (
        ("wrong-binding", "node-replaced", "lease-new"),
        ("bound", "node-bound", "lease-bound"),
    ):
        await harness.observations.ingest(
            ObservationInput.model_validate(
                {
                    "observation_id": observation_id,
                    "kind": "event",
                    "run_id": "run-runner-api",
                    "case_id": "TC-RUNNER-API",
                    "device_role": "primary",
                    "node_id": node_id,
                    "lease_id": lease_id,
                    "source": "native_agent",
                    "target": target,
                    "payload": {"value": "expected", "revision": 1},
                    "timestamp_ms": 1,
                }
            )
        )
    wait_body = {
        "wait_id": "wait-bound",
        "device_role": "primary",
        "kind": "event",
        "target": target,
        "match": {"value": "expected"},
        "timeout_ms": 100,
        "source": source,
    }
    wait_path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/waits"

    invalid = await client.post(
        wait_path,
        headers={**harness.auth, "Idempotency-Key": "wait-invalid"},
        json={**wait_body, "wait_id": "wait-invalid", "match": {"undeclared": 1}},
    )
    first = await client.post(
        wait_path,
        headers={**harness.auth, "Idempotency-Key": "wait-bound"},
        json=wait_body,
    )
    duplicate = await client.post(
        wait_path,
        headers={**harness.auth, "Idempotency-Key": "wait-bound"},
        json=wait_body,
    )
    query = await client.get(
        "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/observations",
        headers=harness.auth,
        params={
            "device_role": "primary",
            "kind": "event",
            "sdk": "mock_complex_sdk",
            "interface": "session",
            "class": "MockComplexSessionObserver",
            "function": "onValueApplied",
            "match": '{"value":"expected"}',
        },
    )
    invalid_target = await client.get(
        "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/observations",
        headers=harness.auth,
        params={
            "device_role": "primary",
            "kind": "event",
            "sdk": "mock_complex_sdk",
            "interface": "session",
            "function": "onValueApplied",
            "name": "duplicate-selector",
        },
    )
    run = await harness.runtime.get_run("run-runner-api")

    assert invalid.status_code == 422
    assert first.status_code == 200
    assert first.json()["observation_id"] == "bound"
    assert duplicate.json() == first.json()
    assert query.status_code == 200
    assert invalid_target.status_code == 422
    assert [item["observation_id"] for item in query.json()] == ["bound"]
    assert run is not None
    assert run.results == []
    outcomes = await harness.observations.query(ObservationQuery(run_id="run-runner-api", kinds=frozenset({"operation"})))
    assert len(outcomes) == 1
    assert outcomes[0].payload["request_id"] == "wait-bound"
    assert outcomes[0].payload["matched_observation_id"] == "bound"


@pytest.mark.anyio
async def test_IR04_result_is_idempotent_and_supervisor_revokes_token(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/result"
    wrong_source = await client.post(
        path,
        headers=harness.auth,
        json={
            "status": "failed",
            "failure_classification": "python_exception",
            "source": {"path": "client.py", "line": 1, "function": "override"},
        },
    )
    accepted = await client.post(
        path,
        headers=harness.auth,
        json={
            "status": "passed",
            "source": {"path": "test_cases/python/runner_api.py", "line": 15, "function": "test_runner_api"},
        },
    )
    duplicate = await client.post(
        path,
        headers=harness.auth,
        json={
            "status": "passed",
            "source": {"path": "test_cases/python/runner_api.py", "line": 15, "function": "test_runner_api"},
        },
    )
    conflict = await client.post(
        path,
        headers=harness.auth,
        json={
            "status": "failed",
            "failure_classification": "python_assertion",
            "source": {"path": "test_cases/python/runner_api.py", "line": 15, "function": "test_runner_api"},
            "diagnostic_traceback": "AssertionError",
            "timestamp_ms": 1_000,
        },
    )
    await harness.case_registry.finish(harness.context.run_id, harness.context.case_id)
    after_revoke = await client.post(
        "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/started",
        headers=harness.auth,
        json={"runner_protocol_version": 1, "python_version": "3.11", "pid": 42},
    )

    assert wrong_source.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "accepted", "duplicate": False}
    assert duplicate.json() == {"status": "accepted", "duplicate": True}
    assert conflict.status_code == 409
    assert harness.credential not in accepted.text
    assert after_revoke.status_code == 403


@pytest.mark.anyio
async def test_IR07_python_failure_records_redacted_diagnostic_once(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/result"
    missing_source = await client.post(path, headers=harness.auth, json={"status": "passed"})
    body = {
        "status": "failed", "failure_classification": "python_assertion", "message": "AssertionError",
        "source": {"path": "test_cases/python/runner_api.py", "line": 19, "function": "test_runner_api"},
        "diagnostic_traceback": f"AssertionError: token={harness.credential} at /Users/example/case.py",
        "timestamp_ms": 1_234,
    }
    missing_diagnostic = await client.post(
        path, headers=harness.auth, json={**body, "diagnostic_traceback": None},
    )
    first = await client.post(path, headers=harness.auth, json=body)
    duplicate = await client.post(path, headers=harness.auth, json=body)
    records = await harness.observations.query(ObservationQuery(run_id=harness.context.run_id))
    assert missing_source.status_code == missing_diagnostic.status_code == 422
    assert first.status_code == duplicate.status_code == 200
    assert first.json()["duplicate"] is False and duplicate.json()["duplicate"] is True
    assert len(records) == 1 and records[0].kind == "log"
    assert records[0].payload["source"]["line"] == 19
    assert records[0].payload["traceback"] == "<redacted>"


def _call_body(operation_id: str = "op-runner-api") -> dict:
    return {
        "operation_id": operation_id,
        "device_role": "primary",
        "target": {
            "sdk": "mock_echo",
            "interface": "echo",
            "class": "EchoService",
            "function": "echo",
        },
        "params": {"message": "hello"},
        "timeout_ms": 150,
        "source": {"path": "test_cases/python/runner_api.py", "line": 19, "function": "test_runner_api"},
    }


@pytest.mark.anyio
async def test_IR10_native_extra_reaches_agent_without_overriding_runner_scope(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls"
    target = {"sdk": "agora_rtc", "interface": "rtc_engine", "class": "AgoraRtcEngineKit", "function": "joinChannel"}
    params = {"channel": "room", "uid": 1001, "_extra": {"permission_fixture": "deny_media_for_testing"}}
    valid = {**_call_body("op-native-extra"), "target": target, "params": params}
    accepted = await client.post(path, headers={**harness.auth, "Idempotency-Key": "op-native-extra"}, json=valid)
    forged = {**_call_body("op-forged-extra"), "target": target, "params": {**params, "_extra": {"run_id": "forged"}}}
    rejected = await client.post(path, headers={**harness.auth, "Idempotency-Key": "op-forged-extra"}, json=forged)

    assert accepted.status_code == rejected.status_code == 200
    assert accepted.json()["code"] == 0
    assert rejected.json()["code"] == 422
    assert len(harness.dispatcher.calls) == 1
    call = harness.dispatcher.calls[0][1][0]
    assert call["params"] == {"channel": "room", "uid": 1001}
    assert call["extra"] == {
        "permission_fixture": "deny_media_for_testing",
        "run_id": "run-runner-api",
        "case_id": "TC-RUNNER-API",
        "device_role": "primary",
    }


@pytest.mark.anyio
async def test_IR05_call_duplicate_pending_and_completed_dispatch_once(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls"
    body = _call_body()
    headers = {**harness.auth, "Idempotency-Key": body["operation_id"]}
    harness.dispatcher.release.clear()

    first = asyncio.create_task(client.post(path, headers=headers, json=body))
    for _ in range(100):
        if harness.dispatcher.calls:
            break
        await asyncio.sleep(0)
    second = asyncio.create_task(client.post(path, headers=headers, json=body))
    await asyncio.sleep(0)
    conflict = await client.post(path, headers=headers, json={**body, "params": {"message": "changed"}})
    harness.dispatcher.release.set()
    first_response, second_response = await asyncio.gather(first, second)
    completed = await client.post(path, headers=headers, json=body)
    run = await harness.runtime.get_run("run-runner-api")

    assert conflict.status_code == 409
    assert first_response.status_code == second_response.status_code == completed.status_code == 200
    assert first_response.json() == second_response.json() == completed.json()
    assert "observation_cursor_before" not in first_response.json()
    assert "step_id" not in first_response.json()
    assert first_response.json()["result"] == {"echo": "ok"}
    assert len(harness.dispatcher.calls) == 1
    assert harness.dispatcher.calls[0][0] == "node-bound"
    assert harness.dispatcher.calls[0][3] == 150
    assert harness.dispatcher.calls[0][4] == "lease-bound"
    assert run is not None
    assert run.results == []
    observations = await harness.observations.query(ObservationQuery(run_id="run-runner-api"))
    assert [(item.operation_id, item.lease_id) for item in observations] == [("op-runner-api", "lease-bound")]
    assert observations[0].kind == "operation"
    assert observations[0].payload["source"]["line"] == 19


@pytest.mark.anyio
async def test_IR05_call_validation_unsupported_resource_and_source_do_not_dispatch(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls"

    async def post(body: dict) -> httpx.Response:
        return await client.post(path, headers={**harness.auth, "Idempotency-Key": body["operation_id"]}, json=body)

    invalid = await post({**_call_body("invalid"), "params": {}})
    unsupported = await post({**_call_body("unsupported"), "target": {**_call_body()["target"], "function": "missing"}})
    cross_scope = await post({
        **_call_body("cross-scope"),
        "resource_ref": {
            "resource_id": "res-1", "run_id": "other", "case_id": "TC-RUNNER-API",
            "device_role": "primary", "resource_type": "sdk_instance",
        },
    })
    forged = await post({
        **_call_body("forged"),
        "resource_ref": {
            "resource_id": "res-1", "run_id": "run-runner-api", "case_id": "TC-RUNNER-API",
            "device_role": "primary", "resource_type": "sdk_instance",
        },
    })
    wrong_source = await post({
        **_call_body("source"),
        "source": {"path": "other.py", "line": 1, "function": "other"},
    })

    assert invalid.status_code == unsupported.status_code == 200
    assert invalid.json()["code"] == 422
    assert unsupported.json()["code"] == 488
    assert cross_scope.status_code == forged.status_code == wrong_source.status_code == 403
    assert harness.dispatcher.calls == []
    outcomes = await harness.observations.query(ObservationQuery(run_id="run-runner-api", kinds=frozenset({"operation"})))
    assert [(item.payload["request_id"], item.payload["code"]) for item in outcomes] == [
        ("invalid", 422), ("unsupported", 488),
    ]


@pytest.mark.anyio
async def test_IR06_native_failure_records_independent_operation_fact(runner_api) -> None:
    client, harness = runner_api
    target = {
        "sdk": "mock_complex_sdk", "interface": "session",
        "class": "MockComplexSessionObserver", "function": "onValueApplied",
    }
    await harness.observations.ingest(ObservationInput.model_validate({
        "observation_id": "before-call", "kind": "event", "run_id": "run-runner-api",
        "case_id": "TC-RUNNER-API", "device_role": "primary", "node_id": "node-bound",
        "lease_id": "lease-bound", "source": "native_agent", "target": target,
        "payload": {"value": "old"}, "timestamp_ms": 1,
    }))
    harness.dispatcher.response_code = 408
    body = _call_body("op-native-failure")
    response = await client.post(
        "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls",
        headers={**harness.auth, "Idempotency-Key": "op-native-failure"},
        json=body,
    )
    run = await harness.runtime.get_run("run-runner-api")
    observations = await harness.observations.query(ObservationQuery(run_id="run-runner-api"))

    assert response.status_code == 200
    assert response.json()["code"] == 408
    assert response.json()["failure_classification"] == "native_failure"
    assert "observation_cursor_before" not in response.json()
    assert len(harness.dispatcher.calls) == 1
    assert run is not None
    assert run.results == []
    assert [item.cursor for item in observations] == [1, 2]
    assert [item.kind for item in observations] == ["event", "operation"]
    assert observations[1].payload["outcome"] == "failed"


@pytest.mark.anyio
async def test_IR06_call_fact_does_not_promote_string_code_to_success(runner_api) -> None:
    client, harness = runner_api
    # HTTP 响应模型会转换 code 类型，但事实不能因此把异常 Native 响应记成成功。
    harness.dispatcher.response_code = "0"
    body = _call_body("op-string-code")
    response = await client.post(
        "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls",
        headers={**harness.auth, "Idempotency-Key": body["operation_id"]}, json=body,
    )
    outcomes = await harness.observations.query(
        ObservationQuery(run_id="run-runner-api", kinds=frozenset({"operation"}))
    )

    assert response.status_code == 200
    assert response.json()["result"] is None
    assert len(outcomes) == 1
    assert outcomes[0].payload["code"] == "0"
    assert outcomes[0].payload["outcome"] == "failed"


@pytest.mark.anyio
async def test_IR05_native_failure_message_is_redacted_in_response_and_evidence(runner_api) -> None:
    client, harness = runner_api
    harness.dispatcher.response_code = 500
    harness.dispatcher.response_message = "failed with token=very-secret"
    body = _call_body("op-secret-failure")

    response = await client.post(
        "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls",
        headers={**harness.auth, "Idempotency-Key": body["operation_id"]},
        json=body,
    )
    run = await harness.runtime.get_run("run-runner-api")
    observations = await harness.observations.query(ObservationQuery(run_id="run-runner-api"))

    assert response.status_code == 200
    assert response.json()["message"] == "<redacted>"
    assert run is not None
    assert run.results == []
    assert observations[0].payload["message"] == "<redacted>"
    assert "very-secret" not in response.text


@pytest.mark.anyio
async def test_IR06_transport_failure_records_one_redacted_operation_fact(runner_api) -> None:
    client, harness = runner_api
    harness.dispatcher.raise_transport_error = True
    body = _call_body("op-transport-failure")
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls"
    headers = {**harness.auth, "Idempotency-Key": body["operation_id"]}

    first = await client.post(path, headers=headers, json=body)
    duplicate = await client.post(path, headers=headers, json=body)
    outcomes = await harness.observations.query(ObservationQuery(run_id="run-runner-api", kinds=frozenset({"operation"})))

    assert first.status_code == duplicate.status_code == 200
    assert first.json() == duplicate.json()
    assert first.json()["code"] == 502
    assert first.json()["failure_classification"] == "transport_failure"
    assert len(harness.dispatcher.calls) == len(outcomes) == 1
    assert outcomes[0].payload["outcome"] == "failed"
    assert "private-transport-token" not in first.text
    assert "private-transport-token" not in str(outcomes[0].payload)


@pytest.mark.anyio
async def test_IR06_finish_waits_for_in_flight_call_fact(runner_api) -> None:
    client, harness = runner_api
    harness.dispatcher.release.clear()
    body = _call_body("op-finish-race")
    call = asyncio.create_task(client.post(
        "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls",
        headers={**harness.auth, "Idempotency-Key": body["operation_id"]}, json=body,
    ))
    for _ in range(100):
        if harness.dispatcher.calls:
            break
        await asyncio.sleep(0)
    assert harness.dispatcher.calls
    finishing = asyncio.create_task(harness.runtime.finish_run("run-runner-api", "passed", 1_000))
    await asyncio.sleep(0)
    assert not finishing.done()

    harness.dispatcher.release.set()
    response = await call
    finished = await finishing
    outcomes = await harness.observations.query(ObservationQuery(run_id="run-runner-api", kinds=frozenset({"operation"})))
    assert response.status_code == 200
    assert finished.status == "passed" and finished.results == []
    assert len(outcomes) == 1
    assert outcomes[0].payload["request_id"] == "op-finish-race"


@pytest.mark.anyio
async def test_IR05_call_canonical_body_and_server_issued_resource_scope(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls"
    body = _call_body("op-create-resource")
    body["params"] = {"message": "hello", "extra": "value"}
    body["create_resource"] = True
    headers = {**harness.auth, "Idempotency-Key": body["operation_id"]}
    first = await client.post(path, headers=headers, json=body)
    duplicate = await client.post(path, headers=headers, json={**body, "params": {"extra": "value", "message": "hello"}})
    reference = first.json()["resource_ref"]
    use_body = {**_call_body("op-use-resource"), "resource_ref": reference}
    used = await client.post(path, headers={**harness.auth, "Idempotency-Key": "op-use-resource"}, json=use_body)
    cross_role = await client.post(
        path,
        headers={**harness.auth, "Idempotency-Key": "op-cross-role"},
        json={**_call_body("op-cross-role"), "resource_ref": {**reference, "device_role": "peer"}},
    )

    assert first.status_code == duplicate.status_code == used.status_code == 200
    assert first.json() == duplicate.json()
    assert reference["resource_type"] == "sdk_instance"
    assert harness.dispatcher.calls[0][1][0]["store_as"] == reference["resource_id"]
    assert harness.dispatcher.calls[1][1][0]["resource_ref"] == reference["resource_id"]
    assert cross_role.status_code == 403
    assert len(harness.dispatcher.calls) == 2


@pytest.mark.anyio
async def test_IR07_finish_case_drains_call_and_releases_resource_mapping(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls"
    body = {**_call_body("op-cleanup"), "create_resource": True}
    harness.dispatcher.release.clear()
    pending = asyncio.create_task(client.post(
        path, headers={**harness.auth, "Idempotency-Key": "op-cleanup"}, json=body,
    ))
    while not harness.dispatcher.calls:
        await asyncio.sleep(0)
    closing = asyncio.create_task(main.run_call_service.finish_case(harness.context))
    await asyncio.sleep(0)
    assert not closing.done()

    harness.dispatcher.release.set()
    response = await pending
    await closing
    assert response.status_code == 200
    assert response.json()["resource_ref"] is not None
    assert not main.run_call_service._operations
    assert not main.run_call_service._resources
    rejected = await client.post(
        path, headers={**harness.auth, "Idempotency-Key": "op-after-cleanup"},
        json=_call_body("op-after-cleanup"),
    )
    assert rejected.status_code == 403
    assert len(harness.dispatcher.calls) == 1


@pytest.mark.anyio
async def test_IR05_terminal_or_cancelled_run_rejects_new_call_without_dispatch(runner_api) -> None:
    client, harness = runner_api
    path = "/api/v1/runner/runs/run-runner-api/cases/TC-RUNNER-API/calls"
    await harness.runtime.request_cancellation("run-runner-api")
    cancelled_body = _call_body("op-after-cancel")
    cancelled = await client.post(
        path, headers={**harness.auth, "Idempotency-Key": cancelled_body["operation_id"]}, json=cancelled_body
    )
    await harness.runtime.finish_run("run-runner-api", "cancelled", 1_000)
    terminal_body = _call_body("op-after-terminal")
    terminal = await client.post(
        path, headers={**harness.auth, "Idempotency-Key": terminal_body["operation_id"]}, json=terminal_body
    )

    assert cancelled.status_code == terminal.status_code == 409
    assert harness.dispatcher.calls == []
    run = await harness.runtime.get_run("run-runner-api")
    assert run is not None and run.results == []


@pytest.mark.anyio
async def test_IR05_same_operation_id_in_two_cases_keeps_both_facts() -> None:
    first_case = _case()
    second_case = replace(first_case, case_id="TC-RUNNER-API-SECOND", name="second")
    binding = RunnerRoleBinding(
        device_role="primary", node_id="node-bound", lease_id="lease-bound"
    )
    contexts = [
        RunnerCaseContext(
            run_id="run-two-cases",
            metadata=RunnerCaseMetadata.from_native_case(case),
            bindings={"primary": binding},
            case_timeout_ms=10_000,
            token_expires_at_ms=2_000,
        )
        for case in (first_case, second_case)
    ]
    observations = ObservationService(now_ms=lambda: 1_000)
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    await runtime.create_run(TestRun(
        run_id="run-two-cases", status="queued", selector=DeviceSelector(),
        cases=[TestCase(case_id=case.case_id, name=case.name, steps=[]) for case in (first_case, second_case)],
    ))
    await runtime.start_run("run-two-cases", [Device(node_id="node-bound")])
    fake = CountingDispatcher()
    service = RunCallService(fake, SDKRegistry.load_from(registry_dir()), RuntimeParamResolver(), runtime, observations)
    request = RunnerCallRequest.model_validate(_call_body("op-shared"))

    first_response = await service.execute(contexts[0], request)
    second_response = await service.execute(contexts[1], request)
    run = await runtime.get_run("run-two-cases")
    records = await observations.query(ObservationQuery(run_id="run-two-cases"))

    assert first_response.operation_id == second_response.operation_id == "op-shared"
    assert len(fake.calls) == 2
    assert run is not None and run.results == []
    assert [item.case_id for item in records] == [first_case.case_id, second_case.case_id]
    assert records[0].observation_id != records[1].observation_id


@pytest.mark.anyio
async def test_IR04_sdk_query_and_wait_ignore_competing_observations(runner_api) -> None:
    client, harness = runner_api
    target = {"sdk": "mock_complex_sdk", "interface": "session", "class": "MockComplexSessionObserver", "function": "onValueApplied"}
    for observation_id, value in (("competing", "other"), ("expected", "wanted")):
        await harness.observations.ingest(ObservationInput.model_validate({
            "observation_id": observation_id, "kind": "event", "run_id": "run-runner-api",
            "case_id": "TC-RUNNER-API", "device_role": "primary", "node_id": "node-bound",
            "lease_id": "lease-bound", "source": "native_agent", "target": target,
            "payload": {"value": value, "revision": 1}, "timestamp_ms": 1,
        }))

    async def forward(request):
        response = await client.request(request.method, str(request.url), headers=request.headers, content=request.content)
        return httpx.Response(response.status_code, headers=response.headers, content=response.content)

    def exercise_sdk():
        with httpx.Client(base_url="http://test", transport=httpx.MockTransport(
            lambda request: anyio.from_thread.run(forward, request)
        )) as transport:
            beacon = BeaconSession(
                base_url="http://test", run_id="run-runner-api", case_id="TC-RUNNER-API",
                run_token=harness.credential, device_roles={"primary"}, source_path="test_cases/python/runner_api.py",
                source_function="test_runner_api", http_client=transport,
            )
            event = beacon.device("primary").mock_complex_sdk.session.on_value_applied
            assert [row.observation_id for row in event.query(match={"value": "wanted"})] == ["expected"]
            assert event.wait(match={"value": "wanted"}, timeout_s=0.1).observation_id == "expected"
            assert event.query(match={"value": "missing"}) == []

    await anyio.to_thread.run_sync(exercise_sdk)
