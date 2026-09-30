"""迁移单节点 Agora RTC 统计可观测性用例。"""

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-RTC-STATS-OBSERVABLE",
    name="macOS Agora L2 rtc stats observable",
    platform="mac",
    devices=["primary"],
    suite="agora_direct_call_l2",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["rtc_stats_observability"],
    token_bindings=[('real-smoke-rtc-stats', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_rtc_stats_observable(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    try:
        assert engine.join_channel(channel="real-smoke-rtc-stats", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
        engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
        assert engine.get_connection_state().code == 0
        engine.on_rtc_stats.wait(timeout_s=5)
    finally:
        assert engine.leave_channel().code == 0
