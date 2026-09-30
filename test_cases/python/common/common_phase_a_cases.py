from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-PY-COMMON-SMOKE",
    name="Python native common smoke",
    platform="common",
    devices=["primary"],
    suite="python_native_phase_a",
    scenario_family="smoke",
    implementation_status="runnable",
    covered_capabilities=["echo_basic"],
    tags=["phase_a", "python_source"],
    sdk_names=["mock_echo"],
)
def test_common_smoke(session: BeaconSession) -> None:
    result = session.device("primary").mock_echo.echo.echo(message="hello")
    assert result.code == 0
