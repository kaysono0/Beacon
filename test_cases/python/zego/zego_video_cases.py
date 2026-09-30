"""ZEGO 双 Agent 发布、播放、快照场景。"""

import os

from beacon_test import BeaconSession, beacon_test


ROOM_ID = os.environ.get("ZEGO_1V1_ROOM_ID") or "beacon-zego-1v1-room"
PRIMARY_USER = os.environ.get("ZEGO_USER1_ID") or "beacon-zego-primary"
PEER_USER = os.environ.get("ZEGO_USER2_ID") or "beacon-zego-peer"
PRIMARY_STREAM = "beacon-zego-primary-video"
PEER_STREAM = "beacon-zego-peer-video"


def _run_video(session: BeaconSession, *, synthetic_peer: bool) -> None:
    primary = session.device("primary").zego_express
    peer = session.device("peer").zego_express
    try:
        assert primary.zego_engine.create_engine_with_profile().code == 0
        assert peer.zego_engine.create_engine_with_profile().code == 0
        if synthetic_peer:
            assert peer.zego_publisher.start_synthetic_video(width=320, height=180, fps=15, pattern="animated_clip").code == 0
        for client, user_id, token_name in (
            (primary, PRIMARY_USER, "ZEGO_USER1_TOKEN"),
            (peer, PEER_USER, "ZEGO_USER2_TOKEN"),
        ):
            assert client.zego_room.login_room(room_id=ROOM_ID, user_id=user_id, token=f"{{{{{token_name}}}}}").code == 0
            client.zego_room.on_room_state_update.wait(match={"room_id": ROOM_ID, "state": 2, "error_code": 0}, timeout_s=5)
        assert primary.zego_preview.start_preview(view_role="primary_local_preview").code == 0
        assert peer.zego_preview.start_preview(view_role="peer_local_preview").code == 0
        for client, stream in ((primary, PRIMARY_STREAM), (peer, PEER_STREAM)):
            assert client.zego_publisher.start_publishing_stream(stream_id=stream).code == 0
            client.zego_publisher.on_publisher_state_update.wait(match={"stream_id": stream, "error_code": 0}, timeout_s=15)
        for client, stream, view_role in (
            (primary, PEER_STREAM, "primary_remote_view"),
            (peer, PRIMARY_STREAM, "peer_remote_view"),
        ):
            assert client.zego_player.start_playing_stream(stream_id=stream, view_role=view_role).code == 0
            client.zego_player.on_player_render_video_first_frame.wait(match={"stream_id": stream}, timeout_s=15)
        assert session.device("primary").beacon_system.clock.wait_in_ms(ms=10000, timeout_s=15).code == 0
        for client, view_role in ((primary, "primary_remote_view"), (peer, "peer_remote_view")):
            assert client.zego_visual_probe.capture_snapshot(view_role=view_role).code == 0
            client.zego_visual_probe.on_rendered_view_snapshot.wait(match={"view_role": view_role, "err_code": 0}, timeout_s=5)
    finally:
        assert primary.zego_player.stop_playing_stream(stream_id=PEER_STREAM).code == 0
        assert peer.zego_player.stop_playing_stream(stream_id=PRIMARY_STREAM).code == 0
        for client in (peer, primary):
            assert client.zego_publisher.stop_publishing_stream().code == 0
            assert client.zego_preview.stop_preview().code == 0
        if synthetic_peer:
            assert peer.zego_publisher.stop_synthetic_video().code == 0
        for client, role in ((peer, "peer"), (primary, "primary")):
            for view_role in (f"{role}_remote_view", f"{role}_local_preview"):
                assert client.zego_visual_probe.release_view(view_role=view_role).code == 0
            assert client.zego_room.logout_room().code == 0
            assert client.zego_engine.destroy_engine().code == 0


@beacon_test(
    case_id="TC-PY-ZEGO-L1-1V1-VIDEO-RENDER-SNAPSHOT",
    name="Python native ZEGO Express 1V1 publish subscribe render and snapshot",
    platform="mac",
    devices=["primary", "peer"],
    suite="python_native_zego_1v1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["stream_publish", "stream_play", "local_video_preview", "visual_snapshot_observability"],
    tags=["zego", "python_source", "l1", "one_to_one", "video"],
    sdk_names=["zego_express"],
)
def test_zego_1v1_video_render_snapshot(session: BeaconSession) -> None:
    _run_video(session, synthetic_peer=False)


@beacon_test(
    case_id="TC-PY-ZEGO-L1-1V1-VIDEO-SYNTH-RENDER-SNAPSHOT",
    name="Python native ZEGO Express 1V1 camera and synthetic video render and snapshot",
    platform="mac",
    devices=["primary", "peer"],
    suite="python_native_zego_1v1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["stream_publish", "stream_play", "local_video_preview", "synthetic_video_source", "visual_snapshot_observability"],
    tags=["zego", "python_source", "l1", "one_to_one", "video", "synthetic"],
    sdk_names=["zego_express"],
)
def test_zego_1v1_synthetic_video_render_snapshot(session: BeaconSession) -> None:
    _run_video(session, synthetic_peer=True)
