"""迁移 ZEGO 双 Agent 房间连通用例。"""

import os

from beacon_test import BeaconSession, beacon_test


ROOM_ID = os.environ.get("ZEGO_1V1_ROOM_ID") or "beacon-zego-1v1-room"
PRIMARY_USER = os.environ.get("ZEGO_USER1_ID") or "beacon-zego-primary"
PEER_USER = os.environ.get("ZEGO_USER2_ID") or "beacon-zego-peer"


@beacon_test(
    case_id="TC-PY-ZEGO-L1-1V1-ROOM-CONNECTED",
    name="Python native ZEGO Express 1V1 room connectivity",
    platform="mac",
    devices=["primary", "peer"],
    suite="python_native_zego_1v1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["engine_lifecycle", "room_login", "room_logout", "room_state_observability"],
    tags=["zego", "python_source", "l1", "one_to_one"],
    sdk_names=["zego_express"],
)
def test_zego_1v1_room_connected(session: BeaconSession) -> None:
    for role in ("primary", "peer"):
        assert session.device(role).zego_express.zego_engine.create_engine_with_profile().code == 0
    try:
        for role, user_id, token_name in (
            ("primary", PRIMARY_USER, "ZEGO_USER1_TOKEN"),
            ("peer", PEER_USER, "ZEGO_USER2_TOKEN"),
        ):
            room = session.device(role).zego_express.zego_room
            assert room.login_room(room_id=ROOM_ID, user_id=user_id, token=f"{{{{{token_name}}}}}").code == 0
            room.on_room_state_update.wait(match={"room_id": ROOM_ID, "state": 2, "error_code": 0}, timeout_s=5)
    finally:
        for role in ("peer", "primary"):
            room = session.device(role).zego_express.zego_room
            engine = session.device(role).zego_express.zego_engine
            try:
                assert room.logout_room().code == 0
            finally:
                assert engine.destroy_engine().code == 0
