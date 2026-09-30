"""Agora 双流低高层切换与统计证据。"""

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE",
    name="macOS Agora 1V1 simulcast high and low layer toggle",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_enhanced",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["synthetic_video_source", "simulcast_dual_stream", "remote_video_layer_selection", "simulcast_layer_observability"],
    token_bindings=[('real-smoke-simulcast', 1001), ('real-smoke-simulcast', 1002)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_1v1_simulcast_layer_toggle(session: BeaconSession) -> None:
    primary_device = session.device("primary")
    primary = primary_device.agora.rtc_engine
    visual = primary_device.agora.visual_probe
    peer = session.device("peer").agora.rtc_engine
    try:
        assert primary.join_channel(channel="real-smoke-simulcast", uid=1001, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_video=True).code == 0
        primary.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=15)
        assert peer.load_sdk().code == 0
        assert peer.set_dual_stream_mode(mode="enabled", low_width=480, low_height=200, low_bitrate=150, low_fps=15).code == 0
        assert peer.start_synthetic_video(width=960, height=400, fps=15, pattern="paired_media_clip").code == 0
        assert peer.join_channel(channel="real-smoke-simulcast", uid=1002, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_video=True, publish_camera=True).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1002}, timeout_s=15)
        assert visual.bind_remote_video(uid=1002, view_role="primary_remote_view").code == 0
        assert primary_device.beacon_system.video_host.show().code == 0
        assert primary.set_remote_video_stream(uid=1002, stream_type="low").code == 0
        low = primary.on_remote_video_stats.wait(match={"uid": 1002, "rx_stream_type": 1}, timeout_s=15)
        assert low.payload["width"] > 0 and low.payload["height"] > 0 and low.payload["received_bitrate"] > 0
        assert primary.set_remote_video_stream(uid=1002, stream_type="high").code == 0
        high = primary.on_remote_video_stats.wait(match={"uid": 1002, "rx_stream_type": 0}, after_cursor=low.cursor, timeout_s=15)
        assert high.payload["width"] > low.payload["width"]
        assert high.payload["height"] > low.payload["height"]
        assert high.payload["received_bitrate"] > 0
        assert high.payload["received_bitrate"] != low.payload["received_bitrate"]
    finally:
        assert visual.release_view(view_role="primary_remote_view").code == 0
        assert primary_device.beacon_system.video_host.hide().code == 0
        assert peer.stop_synthetic_video().code == 0
        assert peer.leave_channel().code == 0
        assert primary.leave_channel().code == 0
