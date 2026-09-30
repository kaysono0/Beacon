"""Agora 双角色音频静音恢复用例。"""

from time import monotonic

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-1V1-AUDIO-MUTE-RECOVER",
    name="macOS Agora 1V1 real audio mute and recovery",
    platform="mac",
    devices=["primary", "peer"],
    suite="agora_direct_call_enhanced",
    scenario_family="direct_call",
    implementation_status="runnable",
    covered_capabilities=["join_channel", "local_audio_control", "remote_audio_stats_observability", "leave_channel"],
    token_bindings=[('real-smoke-1v1-audio-mute-recover', 1301), ('real-smoke-1v1-audio-mute-recover', 1302)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_1v1_audio_mute_recover(session: BeaconSession) -> None:
    primary = session.device("primary").agora.rtc_engine
    peer = session.device("peer").agora.rtc_engine
    try:
        assert primary.load_sdk().code == 0
        assert peer.load_sdk().code == 0
        assert primary.join_channel(channel="real-smoke-1v1-audio-mute-recover", uid=1301, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=False, publish_camera=False, publish_microphone=True).code == 0
        primary.on_join_channel_success.wait(match={"uid": 1301}, timeout_s=15)
        assert peer.join_channel(channel="real-smoke-1v1-audio-mute-recover", uid=1302, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=False, publish_camera=False, publish_microphone=True).code == 0
        peer.on_join_channel_success.wait(match={"uid": 1302}, timeout_s=15)
        assert peer.get_connection_state().code == 0
        deadline = monotonic() + 30
        before = peer.on_remote_audio_stats.wait(match={"uid": 1301}, timeout_s=30)
        while before.payload["received_bitrate"] == 0 and monotonic() < deadline:
            before = peer.on_remote_audio_stats.wait(match={"uid": 1301}, after_cursor=before.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert before.payload["received_bitrate"] > 0
        assert primary.enable_local_audio(enabled=False).code == 0
        assert primary.enable_local_audio(enabled=True).code == 0
        assert peer.get_connection_state().code == 0
        deadline = monotonic() + 30
        recovered = peer.on_remote_audio_stats.wait(match={"uid": 1301}, after_cursor=before.cursor, timeout_s=30)
        while recovered.payload["received_bitrate"] == 0 and monotonic() < deadline:
            recovered = peer.on_remote_audio_stats.wait(match={"uid": 1301}, after_cursor=recovered.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert recovered.payload["received_bitrate"] > 0
    finally:
        assert peer.leave_channel().code == 0
        assert primary.leave_channel().code == 0
