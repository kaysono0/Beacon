import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "python_sdk"))
sys.path.insert(0, str(REPO_ROOT))

from beacon_test.generated import FACADES, AgoraRtcFacade, MockEchoFacade  # noqa: E402
from beacon_test.registry_paths import REGISTRY_DIR_ENV, default_registry_dir, registry_dir  # noqa: E402
from scripts.generation.generate_python_sdk_facade import generate_target_outputs, main  # noqa: E402
from app.sdk.sdk_registry import SDKRegistry  # noqa: E402
import scripts.generation.sdk_registry_compiler as sdk_registry_compiler  # noqa: E402
from scripts.generation.sdk_registry_compiler import compile_registry_source  # noqa: E402


def test_REGISTRY_01_compiles_agora_source_into_canonical_artifact():
    artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "agora")

    assert artifact["sdk"] == "agora_rtc"
    assert {
        "kind": "call",
        "capability": "join_channel",
        "target": {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineKit", "function": "joinChannel"},
        "params_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "uid": {"type": "integer"},
                "token": {"type": "string"},
                "auto_subscribe_audio": {"type": "boolean"},
                "auto_subscribe_video": {"type": "boolean"},
                "publish_camera": {"type": "boolean"},
                "publish_microphone": {"type": "boolean"},
                "publish_synthetic_audio": {"type": "boolean"},
                "publish_media_player": {"type": "boolean"},
                "_extra": {"type": "object"},
            },
            "required": ["channel", "uid"],
        },
    } in artifact["interfaces"]
    callback = next(
        item
        for item in artifact["interfaces"]
        if item["kind"] == "callback" and item["target"]["function"] == "onJoinChannelSuccess"
    )
    assert callback["target"] == {
        "sdk": "agora_rtc",
        "interface": "rtc_engine",
        "class_name": "AgoraRtcEngineDelegate",
        "function": "onJoinChannelSuccess",
    }
    assert callback["payload_schema"]["required"] == ["channel", "uid"]
    assert callback["filterable_fields"] == ["channel", "uid"]
    assert callback["evidence_summary_fields"] == ["channel", "uid", "elapsed_ms"]
    on_error = next(
        item
        for item in artifact["interfaces"]
        if item["kind"] == "callback" and item["target"]["function"] == "onError"
    )
    assert on_error["target"] == {
        "sdk": "agora_rtc",
        "interface": "rtc_engine",
        "class_name": "AgoraRtcEngineDelegate",
        "function": "onError",
    }
    assert on_error["payload_schema"]["required"] == ["code"]
    assert on_error["filterable_fields"] == ["code"]
    assert on_error["evidence_summary_fields"] == ["code"]
    joined_state = next(
        item
        for item in artifact["interfaces"]
        if item["kind"] == "state"
        and item["target"]
        == {
            "sdk": "agora_rtc",
            "interface": "rtc_engine",
            "class_name": "AgoraRtcEngineKit",
            "function": "isJoined",
        }
    )
    assert joined_state["payload_schema"] == {"type": "boolean"}
    preview_state = next(
        item
        for item in artifact["interfaces"]
        if item["kind"] == "state"
        and item["target"]
        == {
            "sdk": "agora_rtc",
            "interface": "video_preview",
            "class_name": "AgoraRtcEngineKit",
            "function": "isPreviewing",
        }
    )
    assert preview_state["payload_schema"] == {"type": "boolean"}


def test_REGISTRY_02_rejects_mapping_with_unknown_capability(tmp_path):
    source = tmp_path / "bad"
    source.mkdir()
    (source / "capabilities.yaml").write_text(
        """
sdk: bad_sdk
capabilities:
  - id: existing
    name: Existing
""",
        encoding="utf-8",
    )
    (source / "mappings.yaml").write_text(
        """
sdk: bad_sdk
mappings:
  - capability: missing
    calls:
      - sdk: bad_sdk
        class_name: Bad
        function: call
""",
        encoding="utf-8",
    )
    (source / "evidence.yaml").write_text("sdk: bad_sdk\nevidence: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown capability"):
        compile_registry_source(source)


def test_REGISTRY_02A_rejects_unknown_adapter_source_keys_before_compilation(tmp_path):
    source = tmp_path / "bad"
    source.mkdir()
    (source / "capabilities.yaml").write_text(
        """
sdk: bad_sdk
capabilities:
  - id: existing
    name: Existing
unexpected: ignored-before-this-change
""",
        encoding="utf-8",
    )
    (source / "mappings.yaml").write_text(
        """
sdk: bad_sdk
mappings:
  - capability: existing
    calls:
      - sdk: bad_sdk
        class_name: Bad
        function: call
""",
        encoding="utf-8",
    )
    (source / "evidence.yaml").write_text("sdk: bad_sdk\nevidence: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source schema capabilities"):
        compile_registry_source(source)


def test_REGISTRY_02B_rejects_targets_from_another_adapter(tmp_path):
    source = tmp_path / "bad"
    source.mkdir()
    (source / "capabilities.yaml").write_text(
        "sdk: bad_sdk\ncapabilities:\n  - id: existing\n    name: Existing\n", encoding="utf-8"
    )
    (source / "mappings.yaml").write_text(
        """
sdk: bad_sdk
mappings:
  - capability: existing
    calls:
      - sdk: another_sdk
        interface: interface
        class_name: Class
        function: call
""",
        encoding="utf-8",
    )
    (source / "evidence.yaml").write_text("sdk: bad_sdk\nevidence: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="target.sdk must match adapter sdk bad_sdk"):
        compile_registry_source(source)


def test_REGISTRY_03_generates_typed_facade_from_registry_artifact():
    outputs = generate_target_outputs(registry_dir())
    agora = outputs["agora_rtc.py"]

    assert "def join_channel(" in agora
    assert "token: str, uid: int | None = None, channel: str | None = None" in agora
    assert "auto_subscribe_audio: bool | None = None" in agora
    assert "publish_microphone: bool | None = None" in agora
    assert "_extra: dict[str, Any] | None = None" in agora
    assert "params['channel'] = channel" in agora
    assert "def setup_local_video(" not in agora
    assert "def setup_remote_video(" not in agora
    assert "def bind_remote_video(self, *, uid: int, view_role: str," in agora
    assert "def capture_snapshot(self, *, view_role: str," in agora
    assert "def on_join_channel_success(self) -> ObservationHandle:" in agora

    calls = []
    session = SimpleNamespace(call=lambda *args, **kwargs: calls.append((args, kwargs)))
    namespace = {}
    exec(compile(agora, "generated/agora_rtc.py", "exec"), namespace)
    engine = namespace["AgoraRtcFacade"](session, "primary").rtc_engine
    engine.join_channel(channel="room", uid=17, publish_microphone=False)
    assert calls == [(("primary", {
        "sdk": "agora_rtc", "interface": "rtc_engine",
        "class_name": "AgoraRtcEngineKit", "function": "joinChannel",
    }, {"channel": "room", "uid": 17, "publish_microphone": False}), {
        "check": True, "timeout_s": 5.0, "resource": None, "create_resource": False,
    })]


def test_REGISTRY_G2_parameter_matrix_generates_enum_nullable_default_map_file_and_extra_shapes():
    artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "mock_complex_sdk")
    matrix_call = next(
        item
        for item in artifact["interfaces"]
        if item["kind"] == "call" and item["target"]["function"] == "setParameterMatrix"
    )

    assert matrix_call["params_schema"] == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "profile": {"type": "string", "enum": ["strict", "relaxed"]},
            "display_name": {"type": ["string", "null"]},
            "labels": {"type": "object", "additionalProperties": {"type": "string"}},
            "file_ref": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "uri": {"type": "string", "minLength": 1},
                    "media_type": {"type": "string"},
                },
                "required": ["uri"],
            },
            "attempts": {"type": "integer", "minimum": 1, "maximum": 3, "default": 2},
            "optional_note": {"type": "string"},
            "_extra": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"fixture": {"type": "string"}},
            },
        },
        "required": ["profile", "display_name", "labels", "file_ref"],
    }

    generated = generate_target_outputs(registry_dir())["mock_complex_sdk.py"]
    assert "from typing import Any, Literal" in generated
    assert "def set_parameter_matrix(" in generated
    assert "profile: Literal['strict', 'relaxed']" in generated
    assert "display_name: str | None" in generated
    assert "labels: dict[str, str]" in generated
    assert "file_ref: dict[str, Any]" in generated
    assert "attempts: int = 2" in generated
    assert "optional_note: str | None = None" in generated
    assert "_extra: dict[str, Any] | None = None" in generated


def test_REGISTRY_G2_parameter_matrix_classifies_invalid_author_input_before_dispatch():
    artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "mock_complex_sdk")
    registry = SDKRegistry([artifact])
    target = {
        "sdk": "mock_complex_sdk",
        "interface": "session",
        "class_name": "MockComplexSession",
        "function": "setParameterMatrix",
    }

    assert registry.validate_invoke(
        target,
        {
            "profile": "strict",
            "display_name": None,
            "labels": {"owner": "qa"},
            "file_ref": {"uri": "fixture://matrix.bin", "media_type": "application/octet-stream"},
        },
        {"fixture": "parameter-matrix"},
    ) is None
    assert registry.validate_invoke(
        target,
        {
            "profile": "strict",
            "display_name": None,
            "labels": {"owner": "qa"},
            "file_ref": {"uri": "fixture://matrix.bin"},
            "attempts": 0,
        },
        {"fixture": "parameter-matrix"},
    ) == {
        "code": 422,
        "message": "invalid sdk parameters at attempts: minimum",
        "failure_classification": {
            "category": "validation",
            "source": "sdk_registry",
            "reason": "invalid_parameters",
            "path": "attempts",
            "validator": "minimum",
        },
    }


def test_REGISTRY_G3_interface_shape_matrix_compiles_result_schemas_and_shared_control_facade(tmp_path):
    artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "mock_complex_sdk")
    calls = {
        item["target"]["function"]: item
        for item in artifact["interfaces"]
        if item["kind"] == "call"
    }

    assert calls["describeValue"]["result_schema"] == {
        "type": "object",
        "properties": {"value": {"type": ["string", "null"]}, "revision": {"type": "integer"}},
        "required": ["value", "revision"],
    }
    assert calls["ensureValue"]["result_schema"] == {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
            "applied": {"type": "boolean"},
            "revision": {"type": "integer"},
        },
        "required": ["value", "applied", "revision"],
    }
    assert calls["resetValue"]["target"]["interface"] == "control"
    assert calls["resetValue"]["result_schema"] == {"type": "null"}
    assert calls["rejectValue"]["result_schema"] == {"type": "null"}

    expected_focused_mapping = {
        "platform": "server_focused_fixture",
        "status": "supported",
        "provider": "MockComplexProtocolWebSocket",
        "bridge_boundary": "server/tests",
    }
    for function in ("describeValue", "ensureValue", "rejectValue", "resetValue"):
        contract = _contract_for(artifact, function)
        assert contract["provider_mappings"][0] == expected_focused_mapping
        assert contract["provider_mappings"][1]["status"] == "designed_but_blocked"

    assert _contract_for(artifact, "resetValue")["server_validation"]["result_schema"] == {"type": "null"}

    (tmp_path / "mock_complex_sdk.json").write_text(json.dumps(artifact), encoding="utf-8")
    facade = generate_target_outputs(tmp_path)["mock_complex_sdk.py"]
    assert "def describe_value(self, *, check: bool = True," in facade
    assert "def ensure_value(self, *, value: str," in facade
    assert "def reject_value(self, *, reason: str," in facade
    assert "def reset_value(self, *, check: bool = True," in facade


def test_REGISTRY_03C_compiles_cross_platform_contract_matrix_from_registry_artifact():
    artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "agora")

    assert len(artifact["contract_matrix"]) == len(artifact["interfaces"])
    join_contract = _contract_for(artifact, "joinChannel")
    renew_contract = _contract_for(artifact, "renewToken")
    callback_contract = _contract_for(artifact, "onJoinChannelSuccess")
    state_contract = _contract_for(artifact, "isJoined")

    assert join_contract["authoring"] == {
        "dynamic": 'ctx.device(role).sdk("agora_rtc").rtc_engine.joinChannel',
        "typed_facade": "ctx.device(role).agora_rtc.rtc_engine.join_channel",
    }
    assert join_contract["server_validation"]["params_schema"]["required"] == ["channel", "uid"]
    assert join_contract["provider_mappings"] == [
        {
            "platform": "mac",
            "status": "supported",
            "provider": "RTCInvocationProvider",
            "bridge_boundary": "agents/mac",
        }
    ]
    assert join_contract["object_lifecycle"] == {
        "handle_kind": "sdk_instance",
        "owner": "provider_bridge",
        "author_visible": False,
    }
    assert join_contract["scheduling"] == {"mode": "sync", "thread": "provider_default"}
    assert renew_contract["authoring"] == {
        "dynamic": 'ctx.device(role).sdk("agora_rtc").rtc_engine.renewToken',
        "typed_facade": "ctx.device(role).agora_rtc.rtc_engine.renew_token",
    }
    assert renew_contract["server_validation"]["params_schema"]["required"] == ["token"]
    assert renew_contract["provider_mappings"] == [
        {
            "platform": "mac",
            "status": "supported",
            "provider": "RTCInvocationProvider",
            "bridge_boundary": "agents/mac",
        }
    ]

    assert callback_contract["callback_lifecycle"] == {
        "handle_kind": "callback_subscription",
        "subscribe": True,
        "observe": True,
        "unsubscribe": True,
        "filterable_fields": ["channel", "uid"],
    }
    assert callback_contract["evidence_projection"] == {
        "evidence_type": "event",
        "report_projection": "step.evidence",
        "summary_fields": ["channel", "uid", "elapsed_ms"],
        "evidence_capability": "join_channel",
    }
    assert callback_contract["scheduling"] == {"mode": "async_callback", "thread": "provider_default"}
    assert state_contract["evidence_projection"]["evidence_type"] == "state"
    visual_contract = _contract_for(artifact, "captureSnapshot")
    assert visual_contract["authoring"] == {
        "dynamic": 'ctx.device(role).sdk("agora_rtc").visual_probe.captureSnapshot',
        "typed_facade": "ctx.device(role).agora_rtc.visual_probe.capture_snapshot",
    }
    assert visual_contract["server_validation"]["params_schema"]["required"] == ["view_role"]
    assert visual_contract["provider_mappings"] == [
        {
            "platform": "mac",
            "status": "supported",
            "provider": "AgoraVisualProbeProvider",
            "bridge_boundary": "agents/mac",
        }
    ]


def test_REGISTRY_03D_contract_matrix_keeps_platform_differences_in_provider_mapping_only():
    system_artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "beacon_system")
    mock_artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "mock_echo")

    wait_contract = _contract_for(system_artifact, "waitInMs")
    assert wait_contract["provider_mappings"] == [
        {
            "platform": "mac",
            "status": "supported",
            "provider": "RTCInvocationProvider",
            "bridge_boundary": "agents/mac",
        },
    ]
    assert wait_contract["authoring"]["typed_facade"] == "ctx.device(role).beacon_system.clock.wait_in_ms"

    echo_contract = _contract_for(mock_artifact, "echo")
    assert echo_contract["provider_mappings"] == [
        {
            "platform": "server_test_dispatcher",
            "status": "supported",
            "provider": "FunctionReplyDispatcher",
            "bridge_boundary": "server/tests",
        },
        {
            "platform": "mac",
            "status": "unsupported",
            "provider": None,
            "bridge_boundary": "agents/mac",
        },
    ]
    assert "platform" not in echo_contract["server_validation"]


def test_REGISTRY_G1_mock_complex_sdk_compiles_full_evidence_matrix_and_typed_facade(tmp_path):
    artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "mock_complex_sdk")

    assert artifact["sdk"] == "mock_complex_sdk"
    assert {
        "kind": "call",
        "capability": "apply_value",
        "target": {
            "sdk": "mock_complex_sdk",
            "interface": "session",
            "class_name": "MockComplexSession",
            "function": "applyValue",
        },
        "params_schema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    } in artifact["interfaces"]
    configure = next(item for item in artifact["interfaces"] if item["target"]["function"] == "configureValue")
    assert configure["params_schema"]["properties"]["options"]["properties"]["metadata"]["properties"]["retries"] == {
        "type": "integer"
    }
    callback = next(
        item
        for item in artifact["interfaces"]
        if item["kind"] == "callback" and item["target"]["function"] == "onValueApplied"
    )
    assert callback["target"]["function"] == "onValueApplied"
    assert callback["filterable_fields"] == ["value"]
    state = next(item for item in artifact["interfaces"] if item["kind"] == "state")
    assert state["target"]["function"] == "getLastAppliedValue"
    metric = next(item for item in artifact["interfaces"] if item["kind"] == "metric")
    assert metric["target"]["function"] == "appliedCount"
    assert metric["payload_schema"] == {"type": "number"}
    artifact_row = next(item for item in artifact["interfaces"] if item["kind"] == "artifact")
    assert artifact_row["target"]["function"] == "latestSnapshot"
    assert artifact_row["filterable_fields"] == ["artifact_type", "metadata.format"]
    log = next(item for item in artifact["interfaces"] if item["kind"] == "log")
    assert log["target"]["function"] == "valueApplied"
    assert log["filterable_fields"] == ["extra.value"]

    for function, evidence_type in (
        ("appliedCount", "metric"),
        ("latestSnapshot", "artifact"),
        ("valueApplied", "log"),
    ):
        evidence_contract = _contract_for(artifact, function)
        assert evidence_contract["evidence_projection"]["evidence_type"] == evidence_type
        assert evidence_contract["evidence_projection"]["report_projection"] == "step.evidence"
        assert evidence_contract["provider_mappings"][0] == {
            "platform": "server_focused_fixture",
            "status": "supported",
            "provider": "MockComplexProtocolWebSocket",
            "bridge_boundary": "server/tests",
        }
        assert evidence_contract["provider_mappings"][1]["status"] == "designed_but_blocked"

    contract = _contract_for(artifact, "applyValue")
    assert contract["provider_mappings"][0] == {
        "platform": "mac_mock_agent",
        "status": "supported",
        "provider": "MockAgentHarness",
        "bridge_boundary": "scripts/validation/run_e2e_mock_tests.py",
    }

    (tmp_path / "mock_complex_sdk.json").write_text(json.dumps(artifact), encoding="utf-8")
    facade = generate_target_outputs(tmp_path)["mock_complex_sdk.py"]
    assert "class MockComplexSdkFacade:" in facade
    assert "def apply_value(self, *, value: str," in facade
    assert "def configure_value(self, *, value: str, options: dict[str, Any]," in facade
    assert "def get_last_applied_value(self, *, check: bool = True," in facade
    assert "def on_value_applied(self) -> ObservationHandle:" in facade
    assert "def applied_count(self) -> ObservationHandle:" in facade
    assert "def latest_snapshot(self) -> ObservationHandle:" in facade
    assert "def value_applied(self) -> ObservationHandle:" in facade
    assert "ObservationHandle(self._session, self._role, 'artifact'," in facade
    assert "ObservationHandle(self._session, self._role, 'log'," in facade


def test_REGISTRY_04_generator_check_reports_stale_output(tmp_path, capsys):
    output_dir = tmp_path / "generated"
    assert main(["--registry-dir", str(registry_dir()), "--output-dir", str(output_dir)]) == 0
    assert main(["--registry-dir", str(registry_dir()), "--output-dir", str(output_dir), "--check"]) == 0
    (output_dir / "agora_rtc.py").write_text("# stale\n", encoding="utf-8")

    assert main(["--registry-dir", str(registry_dir()), "--output-dir", str(output_dir), "--check"]) == 1
    captured = capsys.readouterr()
    assert "generated facade files are out of date:" in captured.err
    assert str(output_dir / "agora_rtc.py") in captured.err


def test_REGISTRY_06_committed_generated_facades_match_registry_artifacts():
    generated_dir = REPO_ROOT / "python_sdk" / "beacon_test" / "generated"
    outputs = generate_target_outputs(registry_dir())

    stale = sorted(
        relative_path
        for relative_path, content in outputs.items()
        if not (generated_dir / relative_path).exists()
        or (generated_dir / relative_path).read_text(encoding="utf-8") != content
    )
    committed = {
        path.relative_to(generated_dir).as_posix()
        for path in generated_dir.rglob("*")
        if path.is_file()
        and not any(
            part == "__pycache__" or part.startswith(".")
            for part in path.relative_to(generated_dir).parts
        )
        and path.suffix != ".pyc"
    }
    orphaned = sorted(committed - set(outputs))

    assert stale == [], f"run scripts/generation/generate_python_sdk_facade.py; out of date: {stale}"
    assert orphaned == [], f"registry no longer produces these facades: {orphaned}"


def test_REGISTRY_06D_generator_check_reports_orphans_and_shows_out_of_repo_paths(tmp_path, capsys):
    output_dir = tmp_path / "generated"
    output_dir.mkdir()
    outputs = generate_target_outputs(registry_dir())
    for relative_path, content in outputs.items():
        (output_dir / relative_path).write_text(content, encoding="utf-8")
    (output_dir / "stale_sdk.py").write_text("# orphan\n", encoding="utf-8")
    cache_dir = output_dir / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "stale_sdk.cpython-311.pyc").write_bytes(b"")

    exit_code = main(["--registry-dir", str(registry_dir()), "--output-dir", str(output_dir), "--check"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "orphan generated files not produced by the registry:" in captured.err
    assert str(output_dir / "stale_sdk.py") in captured.err
    assert "__pycache__" not in captured.err
    assert ".pyc" not in captured.err


def test_REGISTRY_08_unsupported_platform_targets_are_rejected_before_dispatch():
    registry = SDKRegistry.load_from(registry_dir())

    def target(sdk, interface, class_name, function, **overrides):
        payload = {"sdk": sdk, "interface": interface, "class_name": class_name, "function": function}
        payload.update(overrides)
        return payload

    # 火山 room_joined_state：声明过，但只有 mac/unsupported —— 必须在转发前归类为 488。
    joined_state = target("volcengine_rtc", "byte_rtc_room", "ByteRTCRoom", "onRoomStateChangedWithReason")
    error = registry.unsupported_platform_error(joined_state)
    assert error is not None
    assert error["code"] == 488
    assert error["failure_classification"]["category"] == "unsupported"
    assert registry.validate_invoke(joined_state, {}) == error
    # 声明过，因此仍属于「可调用面」（HTTP/WS 层不因未声明而拒绝）。
    assert registry.supports_invoke(joined_state)

    # 有 supported 映射的行不受影响：火山 joinRoom、Agora joinChannel、mock_complex_sdk 的
    # mac_mock_agent 行（后者是 mock E2E 链路依赖的行，不能被本轮判定误伤）。
    for supported in (
        target("volcengine_rtc", "byte_rtc_room", "ByteRTCRoom", "joinRoom"),
        target("agora_rtc", "rtc_engine", "AgoraRtcEngineKit", "joinChannel"),
        target("mock_complex_sdk", "session", "MockComplexSession", "applyValue"),
        target("mock_complex_sdk", "session", "MockComplexSession", "describeValue"),
    ):
        assert registry.unsupported_platform_error(supported) is None, supported

    # 未声明的 target 仍由既有的 schema-missing 分支处理（两步都不放行）。
    undeclared = target("agora_rtc", "rtc_engine", "AgoraRtcEngineKit", "noSuchFunction")
    assert registry.unsupported_platform_error(undeclared) is None
    assert registry.validate_invoke(undeclared, {})["code"] == 488


def _contract_for(artifact, function):
    return next(row for row in artifact["contract_matrix"] if row["target"]["function"] == function)


def test_REGISTRY_05_registry_dir_defaults_to_repo_compiled_artifacts(monkeypatch):
    monkeypatch.delenv(REGISTRY_DIR_ENV, raising=False)

    assert registry_dir() == REPO_ROOT / "sdk_registry" / "compiled"


def test_REGISTRY_05B_registry_dir_honors_env_override(monkeypatch, tmp_path):
    override = tmp_path / "compiled"
    override.mkdir()
    (override / "agora_rtc.json").write_text(
        json.dumps({"sdk": "agora_rtc", "interfaces": [], "contract_matrix": []}),
        encoding="utf-8",
    )
    monkeypatch.setenv(REGISTRY_DIR_ENV, str(override))

    assert registry_dir() == override


def test_REGISTRY_05C_registry_dir_expands_user_home_in_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(REGISTRY_DIR_ENV, "~/external-registry")

    assert registry_dir() == tmp_path / "external-registry"


def test_REGISTRY_05D_registry_dir_ignores_blank_override(monkeypatch):
    monkeypatch.setenv(REGISTRY_DIR_ENV, "   ")

    assert registry_dir() == REPO_ROOT / "sdk_registry" / "compiled"


def test_REGISTRY_05F_default_registry_dir_ignores_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(REGISTRY_DIR_ENV, str(tmp_path))

    assert registry_dir() == tmp_path
    assert default_registry_dir() == REPO_ROOT / "sdk_registry" / "compiled"


def test_REGISTRY_05G_compiler_writes_artifacts_through_the_env_immune_resolver(monkeypatch, tmp_path):
    override = tmp_path / "override"
    written = tmp_path / "written"
    monkeypatch.setenv(REGISTRY_DIR_ENV, str(override))
    monkeypatch.setattr(sdk_registry_compiler, "default_registry_dir", lambda: written)

    sdk_registry_compiler.write_registry_outputs([{"sdk": "probe_sdk"}])

    assert (written / "probe_sdk.json").exists()
    assert not override.exists()


def test_REGISTRY_05H_registry_dir_absolutizes_relative_override(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(REGISTRY_DIR_ENV, "compiled")

    resolved = registry_dir()
    monkeypatch.chdir(tmp_path.parent)

    assert resolved.is_absolute()
    assert resolved == tmp_path / "compiled"


def test_REGISTRY_05I_beacon_test_import_does_not_require_httpx(tmp_path):
    code = (
        "import sys\n"
        "import beacon_test.registry_paths\n"
        "loaded = sorted(name for name in sys.modules if name.split('.')[0] == 'httpx')\n"
        "assert not loaded, f'httpx modules imported: {loaded}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "python_sdk")},
    )

    assert result.returncode == 0, result.stderr


def test_REGISTRY_05J_beacon_test_lazy_exports_reject_unknown_names():
    import beacon_test

    with pytest.raises(AttributeError, match="has no attribute 'not_an_export'"):
        beacon_test.not_an_export  # noqa: B018

    assert "BeaconSession" in dir(beacon_test)
    assert "BeaconTestClient" not in dir(beacon_test)
    assert "not_an_export" not in dir(beacon_test)


_MAC_UNSUPPORTED_FALLBACK = [
    {"platform": "mac", "status": "unsupported", "provider": None, "bridge_boundary": "agents/mac"}
]

_RTC_INVOCATION_MAPPING = [
    {"platform": "mac", "status": "supported", "provider": "RTCInvocationProvider", "bridge_boundary": "agents/mac"}
]

_SERVER_FOCUSED_MAPPINGS = [
    {
        "platform": "server_focused_fixture",
        "status": "supported",
        "provider": "MockComplexProtocolWebSocket",
        "bridge_boundary": "server/tests",
    },
    {
        "platform": "mac_mock_agent",
        "status": "designed_but_blocked",
        "provider": None,
        "bridge_boundary": "scripts/validation/run_e2e_mock_tests.py",
    },
    {"platform": "mac", "status": "unsupported", "provider": None, "bridge_boundary": "agents/mac"},
]

_MAC_MOCK_AGENT_MAPPINGS = [
    {
        "platform": "mac_mock_agent",
        "status": "supported",
        "provider": "MockAgentHarness",
        "bridge_boundary": "scripts/validation/run_e2e_mock_tests.py",
    },
    {"platform": "mac", "status": "unsupported", "provider": None, "bridge_boundary": "agents/mac"},
]

# 迁移到 providers.yaml 之前的编译器输出矩阵：逐行冻结，证明声明化是纯重构。
_PRE_REFACTOR_PROVIDER_MAPPINGS = {
    ("agora", "joinChannel"): _RTC_INVOCATION_MAPPING,
    ("agora", "startPreview"): _RTC_INVOCATION_MAPPING,
    ("agora", "captureSnapshot"): [
        {
            "platform": "mac",
            "status": "supported",
            "provider": "AgoraVisualProbeProvider",
            "bridge_boundary": "agents/mac",
        }
    ],
    ("beacon_system", "waitInMs"): _RTC_INVOCATION_MAPPING,
    ("beacon_system", "applyImpairment"): [
        {
            "platform": "mac",
            "status": "supported",
            "provider": "NetworkConditionProvider",
            "bridge_boundary": "agents/mac",
        }
    ],
    ("mock_echo", "echo"): [
        {
            "platform": "server_test_dispatcher",
            "status": "supported",
            "provider": "FunctionReplyDispatcher",
            "bridge_boundary": "server/tests",
        },
        {"platform": "mac", "status": "unsupported", "provider": None, "bridge_boundary": "agents/mac"},
    ],
    ("mock_complex_sdk", "describeValue"): _SERVER_FOCUSED_MAPPINGS,
    ("mock_complex_sdk", "setParameterMatrix"): _SERVER_FOCUSED_MAPPINGS,
    ("mock_complex_sdk", "appliedCount"): _SERVER_FOCUSED_MAPPINGS,
    ("mock_complex_sdk", "resetValue"): _SERVER_FOCUSED_MAPPINGS,
    ("mock_complex_sdk", "applyValue"): _MAC_MOCK_AGENT_MAPPINGS,
    ("mock_complex_sdk", "getLastAppliedValue"): _MAC_MOCK_AGENT_MAPPINGS,
}


def test_REGISTRY_07A_declaration_migration_keeps_pre_refactor_provider_mappings():
    for (adapter, function), expected in _PRE_REFACTOR_PROVIDER_MAPPINGS.items():
        artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / adapter)
        assert _contract_for(artifact, function)["provider_mappings"] == expected, f"{adapter}:{function}"


def test_REGISTRY_07B_compiler_source_carries_no_sdk_literals():
    offenders = [
        f"{line_number}: {line.strip()}"
        for line_number, line in enumerate(
            (REPO_ROOT / "scripts/generation" / "sdk_registry_compiler.py").read_text(encoding="utf-8").splitlines(),
            start=1,
        )
        if any(name in line for name in ("agora", "beacon_system", "mock_echo", "mock_complex_sdk", "volcengine"))
    ]

    assert offenders == []


def test_REGISTRY_07C_missing_providers_declaration_falls_back_to_mac_unsupported(tmp_path):
    source = tmp_path / "mock_echo"
    shutil.copytree(REPO_ROOT / "sdk_adapters" / "mock_echo", source)
    (source / "providers.yaml").unlink()

    artifact = compile_registry_source(source)

    assert all(row["provider_mappings"] == _MAC_UNSUPPORTED_FALLBACK for row in artifact["contract_matrix"])


@pytest.mark.parametrize(
    ("declaration", "message"),
    [
        ("sdk: other_sdk\nrules: []\n", "sdk must match capabilities.yaml"),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    mappings: []\n",
            "mappings must be a non-empty array",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    functions: []\n    mappings:\n      - platform: mac\n"
            "        status: supported\n        provider: P\n        bridge_boundary: agents/mac\n",
            "functions must be a non-empty string array",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    mappings:\n      - platform: mac\n"
            "        status: maybe\n        provider: P\n        bridge_boundary: agents/mac\n",
            "status is not a supported status",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    mappings:\n      - platform: mac\n"
            "        status: supported\n        provider: P\n",
            "must declare exactly platform, status, provider, bridge_boundary",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    mappings:\n      - platform: mac\n"
            "        status: supported\n        provider: null\n        bridge_boundary: agents/mac\n",
            "status supported requires a non-empty provider",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    mappings:\n      - platform: mac\n"
            "        status: supported\n        provider: ''\n        bridge_boundary: agents/mac\n",
            "status supported requires a non-empty provider",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    mappings:\n      - platform: mac\n"
            "        status: unsupported\n        provider: P\n        bridge_boundary: agents/mac\n",
            "status unsupported requires provider null",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    mappings:\n      - platform: mac_mock_agent\n"
            "        status: designed_but_blocked\n        provider: P\n        bridge_boundary: agents/mac\n",
            "status designed_but_blocked requires provider null",
        ),
        (
            "sdk: mock_echo\nrules: []\n",
            "rules must be a non-empty array",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echoo]\n    mappings:\n      - platform: mac\n"
            "        status: supported\n        provider: P\n        bridge_boundary: agents/mac\n",
            "declares unknown interface\\(s\\) \\['echoo'\\]",
        ),
        (
            "sdk: mock_echo\nrules:\n  - interfaces: [echo]\n    functions: [echoo]\n    mappings:\n"
            "      - platform: mac\n        status: supported\n        provider: P\n        bridge_boundary: agents/mac\n",
            "declares unknown function\\(s\\) \\['echoo'\\]",
        ),
    ],
)
def test_REGISTRY_07D_rejects_malformed_providers_declaration(tmp_path, declaration, message):
    source = tmp_path / "mock_echo"
    shutil.copytree(REPO_ROOT / "sdk_adapters" / "mock_echo", source)
    (source / "providers.yaml").write_text(declaration, encoding="utf-8")

    with pytest.raises(ValueError, match=f"({message}|source schema providers)"):
        compile_registry_source(source)


def test_REGISTRY_07H_declared_names_must_exist_in_compiled_mappings(tmp_path):
    source = tmp_path / "mock_complex_sdk"
    shutil.copytree(REPO_ROOT / "sdk_adapters" / "mock_complex_sdk", source)
    (source / "providers.yaml").write_text(
        """
sdk: mock_complex_sdk
rules:
  - interfaces: [session]
    functions: [describeValue]
    mappings:
      - platform: mac_mock_agent
        status: supported
        provider: MockAgentHarness
        bridge_boundary: scripts/validation/run_e2e_mock_tests.py
""",
        encoding="utf-8",
    )

    artifact = compile_registry_source(source)

    assert _contract_for(artifact, "describeValue")["provider_mappings"][0]["provider"] == "MockAgentHarness"
    assert _contract_for(artifact, "applyValue")["provider_mappings"] == _MAC_UNSUPPORTED_FALLBACK


def test_REGISTRY_07E_provider_rules_match_in_declaration_order(tmp_path):
    source = tmp_path / "ordered_sdk"
    source.mkdir()
    (source / "capabilities.yaml").write_text(
        "sdk: ordered_sdk\ncapabilities:\n  - id: session\n    name: Session\n",
        encoding="utf-8",
    )
    (source / "mappings.yaml").write_text(
        """
sdk: ordered_sdk
mappings:
  - capability: session
    calls:
      - sdk: ordered_sdk
        interface: session
        class_name: Ordered
        function: one
      - sdk: ordered_sdk
        interface: session
        class_name: Ordered
        function: two
""",
        encoding="utf-8",
    )
    (source / "evidence.yaml").write_text("sdk: ordered_sdk\nevidence: []\n", encoding="utf-8")
    (source / "providers.yaml").write_text(
        """
sdk: ordered_sdk
rules:
  - interfaces: [session]
    functions: [one]
    mappings:
      - platform: first_rule
        status: supported
        provider: FirstProvider
        bridge_boundary: server/tests
  - interfaces: [session]
    mappings:
      - platform: second_rule
        status: supported
        provider: SecondProvider
        bridge_boundary: server/tests
""",
        encoding="utf-8",
    )

    artifact = compile_registry_source(source)

    assert _contract_for(artifact, "one")["provider_mappings"][0]["provider"] == "FirstProvider"
    assert _contract_for(artifact, "two")["provider_mappings"][0]["provider"] == "SecondProvider"


# 声明化后，哪些 target 要求 mac handler 完全由 providers.yaml 决定：
# 若声明被误改为 unsupported，约束会静默消失而不是报错，因此逐 SDK 冻结该清单。
_MAC_HANDLER_REQUIRED_TARGETS = {
    "agora": [
        "bindLocalVideo",
        "bindRemoteVideo",
        "captureSnapshot",
        "enableLocalAudio",
        "getConnectionState",
        "isJoined",
        "isPreviewing",
        "joinChannel",
        "leaveChannel",
        "loadSDK",
        "openMediaPlayer",
        "pauseMediaPlayer",
        "playMediaPlayer",
        "releaseView",
        "renewToken",
        "resumeMediaPlayer",
        "setDualStreamMode",
        "setRemoteVideoStream",
        "startPreview",
        "startSyntheticVideo",
        "stopMediaPlayer",
        "stopPreview",
        "stopSyntheticVideo",
        "unloadSDK",
    ],
    "beacon_system": [
        "applyImpairment",
        "focus",
        "getConditionState",
        "hide",
        "rearrange",
        "resetImpairment",
        "show",
        "waitInMs",
    ],
    "mock_complex_sdk": [],
    "mock_echo": [],
}


def test_REGISTRY_07F_mac_handler_required_targets_stay_frozen_after_declaration_migration():
    for adapter, expected in _MAC_HANDLER_REQUIRED_TARGETS.items():
        artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / adapter)

        required = sorted(
            row["target"]["function"]
            for row in artifact["contract_matrix"]
            if row["kind"] in {"call", "state"} and _requires_mac_handler(row["provider_mappings"])
        )

        assert required == expected, adapter


def test_REGISTRY_07G_declared_mac_supported_row_without_handler_still_fails_consistency():
    from app.common.target_consistency import check_target_consistency

    artifact = compile_registry_source(REPO_ROOT / "sdk_adapters" / "agora")
    row = _contract_for(artifact, "joinChannel")
    assert _requires_mac_handler(row["provider_mappings"])

    issues = check_target_consistency(
        registry_rows=[row],
        emitted_targets=[row["target"]],
        provider_handler_targets=[],
        platform="mac",
    )

    assert [issue.code for issue in issues] == ["missing_handler"]


def _requires_mac_handler(provider_mappings):
    return any(
        mapping["platform"] == "mac" and mapping["status"] == "supported" and mapping["provider"]
        for mapping in provider_mappings
    )
