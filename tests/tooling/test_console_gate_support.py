import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.support.console_gate_support import run_autorun_round, write_gate_report  # noqa: E402


@pytest.mark.parametrize("status", ["skipped", "failed"])
def test_CONSOLE_GATE_SUPPORT_01_writes_compatible_report_and_skipped_junit(tmp_path, status):
    report_path = tmp_path / "reports" / "latest" / "gate.json"
    junit_path = report_path.with_suffix(".junit.xml")

    write_gate_report(
        report_path=report_path,
        junit_path=junit_path,
        junit_name="mac-console-sdk",
        junit_classname="mac-console-sdk",
        junit_case_name="app-driven-sdk",
        run_id="run-sdk",
        expected_cases={"TC-B", "TC-A"},
        status=status,
        message=f"sdk error: {tmp_path}/sdk.log; {Path.home()}/sdk.log",
        base_extra={"node_id": "primary"},
        extra={"case_results": [], "artifact_path": str(tmp_path / "frame.jpg"), "home_log": str(Path.home() / "sdk.log")},
    )

    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-sdk"
    assert payload["expected_cases"] == ["TC-A", "TC-B"]
    assert payload["node_id"] == "primary"
    assert payload["case_results"] == []
    assert str(tmp_path) not in report_path.read_text(encoding="utf-8")
    assert payload["artifact_path"].startswith("<workspace>/")
    assert payload["home_log"] == "<home>/sdk.log"

    suite = ET.parse(junit_path).getroot()
    assert suite.attrib == {"name": "mac-console-sdk", "tests": "1", "failures": str(int(status == "failed")), "skipped": str(int(status == "skipped"))}
    expected_message = "sdk error: <workspace>/sdk.log; <home>/sdk.log"
    assert payload["message"] == expected_message
    detail = suite.find(f"testcase/{'failure' if status == 'failed' else 'skipped'}")
    assert detail.attrib["message"] == detail.text == expected_message
    assert str(tmp_path) not in junit_path.read_text(encoding="utf-8")
    assert str(Path.home()) not in junit_path.read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_CONSOLE_GATE_SUPPORT_02_runs_cleanup_before_autorun_and_stops_on_verification_failure():
    events: list[str] = []
    process = object()

    async def cleanup(base_url: str, round_index: int) -> dict:
        events.append(f"cleanup:{base_url}:{round_index}")
        return {"round": round_index, "status": "passed"}

    def launch(base_url: str):
        events.append(f"launch:{base_url}")
        return process

    async def wait(_process: object) -> dict:
        events.append("wait")
        return {"status": "passed"}

    async def verify(_base_url: str, _autorun: dict) -> list[dict]:
        events.append("verify")
        raise RuntimeError("evidence failed")

    async def stop(_process: object) -> None:
        events.append("stop")

    with pytest.raises(RuntimeError, match="evidence failed"):
        await run_autorun_round(
            base_url="http://127.0.0.1:9000",
            round_index=2,
            run_cleanup=cleanup,
            launch_console=launch,
            wait_autorun=wait,
            verify_reports=verify,
            stop_console=stop,
        )

    assert events == [
        "cleanup:http://127.0.0.1:9000:2",
        "launch:http://127.0.0.1:9000",
        "wait",
        "verify",
        "stop",
    ]
