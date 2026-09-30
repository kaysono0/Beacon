"""迁移旧 common 与 Agora 协议烟测到即时调用链。"""

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-COMMON-SMOKE",
    name="Common protocol smoke",
    platform="common",
    devices=["primary"],
    suite="legacy_protocol_smoke",
    scenario_family="legacy_protocol",
    implementation_status="runnable",
    tags=["legacy_protocol_reference"],
    sdk_names=["agora_rtc"],
)
def test_tc_common_smoke(session: BeaconSession) -> None:
    result = session.device("primary").agora.rtc_engine.join_channel(channel="smoke", uid=1001)
    assert result.code == 0


@beacon_test(
    case_id="TC-PY-PROTOCOL-OPERATION-JOIN-TRACER",
    name="Python-native protocol operation join tracer",
    platform="mac",
    devices=["primary"],
    suite="python_native_protocol_operations",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_channel", "join_success_callback"],
    tags=["python_source", "protocol_operation_tracer"],
    token_bindings=[('thin-tracer-room', 1011)],
    sdk_names=["agora_rtc"],
)
def test_protocol_operation_join_tracer(session: BeaconSession) -> None:
    primary = session.device("primary").agora.rtc_engine
    result = primary.join_channel(channel="thin-tracer-room", uid=1011, token="{{AGORA_RTC_TOKEN}}")
    assert result.code == 0
    primary.on_join_channel_success.wait(match={"uid": 1011}, timeout_s=5)


@beacon_test(
    case_id="TC-MAC-AGORA-JOIN-CALLBACK-SUCCESS",
    name="macOS Agora L1 join callback success",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l1",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_success_fact"],
    token_bindings=[('real-smoke', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_join_callback_success(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.join_channel(channel="real-smoke", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
    engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
    assert engine.leave_channel().code == 0


@beacon_test(
    case_id="TC-MAC-SMOKE",
    name="macOS callback smoke",
    platform="mac",
    devices=["primary"],
    suite="legacy_protocol_smoke",
    scenario_family="legacy_protocol",
    implementation_status="runnable",
    tags=["legacy_protocol_reference"],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_smoke(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.join_channel(channel="smoke", uid=1001).code == 0
    engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=3)
