"""Agora 配对合成媒体的音频静音与恢复。"""

from time import monotonic, sleep

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-1V1-AUDIO-PLAYBACK-MUTE-RECOVER",
    name="macOS Agora 1V1 paired audio-video playback, mute, and recovery",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_enhanced",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_channel", "synthetic_video_source", "remote_video_rendering", "remote_video_stats_observability", "local_audio_control", "remote_audio_stats_observability", "leave_channel"],
    token_bindings=[('real-smoke-1v1-audible-audio-mute-recover', 1312), ('real-smoke-1v1-audible-audio-mute-recover', 1311)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_1v1_audio_playback_mute_recover(session: BeaconSession) -> None:
    primary_device = session.device("primary")
    primary = primary_device.agora.rtc_engine
    peer = session.device("peer").agora.rtc_engine
    visual = primary_device.agora.visual_probe
    try:
        assert primary.load_sdk().code == 0
        assert peer.load_sdk().code == 0
        assert peer.start_synthetic_video(width=960, height=400, fps=15, pattern="paired_media_clip").code == 0
        assert peer.join_channel(channel="real-smoke-1v1-audible-audio-mute-recover", uid=1312, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_camera=True, publish_microphone=False, publish_synthetic_audio=True).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1312}, timeout_s=15)
        assert primary.join_channel(channel="real-smoke-1v1-audible-audio-mute-recover", uid=1311, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_camera=False, publish_microphone=False).code == 0
        primary.on_join_channel_success.wait(match={"uid": 1311}, timeout_s=15)
        assert visual.bind_remote_video(uid=1312, view_role="primary_remote_view").code == 0
        assert primary.get_connection_state().code == 0
        frame = primary.on_first_remote_video_frame.wait(match={"uid": 1312}, timeout_s=30)
        assert frame.payload["width"] > 0 and frame.payload["height"] > 0
        first_video = primary.on_remote_video_stats.wait(match={"uid": 1312}, timeout_s=30)
        deadline = monotonic() + 30
        first_audio = primary.on_remote_audio_stats.wait(match={"uid": 1312}, timeout_s=30)
        while first_audio.payload["received_bitrate"] == 0 and monotonic() < deadline:
            first_audio = primary.on_remote_audio_stats.wait(match={"uid": 1312}, after_cursor=first_audio.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert first_audio.payload["received_bitrate"] > 0
        first_rtc = primary.on_rtc_stats.wait(timeout_s=30)
        assert first_video.payload["received_bitrate"] > 0
        assert visual.capture_snapshot(view_role="primary_remote_view").code == 0
        primary.on_snapshot_taken.wait(match={"view_role": "primary_remote_view", "err_code": 0}, timeout_s=5)
        # 展示等待留在 Runner，避免阻塞 Agent 接收取消后的清理命令。
        sleep(10)
        assert peer.enable_local_audio(enabled=False).code == 0
        sleep(10)
        assert peer.enable_local_audio(enabled=True).code == 0
        assert primary.get_connection_state().code == 0
        recovered_video = primary.on_remote_video_stats.wait(match={"uid": 1312}, after_cursor=first_video.cursor, timeout_s=30)
        deadline = monotonic() + 30
        recovered_audio = primary.on_remote_audio_stats.wait(match={"uid": 1312}, after_cursor=first_audio.cursor, timeout_s=30)
        while recovered_audio.payload["received_bitrate"] == 0 and monotonic() < deadline:
            recovered_audio = primary.on_remote_audio_stats.wait(match={"uid": 1312}, after_cursor=recovered_audio.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert recovered_audio.payload["received_bitrate"] > 0
        primary.on_rtc_stats.wait(after_cursor=first_rtc.cursor, timeout_s=30)
        assert recovered_video.payload["received_bitrate"] > 0
        sleep(10)
    finally:
        assert visual.release_view(view_role="primary_remote_view").code == 0
        assert primary.leave_channel().code == 0
        assert peer.leave_channel().code == 0
        assert peer.stop_synthetic_video().code == 0
