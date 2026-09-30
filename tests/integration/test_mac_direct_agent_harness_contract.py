"""Direct Mac Agent harness boundary contract tests."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOCK_HARNESS = ROOT / "scripts/validation" / "run_mac_direct_agent_mock.py"
REAL_HARNESS = ROOT / "scripts/validation" / "run_mac_direct_agent_agora_real.py"
BRIDGE = ROOT / "agents" / "mac" / "demo" / "mac_real_agent_bridge.mm"
PACKET_HANDLER = ROOT / "agents" / "mac" / "demo" / "mac_real_agent_packet_handler.mm"
LOOPBACK_HELPER = ROOT / "agents" / "mac" / "demo" / "mac_real_agent_loopback_helper.mm"
PROTOCOL_CONSTANTS = ROOT / "agent_core" / "include" / "beacon" / "protocol_constants.h"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_IT_MAC_DIRECT_AGENT_harness_waits_for_server_registration_not_stdout_ready():
    for path in [MOCK_HARNESS, REAL_HARNESS]:
        source = read(path)
        assert "wait_agent_registered" in source
        assert "process.stdout.readline" not in source
        assert 'text.strip() == "READY"' not in source
        assert "stdout=asyncio.subprocess.PIPE" not in source
        assert "process.communicate()" not in source


def test_IT_MAC_DIRECT_AGENT_harness_url_encodes_auth_token():
    for path in [MOCK_HARNESS, REAL_HARNESS]:
        source = read(path)
        assert "agent_ws_url(" in source
        assert "/api/v1/agent/ws?token=" not in source


def test_IT_MAC_DIRECT_AGENT_harness_does_not_use_bridge_synthetic_join_callback():
    source = read(MOCK_HARNESS)
    assert "BEACON_DIRECT_AGENT_SYNTHETIC_JOIN_SUCCESS" not in source
    assert "emit_mock_join_success" in source


def test_BRIDGE_MAC_DIRECT_AGENT_runtime_uses_protocol_constants_for_runtime_actions():
    sources = "\n".join(read(path) for path in [BRIDGE, PACKET_HANDLER, LOOPBACK_HELPER])
    constants = read(PROTOCOL_CONSTANTS)
    for name in [
        "kRegisterRequest",
        "kInvokeRequest",
        "kInvokeResponse",
        "kCallbackEventRequest",
    ]:
        assert name in constants
        assert f"beacon::protocol::{name}" in sources


def test_BRIDGE_MAC_DIRECT_AGENT_entry_is_direct_only_without_protocol_stdio():
    bridge = read(BRIDGE)
    runtime_sources = "\n".join(read(path) for path in [BRIDGE, PACKET_HANDLER])
    assert 'std::cout << "READY' not in bridge
    assert "std::getline(std::cin" not in bridge
    assert "BEACON_DIRECT_AGENT_MODE" not in runtime_sources
    assert "StdoutEmitter" not in runtime_sources
    assert "LineQueue" not in runtime_sources
    assert "BEACON_DIRECT_AGENT_SYNTHETIC_JOIN_SUCCESS" not in runtime_sources
    assert "synthetic_join_success_enabled" not in runtime_sources
    assert "join_success_payload_from_packet" not in runtime_sources


def test_BRIDGE_MAC_DIRECT_AGENT_loopback_stdio_is_helper_internal_only():
    helper = read(LOOPBACK_HELPER)
    assert 'std::cout << "READY' in helper
    assert "std::getline(std::cin" in helper


def test_BRIDGE_MAC_DIRECT_AGENT_callback_events_have_unique_event_ids():
    source = read(PACKET_HANDLER)
    assert "std::atomic" in source
    assert 'packet["data"]["event_id"]' in source
    assert 'packet["common"]["op_id"] = event_id' in source


def test_BRIDGE_MAC_DIRECT_AGENT_disables_callback_sender_before_runtime_teardown():
    source = read(BRIDGE)
    assert "CallbackEventSender" in source
    assert "ObserverReset" in source
    assert "SetObserver({})" in source
    assert "sender_->Disable()" in source


def test_BRIDGE_MAC_DIRECT_AGENT_keeps_appkit_main_run_loop_responsive():
    source = read(BRIDGE)

    assert "dispatch_get_global_queue" in source
    assert "[NSApp run]" in source
    assert "exit_code_promise->get_future()" in source
    assert "exit_code_future.get()" in source
    assert "const int exit_code = RunDirectAgent(adapter, helper_manager, node_id);" not in source


def test_IT_MAC_DIRECT_AGENT_mock_harness_writes_canonical_junit(tmp_path):
    module = load_module(MOCK_HARNESS)
    module.REPORT_DIR = tmp_path

    module.write_junit("passed", "ok")

    assert (tmp_path / "mac_direct_agent_mock.junit.xml").exists()
    assert (tmp_path / "report.junit.xml").exists()


def test_IT_MAC_DIRECT_AGENT_real_harness_writes_canonical_junit(tmp_path):
    module = load_module(REAL_HARNESS)
    module.REPORT_DIR = tmp_path

    module.write_junit("skipped", "missing env")

    assert (tmp_path / "mac_direct_agent_real.junit.xml").exists()
    assert (tmp_path / "report.junit.xml").exists()
