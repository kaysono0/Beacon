"""Agora 三角色小房间基线。"""

from time import monotonic

from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-MAC-AGORA-SMALL-ROOM-BASELINE",
    name="macOS Agora Small Room baseline",
    platform="mac",
    devices=["primary", "peer", "peer_b"],
    suite="agora_small_room_enhanced",
    scenario_family="small_room",
    implementation_status="runnable",
    covered_capabilities=["join_success_fact", "rtc_stats_observability", "media_stats_observability", "leave_cleanup"],
    token_bindings=[('small-room-baseline', 1101), ('small-room-baseline', 1102), ('small-room-baseline', 1103)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_small_room_baseline(session: BeaconSession) -> None:
    primary = session.device("primary").agora.rtc_engine
    peer = session.device("peer").agora.rtc_engine
    peer_b = session.device("peer_b").agora.rtc_engine
    try:
        for engine, uid, publish in ((primary, 1101, False), (peer, 1102, True), (peer_b, 1103, True)):
            assert engine.join_channel(channel="small-room-baseline", uid=uid, token="{{AGORA_RTC_TOKEN}}", auto_subscribe_audio=True, auto_subscribe_video=True, publish_microphone=publish).code == 0
            engine.on_join_channel_success.wait(match={"uid": uid}, timeout_s=5)
        assert primary.get_connection_state().code == 0
        for uid in (1102, 1103):
            deadline = monotonic() + 30
            audio = primary.on_remote_audio_stats.wait(match={"uid": uid}, timeout_s=30)
            while audio.payload["received_bitrate"] == 0 and monotonic() < deadline:
                audio = primary.on_remote_audio_stats.wait(match={"uid": uid}, after_cursor=audio.cursor, timeout_s=max(0.1, deadline - monotonic()))
            assert audio.payload["received_bitrate"] > 0
        deadline = monotonic() + 30
        primary_stats = primary.on_rtc_stats.wait(timeout_s=30)
        while primary_stats.payload["rx_audio_kbitrate"] == 0 and monotonic() < deadline:
            primary_stats = primary.on_rtc_stats.wait(after_cursor=primary_stats.cursor, timeout_s=max(0.1, deadline - monotonic()))
        assert primary_stats.payload["rx_audio_kbitrate"] > 0
        for engine in (peer, peer_b):
            assert engine.get_connection_state().code == 0
            deadline = monotonic() + 30
            peer_stats = engine.on_rtc_stats.wait(timeout_s=30)
            while peer_stats.payload["tx_audio_kbitrate"] == 0 and monotonic() < deadline:
                peer_stats = engine.on_rtc_stats.wait(after_cursor=peer_stats.cursor, timeout_s=max(0.1, deadline - monotonic()))
            assert peer_stats.payload["tx_audio_kbitrate"] > 0
    finally:
        for engine in (peer_b, peer, primary):
            assert engine.leave_channel().code == 0
