"""验证 Server mypy 报告 wrapper 的公开命令行合同。"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts/validation" / "run_mypy_reported.py"


def _run_wrapper(tmp_path: Path, command: list[str]) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    log_path = tmp_path / "server.mypy.log"
    junit_path = tmp_path / "server.mypy.junit.xml"
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--cwd",
            str(tmp_path),
            "--log",
            str(log_path),
            "--junit",
            str(junit_path),
            "--failure-tail",
            "2",
            "--",
            *command,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, log_path, junit_path


def test_IT_SRV_TYPE_GATE_wrapper_writes_success_artifacts(tmp_path: Path) -> None:
    output = "Success: no issues found in 1 source file"

    completed, log_path, junit_path = _run_wrapper(
        tmp_path,
        [sys.executable, "-c", f"print({output!r})"],
    )

    assert completed.returncode == 0
    assert output in completed.stdout
    assert log_path.read_text(encoding="utf-8") == f"{output}\n"
    suite = ET.parse(junit_path).getroot()
    assert suite.attrib == {"name": "server-mypy", "tests": "1", "failures": "0"}
    assert suite.find("./testcase/failure") is None


def test_IT_SRV_TYPE_GATE_wrapper_preserves_failure_evidence(tmp_path: Path) -> None:
    diagnostic = "app/example.py:4:7: error: bad <type> & value  [assignment]"
    summary = "Found 1 error in 1 file (checked 1 source file)"
    command = f"print({diagnostic!r}); print({summary!r}); raise SystemExit(3)"

    completed, log_path, junit_path = _run_wrapper(tmp_path, [sys.executable, "-c", command])

    assert completed.returncode == 3
    assert log_path.read_text(encoding="utf-8") == f"{diagnostic}\n{summary}\n"
    assert diagnostic in completed.stderr
    suite = ET.parse(junit_path).getroot()
    assert suite.attrib["failures"] == "1"
    failure = suite.find("./testcase/failure")
    assert failure is not None
    assert failure.attrib["message"] == summary
    assert failure.text == f"{diagnostic}\n{summary}\n"


def test_IT_SRV_TYPE_GATE_wrapper_replaces_stale_passing_junit(tmp_path: Path) -> None:
    junit_path = tmp_path / "server.mypy.junit.xml"
    junit_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<testsuite name="server-mypy" tests="1" failures="0" />',
        encoding="utf-8",
    )
    junit_path.chmod(0o444)

    completed, _, written_junit_path = _run_wrapper(
        tmp_path,
        [sys.executable, "-c", "print('Found 1 error'); raise SystemExit(3)"],
    )

    assert completed.returncode == 3
    suite = ET.parse(written_junit_path).getroot()
    assert suite.attrib["failures"] == "1"


def test_IT_SRV_TYPE_GATE_wrapper_sanitizes_xml_control_characters(tmp_path: Path) -> None:
    output = "app/example.py:1: error:\x1b[31m bad type"
    command = f"print({output!r}); raise SystemExit(3)"

    completed, log_path, junit_path = _run_wrapper(tmp_path, [sys.executable, "-c", command])

    assert completed.returncode == 3
    assert "\x1b" in log_path.read_text(encoding="utf-8")
    failure = ET.parse(junit_path).getroot().find("./testcase/failure")
    assert failure is not None
    assert failure.text == f"app/example.py:1: error:\ufffd[31m bad type\n"


def test_IT_SRV_TYPE_GATE_wrapper_reports_command_start_failure(tmp_path: Path) -> None:
    missing_command = tmp_path / "missing-mypy"

    completed, log_path, junit_path = _run_wrapper(tmp_path, [str(missing_command)])

    assert completed.returncode == 2
    log = log_path.read_text(encoding="utf-8")
    assert "failed to start mypy command" in log
    suite = ET.parse(junit_path).getroot()
    assert suite.attrib["failures"] == "1"
    failure = suite.find("./testcase/failure")
    assert failure is not None
    assert failure.text == log
