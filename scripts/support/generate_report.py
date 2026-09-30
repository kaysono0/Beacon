#!/usr/bin/env python3
"""生成 reports/latest 下的最小 JSON 和 JUnit 报告。

Makefile 目标失败时也会调用本脚本，保证 CI 和本地验证都有固定报告产物。
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_validation_overlay(latest: Path) -> dict:
    overlay_path = latest / "mac_console_agora.json"
    if not overlay_path.exists():
        return {}
    try:
        payload = json.loads(overlay_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    gate_keys = ("core_gate", "enhanced_gate", "resilience_gate")
    gate_status = {
        f"{gate_key}_status": payload[gate_key]["status"]
        for gate_key in gate_keys
        if isinstance(payload.get(gate_key), dict) and "status" in payload[gate_key]
    }
    return {
        "summary": gate_status | {key: value for key, value in summary.items() if key.endswith("_gate_status")},
        "capability_coverage": payload.get("capability_coverage"),
        "scenario_coverage": payload.get("scenario_coverage"),
        "blocked_scenarios": payload.get("blocked_scenarios"),
        "blocked_scenario_summary": payload.get("blocked_scenario_summary"),
        "evidence_coverage": payload.get("evidence_coverage"),
        "repeated_join_leave_resilience": payload.get("repeated_join_leave_resilience"),
        **{gate_key: payload.get(gate_key) for gate_key in gate_keys if gate_key in payload},
    }


def build_report(status: str, case_id: str, step_id: str, latest: Path) -> dict:
    error = 0 if status in {"passed", "skipped"} else 1
    now = utc_now()
    report = {
        "run_id": "run-local-p1",
        "status": status,
        "started_at": now,
        "finished_at": now,
        "summary": {
            "total": 1,
            "passed": 1 if status == "passed" else 0,
            "failed": 1 if status == "failed" else 0,
            "skipped": 1 if status == "skipped" else 0,
        },
        "case_results": [
            {
                "case_id": case_id,
                "status": status,
                "steps": [
                    {
                        "step_id": step_id,
                        "status": status,
                        "error": error,
                        "message": "",
                        "artifacts": [],
                    }
                ],
            }
        ],
        "artifacts": [],
    }
    overlay = _load_validation_overlay(latest)
    summary_overlay = overlay.pop("summary", {})
    if summary_overlay:
        report["summary"].update(summary_overlay)
    for key, value in overlay.items():
        if value is not None:
            report[key] = value
    return report


def main() -> int:
    status = sys.argv[1] if len(sys.argv) > 1 else "passed"
    case_id = sys.argv[2] if len(sys.argv) > 2 else "P1-REPORT"
    step_id = sys.argv[3] if len(sys.argv) > 3 else "generate-report"
    latest = Path("reports/latest")
    (latest / "logs").mkdir(parents=True, exist_ok=True)
    (latest / "artifacts").mkdir(parents=True, exist_ok=True)
    report = build_report(status, case_id, step_id, latest)
    (latest / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    suite = ET.Element("testsuite", name=case_id, tests="1", failures="0" if status != "failed" else "1")
    case = ET.SubElement(suite, "testcase", classname=case_id, name=step_id)
    if status == "failed":
        ET.SubElement(case, "failure", message=step_id).text = step_id
    ET.ElementTree(suite).write(latest / "report.junit.xml", encoding="utf-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
