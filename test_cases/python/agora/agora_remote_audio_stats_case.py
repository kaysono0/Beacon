"""迁移 Agora 双角色远端音频统计用例。"""

from time import monotonic

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-REMOTE-AUDIO-STATS-OBSERVABLE",
    name="macOS Agora L2 remote audio stats observable",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_l2",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["media_stats_observability"],
    token_bindings=[('real-smoke-remote-audio-stats', 1001), ('real-smoke-remote-audio-stats', 1002)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_remote_audio_stats_observable(session: BeaconSession) -> None:
    primary = session.device("primary").agora.rtc_engine
    peer = session.device("peer").agora.rtc_engine
    try:
        assert primary.join_channel(
            channel="real-smoke-remote-audio-stats", uid=1001, token="{{AGORA_RTC_TOKEN}}",
            auto_subscribe_audio=True, auto_subscribe_video=True,
        ).code == 0
        primary.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
        assert peer.join_channel(
            channel="real-smoke-remote-audio-stats", uid=1002, token="{{AGORA_RTC_TOKEN}}", publish_microphone=True,
        ).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1002}, timeout_s=5)
        assert primary.get_connection_state().code == 0
        deadline = monotonic() + 30
        stats = primary.on_remote_audio_stats.wait(match={"uid": 1002}, timeout_s=30)
        while stats.payload["received_bitrate"] == 0 and monotonic() < deadline:
            stats = primary.on_remote_audio_stats.wait(match={"uid": 1002}, after_cursor=stats.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert stats.payload["received_bitrate"] > 0
    finally:
        assert peer.leave_channel().code == 0
        assert primary.leave_channel().code == 0
