"""Agora MediaPlayer 文件发布、暂停与恢复。"""

from time import monotonic, sleep

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-1V1-MEDIA-PLAYER-PAUSE-RESUME",
    name="macOS Agora 1V1 MediaPlayer file publish, pause, and resume",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_enhanced",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_channel", "media_player_source", "media_player_state_observability", "remote_video_rendering", "remote_video_stats_observability", "remote_audio_stats_observability", "visual_snapshot_observability", "leave_channel"],
    token_bindings=[('real-smoke-1v1-media-player-pause-resume', 1322), ('real-smoke-1v1-media-player-pause-resume', 1321)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_1v1_media_player_pause_resume(session: BeaconSession) -> None:
    primary_device = session.device("primary")
    primary = primary_device.agora.rtc_engine
    visual = primary_device.agora.visual_probe
    peer_device = session.device("peer")
    peer = peer_device.agora.rtc_engine
    player = peer_device.agora.media_player
    try:
        assert peer.load_sdk().code == 0
        assert player.open_media_player(source_path="test_cases/sample_960x400_ocean_with_audio.mp4").code == 0
        player.on_media_player_state_changed.wait(match={"state": 2, "reason": 0}, timeout_s=15)
        assert peer.join_channel(channel="real-smoke-1v1-media-player-pause-resume", uid=1322, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_camera=False, publish_microphone=False, publish_media_player=True).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1322}, timeout_s=15)
        assert primary.load_sdk().code == 0
        assert primary.join_channel(channel="real-smoke-1v1-media-player-pause-resume", uid=1321, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_camera=False, publish_microphone=False).code == 0
        primary.on_join_channel_success.wait(match={"uid": 1321}, timeout_s=15)
        assert visual.bind_remote_video(uid=1322, view_role="primary_remote_view").code == 0
        assert player.play_media_player().code == 0
        playing_state = player.on_media_player_state_changed.wait(match={"state": 3, "reason": 0}, timeout_s=5)
        assert primary.get_connection_state().code == 0
        frame = primary.on_first_remote_video_frame.wait(match={"uid": 1322}, timeout_s=30)
        assert frame.payload["width"] > 0 and frame.payload["height"] > 0
        first_video = primary.on_remote_video_stats.wait(match={"uid": 1322}, timeout_s=30)
        deadline = monotonic() + 30
        first_audio = primary.on_remote_audio_stats.wait(match={"uid": 1322}, timeout_s=30)
        while first_audio.payload["received_bitrate"] == 0 and monotonic() < deadline:
            first_audio = primary.on_remote_audio_stats.wait(match={"uid": 1322}, after_cursor=first_audio.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert first_audio.payload["received_bitrate"] > 0
        assert first_video.payload["received_bitrate"] > 0
        # 展示等待留在 Runner，避免阻塞 Agent 接收取消后的清理命令。
        sleep(10)
        assert visual.capture_snapshot(view_role="primary_remote_view").code == 0
        playing_snapshot = primary.on_snapshot_taken.wait(match={"view_role": "primary_remote_view", "err_code": 0}, timeout_s=5)
        assert player.pause_media_player().code == 0
        paused_state = player.on_media_player_state_changed.wait(match={"state": 4, "reason": 0}, after_cursor=playing_state.cursor, timeout_s=5)
        sleep(10)
        assert visual.capture_snapshot(view_role="primary_remote_view").code == 0
        paused_snapshot = primary.on_snapshot_taken.wait(match={"view_role": "primary_remote_view", "err_code": 0}, after_cursor=playing_snapshot.cursor, timeout_s=5)
        assert player.resume_media_player().code == 0
        player.on_media_player_state_changed.wait(match={"state": 3, "reason": 0}, after_cursor=paused_state.cursor, timeout_s=5)
        sleep(10)
        assert primary.get_connection_state().code == 0
        recovered_video = primary.on_remote_video_stats.wait(match={"uid": 1322}, after_cursor=first_video.cursor, timeout_s=30)
        deadline = monotonic() + 30
        recovered_audio = primary.on_remote_audio_stats.wait(match={"uid": 1322}, after_cursor=first_audio.cursor, timeout_s=30)
        while recovered_audio.payload["received_bitrate"] == 0 and monotonic() < deadline:
            recovered_audio = primary.on_remote_audio_stats.wait(match={"uid": 1322}, after_cursor=recovered_audio.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert recovered_audio.payload["received_bitrate"] > 0
        assert recovered_video.payload["received_bitrate"] > 0
        assert visual.capture_snapshot(view_role="primary_remote_view").code == 0
        primary.on_snapshot_taken.wait(match={"view_role": "primary_remote_view", "err_code": 0}, after_cursor=paused_snapshot.cursor, timeout_s=5)
    finally:
        assert visual.release_view(view_role="primary_remote_view").code == 0
        assert primary.leave_channel().code == 0
        assert peer.leave_channel().code == 0
