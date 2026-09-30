"""使用 Native 附加 fixture 验证 Agora 权限失败。"""

from beacon_test import BeaconSession, beacon_test


DENY_MEDIA = {"permission_fixture": "deny_media_for_testing"}


@beacon_test(
    case_id="TC-MAC-AGORA-PERMISSION-DENIED-JOIN-FAILURE",
    name="macOS Agora permission denied join failure",
    platform="mac",
    devices=["primary"],
    suite="agora_failure_recovery_resilience",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["permission_denied_failure"],
    token_bindings=[('permission-denied-smoke', 1003)],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_permission_denied_join_failure(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    assert engine.load_sdk().code == 0
    result = engine.join_channel(
        channel="permission-denied-smoke", uid=1003, token="{{AGORA_RTC_TOKEN}}", _extra=DENY_MEDIA, check=False
    )
    assert result.code == 402
    assert result.failure_classification == "environment"


@beacon_test(
    case_id="TC-MAC-AGORA-PERMISSION-DENIED-PREVIEW-FAILURE",
    name="macOS Agora permission denied preview failure",
    platform="mac",
    devices=["primary"],
    suite="agora_failure_recovery_resilience",
    scenario_family="failure_recovery",
    implementation_status="runnable",
    covered_capabilities=["permission_denied_failure"],
    sdk_names=["agora_rtc"],
)
def test_tc_mac_agora_permission_denied_preview_failure(session: BeaconSession) -> None:
    engine = session.device("primary").agora.rtc_engine
    preview = session.device("primary").agora.video_preview
    assert engine.load_sdk().code == 0
    result = preview.start_preview(_extra=DENY_MEDIA, check=False)
    assert result.code == 402
    assert result.failure_classification == "environment"
