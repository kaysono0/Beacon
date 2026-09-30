from beacon_test import BeaconSession, beacon_test


@beacon_test(
    case_id="TC-PY-MOCK-COMPLEX-REFERENCE-TRACER",
    name="Python-native generic reference SDK tracer",
    platform="common",
    devices=["primary"],
    suite="generic_sdk_reference",
    scenario_family="reference_sdk",
    implementation_status="runnable",
    covered_capabilities=["apply_value", "value_applied", "last_applied_value"],
    tags=["generic_sdk", "python_source", "reference_tracer"],
    sdk_names=["mock_complex_sdk"],
)
def test_mock_complex_reference_tracer(session: BeaconSession) -> None:
    sdk = session.device("primary").mock_complex_sdk.session
    assert sdk.apply_value(value="signal-1").code == 0
    assert sdk.on_value_applied.wait(match={"value": "signal-1"}, timeout_s=5).payload["value"] == "signal-1"
    assert sdk.get_last_applied_value().value == {"value": "signal-1", "revision": 1}


@beacon_test(
    case_id="TC-PY-MOCK-COMPLEX-DIRECT-MATRIX",
    name="Python-native generic reference SDK direct matrix",
    platform="common",
    devices=["primary"],
    suite="generic_sdk_reference",
    scenario_family="reference_sdk",
    implementation_status="runnable",
    covered_capabilities=["configure_value", "apply_value", "value_applied", "last_applied_value"],
    tags=["generic_sdk", "python_source", "reference_tracer", "protocol_operation_tracer", "MOCK_COMPLEX_DIRECT_MATRIX"],
    sdk_names=["mock_complex_sdk"],
)
def test_mock_complex_direct_matrix(session: BeaconSession) -> None:
    sdk = session.device("primary").mock_complex_sdk.session
    complex_options = {
        "enabled": True,
        "ratio": 2.5,
        "tags": ["alpha", "beta"],
        "metadata": {"owner": "qa", "retries": 2},
    }
    assert sdk.configure_value(value="signal-2", options=complex_options).code == 0
    assert sdk.apply_value(value="signal-2").code == 0
    assert sdk.on_value_applied.wait(match={"value": "signal-2"}, timeout_s=5).payload["value"] == "signal-2"
    assert sdk.get_last_applied_value().value == {"value": "signal-2", "revision": 1}
