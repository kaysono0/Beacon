from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-PY-AGORA-SMOKE",
    name="Python native Agora smoke lifecycle",
    platform="mac",
    devices=["primary"],
    suite="python_native_phase_a",
    scenario_family="smoke",
    implementation_status="runnable",
    covered_capabilities=["sdk_lifecycle"],
    tags=["phase_a", "python_source"],
    sdk_names=["agora_rtc"],
)
def test_agora_smoke(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.load_sdk().code == 0
    assert engine.unload_sdk().code == 0


@beacon_test(
    case_id="TC-PY-AGORA-JOIN-CALLBACK",
    name="Python native Agora join callback",
    platform="mac",
    devices=["primary"],
    suite="python_native_phase_a",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_channel"],
    tags=["phase_a", "python_source"],
    token_bindings=[('room', 1001)],
    sdk_names=["agora_rtc"],
)
def test_agora_join_callback(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.join_channel(channel="room", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
    engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)


@beacon_test(
    case_id="TC-PY-AGORA-LEAVE-STATE",
    name="Python native Agora leave state cleanup",
    platform="mac",
    devices=["primary"],
    suite="python_native_phase_a",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["leave_channel", "joined_state"],
    tags=["phase_a", "python_source"],
    sdk_names=["agora_rtc"],
)
def test_agora_leave_state(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.leave_channel().code == 0
    assert engine.is_joined().value is False


@beacon_test(
    case_id="TC-PY-AGORA-INVALID-TOKEN",
    name="Python native Agora invalid token failure",
    platform="mac",
    devices=["primary"],
    suite="python_native_phase_a",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["join_channel", "error_event_observability"],
    tags=["phase_a", "python_source"],
    sdk_names=["agora_rtc"],
)
def test_agora_invalid_token(session: BeaconSession) -> None:
    primary = session.device("primary").agora.rtc_engine
    result = primary.join_channel(channel="room", uid=1001, token="invalid-token", check=False)
    assert result.code == 0
    primary.on_error.wait(match={"code": 110}, timeout_s=15)


@beacon_test(
    case_id="TC-PY-AGORA-1V1-REMOTE-VIDEO",
    name="Python native Agora 1v1 remote video",
    platform="mac",
    devices=["primary", "peer"],
    suite="python_native_phase_a",
    scenario_family="direct_call",
    implementation_status="runnable_or_partial",
    covered_capabilities=["join_channel", "remote_video_rendering"],
    tags=["phase_a", "python_source"],
    token_bindings=[('room', 1001), ('room', 1002)],
    sdk_names=["agora_rtc"],
)
def test_agora_1v1_remote_video(session: BeaconSession) -> None:
    primary = session.device("primary").agora.rtc_engine
    peer = session.device("peer").agora.rtc_engine
    visual = session.device("primary").agora.visual_probe
    try:
        assert primary.join_channel(channel="room", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
        primary.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
        assert peer.join_channel(channel="room", uid=1002, token="{{AGORA_RTC_TOKEN}}").code == 0
        peer.on_join_channel_success.wait(match={"uid": 1002}, timeout_s=5)
        assert visual.bind_remote_video(uid=1002, view_role="primary_remote").code == 0
        frame = primary.on_first_remote_video_frame.wait(match={"uid": 1002}, timeout_s=20)
        assert frame.payload["width"] > 0 and frame.payload["height"] > 0
    finally:
        assert peer.leave_channel().code == 0
        assert primary.leave_channel().code == 0
