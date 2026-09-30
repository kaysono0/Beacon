"""火山 RTC L1：保留原生 engine/room 生命周期和回调目标。"""

import os

from beacon_test import BeaconSession, beacon_test


PRIMARY_ROOM = os.environ.get("VOLCENGINE_RTC_ROOM_ID") or "volcengine-l1-room"
PRIMARY_USER = os.environ.get("VOLCENGINE_RTC_USER_ID") or "volcengine-l1-user"


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-LIFECYCLE",
    name="Python native Volcengine engine lifecycle",
    platform="mac",
    devices=["primary"],
    suite="python_native_volcengine_l1",
    scenario_family="sdk_lifecycle",
    implementation_status="runnable",
    covered_capabilities=["engine_lifecycle"],
    tags=["volcengine", "python_source", "l1"],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_lifecycle(session: BeaconSession) -> None:
    engine = session.device("primary").volcengine_rtc.byte_rtc_engine
    assert engine.create_rtc_engine(app_id="beacon-test").code == 0
    assert engine.destroy_rtc_engine().code == 0


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-JOIN-CALLBACK",
    name="Python native Volcengine join success callback",
    platform="mac",
    devices=["primary"],
    suite="python_native_volcengine_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["room_join"],
    tags=["volcengine", "python_source", "l1"],
    token_bindings=[(PRIMARY_ROOM, PRIMARY_USER)],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_join_callback(session: BeaconSession) -> None:
    engine = session.device("primary").volcengine_rtc.byte_rtc_engine
    room = session.device("primary").volcengine_rtc.byte_rtc_room
    assert engine.create_rtc_engine(app_id="beacon-test").code == 0
    assert room.join_room(
        room_id=PRIMARY_ROOM, user_id=PRIMARY_USER, token="{{VOLCENGINE_RTC_TOKEN}}"
    ).code == 0
    room.on_room_state_changed.wait(match={"room_id": PRIMARY_ROOM, "state": 0}, timeout_s=5)


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-CONNECTION-STATE",
    name="Python native Volcengine connection state transition",
    platform="mac",
    devices=["primary"],
    suite="python_native_volcengine_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["engine_connection_state"],
    tags=["volcengine", "python_source", "l1"],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_connection_state(session: BeaconSession) -> None:
    engine = session.device("primary").volcengine_rtc.byte_rtc_engine
    # 会话清理保留引擎；复用已连接引擎不会重新触发连接态回调。
    assert engine.destroy_rtc_engine().code == 0
    try:
        assert engine.create_rtc_engine(app_id="beacon-test").code == 0
        engine.on_connection_state_changed.wait(match={"state": 3}, timeout_s=5)
    finally:
        assert engine.destroy_rtc_engine().code == 0


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP",
    name="Python native Volcengine leave cleanup without a joined query",
    platform="mac",
    devices=["primary"],
    suite="python_native_volcengine_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["room_leave"],
    tags=["volcengine", "python_source", "l1"],
    token_bindings=[(PRIMARY_ROOM, PRIMARY_USER)],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_leave_cleanup(session: BeaconSession) -> None:
    engine = session.device("primary").volcengine_rtc.byte_rtc_engine
    room = session.device("primary").volcengine_rtc.byte_rtc_room
    assert engine.create_rtc_engine(app_id="beacon-test").code == 0
    assert room.join_room(
        room_id=PRIMARY_ROOM, user_id=PRIMARY_USER, token="{{VOLCENGINE_RTC_TOKEN}}"
    ).code == 0
    assert room.leave_room().code == 0
    room.on_leave_room.wait(match={"room_id": PRIMARY_ROOM}, timeout_s=5)


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-INVALID-TOKEN",
    name="Python native Volcengine invalid token failure",
    platform="mac",
    devices=["primary"],
    suite="python_native_volcengine_l1",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["room_join", "engine_error_events"],
    tags=["volcengine", "python_source", "l1"],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_invalid_token(session: BeaconSession) -> None:
    engine = session.device("primary").volcengine_rtc.byte_rtc_engine
    room = session.device("primary").volcengine_rtc.byte_rtc_room
    assert engine.create_rtc_engine(app_id="beacon-test").code == 0
    result = room.join_room(
        room_id=PRIMARY_ROOM, user_id=PRIMARY_USER, token="invalid-token",
        _extra={"token_fixture": "invalid_for_testing"},
        check=False,
    )
    assert result.code == 401


@beacon_test(
    case_id="TC-PY-VOLCENGINE-L1-RUNTIME-CLEANUP-BASELINE",
    name="Python native Volcengine runtime cleanup baseline",
    platform="mac",
    devices=["primary"],
    suite="python_native_volcengine_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["room_leave", "engine_lifecycle"],
    tags=["volcengine", "python_source", "l1", "runtime-reset-baseline"],
    sdk_names=["volcengine_rtc"],
)
def test_volcengine_runtime_cleanup_baseline(session: BeaconSession) -> None:
    room = session.device("primary").volcengine_rtc.byte_rtc_room
    engine = session.device("primary").volcengine_rtc.byte_rtc_engine
    assert room.leave_room().code == 0
    assert engine.destroy_rtc_engine().code == 0
