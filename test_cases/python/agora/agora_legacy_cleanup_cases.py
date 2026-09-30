"""Agora 生命周期、1V1 样片演示与清理状态用例。"""

import json
from time import monotonic, sleep

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-SUCCESS-THEN-LEAVE-CLEANUP",
    name="macOS Agora L1 leave cleanup",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["leave_cleanup"],
    token_bindings=[('real-smoke-cleanup', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_success_then_leave_cleanup(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    preview = session.device("primary").agora.video_preview
    try:
        assert engine.join_channel(channel="real-smoke-cleanup", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
    finally:
        assert engine.leave_channel().code == 0
        assert engine.is_joined().value is False
        assert preview.is_previewing().value is False


@beacon_test(
    case_id="TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE",
    name="macOS Agora L1 runtime cleanup baseline",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["leave_cleanup"],
    tags=["runtime-reset-baseline"],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_runtime_cleanup_baseline(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    preview = session.device("primary").agora.video_preview
    assert engine.load_sdk().code == 0
    assert preview.stop_preview().code == 0
    assert engine.leave_channel().code == 0
    assert engine.is_joined().value is False
    assert preview.is_previewing().value is False


@beacon_test(
    case_id="TC-MAC-AGORA-REAL-JOIN-CALLBACK",
    name="macOS Agora real join callback",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_core",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_success_fact", "leave_cleanup", "clock_wait"],
    tags=["autorun-order:1"],
    token_bindings=[('real-smoke', 1001)],
    sdk_names=["agora_rtc", "beacon_system"],
)
def test_tc_mac_agora_real_join_callback(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    registration = session.register_callback(
        role="primary",
        event_target={"sdk": "agora_rtc", "interface": "rtc_engine", "class": "AgoraRtcEngineDelegate", "function": "onJoinChannelSuccess"},
        calls=[{"target": {"sdk": "beacon_system", "interface": "clock", "class": "SystemClock", "function": "waitInMs"}, "params": {"ms": 1}}],
    )
    assert registration.code == 0
    try:
        assert engine.join_channel(channel="real-smoke", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
        observed = engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
        execution = observed.callback_execution
        assert execution is not None
        assert execution["defer_matched"] is True
        assert execution["defer_executed"] is True
        assert len(execution["call_results"]) == 1
        result = execution["call_results"][0]
        assert result["target"]["sdk"] == "beacon_system"
        assert result["target"]["function"] == "waitInMs"
        assert result["error"] == 0
        assert json.loads(result["return_value"]) == {"waited": True}
    finally:
        assert engine.leave_channel().code == 0
        assert engine.is_joined().value is False


@beacon_test(
    case_id="TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE",
    name="macOS Agora real join leave and state",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_core",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_success_fact", "connection_state_transition", "leave_cleanup", "media_player_source", "remote_video_rendering", "remote_audio_stats_observability", "visual_snapshot_observability"],
    tags=["autorun-order:2"],
    token_bindings=[('real-smoke', 1001), ('real-smoke', 1002)],
    sdk_names=["agora_rtc", "beacon_system"],
)
def test_tc_mac_agora_real_join_leave_state(session: BeaconSession) -> None:
    primary = session.device("primary")
    engine = primary.agora.rtc_engine
    visual = primary.agora.visual_probe
    peer_device = session.device("peer")
    peer = peer_device.agora.rtc_engine
    player = peer_device.agora.media_player
    try:
        assert peer.load_sdk().code == 0
        assert player.open_media_player(source_path="test_cases/sample_960x400_ocean_with_audio.mp4").code == 0
        player.on_media_player_state_changed.wait(match={"state": 2, "reason": 0}, timeout_s=15)
        assert peer.join_channel(channel="real-smoke", uid=1002, token="{{AGORA_RTC_TOKEN}}", publish_camera=False, publish_microphone=False, publish_media_player=True).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1002}, timeout_s=15)
        assert engine.load_sdk().code == 0
        assert engine.join_channel(channel="real-smoke", uid=1001, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_camera=False, publish_microphone=False).code == 0
        engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
        assert engine.get_connection_state().value == {"state": "connected"}
        assert visual.bind_remote_video(uid=1002, view_role="primary_remote_view").code == 0
        assert player.play_media_player().code == 0
        player.on_media_player_state_changed.wait(match={"state": 3, "reason": 0}, timeout_s=5)
        frame = engine.on_first_remote_video_frame.wait(match={"uid": 1002}, timeout_s=30)
        assert frame.payload["width"] > 0 and frame.payload["height"] > 0
        # 展示等待留在 Runner，避免阻塞 Agent 接收取消后的清理命令。
        sleep(10)
        deadline = monotonic() + 5
        audio = engine.on_remote_audio_stats.wait(match={"uid": 1002}, timeout_s=5)
        while audio.payload["received_bitrate"] == 0 and monotonic() < deadline:
            audio = engine.on_remote_audio_stats.wait(match={"uid": 1002}, after_cursor=audio.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert audio.payload["received_bitrate"] > 0
        assert visual.capture_snapshot(view_role="primary_remote_view").code == 0
        engine.on_snapshot_taken.wait(match={"view_role": "primary_remote_view", "err_code": 0}, timeout_s=5)
    finally:
        assert player.stop_media_player().code == 0
        assert visual.release_view(view_role="primary_remote_view").code == 0
        assert engine.leave_channel().code == 0
        assert engine.is_joined().value is False
        assert engine.unload_sdk().code == 0
        assert peer.leave_channel().code == 0
        assert peer.is_joined().value is False
        assert peer.unload_sdk().code == 0


@beacon_test(
    case_id="TC-MAC-AGORA-REAL-LIFECYCLE",
    name="macOS Agora real lifecycle",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_core",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["leave_cleanup"],
    tags=["autorun-order:0"],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_real_lifecycle(session: BeaconSession) -> None:
    assert session.device("primary").agora.rtc_engine.load_sdk().code == 0


@beacon_test(
    case_id="TC-MAC-AGORA-AUDIO-ONLY-DIRECT-CALL",
    name="macOS Agora audio-only direct call",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_enhanced",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_success_fact", "audio_only_direct_call", "leave_cleanup"],
    token_bindings=[('audio-only-smoke', 1201)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_audio_only_direct_call(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    try:
        assert engine.join_channel(
            channel="audio-only-smoke", uid=1201, token="{{AGORA_RTC_TOKEN}}",
            auto_subscribe_audio=True, auto_subscribe_video=False,
            publish_camera=False, publish_microphone=True,
        ).code == 0
        engine.on_join_channel_success.wait(match={"uid": 1201}, timeout_s=5)
    finally:
        assert engine.leave_channel().code == 0
