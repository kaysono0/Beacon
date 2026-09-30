"""迁移 Agora L1 状态与预览生命周期用例。"""

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-CONNECTION-STATE-SEQUENCE",
    name="macOS Agora L1 connection state sequence",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["connection_state_transition"],
    token_bindings=[('real-smoke-sequence', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_connection_state_sequence(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.join_channel(channel="real-smoke-sequence", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
    engine.on_connection_state_changed.wait(match={"state": 3}, timeout_s=5)
    engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
    assert engine.leave_channel().code == 0
    assert engine.is_joined().value is False


@beacon_test(
    case_id="TC-MAC-AGORA-CONNECTION-STATE-TRANSITION",
    name="macOS Agora L1 connection state transition",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["connection_state_transition"],
    token_bindings=[('real-smoke-state', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_connection_state_transition(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.join_channel(channel="real-smoke-state", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
    engine.on_connection_state_changed.wait(match={"state": 3}, timeout_s=5)
    assert engine.leave_channel().code == 0


@beacon_test(
    case_id="TC-MAC-AGORA-PREVIEW-CONTROL",
    name="macOS Agora L2 preview control",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l2",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["preview_control"],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_preview_control(session: BeaconSession) -> None:
    preview = session.device("primary").agora.video_preview
    assert preview.start_preview().code == 0
    assert preview.is_previewing().value is True
    assert preview.stop_preview().code == 0
    assert preview.is_previewing().value is False


@beacon_test(
    case_id="TC-MAC-AGORA-PREVIEW-LIFECYCLE-AROUND-JOIN",
    name="macOS Agora L2 preview lifecycle around join",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l2",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["preview_control"],
    token_bindings=[('real-smoke-preview-lifecycle', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_preview_lifecycle_around_join(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    preview = session.device("primary").agora.video_preview
    assert engine.join_channel(channel="real-smoke-preview-lifecycle", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
    engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
    try:
        assert preview.start_preview().code == 0
        assert preview.is_previewing().value is True
    finally:
        assert preview.stop_preview().code == 0
    assert preview.is_previewing().value is False
    assert engine.leave_channel().code == 0
