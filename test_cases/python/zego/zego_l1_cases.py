"""ZEGO Express L1：引擎生命周期和房间状态回调。"""

import os

from beacon_test import BeaconSession, beacon_test


ROOM_ID = os.environ.get("ZEGO_RTC_ROOM_ID") or "beacon-zego-l1-room"
USER_ID = os.environ.get("ZEGO_USER1_ID") or "beacon-zego-l1-user"


def _engine(session: BeaconSession):
    return session.device("primary").zego_express.zego_engine


def _room(session: BeaconSession):
    return session.device("primary").zego_express.zego_room


@beacon_test(
    case_id="TC-PY-ZEGO-L1-LIFECYCLE",
    name="Python native ZEGO Express engine lifecycle",
    platform="mac",
    devices=["primary"],
    suite="python_native_zego_l1",
    scenario_family="sdk_lifecycle",
    implementation_status="runnable",
    covered_capabilities=["engine_lifecycle"],
    tags=["zego", "python_source", "l1"],
    sdk_names=["zego_express"],
)
def test_zego_lifecycle(session: BeaconSession) -> None:
    assert _engine(session).create_engine_with_profile().code == 0
    assert _engine(session).destroy_engine().code == 0


@beacon_test(
    case_id="TC-PY-ZEGO-L1-LOGIN-CALLBACK",
    name="Python native ZEGO Express room login callback",
    platform="mac",
    devices=["primary"],
    suite="python_native_zego_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["engine_lifecycle", "room_login", "room_state_observability"],
    tags=["zego", "python_source", "l1"],
    sdk_names=["zego_express"],
)
def test_zego_login_callback(session: BeaconSession) -> None:
    assert _engine(session).create_engine_with_profile().code == 0
    try:
        assert _room(session).login_room(
            room_id=ROOM_ID, user_id=USER_ID, token="{{ZEGO_USER1_TOKEN}}"
        ).code == 0
        _room(session).on_room_state_update.wait(
            match={"room_id": ROOM_ID, "state": 2, "error_code": 0}, timeout_s=5
        )
    finally:
        try:
            assert _room(session).logout_room().code == 0
        finally:
            assert _engine(session).destroy_engine().code == 0


@beacon_test(
    case_id="TC-PY-ZEGO-L1-LOGOUT-CALLBACK",
    name="Python native ZEGO Express room logout callback",
    platform="mac",
    devices=["primary"],
    suite="python_native_zego_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["engine_lifecycle", "room_login", "room_logout", "room_state_observability"],
    tags=["zego", "python_source", "l1"],
    sdk_names=["zego_express"],
)
def test_zego_logout_callback(session: BeaconSession) -> None:
    assert _engine(session).create_engine_with_profile().code == 0
    try:
        assert _room(session).login_room(
            room_id=ROOM_ID, user_id=USER_ID, token="{{ZEGO_USER1_TOKEN}}"
        ).code == 0
        _room(session).on_room_state_update.wait(
            match={"room_id": ROOM_ID, "state": 2, "error_code": 0}, timeout_s=5
        )
        assert _room(session).logout_room().code == 0
        _room(session).on_room_state_update.wait(
            match={"room_id": ROOM_ID, "state": 0, "error_code": 0}, timeout_s=5
        )
    finally:
        assert _engine(session).destroy_engine().code == 0
