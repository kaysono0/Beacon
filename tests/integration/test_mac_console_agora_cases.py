import asyncio
import json
import os
import socket
import sys
import struct
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.support.native_case_catalog import load_cases  # noqa: E402
from scripts.support.generate_report import build_report  # noqa: E402
import scripts.dev.run_mac_console_agora_local_server as local_console_server  # noqa: E402
import scripts.validation.run_mac_console_agora_validation as agora_validation  # noqa: E402
from scripts.validation.run_mac_console_agora_validation import (  # noqa: E402
    AUTORUN_CLEANUP_CASE_ID,
    AUTORUN_ROUNDS_ENV,
    PEER_B_NODE_ID,
    PEER_NODE_ID,
    PRIMARY_NODE_ID,
    agent_node_id_for_role,
    agent_tags_for_role,
    agent_ws_url,
    assert_required_evidence_coverage,
    autorun_round_count,
    build_catalog_coverage,
    build_cleanup_run_summary,
    build_evidence_coverage,
    build_failed_case_evidence_summary,
    build_failure_log_contract_coverage,
    build_gate_report,
    build_reference_validation_matrix,
    build_png_pixel_diagnostics,
    build_peer_isolation_diagnostics,
    build_repeated_join_leave_resilience,
    build_simulcast_layer_diagnostics,
    build_small_room_diagnostics,
    build_visual_call_diagnostics,
    build_visual_evidence_scenarios,
    build_one_to_one_visual_evidence,
    configure_case_token_map,
    expected_autorun_cases,
    required_agent_roles,
    stop_console_app,
    verify_server_reports,
)
from scripts.support.visual_evidence import (  # noqa: E402
    SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
    SCENARIO_SMALL_ROOM,
    VERDICT_NOT_EXERCISED,
    VERDICT_PASSED,
    assert_scenario_has_no_picture_evidence,
    build_not_exercised_scenario,
    build_scenario_visual_evidence,
    png_pixel_diagnostics,
    summarize_visual_evidence,
)


AUTH = {"Authorization": "Bearer local-test-token"}
AGORA_CASE_IDS = {
    "TC-MAC-AGORA-REAL-LIFECYCLE",
    "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
    "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE",
}
AGORA_FAILURE_CASE_ID = "TC-MAC-AGORA-INVALID-TOKEN-FAILURE"
AGORA_ONERROR_DIAGNOSTIC_CASE_ID = "TC-MAC-AGORA-INVALID-TOKEN-ONERROR-DIAGNOSTIC"
AGORA_INVALID_TOKEN_RECOVERY_CASE_ID = "TC-MAC-AGORA-INVALID-TOKEN-THEN-RECOVER"


def test_IT_MAC_CONSOLE_AGORA_autorun_wait_covers_full_visual_suite(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_wait(process, report_path, timeout_seconds):
        captured.update(process=process, report_path=report_path, timeout_seconds=timeout_seconds)
        return {"status": "passed"}

    monkeypatch.setattr(agora_validation, "wait_for_autorun_report", fake_wait)

    result = asyncio.run(agora_validation.wait_autorun_report(object()))

    assert result == {"status": "passed"}
    assert captured["timeout_seconds"] == agora_validation.AUTORUN_TIMEOUT_SECONDS
    assert agora_validation.AUTORUN_TIMEOUT_SECONDS >= 300
AGORA_TOKEN_RENEWAL_RECOVERY_CASE_ID = "TC-MAC-AGORA-TOKEN-RENEWAL-RECOVERY"
AGORA_PERMISSION_DENIED_JOIN_FAILURE_CASE_ID = "TC-MAC-AGORA-PERMISSION-DENIED-JOIN-FAILURE"
AGORA_PERMISSION_DENIED_PREVIEW_FAILURE_CASE_ID = "TC-MAC-AGORA-PERMISSION-DENIED-PREVIEW-FAILURE"
AGORA_JOIN_CALLBACK_TIMEOUT_CASE_ID = "TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT"
AGORA_L1_CASE_ID = "TC-MAC-AGORA-JOIN-CALLBACK-SUCCESS"
AGORA_L1_CONNECTION_CASE_ID = "TC-MAC-AGORA-CONNECTION-STATE-TRANSITION"
AGORA_L1_LEAVE_CLEANUP_CASE_ID = "TC-MAC-AGORA-SUCCESS-THEN-LEAVE-CLEANUP"
AGORA_L1_CONNECTION_SEQUENCE_CASE_ID = "TC-MAC-AGORA-CONNECTION-STATE-SEQUENCE"
AGORA_L1_RUNTIME_CLEANUP_BASELINE_CASE_ID = "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE"
AGORA_L2_PREVIEW_CONTROL_CASE_ID = "TC-MAC-AGORA-PREVIEW-CONTROL"
AGORA_L2_PREVIEW_LIFECYCLE_AROUND_JOIN_CASE_ID = "TC-MAC-AGORA-PREVIEW-LIFECYCLE-AROUND-JOIN"
AGORA_L2_RTC_STATS_OBSERVABLE_CASE_ID = "TC-MAC-AGORA-RTC-STATS-OBSERVABLE"
AGORA_L2_LOCAL_VIDEO_STATS_OBSERVABLE_CASE_ID = "TC-MAC-AGORA-LOCAL-VIDEO-STATS-OBSERVABLE"
AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID = "TC-MAC-AGORA-REMOTE-AUDIO-STATS-OBSERVABLE"
AGORA_L2_REMOTE_VIDEO_STATS_OBSERVABLE_CASE_ID = "TC-MAC-AGORA-REMOTE-VIDEO-STATS-OBSERVABLE"
AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID = "TC-MAC-AGORA-1V1-REMOTE-VIDEO-RENDERED"
AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID = "TC-MAC-AGORA-1V1-REMOTE-VIDEO-SYNTH-PEER"
AGORA_SMALL_ROOM_BASELINE_CASE_ID = "TC-MAC-AGORA-SMALL-ROOM-BASELINE"
AGORA_AUDIO_ONLY_DIRECT_CALL_CASE_ID = "TC-MAC-AGORA-AUDIO-ONLY-DIRECT-CALL"
AGORA_AUDIO_MUTE_RECOVER_CASE_ID = "TC-MAC-AGORA-1V1-AUDIO-MUTE-RECOVER"
AGORA_AUDIO_PLAYBACK_MUTE_RECOVER_CASE_ID = "TC-MAC-AGORA-1V1-AUDIO-PLAYBACK-MUTE-RECOVER"
AGORA_MEDIA_PLAYER_PAUSE_RESUME_CASE_ID = "TC-MAC-AGORA-1V1-MEDIA-PLAYER-PAUSE-RESUME"
AGORA_4_GRID_MEDIA_CASE_ID = "TC-MAC-AGORA-4-GRID-CAMERA-MEDIA-SEGMENTS"
AGORA_9_GRID_MEDIA_CASE_ID = "TC-MAC-AGORA-9-GRID-CAMERA-MEDIA-SEGMENTS"
AGORA_WEAK_NETWORK_RECOVERY_CASE_ID = "TC-MAC-AGORA-WEAK-NETWORK-RECOVERY"
VISUAL_ARTIFACT_KEYS = ("primary_local_preview", "primary_remote_view", "peer_local_preview", "peer_remote_view")


def test_IT_MAC_CONSOLE_LOCAL_SERVER_rejects_an_occupied_port_before_startup():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        occupied_port = listener.getsockname()[1]

        with pytest.raises(RuntimeError, match=f"port {occupied_port} is already in use"):
            local_console_server.ensure_port_available("127.0.0.1", occupied_port)


def test_IT_MAC_CONSOLE_LOCAL_SERVER_main_rejects_an_occupied_port_before_server_creation(monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        occupied_port = listener.getsockname()[1]
        monkeypatch.setattr(local_console_server, "PORT", occupied_port)

        def unexpected_server_config(*_args, **_kwargs):
            raise AssertionError("uvicorn must not be configured when the port is occupied")

        monkeypatch.setattr(local_console_server.uvicorn, "Config", unexpected_server_config)

        with pytest.raises(RuntimeError, match=f"port {occupied_port} is already in use"):
            local_console_server.main()


@pytest.mark.anyio
async def test_IT_MAC_CONSOLE_LOCAL_SERVER_rejects_a_server_thread_that_did_not_start():
    class FailedServer:
        started = False

    class DeadThread:
        @staticmethod
        def is_alive() -> bool:
            return False

    with pytest.raises(RuntimeError, match="server process stopped before startup completed"):
        await local_console_server.wait_for_owned_server(FailedServer(), DeadThread())


@pytest.mark.anyio
async def test_IT_MAC_CONSOLE_LOCAL_SERVER_does_not_start_agents_when_owned_server_fails(monkeypatch):
    class FailedServer:
        started = False

    class DeadThread:
        @staticmethod
        def is_alive() -> bool:
            return False

    agent_start_attempted = False

    async def unexpected_agent_start(*_args, **_kwargs):
        nonlocal agent_start_attempted
        agent_start_attempted = True
        raise AssertionError("agents must not start before the owned server is ready")

    monkeypatch.setattr(local_console_server, "start_console_agents", unexpected_agent_start)

    with pytest.raises(RuntimeError, match="server process stopped before startup completed"):
        await local_console_server.serve_until_stopped(
            "http://127.0.0.1:8000",
            "ws://127.0.0.1:8000",
            local_console_server.threading.Event(),
            FailedServer(),
            DeadThread(),
        )

    assert agent_start_attempted is False


@pytest.mark.anyio
async def test_IT_MAC_CONSOLE_LOCAL_SERVER_stops_started_agents_when_later_start_fails(monkeypatch):
    first_process = object()
    stopped: list[object] = []
    starts = 0

    async def fake_start(*_args, **_kwargs):
        nonlocal starts
        starts += 1
        if starts == 2:
            raise RuntimeError("peer failed to start")
        return first_process

    async def fake_stop(process):
        stopped.append(process)

    monkeypatch.setattr(local_console_server, "configure_rtc_token", lambda: None)
    monkeypatch.setattr(local_console_server, "configure_console_case_token_map", lambda: None)
    monkeypatch.setattr(local_console_server, "run", lambda _command: None)
    monkeypatch.setattr(local_console_server, "start_native_websocket_agent", fake_start)
    monkeypatch.setattr(local_console_server, "stop_native_websocket_agent", fake_stop)

    with pytest.raises(RuntimeError, match="peer failed to start"):
        await local_console_server.start_real_agents("http://127.0.0.1:8000", "ws://127.0.0.1:8000")

    assert stopped == [first_process]


@pytest.mark.anyio
async def test_IT_MAC_CONSOLE_LOCAL_SERVER_stops_started_mock_when_later_start_fails(monkeypatch):
    first_agent = object()
    stopped: list[list[object]] = []
    starts = 0

    async def fake_start(*_args, **_kwargs):
        nonlocal starts
        starts += 1
        if starts == 2:
            raise RuntimeError("second mock failed to start")
        return first_agent

    async def fake_stop(agents):
        stopped.append(list(agents))

    monkeypatch.setattr(local_console_server, "start_agent", fake_start)
    monkeypatch.setattr(local_console_server, "stop_mock_agents", fake_stop)

    with pytest.raises(RuntimeError, match="second mock failed to start"):
        await local_console_server.start_mock_agents("ws://127.0.0.1:8000")

    assert stopped == [[first_agent]]


def _write_rgba_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int, int]]) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = []
    for y in range(height):
        start = y * width
        row = b"".join(bytes(pixel) for pixel in pixels[start : start + width])
        rows.append(b"\x00" + row)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _visual_view_declarations() -> tuple[dict, ...]:
    """1V1 场景的四个必需视图声明，与 console agora gate 的声明形状保持一致。"""
    return (
        {
            "view_role": "primary_local_preview",
            "node_id": PRIMARY_NODE_ID,
            "node_role": "primary",
            "uid": 1001,
            "kind": "local",
            "sdk": "agora_rtc",
        },
        {
            "view_role": "primary_remote_view",
            "node_id": PRIMARY_NODE_ID,
            "node_role": "primary",
            "uid": 1002,
            "kind": "remote",
            "sdk": "agora_rtc",
        },
        {
            "view_role": "peer_local_preview",
            "node_id": PEER_NODE_ID,
            "node_role": "peer",
            "uid": 1002,
            "kind": "local",
            "sdk": "agora_rtc",
        },
        {
            "view_role": "peer_remote_view",
            "node_id": PEER_NODE_ID,
            "node_role": "peer",
            "uid": 1001,
            "kind": "remote",
            "sdk": "agora_rtc",
        },
    )


def _judge_visual_evidence(evidence: list[dict]) -> dict:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                    "status": "passed",
                    "observations": evidence,
                }
            ]
        }
    ]
    return build_scenario_visual_evidence(
        scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
        case_ids=(AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,),
        views=_visual_view_declarations(),
        reports=reports,
    )


def _complete_view_evidence(artifacts: dict[str, Path]) -> list[dict]:
    """四个视图的完整 L1 证据：落盘契约两段（请求 + 回调）、绑定、首帧与收发活性。"""
    return _bidirectional_visual_evidence(artifacts, "onSnapshotRequested") + _bidirectional_visual_evidence(
        artifacts, "onSnapshotTaken"
    )


def _patch_evidence(
    evidence: list[dict],
    *,
    function: str,
    node_id: str | None = None,
    view_role: str | None = None,
    **updates: object,
) -> list[dict]:
    matched = 0
    for item in evidence:
        if item["target"]["function"] != function:
            continue
        if node_id is not None and item["node_id"] != node_id:
            continue
        if view_role is not None and item["payload"].get("artifact_key") != view_role:
            continue
        item["payload"].update(updates)
        matched += 1
    assert matched, f"no evidence matched {function} node_id={node_id} view_role={view_role}"
    return evidence


def _drop_evidence(evidence: list[dict], function: str, node_id: str) -> list[dict]:
    return [
        item
        for item in evidence
        if not (item["target"]["function"] == function and item["node_id"] == node_id)
    ]


def _bidirectional_visual_evidence(artifacts: dict[str, Path], snapshot_function: str) -> list[dict]:
    snapshot_payload_extra = {
        "onSnapshotTaken": {
            "primary_local_preview": {"uid": 0, "width": 1, "height": 1, "err_code": 0},
            "primary_remote_view": {"uid": 1002, "width": 1, "height": 1, "err_code": 0},
            "peer_local_preview": {"uid": 0, "width": 1, "height": 1, "err_code": 0},
            "peer_remote_view": {"uid": 1001, "width": 1, "height": 1, "err_code": 0},
        },
        "onSnapshotRequested": {
            "primary_local_preview": {"uid": 0, "return_code": 0},
            "primary_remote_view": {"uid": 1002, "return_code": 0},
            "peer_local_preview": {"uid": 0, "return_code": 0},
            "peer_remote_view": {"uid": 1001, "return_code": 0},
        },
    }[snapshot_function]
    evidence = [
        {
            "node_id": PRIMARY_NODE_ID,
            "target": {"function": "bindRemoteVideo"},
            "payload": {"uid": 1002, "view_id": "primary_remote_view", "configured": True},
        },
        {
            "node_id": PEER_NODE_ID,
            "target": {"function": "bindRemoteVideo"},
            "payload": {"uid": 1001, "view_id": "peer_remote_view", "configured": True},
        },
        {
            "node_id": PRIMARY_NODE_ID,
            "target": {"function": "onFirstRemoteVideoFrame"},
            "payload": {"uid": 1002, "width": 640, "height": 360},
        },
        {
            "node_id": PEER_NODE_ID,
            "target": {"function": "onFirstRemoteVideoFrame"},
            "payload": {"uid": 1001, "width": 640, "height": 360},
        },
        {
            "node_id": PRIMARY_NODE_ID,
            "target": {"function": "onLocalVideoStats"},
            "payload": {"uid": 1001, "sent_bitrate": 640, "sent_frame_rate": 15, "source_type": 0},
        },
        {
            "node_id": PEER_NODE_ID,
            "target": {"function": "onLocalVideoStats"},
            "payload": {"uid": 1002, "sent_bitrate": 640, "sent_frame_rate": 15, "source_type": 0},
        },
        {
            "node_id": PRIMARY_NODE_ID,
            "target": {"function": "onRemoteVideoStats"},
            "payload": {
                "uid": 1002,
                "received_bitrate": 512,
                "decoder_output_frame_rate": 15,
                "renderer_output_frame_rate": 15,
            },
        },
        {
            "node_id": PEER_NODE_ID,
            "target": {"function": "onRemoteVideoStats"},
            "payload": {
                "uid": 1001,
                "received_bitrate": 512,
                "decoder_output_frame_rate": 15,
                "renderer_output_frame_rate": 15,
            },
        },
        {
            "node_id": PRIMARY_NODE_ID,
            "target": {"function": "onRtcStats"},
            "payload": {"rx_video_kbitrate": 686, "tx_video_kbitrate": 640},
        },
        {
            "node_id": PEER_NODE_ID,
            "target": {"function": "onRtcStats"},
            "payload": {"rx_video_kbitrate": 686, "tx_video_kbitrate": 640},
        },
    ]
    for key, path in artifacts.items():
        node_id = PRIMARY_NODE_ID if key.startswith("primary_") else PEER_NODE_ID
        payload = {
            "artifact_key": key,
            "file_path": str(path),
            **snapshot_payload_extra[key],
        }
        evidence.append({"node_id": node_id, "target": {"function": snapshot_function}, "payload": payload})
    return evidence










def test_IT_MAC_CONSOLE_AGORA_04_agent_ws_url_encodes_token_query() -> None:
    token = "abc+def&x=y#fragment"

    url = agent_ws_url("ws://127.0.0.1:9000", token)

    parsed = urlparse(url)
    assert parsed.path == "/api/v1/agent/ws"
    assert parse_qs(parsed.query)["token"] == [token]


def test_IT_MAC_CONSOLE_AGORA_04a_real_harness_has_no_python_protocol_relay() -> None:
    source = (ROOT / "scripts/validation/run_mac_agora_e2e_tests.py").read_text(encoding="utf-8")

    assert "class RealAgentBridge" not in source
    assert "stdin=asyncio.subprocess.PIPE" not in source


def test_IT_MAC_CONSOLE_AGORA_04a_direct_agent_is_not_hidden_behind_a_mode_switch() -> None:
    scripts = (
        "run_mac_agora_e2e_tests.py",
        "run_mac_console_agora_validation.py",
        "run_mac_direct_agent_mock.py",
        "run_mac_direct_agent_agora_real.py",
    )

    for script in scripts:
        source = (ROOT / "scripts/validation" / script).read_text(encoding="utf-8")
        assert "BEACON_DIRECT_AGENT_MODE" not in source, script


def test_IT_MAC_CONSOLE_AGORA_04a_console_gate_launches_native_direct_agents() -> None:
    source = (ROOT / "scripts/validation/run_mac_console_agora_validation.py").read_text(encoding="utf-8")

    assert "start_native_websocket_agent" in source
    assert "RealAgentBridge" not in source
    assert "websockets.connect" not in source


def test_IT_MAC_CONSOLE_AGORA_04a_console_gate_reaps_each_autorun_process() -> None:
    source = (ROOT / "scripts/validation/run_mac_console_agora_validation.py").read_text(encoding="utf-8")

    assert "async def stop_console_app(" in source
    assert "run_shared_autorun_round(" in source
    assert "stop_console=stop_console_app" in source


def test_IT_MAC_CONSOLE_AGORA_04a_stop_console_app_terminates_waits_and_closes_pipes() -> None:
    class Stream:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class Process:
        def __init__(self) -> None:
            self.returncode = None
            self.terminated = False
            self.waited = False
            self.stdout = Stream()
            self.stderr = Stream()

        def poll(self):
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            self.returncode = 0
            return 0

    process = Process()
    asyncio.run(stop_console_app(process))

    assert process.terminated is True
    assert process.waited is True
    assert process.stdout.closed is True
    assert process.stderr.closed is True


def test_IT_MAC_CONSOLE_AGORA_04a_mac_agent_runtime_is_split_by_responsibility() -> None:
    expected = {
        "mac_real_agent_transport.mm",
        "mac_real_agent_packet_handler.mm",
        "mac_real_agent_loopback_helper.mm",
        "mac_real_agent_bridge.mm",
    }

    assert expected <= {path.name for path in (ROOT / "agents/mac/demo").glob("mac_real_agent_*.mm")}


def test_IT_MAC_CONSOLE_AGORA_04b_validation_gate_report_splits_core_enhanced_and_resilience(monkeypatch):
    monkeypatch.chdir(ROOT)

    cases = [case for case in load_cases() if case["platform"] == "mac"]
    reports = [
        {"case_results": [{"case_id": "TC-MAC-AGORA-REAL-LIFECYCLE", "status": "passed"}]},
        {"case_results": [{"case_id": "TC-MAC-AGORA-REAL-JOIN-CALLBACK", "status": "passed"}]},
        {"case_results": [{"case_id": "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE", "status": "passed"}]},
    ]

    gate_report = build_gate_report(cases, reports)

    assert gate_report["core_gate"]["status"] == "passed"
    assert gate_report["core_gate"]["executed_cases"] == sorted(AGORA_CASE_IDS)
    assert AGORA_L2_PREVIEW_CONTROL_CASE_ID in gate_report["enhanced_gate"]["catalog_runnable_cases"]
    assert AGORA_L2_LOCAL_VIDEO_STATS_OBSERVABLE_CASE_ID in gate_report["enhanced_gate"]["catalog_runnable_cases"]
    assert AGORA_SMALL_ROOM_BASELINE_CASE_ID in gate_report["enhanced_gate"]["catalog_runnable_cases"]
    assert AGORA_SMALL_ROOM_BASELINE_CASE_ID not in gate_report["enhanced_gate"]["catalog_blocked_cases"]
    assert AGORA_FAILURE_CASE_ID in gate_report["resilience_gate"]["catalog_runnable_cases"]


def test_IT_MAC_CONSOLE_AGORA_04c_expected_autorun_cases_include_all_runnable_layers(monkeypatch):
    monkeypatch.chdir(ROOT)

    case_ids = expected_autorun_cases([case for case in load_cases() if case["platform"] == "mac"])

    assert AGORA_CASE_IDS.issubset(case_ids)
    assert AGORA_L2_PREVIEW_CONTROL_CASE_ID in case_ids
    assert AGORA_L2_RTC_STATS_OBSERVABLE_CASE_ID in case_ids
    assert AGORA_L2_LOCAL_VIDEO_STATS_OBSERVABLE_CASE_ID in case_ids
    assert AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID in case_ids
    assert AGORA_L2_REMOTE_VIDEO_STATS_OBSERVABLE_CASE_ID in case_ids
    assert AGORA_FAILURE_CASE_ID in case_ids
    assert AGORA_PERMISSION_DENIED_PREVIEW_FAILURE_CASE_ID in case_ids
    assert AGORA_L1_CONNECTION_SEQUENCE_CASE_ID in case_ids
    assert AGORA_L1_RUNTIME_CLEANUP_BASELINE_CASE_ID in case_ids
    assert AGORA_L2_PREVIEW_LIFECYCLE_AROUND_JOIN_CASE_ID in case_ids
    assert AGORA_TOKEN_RENEWAL_RECOVERY_CASE_ID in case_ids
    assert AGORA_SMALL_ROOM_BASELINE_CASE_ID in case_ids
    assert AGORA_AUDIO_ONLY_DIRECT_CALL_CASE_ID in case_ids
    assert AGORA_AUDIO_PLAYBACK_MUTE_RECOVER_CASE_ID in case_ids


def test_IT_MAC_CONSOLE_AGORA_04d_native_server_gets_case_specific_token_map(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr("scripts.validation.run_mac_console_agora_validation.build_rtc_token", lambda channel, uid: f"token:{channel}:{uid}")

    token_map = configure_case_token_map()

    assert token_map["real-smoke-1v1-visual#1001"] == "token:real-smoke-1v1-visual:1001"
    assert token_map["real-smoke-1v1-visual#1002"] == "token:real-smoke-1v1-visual:1002"
    assert token_map["small-room-baseline#1101"] == "token:small-room-baseline:1101"
    assert token_map["small-room-baseline#1102"] == "token:small-room-baseline:1102"
    assert token_map["small-room-baseline#1103"] == "token:small-room-baseline:1103"
    assert token_map["token-renewal-recovery-smoke#1007"] == "token:token-renewal-recovery-smoke:1007"
    assert "real-smoke-runtime-baseline#1001" not in token_map
    assert json.loads(os.environ["BEACON_AGORA_RTC_TOKEN_MAP"]) == token_map


def test_IT_MAC_CONSOLE_AGORA_04d_subset_gate_clears_token_map_when_cleanup_needs_no_token(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("BEACON_AGORA_RTC_TOKEN_MAP", '{"stale":"token"}')
    monkeypatch.setattr("scripts.validation.run_mac_console_agora_validation.EXPECTED_CASES", {AGORA_FAILURE_CASE_ID})
    monkeypatch.setattr("scripts.validation.run_mac_console_agora_validation.build_rtc_token", lambda channel, uid: f"token:{channel}:{uid}")

    token_map = configure_case_token_map()

    assert token_map == {}
    assert "BEACON_AGORA_RTC_TOKEN_MAP" not in os.environ
    assert AUTORUN_CLEANUP_CASE_ID == AGORA_L1_RUNTIME_CLEANUP_BASELINE_CASE_ID


def test_IT_MAC_CONSOLE_AGORA_04d_autorun_round_count_defaults_to_repeated_gate(monkeypatch):
    monkeypatch.delenv(AUTORUN_ROUNDS_ENV, raising=False)

    assert autorun_round_count() == 2


def test_IT_MAC_CONSOLE_AGORA_04d_autorun_round_count_accepts_focused_subset_override(monkeypatch):
    monkeypatch.setenv(AUTORUN_ROUNDS_ENV, "1")

    assert autorun_round_count() == 1


def test_IT_MAC_CONSOLE_AGORA_04d_autorun_round_count_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv(AUTORUN_ROUNDS_ENV, "0")

    try:
        autorun_round_count()
    except ValueError as exc:
        assert AUTORUN_ROUNDS_ENV in str(exc)
    else:
        raise AssertionError("invalid autorun round count should fail")




def test_IT_MAC_CONSOLE_AGORA_04d_make_report_absorbs_validation_gate_and_coverage(tmp_path):
    latest = tmp_path / "reports" / "latest"
    latest.mkdir(parents=True)
    (latest / "mac_console_agora.json").write_text(
        json.dumps(
            {
                "summary": {
                    "core_gate_status": "passed",
                    "enhanced_gate_status": "not_run",
                    "resilience_gate_status": "not_run",
                },
                "capability_coverage": {"total": 4, "covered": 2, "percent": 50},
                "scenario_coverage": {
                    "families": {
                        "direct_call": {
                            "total": 2,
                            "runnable": 1,
                            "runnable_or_partial": 0,
                            "designed_but_blocked": 1,
                        }
                    }
                },
                "blocked_scenarios": [{"case_id": AGORA_SMALL_ROOM_BASELINE_CASE_ID}],
                "blocked_scenario_summary": {
                    "total": 1,
                    "by_owner_layer": {
                        "validation_harness": {"count": 1, "case_ids": [AGORA_SMALL_ROOM_BASELINE_CASE_ID]}
                    },
                    "by_blocked_category": {
                        "missing_multi_node_orchestration": {
                            "count": 1,
                            "case_ids": [AGORA_SMALL_ROOM_BASELINE_CASE_ID],
                        }
                    },
                },
                "evidence_coverage": {
                    "status": "passed",
                    "total_required_functions": 2,
                    "observed_required_functions": 2,
                    "missing": {},
                    "by_case": {},
                },
                "repeated_join_leave_resilience": {
                    "status": "passed",
                    "rounds": 2,
                    "reports_verified": 6,
                    "cleanup_runs": [],
                },
                "core_gate": {"status": "passed", "executed_cases": sorted(AGORA_CASE_IDS)},
                "enhanced_gate": {"status": "not_run", "executed_cases": []},
                "resilience_gate": {"status": "not_run", "executed_cases": []},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = build_report("passed", "P1-REPORT", "generate-report", latest)

    assert report["summary"]["core_gate_status"] == "passed"
    assert report["summary"]["enhanced_gate_status"] == "not_run"
    assert report["summary"]["resilience_gate_status"] == "not_run"
    assert report["capability_coverage"] == {"total": 4, "covered": 2, "percent": 50}
    assert report["scenario_coverage"]["families"]["direct_call"]["runnable_or_partial"] == 0
    assert report["scenario_coverage"]["families"]["direct_call"]["designed_but_blocked"] == 1
    assert report["blocked_scenarios"] == [{"case_id": AGORA_SMALL_ROOM_BASELINE_CASE_ID}]
    assert report["blocked_scenario_summary"]["by_owner_layer"]["validation_harness"]["case_ids"] == [
        AGORA_SMALL_ROOM_BASELINE_CASE_ID
    ]
    assert report["evidence_coverage"]["status"] == "passed"
    assert report["repeated_join_leave_resilience"]["rounds"] == 2
    assert report["core_gate"]["executed_cases"] == sorted(AGORA_CASE_IDS)


def test_IT_MAC_CONSOLE_AGORA_04d_catalog_coverage_reports_blocked_scenarios_and_capabilities(monkeypatch):
    monkeypatch.chdir(ROOT)

    cases = [case for case in load_cases() if case["platform"] == "mac"]
    reports = [
        {"case_results": [{"case_id": AGORA_L1_CASE_ID, "status": "passed"}]},
        {"case_results": [{"case_id": AGORA_FAILURE_CASE_ID, "status": "failed"}]},
    ]

    coverage = build_catalog_coverage(cases, reports)

    assert coverage["scenario_coverage"]["families"]["direct_call"]["runnable"] >= 1
    assert coverage["scenario_coverage"]["families"]["small_room"]["runnable"] == 1
    assert coverage["scenario_coverage"]["families"]["small_room"]["designed_but_blocked"] == 0
    assert AGORA_SMALL_ROOM_BASELINE_CASE_ID not in {item["case_id"] for item in coverage["blocked_scenarios"]}
    blocked = {item["case_id"]: item for item in coverage["blocked_scenarios"]}
    assert AGORA_WEAK_NETWORK_RECOVERY_CASE_ID not in blocked
    assert AGORA_AUDIO_ONLY_DIRECT_CALL_CASE_ID not in blocked
    assert coverage["capability_coverage"]["total"] >= 1
    assert "join_success_fact" in coverage["capability_coverage"]["covered_capabilities"]
    assert "invalid_token_failure" not in coverage["capability_coverage"]["covered_capabilities"]


def test_IT_MAC_CONSOLE_AGORA_04d_reference_matrix_uses_generic_capabilities_without_promoting_partial_recovery(monkeypatch):
    monkeypatch.chdir(ROOT)

    cases = [case for case in load_cases() if case["platform"] == "mac"]
    reports = [
        {
            "case_results": [
                {"case_id": case["case_id"], "status": "passed"}
                for case in cases
                if case.get("implementation_status") == "runnable"
            ]
        }
    ]

    matrix = build_reference_validation_matrix(
        cases,
        reports,
        evidence_coverage={"status": "passed", "missing": {}, "by_case": {}},
        visual_diagnostics={"artifact_proof_passed": True},
        visual_evidence_scenarios={
            "scenarios": {
                SCENARIO_ONE_TO_ONE_MEDIA_QUALITY: {
                    "status": VERDICT_PASSED,
                    "case_ids": [AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID],
                    "missing_views": [],
                    "fail_reasons": {},
                },
                SCENARIO_SMALL_ROOM: {"status": VERDICT_NOT_EXERCISED},
            }
        },
        small_room_diagnostics={"small_room_proof_passed": True},
        resilience_diagnostics={"status": "passed"},
    )

    assert matrix["status"] == "passed"
    assert matrix["boundary"] == "adapter_reference_validation"
    assert matrix["capabilities"]["call"]["status"] == "passed"
    assert matrix["capabilities"]["callback"]["status"] == "passed"
    assert matrix["capabilities"]["state"]["status"] == "passed"
    assert matrix["capabilities"]["metric"]["status"] == "passed"
    assert matrix["capabilities"]["artifact"]["status"] == "passed"
    assert matrix["capabilities"]["log"]["status"] == "failure_report_contract"
    assert matrix["capabilities"]["log"]["evidence_status"] == "not_exercised"
    assert matrix["capabilities"]["device"]["status"] == "passed"
    assert matrix["capabilities"]["report"]["status"] == "passed"
    assert matrix["scenarios"]["one_to_one_media_quality"]["status"] == "passed"
    assert matrix["scenarios"]["small_room"]["status"] == "passed"
    assert matrix["scenarios"]["weak_network_recovery"]["status"] == "missing"


def test_IT_MAC_CONSOLE_AGORA_04d_failure_log_contract_requires_existing_report_fields() -> None:
    coverage = build_failure_log_contract_coverage(
        [
            {
                "case_results": [
                    {
                        "case_id": "TC-MAC-AGORA-INVALID-TOKEN-FAILURE",
                        "status": "failed",
                        "related_logs": {"warnings_errors": []},
                        "log_artifacts": [],
                        "log_query": {"run_id": "run-log-contract"},
                    }
                ]
            }
        ]
    )

    assert coverage == {
        "evidence_status": "passed",
        "required_fields": ["related_logs", "log_artifacts", "log_query"],
        "validated_case_ids": ["TC-MAC-AGORA-INVALID-TOKEN-FAILURE"],
        "missing_fields": {},
    }


def test_IT_MAC_CONSOLE_AGORA_04d_evidence_coverage_identifies_missing_required_functions() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_L2_REMOTE_VIDEO_STATS_OBSERVABLE_CASE_ID,
                    "status": "passed",
                    "observations": [
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteVideoStats"},
                            "payload": {"uid": 2002},
                        }
                    ],
                },
                {
                    "case_id": AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID,
                    "status": "passed",
                    "observations": [],
                },
            ]
        }
    ]

    coverage = build_evidence_coverage(reports)

    assert coverage["status"] == "failed"
    assert coverage["by_case"][AGORA_L2_REMOTE_VIDEO_STATS_OBSERVABLE_CASE_ID]["missing_functions"] == []
    assert coverage["by_case"][AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID]["missing_functions"] == [
        "onRemoteAudioStats"
    ]


def test_IT_MAC_CONSOLE_AGORA_04d_evidence_coverage_aggregates_step_rows_per_case() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_L1_CASE_ID,
                    "step_id": "join",
                    "status": "passed",
                    "observations": [
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onJoinChannelSuccess"},
                            "payload": {"uid": 1001},
                        }
                    ],
                },
                {
                    "case_id": AGORA_L1_CASE_ID,
                    "step_id": "leave",
                    "status": "passed",
                    "observations": [],
                },
            ]
        }
    ]

    coverage = build_evidence_coverage(reports)

    assert coverage["status"] == "passed"
    assert coverage["by_case"][AGORA_L1_CASE_ID]["observed_functions"] == ["onJoinChannelSuccess"]
    assert coverage["by_case"][AGORA_L1_CASE_ID]["missing_functions"] == []


def test_IT_MAC_CONSOLE_AGORA_04d_visual_evidence_coverage_allows_rtc_stats_without_remote_video_stats() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                    "status": "passed",
                    "observations": [
                        {"target": {"function": "bindRemoteVideo"}, "payload": {}},
                        {"target": {"function": "onFirstRemoteVideoFrame"}, "payload": {}},
                        {"target": {"function": "onLocalVideoStats"}, "payload": {}},
                        {"target": {"function": "onRtcStats"}, "payload": {"rx_video_kbitrate": 1}},
                    ],
                }
            ]
        }
    ]

    coverage = build_evidence_coverage(reports)

    assert coverage["status"] == "passed"
    assert "onRemoteVideoStats" not in coverage["by_case"][AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID][
        "required_functions"
    ]


def test_IT_MAC_CONSOLE_AGORA_04d_required_evidence_coverage_raises_on_missing_function() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID,
                    "status": "passed",
                    "observations": [],
                }
            ]
        }
    ]

    try:
        assert_required_evidence_coverage(reports)
    except AssertionError as exc:
        assert AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID in str(exc)
        assert "onRemoteAudioStats" in str(exc)
    else:
        raise AssertionError("missing evidence coverage should fail the gate")


def test_IT_MAC_CONSOLE_AGORA_04d_repeated_join_leave_resilience_summarizes_rounds_and_cleanup() -> None:
    round_results = [
        {"round": 1, "reports_verified": 3},
        {"round": 2, "reports_verified": 3},
    ]
    cleanup_runs = [
        {"round": 1, "status": "passed", "run_id": "run-cleanup-1", "case_count": 1, "failed_case_ids": []},
        {"round": 2, "status": "passed", "run_id": "run-cleanup-2", "case_count": 1, "failed_case_ids": []},
    ]

    summary = build_repeated_join_leave_resilience(round_results, cleanup_runs)

    assert summary == {
        "status": "passed",
        "rounds": 2,
        "reports_verified": 6,
        "cleanup_runs": cleanup_runs,
        "round_results": [
            {
                "round": 1,
                "status": "passed",
                "autorun_status": "passed",
                "reports_verified": 3,
                "failed_case_ids": [],
                "cleanup_run_id": "run-cleanup-1",
                "cleanup_status": "passed",
                "cleanup_failed_case_ids": [],
                "evidence_gaps": {},
            },
            {
                "round": 2,
                "status": "passed",
                "autorun_status": "passed",
                "reports_verified": 3,
                "failed_case_ids": [],
                "cleanup_run_id": "run-cleanup-2",
                "cleanup_status": "passed",
                "cleanup_failed_case_ids": [],
                "evidence_gaps": {},
            },
        ],
        "failed_rounds": [],
        "evidence_gaps": {},
    }


def test_IT_MAC_CONSOLE_AGORA_04e_repeated_join_leave_resilience_reports_failed_autorun_case() -> None:
    cleanup_runs = [
        {"round": 1, "status": "passed", "run_id": "run-cleanup-1", "case_count": 1, "failed_case_ids": []},
        {"round": 2, "status": "passed", "run_id": "run-cleanup-2", "case_count": 1, "failed_case_ids": []},
    ]

    summary = build_repeated_join_leave_resilience(
        [
            {"round": 1, "status": "passed", "reports_verified": 3},
            {
                "round": 2,
                "status": "failed",
                "reports_verified": 2,
                "failed_case_ids": [AGORA_L1_CASE_ID],
            },
        ],
        cleanup_runs,
    )

    assert summary["status"] == "failed"
    assert summary["failed_rounds"] == [2]
    assert summary["round_results"][1]["autorun_status"] == "failed"
    assert summary["round_results"][1]["failed_case_ids"] == [AGORA_L1_CASE_ID]


def test_IT_MAC_CONSOLE_AGORA_04f_repeated_join_leave_resilience_reports_cleanup_failure() -> None:
    summary = build_repeated_join_leave_resilience(
        [{"round": 1, "status": "passed", "reports_verified": 3}],
        [
            {
                "round": 1,
                "status": "failed",
                "run_id": "run-cleanup-1",
                "case_count": 1,
                "failed_case_ids": ["TC-MAC-AGORA-AUTORUN-CLEANUP"],
            }
        ],
    )

    assert summary["status"] == "failed"
    assert summary["failed_rounds"] == [1]
    assert summary["round_results"][0]["cleanup_run_id"] == "run-cleanup-1"
    assert summary["round_results"][0]["cleanup_failed_case_ids"] == ["TC-MAC-AGORA-AUTORUN-CLEANUP"]


def test_IT_MAC_CONSOLE_AGORA_04g_repeated_join_leave_resilience_reports_evidence_gaps() -> None:
    summary = build_repeated_join_leave_resilience(
        [
            {
                "round": 1,
                "status": "passed",
                "reports_verified": 3,
                "evidence_gaps": {AGORA_L1_CASE_ID: ["onJoinChannelSuccess"]},
            }
        ],
        [{"round": 1, "status": "passed", "run_id": "run-cleanup-1", "case_count": 1, "failed_case_ids": []}],
    )

    assert summary["status"] == "failed"
    assert summary["failed_rounds"] == [1]
    assert summary["evidence_gaps"] == {"1": {AGORA_L1_CASE_ID: ["onJoinChannelSuccess"]}}
    assert summary["round_results"][0]["evidence_gaps"] == {AGORA_L1_CASE_ID: ["onJoinChannelSuccess"]}


def test_IT_MAC_CONSOLE_AGORA_04h_peer_isolation_diagnostics_summarize_remote_stats() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID,
                    "status": "passed",
                    "observations": [
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteAudioStats"},
                            "payload": {"uid": 2002},
                        }
                    ],
                }
            ]
        },
        {
            "case_results": [
                {
                    "case_id": AGORA_L2_REMOTE_VIDEO_STATS_OBSERVABLE_CASE_ID,
                    "status": "passed",
                    "observations": [
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteVideoStats"},
                            "payload": {"uid": 2002},
                        }
                    ],
                }
            ]
        },
    ]

    diagnostics = build_peer_isolation_diagnostics(reports)

    assert diagnostics == {
        "primary_node_id": PRIMARY_NODE_ID,
        "peer_node_id": PEER_NODE_ID,
        "remote_audio_stats_on_primary": True,
        "remote_video_stats_on_primary": True,
        "unexpected_peer_owned_primary_evidence": [],
    }


def test_IT_MAC_CONSOLE_AGORA_04i_cleanup_run_summary_counts_run_response_cases() -> None:
    cleanup = {
        "run_id": "run-cleanup-001",
        "status": "passed",
        "cases": [
            {"case_id": "TC-MAC-AGORA-AUTORUN-CLEANUP", "status": "passed"},
        ],
    }

    summary = build_cleanup_run_summary(2, cleanup)

    assert summary == {
        "round": 2,
        "status": "passed",
        "run_id": "run-cleanup-001",
        "case_count": 1,
        "failed_case_ids": [],
    }


def test_IT_MAC_CONSOLE_AGORA_04j_cleanup_run_summary_ignores_case_summary_without_status() -> None:
    cleanup = {
        "run_id": "run-cleanup-001",
        "status": "passed",
        "cases": [
            {"case_id": "TC-MAC-AGORA-AUTORUN-CLEANUP"},
        ],
    }

    summary = build_cleanup_run_summary(2, cleanup)

    assert summary == {
        "round": 2,
        "status": "passed",
        "run_id": "run-cleanup-001",
        "case_count": 1,
        "failed_case_ids": [],
    }


def test_IT_MAC_CONSOLE_AGORA_04k_cleanup_run_summary_reports_failed_case_ids() -> None:
    cleanup = {
        "run_id": "run-cleanup-001",
        "status": "failed",
        "case_results": [
            {"case_id": "TC-MAC-AGORA-AUTORUN-CLEANUP", "status": "failed"},
            {"case_id": "TC-MAC-AGORA-AUTORUN-CLEANUP", "status": "passed"},
        ],
    }

    summary = build_cleanup_run_summary(2, cleanup)

    assert summary == {
        "round": 2,
        "status": "failed",
        "run_id": "run-cleanup-001",
        "case_count": 2,
        "failed_case_ids": ["TC-MAC-AGORA-AUTORUN-CLEANUP"],
    }


@pytest.mark.anyio
async def test_IT_MAC_CONSOLE_AGORA_04l_verify_server_reports_preserves_autorun_failure_error() -> None:
    autorun = {
        "status": "failed",
        "error": "Autorun cleanup failed: run-cleanup status=failed",
        "cases": [],
    }

    try:
        await verify_server_reports("http://127.0.0.1:1", autorun)
    except AssertionError as exc:
        assert str(exc) == "Autorun cleanup failed: run-cleanup status=failed"
    else:
        raise AssertionError("autorun failure error should stop report verification")








def test_IT_MAC_CONSOLE_AGORA_06b_small_room_diagnostics_require_two_remote_peers() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_SMALL_ROOM_BASELINE_CASE_ID,
                    "status": "passed",
                    "observations": [
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteAudioStats"},
                            "payload": {"uid": 1102, "received_bitrate": 12},
                        },
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteAudioStats"},
                            "payload": {"uid": 1103, "received_bitrate": 10},
                        },
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"rx_audio_kbitrate": 8},
                        },
                        {
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"tx_audio_kbitrate": 9},
                        },
                        {
                            "node_id": PEER_B_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"tx_audio_kbitrate": 11},
                        },
                    ],
                }
            ]
        }
    ]

    diagnostics = build_small_room_diagnostics(reports)

    assert diagnostics == {
        "primary_node_id": PRIMARY_NODE_ID,
        "peer_node_ids": [PEER_NODE_ID, PEER_B_NODE_ID],
        "primary_uid": 1101,
        "peer_uids": [1102, 1103],
        "remote_audio_stats_on_primary_uids": [1102, 1103],
        "peer_audio_transmit_observed_uids": [1102, 1103],
        "primary_rtc_audio_receive_observed": True,
        "small_room_proof_passed": True,
    }


def test_IT_MAC_CONSOLE_AGORA_06b_small_room_diagnostics_accept_aggregate_rx_with_peer_tx() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_SMALL_ROOM_BASELINE_CASE_ID,
                    "status": "passed",
                    "observations": [
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteAudioStats"},
                            "payload": {"uid": 1102, "received_bitrate": 50},
                        },
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"rx_audio_kbitrate": 97},
                        },
                        {
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"tx_audio_kbitrate": 48},
                        },
                        {
                            "node_id": PEER_B_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"tx_audio_kbitrate": 49},
                        },
                    ],
                }
            ]
        }
    ]

    diagnostics = build_small_room_diagnostics(reports)

    assert diagnostics["remote_audio_stats_on_primary_uids"] == [1102]
    assert diagnostics["peer_audio_transmit_observed_uids"] == [1102, 1103]
    assert diagnostics["primary_rtc_audio_receive_observed"] is True
    assert diagnostics["small_room_proof_passed"] is True


def test_IT_MAC_CONSOLE_AGORA_simulcast_layer_diagnostics_requires_observed_stat_changes() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": "TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE",
                    "status": "passed",
                    "observations": [
                        {
                            "kind": "event",
                            "cursor": 1,
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteVideoStats"},
                            "payload": {
                                "uid": 1002,
                                "rx_stream_type": 1,
                                "width": 320,
                                "height": 180,
                                "received_bitrate": 150,
                            },
                        },
                        {
                            "kind": "event",
                            "cursor": 2,
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "onRemoteVideoStats"},
                            "payload": {
                                "uid": 1002,
                                "rx_stream_type": 1,
                                "width": 640,
                                "height": 360,
                                "received_bitrate": 640,
                            },
                        },
                    ],
                },
                {
                    "case_id": "TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE",
                    "status": "passed",
                    "observations": [
                        {
                            "kind": "event",
                            "cursor": 3,
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteVideoStats"},
                            "payload": {
                                "uid": 1002,
                                "rx_stream_type": 0,
                                "width": 640,
                                "height": 360,
                                "received_bitrate": 640,
                            },
                        }
                    ],
                },
            ]
        }
    ]

    diagnostics = build_simulcast_layer_diagnostics(reports)

    assert diagnostics["low_layer_sample"] == {"width": 320, "height": 180, "received_bitrate": 150}
    assert diagnostics["high_layer_sample"] == {"width": 640, "height": 360, "received_bitrate": 640}
    assert diagnostics["dimensions_increased"] is True
    assert diagnostics["bitrate_changed"] is True
    assert diagnostics["bitrate_delta_kbps"] == 490
    assert diagnostics["simulcast_layer_proof_passed"] is True

    reports[0]["case_results"][1]["observations"][0]["payload"]["received_bitrate"] = 150
    assert build_simulcast_layer_diagnostics(reports)["simulcast_layer_proof_passed"] is False


@pytest.mark.parametrize("first_high_cursor,first_high_bitrate,expected", [(101, 500, True), (99, 500, False), (101, 150, False)])
def test_IT_MAC_CONSOLE_AGORA_simulcast_summary_keeps_cursors_within_each_run(first_high_cursor, first_high_bitrate, expected) -> None:
    def report(run_id, low_cursor, high_cursor, low_bitrate, high_bitrate):
        return {
            "run_id": run_id,
            "case_results": [{
                "case_id": "TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE",
                "observations": [{
                    "kind": "event", "cursor": cursor, "node_id": PRIMARY_NODE_ID,
                    "target": {"function": "onRemoteVideoStats"},
                    "payload": {"uid": 1002, "rx_stream_type": stream_type, "width": width, "height": height, "received_bitrate": bitrate},
                } for cursor, stream_type, width, height, bitrate in [
                    (low_cursor, 1, 480, 200, low_bitrate),
                    (high_cursor, 0, 960, 400, high_bitrate),
                ]],
            }],
        }

    reports = [report("run-a", 100, first_high_cursor, 150, first_high_bitrate), report("run-b", 10, 11, 500, 700)]
    diagnostics = build_simulcast_layer_diagnostics(reports)
    assert diagnostics["simulcast_layer_proof_passed"] is expected
    assert diagnostics["bitrate_delta_kbps"] == 200
    assert [item["run_id"] for item in diagnostics["run_diagnostics"]] == ["run-a", "run-b"]
    assert [item["simulcast_layer_proof_passed"] for item in diagnostics["run_diagnostics"]] == [expected, True]
















def test_IT_MAC_CONSOLE_AGORA_06f_invalid_token_then_recover_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    recovery_case = cases[AGORA_INVALID_TOKEN_RECOVERY_CASE_ID]
    assert recovery_case["scenario_family"] == "failure_recovery"
    assert recovery_case["implementation_status"] == "runnable"
    assert recovery_case["covered_capabilities"] == [
        "invalid_token_failure",
        "recovery_after_failure",
        "join_success_fact",
        "leave_cleanup",
    ]
    assert recovery_case["suite"] == "agora_failure_recovery_resilience"










def test_IT_MAC_CONSOLE_AGORA_10_l1_leave_cleanup_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    cleanup_case = cases[AGORA_L1_LEAVE_CLEANUP_CASE_ID]
    assert cleanup_case["platform"] == "mac"
    assert cleanup_case["suite"] == "agora_direct_call_l1"
    assert cleanup_case["covered_capabilities"] == ["leave_cleanup"]




def test_IT_MAC_CONSOLE_AGORA_12_l1_connection_state_sequence_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    sequence_case = cases[AGORA_L1_CONNECTION_SEQUENCE_CASE_ID]
    assert sequence_case["platform"] == "mac"
    assert sequence_case["suite"] == "agora_direct_call_l1"
    assert sequence_case["covered_capabilities"] == ["connection_state_transition"]




def test_IT_MAC_CONSOLE_AGORA_14_l1_runtime_cleanup_baseline_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    baseline_case = cases[AGORA_L1_RUNTIME_CLEANUP_BASELINE_CASE_ID]
    assert baseline_case["platform"] == "mac"
    assert baseline_case["suite"] == "agora_direct_call_l1"
    assert baseline_case["covered_capabilities"] == ["leave_cleanup"]




def test_IT_MAC_CONSOLE_AGORA_16_l2_preview_control_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    preview_case = cases[AGORA_L2_PREVIEW_CONTROL_CASE_ID]
    assert preview_case["platform"] == "mac"
    assert preview_case["suite"] == "agora_direct_call_l2"
    assert preview_case["covered_capabilities"] == ["preview_control"]




def test_IT_MAC_CONSOLE_AGORA_18_l2_preview_lifecycle_around_join_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    preview_case = cases[AGORA_L2_PREVIEW_LIFECYCLE_AROUND_JOIN_CASE_ID]
    assert preview_case["platform"] == "mac"
    assert preview_case["suite"] == "agora_direct_call_l2"
    assert preview_case["covered_capabilities"] == ["preview_control"]




def test_IT_MAC_CONSOLE_AGORA_20_l2_rtc_stats_observable_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    stats_case = cases[AGORA_L2_RTC_STATS_OBSERVABLE_CASE_ID]
    assert stats_case["platform"] == "mac"
    assert stats_case["suite"] == "agora_direct_call_l2"
    assert stats_case["covered_capabilities"] == ["rtc_stats_observability"]




def test_IT_MAC_CONSOLE_AGORA_22_l2_local_video_stats_observable_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    stats_case = cases[AGORA_L2_LOCAL_VIDEO_STATS_OBSERVABLE_CASE_ID]
    assert stats_case["platform"] == "mac"
    assert stats_case["suite"] == "agora_direct_call_l2"
    assert stats_case["covered_capabilities"] == ["media_stats_observability"]




def test_IT_MAC_CONSOLE_AGORA_24_l2_remote_audio_stats_observable_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    stats_case = cases[AGORA_L2_REMOTE_AUDIO_STATS_OBSERVABLE_CASE_ID]
    assert stats_case["platform"] == "mac"
    assert stats_case["suite"] == "agora_direct_call_l2"
    assert stats_case["covered_capabilities"] == ["media_stats_observability"]




def test_IT_MAC_CONSOLE_AGORA_26_l2_remote_video_stats_observable_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    stats_case = cases[AGORA_L2_REMOTE_VIDEO_STATS_OBSERVABLE_CASE_ID]
    assert stats_case["platform"] == "mac"
    assert stats_case["suite"] == "agora_direct_call_l2"
    assert stats_case["covered_capabilities"] == ["media_stats_observability"]




def test_IT_MAC_CONSOLE_AGORA_36_1v1_remote_video_rendered_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    visual_case = cases[AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID]
    assert visual_case["suite"] == "agora_direct_call_enhanced"
    assert visual_case["covered_capabilities"] == ["remote_video_rendering"]


def test_IT_MAC_CONSOLE_AGORA_37_visual_call_diagnostics_require_remote_view_and_first_frame() -> None:
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                    "status": "passed",
                    "observations": [
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "bindRemoteVideo"},
                            "payload": {"uid": 1002, "view_id": "primary_remote_view", "configured": True},
                        },
                        {
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "bindRemoteVideo"},
                            "payload": {"uid": 1001, "view_id": "peer_remote_view", "configured": True},
                        },
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onFirstRemoteVideoFrame"},
                            "payload": {"uid": 1002, "width": 640, "height": 360},
                        },
                        {
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "onFirstRemoteVideoFrame"},
                            "payload": {"uid": 1001, "width": 640, "height": 360},
                        },
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRemoteVideoStats"},
                            "payload": {
                                "uid": 1002,
                                "received_bitrate": 512,
                                "decoder_output_frame_rate": 15,
                                "renderer_output_frame_rate": 15,
                            },
                        },
                        {
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "onRemoteVideoStats"},
                            "payload": {
                                "uid": 1001,
                                "received_bitrate": 512,
                                "decoder_output_frame_rate": 15,
                                "renderer_output_frame_rate": 15,
                            },
                        },
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onLocalVideoStats"},
                            "payload": {"uid": 1001, "sent_bitrate": 640, "sent_frame_rate": 15},
                        },
                        {
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "onLocalVideoStats"},
                            "payload": {"uid": 1002, "sent_bitrate": 640, "sent_frame_rate": 15},
                        },
                        {
                            "node_id": PRIMARY_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"rx_video_kbitrate": 686},
                        },
                        {
                            "node_id": PEER_NODE_ID,
                            "target": {"function": "onRtcStats"},
                            "payload": {"rx_video_kbitrate": 686},
                        },
                    ],
                }
            ]
        }
    ]

    diagnostics = build_visual_call_diagnostics(reports)

    assert diagnostics == {
        "primary_node_id": PRIMARY_NODE_ID,
        "peer_node_id": PEER_NODE_ID,
        "primary_uid": 1001,
        "peer_uid": 1002,
        "primary_remote_view_id": "primary_remote_view",
        "peer_remote_view_id": "peer_remote_view",
        "view_capture_artifacts": {},
        "sdk_snapshot_artifacts": {},
        "snapshot_callbacks": {},
        "snapshot_request_artifacts": {},
        "snapshot_requests": [],
        "primary_local_video_send_observed": True,
        "peer_local_video_send_observed": True,
        "primary_to_peer_remote_video_receive_observed": True,
        "peer_to_primary_remote_video_receive_observed": True,
        "pixel_diagnostics": {
            key: {
                "path": "",
                "exists": False,
                "bytes": 0,
                "width": 0,
                "height": 0,
                "total_pixels": 0,
                "non_empty_pixels": 0,
                "non_empty": False,
            }
            for key in ("primary_local_preview", "primary_remote_view", "peer_local_preview", "peer_remote_view")
        },
        "artifact_proof_passed": False,
        "missing_views": sorted(VISUAL_ARTIFACT_KEYS),
        "fail_reasons": {
            key: [
                "snapshot_callback_missing",
                "snapshot_request_missing",
            ]
            for key in sorted(VISUAL_ARTIFACT_KEYS)
        },
        "primary_remote_view_bound": True,
        "peer_remote_view_bound": True,
        "primary_first_remote_video_frame_observed": True,
        "peer_first_remote_video_frame_observed": True,
        "primary_remote_video_stats_observed": True,
        "peer_remote_video_stats_observed": True,
        "primary_rtc_video_receive_observed": True,
        "peer_rtc_video_receive_observed": True,
    }


def test_IT_MAC_CONSOLE_AGORA_37b_png_pixel_diagnostics_marks_blank_and_non_empty_artifacts(tmp_path) -> None:
    blank = tmp_path / "blank.png"
    non_empty = tmp_path / "non-empty.png"
    _write_rgba_png(blank, 2, 1, [(0, 0, 0, 255), (0, 0, 0, 255)])
    _write_rgba_png(non_empty, 2, 1, [(0, 0, 0, 255), (17, 34, 51, 255)])

    assert build_png_pixel_diagnostics(blank) == {
        "path": str(blank),
        "exists": True,
        "bytes": blank.stat().st_size,
        "width": 2,
        "height": 1,
        "total_pixels": 2,
        "content_pixels": 2,
        "content_bounds": {"left": 0, "top": 0, "right": 2, "bottom": 1},
        "non_empty_pixels": 0,
        "non_empty": False,
    }
    assert build_png_pixel_diagnostics(non_empty) == {
        "path": str(non_empty),
        "exists": True,
        "bytes": non_empty.stat().st_size,
        "width": 2,
        "height": 1,
        "total_pixels": 2,
        "content_pixels": 2,
        "content_bounds": {"left": 0, "top": 0, "right": 2, "bottom": 1},
        "non_empty_pixels": 1,
        "non_empty": True,
    }


def test_IT_MAC_CONSOLE_AGORA_37b2_png_pixel_diagnostics_treats_empty_path_as_missing() -> None:
    assert png_pixel_diagnostics("")["exists"] is False
    assert png_pixel_diagnostics("")["non_empty"] is False


def _four_non_empty_artifacts(tmp_path) -> dict[str, Path]:
    artifacts = {key: tmp_path / f"{key}.png" for key in VISUAL_ARTIFACT_KEYS}
    for index, path in enumerate(artifacts.values(), start=1):
        _write_rgba_png(path, 2, 2, [(index, index + 1, index + 2, 255)] * 4)
    return artifacts


def test_IT_MAC_CONSOLE_AGORA_37c_visual_evidence_standard_passes_four_views(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)

    scenario = _judge_visual_evidence(_complete_view_evidence(artifacts))

    assert scenario["status"] == VERDICT_PASSED
    assert scenario["missing_views"] == []
    assert scenario["fail_reasons"] == {}
    assert scenario["required_views"] == sorted(VISUAL_ARTIFACT_KEYS)
    assert scenario["views"]["primary_remote_view"]["binding"]["configured"] is True
    assert scenario["views"]["primary_remote_view"]["liveness"]["remote_receive"] is True
    assert scenario["views"]["primary_local_preview"]["liveness"]["local_send"] is True


def test_IT_MAC_CONSOLE_AGORA_37d_visual_evidence_standard_fails_when_one_remote_png_is_blank(
    tmp_path,
) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    _write_rgba_png(artifacts["peer_remote_view"], 2, 2, [(0, 0, 0, 255)] * 4)

    scenario = _judge_visual_evidence(_complete_view_evidence(artifacts))

    assert scenario["status"] == "missing"
    assert scenario["missing_views"] == ["peer_remote_view"]
    assert scenario["fail_reasons"]["peer_remote_view"] == ["artifact_empty_content"]


def test_IT_MAC_CONSOLE_AGORA_37e_visual_evidence_standard_fails_when_only_border_is_non_empty(
    tmp_path,
) -> None:
    artifacts = {key: tmp_path / f"{key}-border.png" for key in VISUAL_ARTIFACT_KEYS}

    def bordered_pixels(color: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
        pixels = []
        for y in range(8):
            for x in range(8):
                if x in {0, 1, 6, 7} or y in {0, 1, 6, 7}:
                    pixels.append(color)
                else:
                    pixels.append((0, 0, 0, 255))
        return pixels

    for path in artifacts.values():
        _write_rgba_png(path, 8, 8, bordered_pixels((0, 255, 0, 255)))

    scenario = _judge_visual_evidence(_complete_view_evidence(artifacts))

    assert scenario["status"] == "missing"
    assert scenario["missing_views"] == sorted(VISUAL_ARTIFACT_KEYS)
    assert all(
        scenario["fail_reasons"][key] == ["artifact_empty_content"] for key in VISUAL_ARTIFACT_KEYS
    )


def test_IT_MAC_CONSOLE_AGORA_37f_visual_diagnostics_use_sdk_snapshot_callbacks(tmp_path) -> None:
    artifacts = {key: tmp_path / f"{key}-snapshot.png" for key in VISUAL_ARTIFACT_KEYS}
    for index, path in enumerate(artifacts.values(), start=1):
        _write_rgba_png(path, 1, 1, [(index, index + 1, index + 2, 255)])
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                    "status": "passed",
                    "observations": _complete_view_evidence(artifacts),
                }
            ]
        }
    ]

    diagnostics = build_visual_call_diagnostics(reports)

    assert diagnostics["artifact_proof_passed"] is True
    assert diagnostics["sdk_snapshot_artifacts"] == {key: str(path) for key, path in artifacts.items()}
    assert diagnostics["snapshot_callbacks"]["primary_local_preview"]["uid"] == 0
    assert diagnostics["snapshot_callbacks"]["primary_remote_view"]["uid"] == 1002
    assert diagnostics["snapshot_callbacks"]["peer_local_preview"]["uid"] == 0
    assert diagnostics["snapshot_callbacks"]["peer_remote_view"]["uid"] == 1001


def test_IT_MAC_CONSOLE_AGORA_37g_visual_diagnostics_require_snapshot_callbacks_not_just_requests(
    tmp_path,
) -> None:
    artifacts = {key: tmp_path / f"{key}-request.png" for key in VISUAL_ARTIFACT_KEYS}
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                    "status": "passed",
                    "observations": _bidirectional_visual_evidence(artifacts, "onSnapshotRequested"),
                }
            ]
        }
    ]

    diagnostics = build_visual_call_diagnostics(reports)

    assert diagnostics["artifact_proof_passed"] is False
    assert diagnostics["sdk_snapshot_artifacts"] == {}
    assert len(diagnostics["snapshot_requests"]) == 4
    assert diagnostics["snapshot_callbacks"] == {}


def test_IT_MAC_CONSOLE_AGORA_37h_visual_evidence_standard_requires_both_snapshot_legs(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)

    scenario = _judge_visual_evidence(
        _bidirectional_visual_evidence(artifacts, "onSnapshotRequested")
    )

    assert scenario["status"] == "missing"
    assert all(
        scenario["fail_reasons"][key] == ["snapshot_callback_missing"]
        for key in VISUAL_ARTIFACT_KEYS
    )


def test_IT_MAC_CONSOLE_AGORA_37i_visual_evidence_standard_names_snapshot_error(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    artifacts["primary_remote_view"].unlink()
    evidence = _patch_evidence(
        _complete_view_evidence(artifacts),
        function="onSnapshotTaken",
        view_role="primary_remote_view",
        err_code=-2,
    )

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["missing_views"] == ["primary_remote_view"]
    assert scenario["fail_reasons"]["primary_remote_view"] == [
        "artifact_file_missing",
        "snapshot_error",
    ]


def test_IT_MAC_CONSOLE_AGORA_37j_visual_evidence_standard_rejects_snapshot_path_mismatch(
    tmp_path,
) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    other_path = tmp_path / "other.png"
    _write_rgba_png(other_path, 2, 2, [(9, 9, 9, 255)] * 4)
    evidence = _patch_evidence(
        _complete_view_evidence(artifacts),
        function="onSnapshotRequested",
        view_role="peer_local_preview",
        file_path=str(other_path),
    )

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["peer_local_preview"] == ["snapshot_path_mismatch"]


def test_IT_MAC_CONSOLE_AGORA_37k_visual_evidence_standard_reports_missing_artifact_file(
    tmp_path,
) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    artifacts["peer_remote_view"].unlink()

    scenario = _judge_visual_evidence(_complete_view_evidence(artifacts))

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["peer_remote_view"] == ["artifact_file_missing"]


def test_IT_MAC_CONSOLE_AGORA_37l_visual_evidence_standard_reports_dead_video_liveness(
    tmp_path,
) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = _complete_view_evidence(artifacts)
    evidence = _drop_evidence(evidence, "onRemoteVideoStats", PEER_NODE_ID)
    evidence = _patch_evidence(
        evidence, function="onRtcStats", node_id=PEER_NODE_ID, rx_video_kbitrate=0
    )

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["missing_views"] == ["peer_remote_view"]
    assert scenario["fail_reasons"]["peer_remote_view"] == [
        "remote_video_receive_missing",
        "rtc_video_receive_missing",
    ]


def test_IT_MAC_CONSOLE_AGORA_37m_visual_evidence_standard_rejects_foreign_node_evidence(
    tmp_path,
) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = _complete_view_evidence(artifacts)
    for item in evidence:
        if (
            item["node_id"] == PRIMARY_NODE_ID
            and item["payload"].get("artifact_key") == "primary_remote_view"
        ):
            item["node_id"] = PEER_NODE_ID

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["missing_views"] == ["primary_remote_view"]
    assert "foreign_node_evidence" in scenario["fail_reasons"]["primary_remote_view"]
    assert scenario["views"]["primary_remote_view"]["foreign_node_evidence"] == [PEER_NODE_ID]


def test_IT_MAC_CONSOLE_AGORA_37n_visual_evidence_standard_ignores_unknown_view_roles(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = [
        item
        for item in _complete_view_evidence(artifacts)
        if item["payload"].get("artifact_key") != "peer_remote_view"
    ]
    evidence.append(
        {
            "node_id": PEER_NODE_ID,
            "target": {"function": "onSnapshotTaken"},
            "payload": {
                "artifact_key": "unknown_view",
                "file_path": str(artifacts["peer_remote_view"]),
                "uid": 1001,
                "err_code": 0,
            },
        }
    )

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["missing_views"] == ["peer_remote_view"]
    assert "unknown_view" not in scenario["views"]


def test_IT_MAC_CONSOLE_AGORA_37o_visual_evidence_standard_records_picture_source(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = _patch_evidence(
        _complete_view_evidence(artifacts),
        function="onLocalVideoStats",
        node_id=PEER_NODE_ID,
        source_type=4,
    )
    evidence = _patch_evidence(
        evidence, function="onLocalVideoStats", node_id=PRIMARY_NODE_ID, source_type=0
    )

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == VERDICT_PASSED
    assert scenario["views"]["peer_local_preview"]["source"] == {
        "source_type": 4,
        "origin": "synthetic",
        "publisher_node_id": PEER_NODE_ID,
        "observed": [
            {"source_type": 4, "origin": "synthetic", "publisher_node_id": PEER_NODE_ID}
        ],
    }
    assert scenario["views"]["primary_local_preview"]["source"] == {
        "source_type": 0,
        "origin": "camera",
        "publisher_node_id": PRIMARY_NODE_ID,
        "observed": [{"source_type": 0, "origin": "camera", "publisher_node_id": PRIMARY_NODE_ID}],
    }
    assert scenario["views"]["primary_remote_view"]["source"]["origin"] == "synthetic"
    assert scenario["views"]["primary_remote_view"]["source"]["publisher_node_id"] == PEER_NODE_ID


def test_IT_MAC_CONSOLE_AGORA_37o1_visual_evidence_standard_fails_closed_for_declared_source_type(
    tmp_path,
) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = _patch_evidence(
        _complete_view_evidence(artifacts),
        function="onLocalVideoStats",
        node_id=PEER_NODE_ID,
        source_type=4,
    )
    views = [dict(view) for view in _visual_view_declarations()]
    next(view for view in views if view["view_role"] == "peer_local_preview")["expected_source_type"] = 4

    scenario = build_scenario_visual_evidence(
        scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
        case_ids=(AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID,),
        views=tuple(views),
        reports=[{"case_results": [{"case_id": AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID, "observations": evidence}]}],
    )
    assert scenario["status"] == VERDICT_PASSED

    _patch_evidence(evidence, function="onLocalVideoStats", node_id=PEER_NODE_ID, source_type=0)
    mismatch = build_scenario_visual_evidence(
        scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
        case_ids=(AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID,),
        views=tuple(views),
        reports=[{"case_results": [{"case_id": AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID, "observations": evidence}]}],
    )
    assert mismatch["fail_reasons"]["peer_local_preview"] == ["source_type_mismatch"]

    _patch_evidence(evidence, function="onLocalVideoStats", node_id=PEER_NODE_ID, source_type=None)
    missing = build_scenario_visual_evidence(
        scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
        case_ids=(AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID,),
        views=tuple(views),
        reports=[{"case_results": [{"case_id": AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID, "observations": evidence}]}],
    )
    assert missing["fail_reasons"]["peer_local_preview"] == ["source_type_missing"]


def test_IT_MAC_CONSOLE_AGORA_37s_visual_evidence_standard_binds_from_snapshot_evidence(tmp_path) -> None:
    """真实链路 evidence 只含回调事件：没有 bindRemoteVideo 调用结果时绑定仍须成立。"""
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = [
        item
        for item in _complete_view_evidence(artifacts)
        if item["target"]["function"] != "bindRemoteVideo"
    ]

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == VERDICT_PASSED
    assert scenario["views"]["primary_remote_view"]["binding"]["source"] == "snapshot_evidence"
    assert scenario["views"]["peer_remote_view"]["binding"]["source"] == "snapshot_evidence"


def test_IT_MAC_CONSOLE_AGORA_37t_visual_evidence_standard_requires_remote_view_binding(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = [
        item
        for item in _complete_view_evidence(artifacts)
        if item["target"]["function"] != "bindRemoteVideo"
        and not (
            item["payload"].get("artifact_key") == "peer_remote_view"
            and item["node_id"] == PEER_NODE_ID
        )
    ]

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["missing_views"] == ["peer_remote_view"]
    assert scenario["views"]["peer_remote_view"]["binding"]["source"] == "none"
    assert "remote_view_not_bound" in scenario["fail_reasons"]["peer_remote_view"]


def test_IT_MAC_CONSOLE_AGORA_37u_visual_evidence_standard_keeps_both_picture_sources(
    tmp_path,
) -> None:
    """同一场景跑真相机与合成源两个 case 时，来源必须记为 mixed 并保留两次观测。"""
    artifacts = _four_non_empty_artifacts(tmp_path)
    camera_evidence = _bidirectional_visual_evidence(artifacts, "onSnapshotRequested") + _bidirectional_visual_evidence(
        artifacts, "onSnapshotTaken"
    )
    synthetic_evidence = _patch_evidence(
        _bidirectional_visual_evidence(artifacts, "onSnapshotRequested")
        + _bidirectional_visual_evidence(artifacts, "onSnapshotTaken"),
        function="onLocalVideoStats",
        node_id=PEER_NODE_ID,
        source_type=4,
    )
    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                    "status": "passed",
                    "observations": camera_evidence,
                }
            ]
        },
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID,
                    "status": "passed",
                    "observations": synthetic_evidence,
                }
            ]
        },
    ]

    scenario = build_scenario_visual_evidence(
        scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
        case_ids=(AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID, AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID),
        views=_visual_view_declarations(),
        reports=reports,
    )

    assert scenario["status"] == VERDICT_PASSED
    assert scenario["case_ids"] == [
        AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
        AGORA_1V1_REMOTE_VIDEO_SYNTH_PEER_CASE_ID,
    ]
    source = scenario["views"]["peer_local_preview"]["source"]
    assert source["origin"] == "mixed"
    assert source["source_type"] is None
    assert sorted(item["origin"] for item in source["observed"]) == ["camera", "synthetic"]


def test_IT_MAC_CONSOLE_AGORA_37v_small_room_audio_proof_never_promotes_picture_scenario() -> None:
    """Small Room 通过的是音频 proof：画面场景必须仍是 not_exercised，不得被捎带成 passed。"""
    report = {
        "case_results": [
            {
                "case_id": AGORA_SMALL_ROOM_BASELINE_CASE_ID,
                "status": "passed",
                "observations": [
                    {
                        "node_id": PRIMARY_NODE_ID,
                        "target": {"function": "onRemoteAudioStats"},
                        "payload": {"uid": 1102},
                    },
                    {
                        "node_id": PRIMARY_NODE_ID,
                        "target": {"function": "onRtcStats"},
                        "payload": {"rx_audio_kbitrate": 40},
                    },
                    {
                        "node_id": PEER_NODE_ID,
                        "target": {"function": "onRtcStats"},
                        "payload": {"tx_audio_kbitrate": 40},
                    },
                    {
                        "node_id": PEER_B_NODE_ID,
                        "target": {"function": "onRtcStats"},
                        "payload": {"tx_audio_kbitrate": 40},
                    },
                ],
            }
        ]
    }

    assert build_small_room_diagnostics([report])["small_room_proof_passed"] is True

    scenarios = build_visual_evidence_scenarios([report], {AGORA_SMALL_ROOM_BASELINE_CASE_ID})

    assert scenarios["status"] == "passed"
    assert scenarios["scenarios"][SCENARIO_SMALL_ROOM]["status"] == VERDICT_NOT_EXERCISED
    assert scenarios["not_exercised_scenarios"] == [SCENARIO_ONE_TO_ONE_MEDIA_QUALITY, SCENARIO_SMALL_ROOM]
    assert scenarios["passed_scenarios"] == []


def test_IT_MAC_CONSOLE_AGORA_37w_visual_evidence_standard_names_request_failure(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = _patch_evidence(
        _complete_view_evidence(artifacts),
        function="onSnapshotRequested",
        view_role="primary_local_preview",
        return_code=1,
    )

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["primary_local_preview"] == ["snapshot_request_failed"]


def test_IT_MAC_CONSOLE_AGORA_37x_visual_evidence_standard_names_undecodable_artifact(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    artifacts["peer_local_preview"].write_bytes(b"not an image at all")

    scenario = _judge_visual_evidence(_complete_view_evidence(artifacts))

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["peer_local_preview"] == ["artifact_undecodable"]


def test_IT_MAC_CONSOLE_AGORA_37y_visual_evidence_standard_names_zero_dimension_artifact(
    tmp_path,
) -> None:
    """零尺寸是解码器只会对畸形输入给出的结果，用注入探针钉住这条规则本身。"""
    artifacts = _four_non_empty_artifacts(tmp_path)

    def zero_dimension_probe(path: str):
        facts = png_pixel_diagnostics(path)
        if path == str(artifacts["primary_remote_view"]):
            return {**facts, "width": 0, "height": 0, "total_pixels": 0, "non_empty": False}
        return facts

    reports = [
        {
            "case_results": [
                {
                    "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                    "status": "passed",
                    "observations": _complete_view_evidence(artifacts),
                }
            ]
        }
    ]
    scenario = build_scenario_visual_evidence(
        scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
        case_ids=(AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,),
        views=_visual_view_declarations(),
        reports=reports,
        pixel_probe=zero_dimension_probe,
    )

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["primary_remote_view"] == ["artifact_zero_dimension"]


def test_IT_MAC_CONSOLE_AGORA_37z_visual_evidence_standard_names_missing_first_remote_frame(
    tmp_path,
) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = _drop_evidence(_complete_view_evidence(artifacts), "onFirstRemoteVideoFrame", PRIMARY_NODE_ID)

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["primary_remote_view"] == ["first_remote_video_frame_missing"]


def test_IT_MAC_CONSOLE_AGORA_37aa_visual_evidence_standard_names_missing_local_send(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)
    evidence = _drop_evidence(_complete_view_evidence(artifacts), "onLocalVideoStats", PRIMARY_NODE_ID)
    evidence = _patch_evidence(
        evidence, function="onRtcStats", node_id=PRIMARY_NODE_ID, tx_video_kbitrate=0
    )

    scenario = _judge_visual_evidence(evidence)

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["primary_local_preview"] == ["local_video_send_missing"]


def test_IT_MAC_CONSOLE_AGORA_37ab_visual_evidence_declaration_guards_not_exercised(tmp_path) -> None:
    artifacts = _four_non_empty_artifacts(tmp_path)

    with pytest.raises(AssertionError, match="must be judged by build_scenario_visual_evidence"):
        build_not_exercised_scenario(
            scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
            owner_layer="adapter_reference_validation",
            reason="probe",
            follow_up="probe",
            views=_visual_view_declarations(),
        )

    with pytest.raises(AssertionError, match="already produced picture evidence"):
        assert_scenario_has_no_picture_evidence(
            scenario_id=SCENARIO_SMALL_ROOM,
            reports=[
                {
                    "case_results": [
                        {
                            "case_id": AGORA_SMALL_ROOM_BASELINE_CASE_ID,
                            "status": "passed",
                            "observations": _complete_view_evidence(artifacts),
                        }
                    ]
                }
            ],
            case_ids=(AGORA_SMALL_ROOM_BASELINE_CASE_ID,),
        )

    assert_scenario_has_no_picture_evidence(
        scenario_id=SCENARIO_SMALL_ROOM,
        reports=[
            {
                "case_results": [
                    {
                        "case_id": AGORA_SMALL_ROOM_BASELINE_CASE_ID,
                        "status": "passed",
                        "observations": [
                            {
                                "node_id": PRIMARY_NODE_ID,
                                "target": {"function": "onRemoteAudioStats"},
                                "payload": {"uid": 1102},
                            }
                        ],
                    }
                ]
            }
        ],
        case_ids=(AGORA_SMALL_ROOM_BASELINE_CASE_ID,),
    )


def test_IT_MAC_CONSOLE_AGORA_37ac_visual_evidence_summary_fails_closed_on_unknown_status() -> None:
    summary = summarize_visual_evidence(
        {
            "one_to_one_media_quality": {"scenario_id": "one_to_one_media_quality", "status": "skipped"},
            "small_room": {"scenario_id": "small_room", "status": VERDICT_NOT_EXERCISED},
        }
    )

    assert summary["status"] == "missing"
    assert summary["missing_scenarios"] == ["one_to_one_media_quality"]


def test_IT_MAC_CONSOLE_AGORA_37ad_artifact_proof_is_the_scenario_verdict(tmp_path) -> None:
    """冻结投影关系：artifact_proof_passed 必须等于 1V1 场景 verdict。"""
    passing_artifacts = _four_non_empty_artifacts(tmp_path)

    def diagnostics_for(artifacts: dict[str, Path]) -> dict:
        reports = [
            {
                "case_results": [
                    {
                        "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                        "status": "passed",
                        "observations": _complete_view_evidence(artifacts),
                    }
                ]
            }
        ]
        return build_visual_call_diagnostics(reports), build_one_to_one_visual_evidence(reports)

    diagnostics, scenario = diagnostics_for(passing_artifacts)
    assert scenario["status"] == VERDICT_PASSED
    assert diagnostics["artifact_proof_passed"] == (scenario["status"] == VERDICT_PASSED) is True

    blanked = dict(passing_artifacts)
    blanked["peer_remote_view"] = tmp_path / "blank-remote.png"
    _write_rgba_png(blanked["peer_remote_view"], 2, 2, [(0, 0, 0, 255)] * 4)
    diagnostics, scenario = diagnostics_for(blanked)
    assert scenario["status"] == "missing"
    assert diagnostics["artifact_proof_passed"] == (scenario["status"] == VERDICT_PASSED) is False


def test_IT_MAC_CONSOLE_AGORA_37ae_reference_matrix_reads_scene_verdict_not_a_second_judgment(
    monkeypatch,
) -> None:
    """子集运行未选择 1V1 用例时，矩阵必须跟着场景段记 not_exercised，而不是自判 missing。"""
    monkeypatch.chdir(ROOT)

    cases = [case for case in load_cases() if case["platform"] == "mac"]
    reports = [
        {
            "case_results": [
                {"case_id": case["case_id"], "status": "passed"}
                for case in cases
                if case.get("implementation_status") == "runnable"
            ]
        }
    ]

    matrix = build_reference_validation_matrix(
        cases,
        reports,
        evidence_coverage={"status": "passed", "missing": {}, "by_case": {}},
        visual_diagnostics={"artifact_proof_passed": False},
        visual_evidence_scenarios={
            "scenarios": {
                SCENARIO_ONE_TO_ONE_MEDIA_QUALITY: {
                    "status": VERDICT_NOT_EXERCISED,
                    "case_ids": [],
                    "missing_views": [],
                    "fail_reasons": {},
                    "reason": "subset run",
                    "follow_up": "run the 1v1 case",
                },
                SCENARIO_SMALL_ROOM: {"status": VERDICT_NOT_EXERCISED},
            }
        },
        small_room_diagnostics={"small_room_proof_passed": True},
        resilience_diagnostics={"status": "passed"},
    )

    assert matrix["capabilities"]["artifact"]["status"] == VERDICT_NOT_EXERCISED
    assert matrix["capabilities"]["artifact"]["reason"] == "subset run"
    assert matrix["scenarios"]["one_to_one_media_quality"]["status"] == VERDICT_NOT_EXERCISED
    assert matrix["status"] == "passed"


def test_IT_MAC_CONSOLE_AGORA_37af_truncated_snapshot_is_undecodable_not_a_crash(tmp_path) -> None:
    """IHDR 声称的行数多于 IDAT 实际行数：必须判为不可解码，而不是把 gate 崩在 traceback 上。"""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    artifacts = _four_non_empty_artifacts(tmp_path)
    truncated = artifacts["primary_local_preview"]
    truncated.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 4, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + b"\x01\x02\x03\xff"))
        + chunk(b"IEND", b"")
    )

    facts = png_pixel_diagnostics(truncated)

    assert facts["exists"] is True
    assert facts["error"]

    scenario = _judge_visual_evidence(_complete_view_evidence(artifacts))

    assert scenario["status"] == "missing"
    assert scenario["fail_reasons"]["primary_local_preview"] == ["artifact_undecodable"]


def test_IT_MAC_CONSOLE_AGORA_37p_agora_gate_fails_closed_when_visual_evidence_is_absent() -> None:
    scenarios = build_visual_evidence_scenarios([], {AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID})

    assert scenarios["status"] == "missing"
    assert scenarios["missing_scenarios"] == [SCENARIO_ONE_TO_ONE_MEDIA_QUALITY]
    assert scenarios["not_exercised_scenarios"] == [SCENARIO_SMALL_ROOM]
    small_room = scenarios["scenarios"][SCENARIO_SMALL_ROOM]
    assert small_room["status"] == VERDICT_NOT_EXERCISED
    assert small_room["owner_layer"] == "adapter_reference_validation"
    assert small_room["follow_up"]
    one_to_one = scenarios["scenarios"][SCENARIO_ONE_TO_ONE_MEDIA_QUALITY]
    assert one_to_one["status"] == "missing"
    assert set(one_to_one["missing_views"]) == set(VISUAL_ARTIFACT_KEYS)


def test_IT_MAC_CONSOLE_AGORA_37q_agora_gate_marks_unselected_visual_scenario_not_exercised() -> None:
    scenarios = build_visual_evidence_scenarios([], {AGORA_SMALL_ROOM_BASELINE_CASE_ID})

    one_to_one = scenarios["scenarios"][SCENARIO_ONE_TO_ONE_MEDIA_QUALITY]
    assert one_to_one["status"] == VERDICT_NOT_EXERCISED
    assert one_to_one["owner_layer"] == "adapter_reference_validation"
    assert scenarios["status"] == "passed"


def test_IT_MAC_CONSOLE_AGORA_37r_volcengine_gate_gates_visual_scenarios_by_selection() -> None:
    from scripts.validation.run_mac_console_volcengine_validation import (
        SYNTH_1V1_CASE_ID,
        assert_visual_evidence_passed,
        build_visual_evidence_scenarios as build_volcengine_scenarios,
        visual_call_views,
    )

    pairs = {SYNTH_1V1_CASE_ID: [("room-a", "user-a"), ("room-a", "user-b")]}

    # 未选择 1V1 用例（子集运行）：两个场景都显式登记 not_exercised，不伪称已覆盖。
    scenarios = build_volcengine_scenarios([], set(), {})
    assert scenarios["status"] == "passed"
    assert scenarios["missing_scenarios"] == []
    assert scenarios["not_exercised_scenarios"] == [SCENARIO_ONE_TO_ONE_MEDIA_QUALITY, SCENARIO_SMALL_ROOM]
    assert all(
        scenarios["scenarios"][scenario_id]["owner_layer"] == "sdk_adapter_volcengine_rtc"
        for scenario_id in scenarios["not_exercised_scenarios"]
    )

    # 选中 1V1 用例后转为硬门：没有画面证据时 one_to_one 判 missing，且四个必需视图全部点名。
    scenarios = build_volcengine_scenarios([], {SYNTH_1V1_CASE_ID}, pairs)
    assert scenarios["status"] == "missing"
    assert scenarios["missing_scenarios"] == [SCENARIO_ONE_TO_ONE_MEDIA_QUALITY]
    one_to_one = scenarios["scenarios"][SCENARIO_ONE_TO_ONE_MEDIA_QUALITY]
    assert one_to_one["status"] == "missing"
    assert set(one_to_one["missing_views"]) == {
        view["view_role"] for view in visual_call_views("user-a", "user-b")
    }
    with pytest.raises(AssertionError, match="visual evidence failed"):
        assert_visual_evidence_passed(scenarios)


def test_IT_MAC_CONSOLE_AGORA_37r1_volcengine_gate_requires_synthetic_peer_source_for_both_variants(
    tmp_path,
) -> None:
    from scripts.validation.run_mac_console_volcengine_validation import (
        NODE_ID as VOLCENGINE_PRIMARY_NODE_ID,
        PEER_NODE_ID as VOLCENGINE_PEER_NODE_ID,
        RENDERED_1V1_CASE_ID,
        SYNTH_1V1_CASE_ID,
        build_visual_evidence_scenarios as build_volcengine_scenarios,
    )

    def volcengine_evidence(peer_source_type: int) -> list[dict]:
        evidence = _complete_view_evidence(_four_non_empty_artifacts(tmp_path))
        for item in evidence:
            if item["node_id"] == PRIMARY_NODE_ID:
                item["node_id"] = VOLCENGINE_PRIMARY_NODE_ID
            elif item["node_id"] == PEER_NODE_ID:
                item["node_id"] = VOLCENGINE_PEER_NODE_ID
            payload = item["payload"]
            if payload.get("uid") == 1001:
                payload["uid"] = "user-a"
            elif payload.get("uid") == 1002:
                payload["uid"] = "user-b"
            if item["target"]["function"] == "onLocalVideoStats" and item["node_id"] == VOLCENGINE_PEER_NODE_ID:
                payload["source_type"] = peer_source_type
        return evidence

    reports = [
        {"case_results": [{"case_id": RENDERED_1V1_CASE_ID, "observations": volcengine_evidence(4)}]},
        {"case_results": [{"case_id": SYNTH_1V1_CASE_ID, "observations": volcengine_evidence(4)}]},
    ]
    pairs = {
        RENDERED_1V1_CASE_ID: [("room-a", "user-a"), ("room-a", "user-b")],
        SYNTH_1V1_CASE_ID: [("room-a", "user-a"), ("room-a", "user-b")],
    }

    scenarios = build_volcengine_scenarios(reports, set(pairs), pairs)

    assert scenarios["status"] == VERDICT_PASSED

    reports[0]["case_results"][0]["observations"] = volcengine_evidence(0)
    mismatch = build_volcengine_scenarios(reports, set(pairs), pairs)
    assert mismatch["scenarios"][SCENARIO_ONE_TO_ONE_MEDIA_QUALITY]["fail_reasons"] == {
        "peer_local_preview": ["source_type_mismatch"],
        "primary_remote_view": ["source_type_mismatch"],
    }


def test_IT_MAC_CONSOLE_AGORA_38_failed_visual_case_evidence_summary_preserves_observed_functions() -> None:
    report = {
        "case_results": [
            {
                "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
                "step_id": "observe-1v1-remote-video-frame",
                "status": "failed",
                "error": {"code": 408, "message": "assertion timeout: event_exists"},
                "observations": [
                    {
                        "node_id": PRIMARY_NODE_ID,
                        "target": {"function": "bindRemoteVideo"},
                        "payload": {"uid": 1002, "view_id": "primary_remote_view", "configured": True},
                    },
                    {
                        "node_id": PRIMARY_NODE_ID,
                        "target": {"function": "onRemoteVideoStats"},
                        "payload": {"uid": 1002, "width": 640, "height": 360},
                    },
                    {
                        "node_id": PRIMARY_NODE_ID,
                        "target": {"function": "onRtcStats"},
                        "payload": {"rx_video_kbitrate": 686},
                    },
                ],
            }
        ]
    }
    case = {
        "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
        "run_id": "run-visual-failed",
        "status": "failed",
    }

    summary = build_failed_case_evidence_summary(case, report)
    visual_evidence = summary.pop("visual_evidence")

    assert summary == {
        "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
        "run_id": "run-visual-failed",
        "failure": {
            "case_id": AGORA_1V1_REMOTE_VIDEO_RENDERED_CASE_ID,
            "step_id": "observe-1v1-remote-video-frame",
            "status": "failed",
            "error": {"code": 408, "message": "assertion timeout: event_exists"},
        },
        "evidence": [
            {
                "node_id": PRIMARY_NODE_ID,
                "function": "bindRemoteVideo",
                "payload": {"uid": 1002, "view_id": "primary_remote_view", "configured": True},
            },
            {
                "node_id": PRIMARY_NODE_ID,
                "function": "onRemoteVideoStats",
                "payload": {"uid": 1002, "width": 640, "height": 360},
            },
            {
                "node_id": PRIMARY_NODE_ID,
                "function": "onRtcStats",
                "payload": {"rx_video_kbitrate": 686},
            },
        ],
        "bind_remote_video_observed": True,
        "first_remote_video_frame_observed": False,
        "remote_video_stats_observed": True,
        "rtc_video_receive_observed": True,
    }
    assert visual_evidence["status"] == "missing"
    assert visual_evidence["missing_views"] == sorted(VISUAL_ARTIFACT_KEYS)
    assert "snapshot_callback_missing" in visual_evidence["fail_reasons"]["primary_local_preview"]




def test_IT_MAC_CONSOLE_AGORA_28_permission_denied_join_failure_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    failure_case = cases[AGORA_PERMISSION_DENIED_JOIN_FAILURE_CASE_ID]
    assert failure_case["scenario_family"] == "failure_recovery"
    assert failure_case["implementation_status"] == "runnable"
    assert failure_case["covered_capabilities"] == ["permission_denied_failure"]
    assert failure_case["suite"] == "agora_failure_recovery_resilience"




def test_IT_MAC_CONSOLE_AGORA_30_permission_denied_preview_failure_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    failure_case = cases[AGORA_PERMISSION_DENIED_PREVIEW_FAILURE_CASE_ID]
    assert failure_case["scenario_family"] == "failure_recovery"
    assert failure_case["implementation_status"] == "runnable"
    assert failure_case["covered_capabilities"] == ["permission_denied_failure"]
    assert failure_case["suite"] == "agora_failure_recovery_resilience"




def test_IT_MAC_CONSOLE_AGORA_32_join_callback_timeout_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    timeout_case = cases[AGORA_JOIN_CALLBACK_TIMEOUT_CASE_ID]
    assert timeout_case["scenario_family"] == "failure_recovery"
    assert timeout_case["implementation_status"] == "runnable"
    assert timeout_case["covered_capabilities"] == ["join_callback_timeout"]
    assert timeout_case["suite"] == "agora_failure_recovery_resilience"




def test_IT_MAC_CONSOLE_AGORA_34_onerror_diagnostic_case_is_visible_to_console_api(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = {item["case_id"]: item for item in response.json()["cases"]}
    diagnostic_case = cases[AGORA_ONERROR_DIAGNOSTIC_CASE_ID]
    assert diagnostic_case["scenario_family"] == "failure_recovery"
    assert diagnostic_case["implementation_status"] == "runnable_or_partial"
    assert diagnostic_case["covered_capabilities"] == [
        "invalid_token_failure",
        "error_event_observability",
    ]
    assert diagnostic_case["suite"] == "agora_failure_recovery_resilience"
