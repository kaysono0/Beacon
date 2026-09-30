"""迁移 Agora token 恢复与被抑制回调的超时用例。"""

from beacon_test import BeaconSession, beacon_test
from beacon_test.target_session import ObservationTimeoutError


@beacon_test(
    case_id="TC-MAC-AGORA-INVALID-TOKEN-THEN-RECOVER",
    name="macOS Agora invalid token then recover",
    platform="mac",
    devices=["primary"],
    suite="agora_failure_recovery_resilience",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["invalid_token_failure", "recovery_after_failure", "join_success_fact", "leave_cleanup"],
    token_bindings=[('invalid-token-recovery-smoke-ok', 1001)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_invalid_token_then_recover(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.load_sdk().code == 0
    invalid = engine.join_channel(channel="invalid-token-recovery-smoke", uid=1006, token="invalid-token", check=False)
    assert invalid.code == 0
    engine.on_error.wait(match={"code": 110}, timeout_s=15)
    assert engine.unload_sdk().code == 0
    assert engine.load_sdk().code == 0
    try:
        assert engine.join_channel(channel="invalid-token-recovery-smoke-ok", uid=1001, token="{{AGORA_RTC_TOKEN}}").code == 0
        engine.on_join_channel_success.wait(match={"uid": 1001}, timeout_s=5)
    finally:
        assert engine.leave_channel().code == 0
        assert engine.is_joined().value is False


@beacon_test(
    case_id="TC-MAC-AGORA-TOKEN-RENEWAL-RECOVERY",
    name="macOS Agora token renewal recovery",
    platform="mac",
    devices=["primary"],
    suite="agora_failure_recovery_resilience",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["invalid_token_failure", "token_renewal_recovery", "join_success_fact", "leave_cleanup"],
    token_bindings=[('token-renewal-recovery-smoke', 1007)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_token_renewal_recovery(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.load_sdk().code == 0
    try:
        expired = engine.join_channel(channel="token-renewal-recovery-smoke", uid=1007, token="expired-token", check=False)
        assert expired.code == 0
        engine.on_error.wait(match={"code": 110}, timeout_s=15)
        assert engine.renew_token(channel="token-renewal-recovery-smoke", uid=1007, token="{{AGORA_RTC_TOKEN}}").code == 0
    finally:
        assert engine.leave_channel().code == 0
        assert engine.is_joined().value is False


@beacon_test(
    case_id="TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT",
    name="macOS Agora join callback timeout",
    platform="mac",
    devices=["primary"],
    suite="agora_failure_recovery_resilience",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["join_callback_timeout"],
    token_bindings=[('join-timeout-smoke', 1004)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_join_callback_timeout(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.load_sdk().code == 0
    try:
        assert engine.join_channel(
            channel="join-timeout-smoke", uid=1004, token="{{AGORA_RTC_TOKEN}}",
            _extra={"callback_fixture": "suppress_join_success_for_testing"},
        ).code == 0
        try:
            engine.on_join_channel_success.wait(timeout_s=5)
        except ObservationTimeoutError:
            pass
        else:
            raise AssertionError("suppressed join callback was observed")
    finally:
        assert engine.leave_channel().code == 0
