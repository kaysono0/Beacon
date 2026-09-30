"""迁移 Agora 无效 token 的调用失败与错误回调用例。"""

from beacon_test import BeaconSession, beacon_test


def _assert_invalid_token_error(session: BeaconSession, *, channel: str, uid: int) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.load_sdk().code == 0
    result = engine.join_channel(channel=channel, uid=uid, token="invalid-token", check=False)
    assert result.code == 0
    engine.on_error.wait(match={"code": 110}, timeout_s=15)


@beacon_test(
    case_id="TC-MAC-AGORA-INVALID-TOKEN-FAILURE",
    name="macOS Agora invalid token failure",
    platform="mac",
    devices=["primary"],
    suite="agora_failure_recovery_resilience",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["invalid_token_failure"],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_invalid_token_failure(session: BeaconSession) -> None:
    _assert_invalid_token_error(session, channel="invalid-token-smoke", uid=1002)


@beacon_test(
    case_id="TC-MAC-AGORA-INVALID-TOKEN-ONERROR-DIAGNOSTIC",
    name="macOS Agora invalid token onError diagnostic",
    platform="mac",
    devices=["primary"],
    suite="agora_failure_recovery_resilience",
    scenario_family="failure_recovery",
    implementation_status="runnable_or_partial",
    covered_capabilities=["invalid_token_failure", "error_event_observability"],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_invalid_token_onerror_diagnostic(session: BeaconSession) -> None:
    _assert_invalid_token_error(session, channel="invalid-token-diagnostic-smoke", uid=1005)
