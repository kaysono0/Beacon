from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


def _load_e2e_mock_module(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "websockets",
        SimpleNamespace(ConnectionClosed=RuntimeError),
    )
    monkeypatch.syspath_prepend(str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "beacon_run_e2e_mock_tests",
        ROOT / "scripts/validation" / "run_e2e_mock_tests.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_E2E_MOCK_CALLBACK_CONTRACT_reports_observation_without_defer(monkeypatch):
    module = _load_e2e_mock_module(monkeypatch)
    harness = module.MockAgentHarness(object())
    harness._lease_id = "lease-1"

    event = harness._callback_event(
        {
            "common": {"op_id": "op-1"},
            "data": {"node_id": "node-1"},
        },
        {"run_id": "run-1", "case_id": "case-1", "step_id": "step-1"},
        {
            "sdk": "mock_complex_sdk",
            "interface": "session",
            "class_name": "MockComplexSessionObserver",
            "function": "onValueApplied",
        },
        {"value": "ready"},
    )

    assert "callback_execution" not in event["data"]
