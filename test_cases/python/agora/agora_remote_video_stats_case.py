"""迁移 Agora 双角色远端视频统计与快照用例。"""

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-REMOTE-VIDEO-STATS-OBSERVABLE",
    name="macOS Agora L2 remote video stats observable",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_l2",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["media_stats_observability"],
    token_bindings=[('real-smoke-remote-video-stats', 1001), ('real-smoke-remote-video-stats', 1002)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_remote_video_stats_observable(session: BeaconSession) -> None:
    primary = session.device("primary").agora.rtc_engine
    peer = session.device("peer").agora.rtc_engine
    peer_preview = session.device("peer").agora.video_preview
    peer_visual = session.device("peer").agora.visual_probe
    primary_visual = session.device("primary").agora.visual_probe
    try:
        assert primary.join_channel(channel="real-smoke-remote-video-stats", uid=1001, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True).code == 0
        primary.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
        assert peer.join_channel(channel="real-smoke-remote-video-stats", uid=1002, token="{{AGORA_RTC_TOKEN}}", publish_camera=True).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1002}, timeout_s=5)
        assert peer_visual.bind_local_video(view_role="local_preview").code == 0
        assert peer_preview.start_preview().code == 0
        assert primary_visual.bind_remote_video(uid=1002, view_role="primary_remote_view").code == 0
        assert primary.get_connection_state().code == 0
        first_frame = primary.on_first_remote_video_frame.wait(match={"uid": 1002}, timeout_s=20)
        assert first_frame.payload["width"] > 0 and first_frame.payload["height"] > 0
        stats = primary.on_remote_video_stats.wait(match={"uid": 1002}, timeout_s=20)
        assert stats.payload["width"] > 0 and stats.payload["height"] > 0
        assert stats.payload["received_bitrate"] > 0
        assert primary_visual.capture_snapshot(view_role="primary_remote_view").code == 0
        primary.on_snapshot_taken.wait(match={"view_role": "primary_remote_view", "err_code": 0}, timeout_s=5)
    finally:
        assert peer_preview.stop_preview().code == 0
        assert peer.leave_channel().code == 0
        assert primary.leave_channel().code == 0
        assert primary_visual.release_view(view_role="primary_remote_view").code == 0
