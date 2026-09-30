"""Agora 摄像头与分段 MediaPlayer 的多宫格用例。"""

from time import sleep

from beacon_test import BeaconSession, beacon_test


GRID_MEDIA_SOURCE = "test_cases/media/grid_segments.mp4"
GRID_SEGMENTS = (
    ("segment_1", 1401, 0),
    ("segment_2", 1402, 60_000),
    ("segment_3", 1403, 120_000),
    ("segment_4", 1404, 180_000),
    ("segment_5", 1405, 240_000),
    ("segment_6", 1406, 300_000),
    ("segment_7", 1407, 360_000),
    ("segment_8", 1408, 420_000),
)


def _run_grid(session: BeaconSession, *, channel: str, segments: tuple[tuple[str, int, int], ...]) -> None:
    primary_device = session.device("primary")
    primary = primary_device.agora
    try:
        assert primary.rtc_engine.load_sdk().code == 0
        assert primary.visual_probe.bind_local_video(view_role="primary_grid_camera").code == 0
        assert primary.video_preview.start_preview().code == 0
        assert primary.rtc_engine.join_channel(channel=channel, uid=1400, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=False, auto_subscribe_video=True, publish_camera=True, publish_microphone=False).code == 0
        primary.rtc_engine.on_join_channel_success.wait(match={"uid": 1400}, timeout_s=15)
        for role, uid, start_pos_ms in segments:
            client = session.device(role).agora
            assert client.rtc_engine.load_sdk().code == 0
            assert client.media_player.open_media_player(source_path=GRID_MEDIA_SOURCE, start_pos_ms=start_pos_ms).code == 0
            client.media_player.on_media_player_state_changed.wait(match={"state": 2, "reason": 0}, timeout_s=15)
            assert client.rtc_engine.join_channel(channel=channel, uid=uid, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=False, auto_subscribe_video=True, publish_camera=False, publish_microphone=False, publish_media_player=True).code == 0
            client.rtc_engine.on_join_channel_success.wait(match={"uid": uid}, timeout_s=15)
        for role, uid, _ in segments:
            assert primary.visual_probe.bind_remote_video(uid=uid, view_role=f"primary_grid_{role}").code == 0
        for role, _, _ in segments:
            assert session.device(role).agora.media_player.play_media_player().code == 0
        assert primary.rtc_engine.get_connection_state().code == 0
        for _, uid, _ in segments:
            stats = primary.rtc_engine.on_remote_video_stats.wait(match={"uid": uid}, timeout_s=30)
            assert stats.payload["width"] > 0 and stats.payload["height"] > 0
            assert stats.payload["received_bitrate"] > 0
        # 展示等待留在 Runner，避免阻塞 Agent 接收取消后的清理命令。
        sleep(10)
        for view_role in ("primary_grid_camera", *(f"primary_grid_{role}" for role, _, _ in segments)):
            assert primary.visual_probe.capture_snapshot(view_role=view_role).code == 0
            primary.rtc_engine.on_snapshot_taken.wait(match={"view_role": view_role, "err_code": 0}, timeout_s=5)
    finally:
        for role, _, _ in segments:
            assert primary.visual_probe.release_view(view_role=f"primary_grid_{role}").code == 0
        assert primary.video_preview.stop_preview().code == 0
        assert primary.visual_probe.release_view(view_role="primary_grid_camera").code == 0
        assert primary.rtc_engine.leave_channel().code == 0
        for role, _, _ in segments:
            client = session.device(role).agora
            assert client.media_player.stop_media_player().code == 0
            assert client.rtc_engine.leave_channel().code == 0


@beacon_test(
    case_id="TC-MAC-AGORA-4-GRID-CAMERA-MEDIA-SEGMENTS",
    name="macOS Agora 4-grid camera with three MediaPlayer time segments",
    platform="mac",
    devices=["primary", "segment_1", "segment_4", "segment_7"],
    suite="agora_direct_call_enhanced",
    scenario_family="grid_media_demo",
    implementation_status="runnable",
    covered_capabilities=["join_channel", "media_player_source", "remote_video_rendering", "remote_video_stats_observability", "visual_snapshot_observability", "leave_channel"],
    token_bindings=[('real-smoke-4-grid-media-segments', 1400), ('real-smoke-4-grid-media-segments', 1401), ('real-smoke-4-grid-media-segments', 1404), ('real-smoke-4-grid-media-segments', 1407)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_4_grid_camera_media_segments(session: BeaconSession) -> None:
    _run_grid(session, channel="real-smoke-4-grid-media-segments", segments=(GRID_SEGMENTS[0], GRID_SEGMENTS[3], GRID_SEGMENTS[6]))


@beacon_test(
    case_id="TC-MAC-AGORA-9-GRID-CAMERA-MEDIA-SEGMENTS",
    name="macOS Agora 9-grid camera with eight MediaPlayer time segments",
    platform="mac",
    devices=["primary", "segment_1", "segment_2", "segment_3", "segment_4", "segment_5", "segment_6", "segment_7", "segment_8"],
    suite="agora_direct_call_enhanced",
    scenario_family="grid_media_demo",
    implementation_status="runnable",
    covered_capabilities=["join_channel", "media_player_source", "remote_video_rendering", "remote_video_stats_observability", "visual_snapshot_observability", "leave_channel"],
    token_bindings=[('real-smoke-9-grid-media-segments', 1400), ('real-smoke-9-grid-media-segments', 1401), ('real-smoke-9-grid-media-segments', 1402), ('real-smoke-9-grid-media-segments', 1403), ('real-smoke-9-grid-media-segments', 1404), ('real-smoke-9-grid-media-segments', 1405), ('real-smoke-9-grid-media-segments', 1406), ('real-smoke-9-grid-media-segments', 1407), ('real-smoke-9-grid-media-segments', 1408)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_9_grid_camera_media_segments(session: BeaconSession) -> None:
    _run_grid(session, channel="real-smoke-9-grid-media-segments", segments=GRID_SEGMENTS)
