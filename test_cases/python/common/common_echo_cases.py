from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-COMMON-ECHO-CALL",
    name="Common mock_echo basic call",
    platform="common",
    suite="mock_echo_l1",
    scenario_family="echo_basic",
    implementation_status="runnable",
    covered_capabilities=["echo_basic"],
    sdk_names=["mock_echo"],
)
def test_common_echo_call(session: BeaconSession) -> None:
    assert session.device("primary").mock_echo.echo.echo(message="hello beacon").code == 0


@beacon_test(
    case_id="TC-COMMON-ECHO-CALLBACK",
    name="Common mock_echo call with callback",
    platform="common",
    suite="mock_echo_l2",
    scenario_family="echo_callback",
    implementation_status="runnable",
    covered_capabilities=["echo_callback"],
    sdk_names=["mock_echo"],
)
def test_common_echo_callback(session: BeaconSession) -> None:
    echo = session.device("primary").mock_echo.echo
    session.register_callback(
        role="primary",
        event_target={"sdk": "mock_echo", "interface": "echo", "class": "EchoDelegate", "function": "onEchoReceived"},
        calls=[{"target": {"sdk": "mock_echo", "interface": "echo", "class": "EchoService", "function": "getLastEcho"}, "params": {}}],
    )
    assert echo.echo_with_callback(message="ping").code == 0
    observed = echo.on_echo_received.wait(timeout_s=3)
    assert observed.callback_execution is not None
    assert observed.callback_execution["defer_matched"] is True
    assert observed.callback_execution["defer_executed"] is True
    assert observed.callback_execution["call_results"][0]["return_value"] == '{"message": "ping"}'


@beacon_test(
    case_id="TC-COMMON-ECHO-STATE",
    name="Common mock_echo state tracking",
    platform="common",
    suite="mock_echo_l2",
    scenario_family="echo_state",
    implementation_status="runnable",
    covered_capabilities=["echo_basic", "echo_state"],
    sdk_names=["mock_echo"],
)
def test_common_echo_state(session: BeaconSession) -> None:
    echo = session.device("primary").mock_echo.echo
    assert echo.echo(message="state-check").code == 0
    assert echo.get_last_echo().value == {"message": "state-check"}
