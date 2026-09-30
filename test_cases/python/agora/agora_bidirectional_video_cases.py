"""Agora 双角色视频显示与合成源用例。"""

from time import sleep

from beacon_test import BeaconSession, beacon_test


def _run_bidirectional_video(session: BeaconSession, *, synthetic_peer: bool) -> None:
    primary = session.device("primary").agora.rtc_engine
    peer = session.device("peer").agora.rtc_engine
    primary_visual = session.device("primary").agora.visual_probe
    peer_visual = session.device("peer").agora.visual_probe
    primary_preview = session.device("primary").agora.video_preview
    peer_preview = session.device("peer").agora.video_preview
    channel = "real-smoke-1v1-synth" if synthetic_peer else "real-smoke-1v1-visual"
    try:
        assert primary_visual.bind_local_video(view_role="primary_local_preview").code == 0
        assert primary_preview.start_preview().code == 0
        assert primary.join_channel(channel=channel, uid=1001, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_camera=True, publish_microphone=True).code == 0
        primary.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=15)
        if synthetic_peer:
            assert peer.load_sdk().code == 0
            assert peer.start_synthetic_video(width=320, height=180, fps=15, pattern="animated_clip").code == 0
        assert peer_visual.bind_local_video(view_role="peer_local_preview").code == 0
        assert peer_preview.start_preview().code == 0
        assert peer.join_channel(channel=channel, uid=1002, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_camera=True, publish_microphone=True).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1002}, timeout_s=15)
        assert primary_visual.bind_remote_video(uid=1002, view_role="primary_remote_view").code == 0
        assert peer_visual.bind_remote_video(uid=1001, view_role="peer_remote_view").code == 0
        for engine, uid in ((primary, 1002), (peer, 1001)):
            frame = engine.on_first_remote_video_frame.wait(match={"uid": uid}, timeout_s=20)
            assert frame.payload["width"] > 0 and frame.payload["height"] > 0
        # 展示等待留在 Runner，避免阻塞 Agent 接收取消后的清理命令。
        sleep(10)
        for visual, engine, view_role in (
            (primary_visual, primary, "primary_local_preview"),
            (primary_visual, primary, "primary_remote_view"),
            (peer_visual, peer, "peer_local_preview"),
            (peer_visual, peer, "peer_remote_view"),
        ):
            assert visual.capture_snapshot(view_role=view_role).code == 0
            engine.on_snapshot_taken.wait(match={"view_role": view_role, "err_code": 0}, timeout_s=5)
    finally:
        assert primary_preview.stop_preview().code == 0
        assert peer_preview.stop_preview().code == 0
        assert peer.leave_channel().code == 0
        assert primary.leave_channel().code == 0
        for visual, view_role in (
            (primary_visual, "primary_local_preview"),
            (primary_visual, "primary_remote_view"),
            (peer_visual, "peer_local_preview"),
            (peer_visual, "peer_remote_view"),
        ):
            assert visual.release_view(view_role=view_role).code == 0
        if synthetic_peer:
            assert peer.stop_synthetic_video().code == 0


@beacon_test(
    case_id="TC-MAC-AGORA-1V1-REMOTE-VIDEO-RENDERED",
    name="macOS Agora 1V1 bidirectional remote video rendered",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_enhanced",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["remote_video_rendering"],
    token_bindings=[('real-smoke-1v1-visual', 1001), ('real-smoke-1v1-visual', 1002)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_1v1_remote_video_rendered(session: BeaconSession) -> None:
    _run_bidirectional_video(session, synthetic_peer=False)


@beacon_test(
    case_id="TC-MAC-AGORA-1V1-REMOTE-VIDEO-SYNTH-PEER",
    name="macOS Agora 1V1 remote video rendered with synthetic peer source",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_enhanced",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["synthetic_video_source", "remote_video_rendering"],
    token_bindings=[('real-smoke-1v1-synth', 1001), ('real-smoke-1v1-synth', 1002)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_1v1_remote_video_synth_peer(session: BeaconSession) -> None:
    _run_bidirectional_video(session, synthetic_peer=True)
