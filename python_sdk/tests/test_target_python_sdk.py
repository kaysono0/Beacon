"""Target-only 同步 Python SDK 合同。"""

import inspect
import json
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python_sdk"))
sys.path.insert(0, str(ROOT))

from beacon_test import BeaconSession, CallResult, NativeCallError, ResourceRef  # noqa: E402
from beacon_test.generated import FACADES  # noqa: E402
from beacon_test.target_session import (  # noqa: E402
    AuthoringError,
    ObservationHandle,
    ObservationTimeoutError,
    ResourceScopeError,
    RunnerProtocolError,
    ServerUnavailableError,
)
from scripts.generation.generate_python_sdk_facade import generate_target_outputs, main  # noqa: E402


def session(handler):
    client = httpx.Client(base_url="http://server", transport=httpx.MockTransport(handler))
    return BeaconSession(
        base_url="http://server", run_id="run-1", case_id="case-1", run_token="secret",
        device_roles={"primary"}, source_path="cases/example.py", source_function="test_example", http_client=client,
    )


def call_reply(request, *, code=0, resource=None):
    body = json.loads(request.content)
    return httpx.Response(200, json={
        "operation_id": body["operation_id"], "device_role": "primary", "node_id": "mac-1",
        "code": code, "message": "ok" if code == 0 else "native failed", "result": {"echo": True},
        "resource_ref": resource, "failure_classification": None,
        "started_at_ms": 10, "finished_at_ms": 20,
    })


def observation(cursor=1):
    return {
        "cursor": cursor, "observation_id": f"obs-{cursor}", "kind": "event", "device_role": "primary",
        "run_id": "run-1", "case_id": "case-1", "step_id": None, "operation_id": None,
        "node_id": "mac-1", "lease_id": "lease-1", "source": "agent", "ingested_at_ms": 14,
        "target": {"sdk": "mock_echo", "interface": "echo", "class_name": "EchoDelegate", "function": "onEchoReceived"},
        "payload": {"message": "ready"}, "timestamp_ms": 12,
    }


def test_TARGET_PYSDK_callback_registration_is_role_bound_and_checked():
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "registration_id": body["registration_id"], "device_role": body["device_role"],
            "node_id": "mac-1", "code": 0, "message": "installed",
            "started_at_ms": 10, "finished_at_ms": 20,
        })

    beacon = session(handler)
    event = {"sdk": "mock_echo", "interface": "echo", "class": "EchoDelegate", "function": "onEchoReceived"}
    call = {"target": {"sdk": "mock_echo", "interface": "echo", "class": "EchoService", "function": "getLastEcho"}, "params": {}}
    result = beacon.register_callback(role="primary", event_target=event, calls=[call], repeat=2)
    assert result.code == 0
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert request.url.path == "/api/v1/runner/runs/run-1/cases/case-1/callbacks"
    assert request.headers["idempotency-key"] == body["registration_id"]
    assert body["event_target"] == event and body["calls"] == [call] and body["repeat"] == 2
    assert body["source"]["path"] == "cases/example.py"
    with pytest.raises(AuthoringError):
        beacon.register_callback(role="peer", event_target=event, calls=[call])
    with pytest.raises(AuthoringError):
        beacon.register_callback(role="primary", event_target=event, calls=[])
    with pytest.raises(AuthoringError):
        beacon.register_callback(role="primary", event_target=event, calls=[call], repeat=0)
    assert len(requests) == 1

    def failed(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "registration_id": body["registration_id"], "device_role": "primary", "node_id": "mac-1",
            "code": 488, "message": "unsupported", "started_at_ms": 10, "finished_at_ms": 20,
        })

    rejected = session(failed)
    assert rejected.register_callback(role="primary", event_target=event, calls=[call], check=False).code == 488
    with pytest.raises(NativeCallError):
        rejected.register_callback(role="primary", event_target=event, calls=[call])


def test_TARGET_PYSDK_01_call_is_immediate_role_bound_and_has_no_step():
    requests = []

    def handler(request):
        requests.append(request)
        return call_reply(request)

    beacon = session(handler)
    method = beacon.device("primary").mock_echo.echo.echo
    assert "message: 'str'" in str(inspect.signature(method))
    result = method(message="hello")
    assert isinstance(result, CallResult)
    assert result.value == {"echo": True}
    assert not hasattr(result, "step_id")
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert request.url.path == "/api/v1/runner/runs/run-1/cases/case-1/calls"
    assert request.headers["authorization"] == "Bearer secret"
    assert UUID(body["operation_id"]).version == 4
    assert request.headers["idempotency-key"] == body["operation_id"]
    assert body["device_role"] == "primary" and "node_id" not in body
    assert body["params"] == {"message": "hello"}
    assert body["source"]["path"] == "cases/example.py"
    assert body["source"]["function"] == "test_example"
    assert body["source"]["line"] > 0
    assert request.extensions["timeout"]["read"] == 7.0
    with pytest.raises(AuthoringError):
        beacon.device("undeclared")


def test_TARGET_PYSDK_02_check_false_resource_and_protocol_errors():
    ref = {"resource_id": "resource-1", "run_id": "run-1", "case_id": "case-1", "device_role": "primary", "resource_type": "sdk_instance"}
    requests = []

    def handler(request):
        requests.append(request)
        return call_reply(request, code=488, resource=ref)

    beacon = session(handler)
    method = beacon.device("primary").mock_echo.echo.echo
    result = method(message="x", check=False, timeout_s=0.5)
    assert result.code == 488 and result.resource == ResourceRef(**ref)
    assert json.loads(requests[0].content)["timeout_ms"] == 500
    assert requests[0].extensions["timeout"]["read"] == 2.5
    with pytest.raises(NativeCallError) as error:
        method(message="x")
    assert error.value.result.code == 488
    with pytest.raises(ResourceScopeError):
        method(message="x", resource=ResourceRef(**{**ref, "case_id": "other"}))
    assert len(requests) == 2

    def reject(_request):
        return httpx.Response(403, json={"detail": "scope rejected"})

    with pytest.raises(RunnerProtocolError):
        session(reject).device("primary").mock_echo.echo.echo(message="x", check=False)


def test_TARGET_PYSDK_03_event_wait_and_query_use_cursor_only_for_freshness():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[observation()])
        return httpx.Response(200, json=observation(2))

    beacon = session(handler)
    event = beacon.device("primary").mock_echo.echo.on_echo_received
    rows = event.query(match={"message": "ready"})
    assert rows[0].payload["message"] == "ready"
    assert event.wait(match={"message": "ready"}).cursor == 2
    assert event.wait(after_cursor=rows[0].cursor).cursor == 2
    assert requests[0].url.path.endswith("/observations")
    assert requests[0].url.params["after_cursor"] == "0"
    assert requests[0].url.params["class"] == "EchoDelegate"
    assert requests[0].url.params["function"] == "onEchoReceived"
    assert "name" not in requests[0].url.params
    assert json.loads(requests[0].url.params["match"]) == {"message": "ready"}
    first_wait = json.loads(requests[1].content)
    assert first_wait["match"] == {"message": "ready"}
    assert first_wait["after_cursor"] is None
    assert UUID(first_wait["wait_id"]).version == 4
    assert requests[1].headers["idempotency-key"] == first_wait["wait_id"]
    assert json.loads(requests[2].content)["after_cursor"] == 1
    assert "after_operation_id" not in json.loads(requests[2].content)

    beacon.device("primary").mock_echo.echo.get_last_echo_observations.query()
    beacon.device("primary").mock_complex_sdk.diagnostics.value_applied.query(match={"level": "INFO"})
    assert requests[3].url.params["kind"] == "state"
    assert requests[4].url.params["kind"] == "log"


def test_TARGET_PYSDK_04_wait_timeout_and_transport_error_do_not_retry():
    calls = []

    def timeout(request):
        calls.append(request)
        return httpx.Response(408, json={"detail": "timed out"})

    with pytest.raises(ObservationTimeoutError):
        session(timeout).device("primary").mock_echo.echo.on_echo_received.wait()
    assert len(calls) == 1

    def disconnected(request):
        calls.append(request)
        raise httpx.ConnectError("offline")

    with pytest.raises(ServerUnavailableError):
        session(disconnected).device("primary").mock_echo.echo.echo(message="x")
    assert len(calls) == 2


def test_TARGET_PYSDK_05_target_generation_is_isolated_and_rejects_reserved_parameters(tmp_path):
    assert main(["--check"]) == 0
    assert main(["--check"]) == 0
    artifact = {
        "sdk": "collision", "interfaces": [{"kind": "call", "target": {"sdk": "collision", "interface": "x", "class_name": "X", "function": "f"},
        "params_schema": {"properties": {"check": {"type": "boolean"}}, "required": ["check"]}}],
    }
    (tmp_path / "collision.json").write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="conflicts with facade control"):
        generate_target_outputs(tmp_path)
    artifact["interfaces"][0]["params_schema"] = {"properties": {"params": {"type": "object"}}, "required": ["params"]}
    (tmp_path / "collision.json").write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="conflicts with facade control"):
        generate_target_outputs(tmp_path)
    artifact["interfaces"][0]["params_schema"] = {"properties": {"timeout_s": {"type": "number"}}, "required": ["timeout_s"]}
    (tmp_path / "collision.json").write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="conflicts with facade control"):
        generate_target_outputs(tmp_path)


def test_TARGET_PYSDK_06_generated_facade_discovery_smoke():
    requests = []

    def handler(request):
        requests.append(request)
        return call_reply(request)

    beacon = session(handler)
    method_count = 0
    observation_count = 0
    for sdk in FACADES:
        facade = getattr(beacon.device("primary"), sdk)
        for interface_name, interface_property in vars(type(facade)).items():
            if not isinstance(interface_property, property):
                continue
            interface = getattr(facade, interface_name)
            for name, member in vars(type(interface)).items():
                if name.startswith("_"):
                    continue
                if isinstance(member, property):
                    assert isinstance(getattr(interface, name), ObservationHandle)
                    observation_count += 1
                    continue
                if not callable(member):
                    continue
                required = {
                    key: "sample"
                    for key, parameter in inspect.signature(member).parameters.items()
                    if key != "self" and parameter.default is inspect.Parameter.empty
                }
                assert getattr(interface, name)(**required).code == 0
                method_count += 1
    # 仅检查导出可达性；参数和返回合同由下面的具体行为用例验证。
    assert method_count > 0 and observation_count > 0
    assert len(requests) == method_count
    assert all(request.url.path.endswith("/calls") for request in requests)


@pytest.mark.parametrize("endpoint,id_field", [("calls", "operation_id"), ("callbacks", "registration_id")])
@pytest.mark.parametrize("wrong_field", ["identity", "device_role"])
def test_TARGET_PYSDK_07_rejects_reply_from_another_request_or_role(endpoint, id_field, wrong_field):
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        reply = {
            id_field: body[id_field], "device_role": "primary", "node_id": "mac-1",
            "code": 0, "message": "ok", "result": {}, "started_at_ms": 10, "finished_at_ms": 20,
        }
        reply[id_field if wrong_field == "identity" else "device_role"] = "another"
        return httpx.Response(200, json=reply)

    beacon = session(handler)
    with pytest.raises(RunnerProtocolError, match="response identity mismatch"):
        if endpoint == "calls":
            beacon.device("primary").mock_echo.echo.echo(message="hello", check=False)
        else:
            beacon.register_callback(
                role="primary", event_target=observation()["target"],
                calls=[{"target": observation()["target"], "params": {}}], check=False,
            )
    assert len(requests) == 1


@pytest.mark.parametrize("endpoint", ["calls", "callbacks", "observations", "waits"])
def test_TARGET_PYSDK_08_malformed_response_is_a_protocol_error(endpoint):
    beacon = session(lambda _: httpx.Response(200, json=[{}] if endpoint == "observations" else {}))
    with pytest.raises(RunnerProtocolError, match="invalid Runner"):
        if endpoint == "calls":
            beacon.device("primary").mock_echo.echo.echo(message="hello")
        elif endpoint == "callbacks":
            beacon.register_callback(role="primary", event_target=observation()["target"], calls=[{}])
        elif endpoint == "observations":
            beacon.device("primary").mock_echo.echo.on_echo_received.query()
        else:
            beacon.device("primary").mock_echo.echo.on_echo_received.wait()


def test_TARGET_PYSDK_09_join_options_preserve_absence_and_false_values():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return call_reply(request)

    engine = session(handler).device("primary").agora.rtc_engine
    engine.join_channel(channel="room", uid=0)
    engine.join_channel(
        channel="room", uid=0, token="", auto_subscribe_audio=False, auto_subscribe_video=False,
        publish_camera=False, publish_microphone=False, publish_media_player=False,
        publish_synthetic_audio=False, _extra={},
    )
    assert requests[0]["target"] == {
        "sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineKit", "function": "joinChannel",
    }
    assert requests[0]["params"] == {"channel": "room", "uid": 0}
    assert requests[1]["params"] == {
        "channel": "room", "uid": 0, "token": "", "auto_subscribe_audio": False,
        "auto_subscribe_video": False, "publish_camera": False, "publish_microphone": False,
        "publish_media_player": False, "publish_synthetic_audio": False, "_extra": {},
    }


def test_TARGET_PYSDK_10_nested_parameters_and_resource_controls_remain_distinct():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return call_reply(request)

    method = session(handler).device("primary").mock_complex_sdk.session.set_parameter_matrix
    ref = ResourceRef(resource_id="r1", run_id="run-1", case_id="case-1", device_role="primary", resource_type="sdk_instance")
    inputs = {"profile": "strict", "display_name": None, "labels": {"room": "alpha"}, "file_ref": {"path": "clip.mp4"}}
    method(**inputs)
    method(**inputs, attempts=0, optional_note="", _extra={"nested": [0, False, None]}, resource=ref, create_resource=True)
    assert requests[0]["params"] == {**inputs, "attempts": 2}
    assert requests[1]["params"] == {**inputs, "attempts": 0, "optional_note": "", "_extra": {"nested": [0, False, None]}}
    assert requests[1]["resource_ref"] == vars(ref)
    assert requests[1]["create_resource"] is True
    assert "resource" not in requests[1]["params"] and "create_resource" not in requests[1]["params"]


def test_TARGET_PYSDK_11_invalid_authoring_never_sends_requests():
    requests = []
    beacon = session(lambda request: requests.append(request))
    event = beacon.device("primary").mock_echo.echo.on_echo_received
    with pytest.raises(AuthoringError, match="positive"):
        beacon.device("primary").mock_echo.echo.echo(message="x", timeout_s=0)
    with pytest.raises(AuthoringError, match="non-negative"):
        event.query(after_cursor=-1)
    with pytest.raises(AuthoringError, match="non-negative"):
        event.wait(after_cursor=-1)
    assert requests == []


def test_TARGET_PYSDK_12_http_timeout_and_invalid_json_have_distinct_errors():
    from beacon_test.target_session import DispatchTimeoutError

    def timeout(request):
        raise httpx.ReadTimeout("deadline", request=request)

    with pytest.raises(DispatchTimeoutError, match="timed out") as error:
        session(timeout).device("primary").mock_echo.echo.echo(message="x")
    assert isinstance(error.value.__cause__, httpx.ReadTimeout)
    with pytest.raises(RunnerProtocolError, match="invalid JSON"):
        session(lambda _: httpx.Response(200, text="not-json")).device("primary").mock_echo.echo.echo(message="x")
