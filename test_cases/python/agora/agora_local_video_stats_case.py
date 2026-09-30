"""迁移 Agora 本地视频统计用例，保留非零帧证据门槛。"""

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-LOCAL-VIDEO-STATS-OBSERVABLE",
    name="macOS Agora L2 local video stats observable",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l2",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["media_stats_observability"],
    token_bindings=[('real-smoke-local-video-stats', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_local_video_stats_observable(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    visual = session.device("primary").agora.visual_probe
    preview = session.device("primary").agora.video_preview
    try:
        assert engine.join_channel(channel="real-smoke-local-video-stats", uid=1001, token="{{AGORA_RTC_TOKEN}}", publish_camera=True).code == 0
        engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
        assert visual.bind_local_video(view_role="local_preview").code == 0
        assert preview.start_preview().code == 0
        assert engine.get_connection_state().code == 0
        stats = engine.on_local_video_stats.wait(timeout_s=5)
        assert stats.payload["capture_frame_rate"] > 0 and stats.payload["sent_frame_rate"] > 0
        assert stats.payload["sent_bitrate"] > 0
    finally:
        assert preview.stop_preview().code == 0
        assert engine.leave_channel().code == 0
