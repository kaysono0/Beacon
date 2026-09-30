"""IR-07 独立 Runner 进程侧握手、分类和凭证边界。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python_sdk"))

from beacon_test import runner  # noqa: E402
from beacon_test.target_session import CallResult, UnsupportedCallError  # noqa: E402


class FakeSession:
    def __init__(self, **kwargs):
        self.requests = []
        self.options = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def _request(self, method, suffix, **kwargs):
        self.requests.append((method, suffix, kwargs["json"]))
        return {"status": "accepted"}


def _unsupported_case(session):
    raise UnsupportedCallError(CallResult(
        operation_id="op-unsupported", device_role="primary", node_id="node-1", code=488,
        message="unsupported", value=None, resource=None, failure_classification="unsupported",
        started_at_ms=1, finished_at_ms=2,
    ))


@pytest.mark.parametrize(
    ("case", "expected_status", "expected_classification", "expected_exit"),
    [
        (lambda session: None, "passed", None, 0),
        (_unsupported_case, "unsupported", None, 1),
        (lambda session: (_ for _ in ()).throw(AssertionError("secret")), "failed", "python_assertion", 1),
        (lambda session: (_ for _ in ()).throw(ValueError("secret")), "failed", "python_exception", 1),
    ],
)
def test_TARGET_RUNNER_01_handshake_then_candidate_result(
    monkeypatch, case, expected_status, expected_classification, expected_exit,
):
    sessions = []

    def make_session(**kwargs):
        session = FakeSession(**kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(runner, "BeaconSession", make_session)
    monkeypatch.setattr(runner, "_load_case", lambda *_: case)
    result = runner.run_case(
        base_url="http://server", repo_root=ROOT, source_path="test_cases/python/example.py",
        function_name="case", run_id="run-1", case_id="case-1", roles=frozenset({"primary"}), token="secret",
    )
    assert result == expected_exit
    session = sessions[0]
    assert session.options["run_token"] == "secret"
    assert [request[1] for request in session.requests] == ["/started", "/result"]
    assert session.requests[0][2]["pid"] > 0
    payload = session.requests[1][2]
    assert payload["status"] == expected_status
    assert payload["failure_classification"] == expected_classification
    assert "secret" not in payload["message"]
    assert payload["source"]["path"] == "test_cases/python/example.py"
    assert payload["source"]["function"] == "case"
    assert payload["source"]["line"] >= 1
    if expected_status == "failed":
        assert "secret" not in payload["diagnostic_traceback"]
        assert "/Users/" not in payload["diagnostic_traceback"]


def test_TARGET_RUNNER_02_import_failure_is_candidate_not_uncaught(monkeypatch):
    sessions = []

    def make_session(**kwargs):
        session = FakeSession(**kwargs)
        sessions.append(session)
        return session

    def fail_import(*_):
        raise ImportError("private path")

    monkeypatch.setattr(runner, "BeaconSession", make_session)
    monkeypatch.setattr(runner, "_load_case", fail_import)
    assert runner.run_case(
        base_url="http://server", repo_root=ROOT, source_path="test_cases/python/example.py",
        function_name="case", run_id="run-1", case_id="case-1", roles=frozenset({"primary"}), token="secret",
    ) == 1
    payload = sessions[0].requests[-1][2]
    assert payload["status"] == "failed" and payload["failure_classification"] == "import_error"
    assert payload["message"] == "ImportError"
    assert payload["source"] == {"path": "test_cases/python/example.py", "function": "case", "line": 1}
    assert "ImportError" in payload["diagnostic_traceback"]
    assert "/Users/" not in payload["diagnostic_traceback"]


def test_TARGET_RUNNER_03_rejects_source_outside_repository(tmp_path):
    with pytest.raises(ImportError, match="outside trusted repository"):
        runner._load_case(tmp_path, "../private.py", "case")


def test_TARGET_RUNNER_03_outside_source_reports_import_error(monkeypatch, tmp_path):
    sessions = []

    def make_session(**kwargs):
        session = FakeSession(**kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(runner, "BeaconSession", make_session)
    assert runner.run_case(
        base_url="http://server", repo_root=tmp_path, source_path="../private.py",
        function_name="case", run_id="run-1", case_id="case-1",
        roles=frozenset({"primary"}), token="secret",
    ) == 1
    assert [request[1] for request in sessions[0].requests] == ["/started", "/result"]
    assert sessions[0].requests[-1][2]["failure_classification"] == "import_error"


def test_TARGET_RUNNER_03_exception_line_comes_from_case_source(monkeypatch, tmp_path):
    source_path = "test_cases/target_runtime/failing.py"
    source = tmp_path / source_path
    source.parent.mkdir(parents=True)
    source.write_text(
        "def failing(session):\n    value = 1\n    raise AssertionError('token=private-value')\n",
        encoding="utf-8",
    )
    sessions = []

    def make_session(**kwargs):
        session = FakeSession(**kwargs)
        sessions.append(session)
        return session

    monkeypatch.setattr(runner, "BeaconSession", make_session)
    assert runner.run_case(
        base_url="http://server", repo_root=tmp_path, source_path=source_path,
        function_name="failing", run_id="run-1", case_id="case-1",
        roles=frozenset({"primary"}), token="private-value",
    ) == 1
    payload = sessions[0].requests[-1][2]
    assert payload["source"] == {"path": source_path, "function": "failing", "line": 3}
    assert "private-value" not in payload["diagnostic_traceback"]
    assert "/Users/" not in payload["diagnostic_traceback"]


def test_TARGET_RUNNER_04_token_must_not_appear_in_arguments(monkeypatch):
    monkeypatch.delenv(runner.RUNNER_TOKEN_ENV, raising=False)
    with pytest.raises(SystemExit) as error:
        runner.main([
            "--repo-root", str(ROOT),
            "--source-path", "test_cases/python/example.py", "--function-name", "case",
            "--role", "primary",
        ])
    assert error.value.code == 2
