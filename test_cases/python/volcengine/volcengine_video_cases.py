"""火山引擎双角色视频与四视图快照用例。"""

import os

from beacon_test import BeaconSession, beacon_test


ROOM_ID = os.environ.get("VOLCENGINE_RTC_ROOM_ID") or "volcengine-1v1-room"
PRIMARY_USER = os.environ.get("VOLCENGINE_RTC_PRIMARY_USER_ID") or "volcengine-1v1-primary"
PEER_USER = os.environ.get("VOLCENGINE_RTC_PEER_USER_ID") or "volcengine-1v1-peer"


def _run_video(session: BeaconSession, *, width: int, height: int, pattern: str) -> None:
    primary_device = session.device("primary")
    peer_device = session.device("peer")
    primary = primary_device.volcengine_rtc.byte_rtc_engine
    peer = peer_device.volcengine_rtc.byte_rtc_engine
    primary_room = primary_device.volcengine_rtc.byte_rtc_room
    peer_room = peer_device.volcengine_rtc.byte_rtc_room
    primary_visual = primary_device.volcengine_rtc.visual_probe
    peer_visual = peer_device.volcengine_rtc.visual_probe
    try:
        assert primary.create_rtc_engine(app_id="beacon-test").code == 0
        assert primary.start_video_capture().code == 0
        assert primary_visual.bind_local_video(view_role="primary_local_preview").code == 0
        assert primary_room.join_room(room_id=ROOM_ID, user_id=PRIMARY_USER, token="{{VOLCENGINE_RTC_TOKEN}}", publish_video=True, auto_subscribe_video=True).code == 0
        primary_room.on_room_state_changed.wait(match={"room_id": ROOM_ID, "state": 0}, timeout_s=5)
        assert peer.create_rtc_engine(app_id="beacon-test").code == 0
        assert peer.start_synthetic_video(width=width, height=height, fps=15, pattern=pattern).code == 0
        assert peer_visual.bind_local_video(view_role="peer_local_preview").code == 0
        assert peer_room.join_room(room_id=ROOM_ID, user_id=PEER_USER, token="{{VOLCENGINE_RTC_TOKEN}}", publish_video=True, auto_subscribe_video=True).code == 0
        peer_room.on_room_state_changed.wait(match={"room_id": ROOM_ID, "state": 0}, timeout_s=5)
        assert primary_visual.bind_remote_video(uid=PEER_USER, view_role="primary_remote_view").code == 0
        assert peer_visual.bind_remote_video(uid=PRIMARY_USER, view_role="peer_remote_view").code == 0
        for engine, remote_user in ((primary, PEER_USER), (peer, PRIMARY_USER)):
            frame = engine.on_first_remote_video_frame.wait(match={"uid": remote_user}, timeout_s=20)
            assert frame.payload["width"] > 0 and frame.payload["height"] > 0
        assert primary_device.beacon_system.clock.wait_in_ms(ms=10000, timeout_s=15).code == 0
        for visual, engine, view_role in (
            (primary_visual, primary, "primary_local_preview"),
            (primary_visual, primary, "primary_remote_view"),
            (peer_visual, peer, "peer_local_preview"),
            (peer_visual, peer, "peer_remote_view"),
        ):
            assert visual.capture_snapshot(view_role=view_role).code == 0
            engine.on_snapshot_taken.wait(match={"view_role": view_role, "err_code": 0}, timeout_s=5)
    finally:
        assert peer.stop_synthetic_video().code == 0
        assert primary.stop_video_capture().code == 0
        assert peer_room.leave_room().code == 0
        assert primary_room.leave_room().code == 0
        for visual, view_role in (
            (primary_visual, "primary_local_preview"),
            (primary_visual, "primary_remote_view"),
            (peer_visual, "peer_local_preview"),
            (peer_visual, "peer_remote_view"),
        ):
            assert visual.release_view(view_role=view_role).code == 0


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH",
    name="Python native Volcengine 1V1 remote video with synthetic peer source",
    platform="mac",
    devices=["primary", "peer"],
    suite="python_native_volcengine_1v1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["engine_video_capture", "visual_probe", "synthetic_video_source", "remote_video_rendering", "visual_snapshot_observability"],
    tags=["volcengine", "python_source", "l1"],
    token_bindings=[(ROOM_ID, PRIMARY_USER), (ROOM_ID, PEER_USER)],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_1v1_remote_video_synth(session: BeaconSession) -> None:
    _run_video(session, width=320, height=180, pattern="animated_clip")


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED",
    name="Python native Volcengine 1V1 remote video rendered with mock peer source",
    platform="mac",
    devices=["primary", "peer"],
    suite="python_native_volcengine_1v1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["engine_video_capture", "visual_probe", "synthetic_video_source", "remote_video_rendering", "visual_snapshot_observability"],
    tags=["volcengine", "python_source", "l1"],
    token_bindings=[(ROOM_ID, PRIMARY_USER), (ROOM_ID, PEER_USER)],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_1v1_remote_video_rendered(session: BeaconSession) -> None:
    _run_video(session, width=640, height=480, pattern="moving_stripe")
