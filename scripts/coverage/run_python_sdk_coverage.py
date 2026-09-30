#!/usr/bin/env python3
"""Run Python SDK coverage and write stable artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CASE_ID = "COVERAGE-PYTHON-SDK"
SOURCE_PREFIX = "python_sdk/beacon_test/"
DEFAULT_TESTS = (
    "../python_sdk/tests/test_target_python_sdk.py",
    "../python_sdk/tests/test_target_runner_process.py",
    "../tests/integration/test_sdk_registry.py",
    "tests/test_runner_api.py",
    "tests/test_runner_case_registry.py",
    "tests/test_runner_supervisor.py",
    "tests/test_control_evidence_dispatch_coverage.py",
)


@dataclass(frozen=True)
class Paths:
    root: Path
    server_dir: Path
    reports_dir: Path
    data_file: Path
    log_path: Path
    raw_json_path: Path
    xml_path: Path
    summary_path: Path
    junit_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def report_text(value: str, root: Path) -> str:
    return value.replace(str(root), ".").replace(str(Path.home()), "~")


def prepare_paths(root: Path, reports_dir: Path) -> Paths:
    return Paths(
        root=root,
        server_dir=root / "server",
        reports_dir=reports_dir,
        data_file=root / ".build" / "coverage" / "python-sdk" / ".coverage",
        log_path=reports_dir / "python_sdk.coverage.pytest.log",
        raw_json_path=reports_dir / "python_sdk.coverage.json",
        xml_path=reports_dir / "python_sdk.coverage.xml",
        summary_path=reports_dir / "python_sdk.coverage-summary.json",
        junit_path=reports_dir / "python_sdk.coverage.junit.xml",
    )


def percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


def normalize_path(root: Path, path: str) -> str:
    absolute = Path(path).resolve()
    try:
        return absolute.relative_to(root).as_posix()
    except ValueError:
        return path


def file_summary(root: Path, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary", {})
    statements = int(summary.get("num_statements", 0) or 0)
    covered_lines = int(summary.get("covered_lines", 0) or 0)
    branches = int(summary.get("num_branches", 0) or 0)
    covered_branches = int(summary.get("covered_branches", 0) or 0)
    return {
        "path": normalize_path(root, path),
        "num_statements": statements,
        "covered_lines": covered_lines,
        "line_percent": percent(covered_lines, statements),
        "num_branches": branches,
        "covered_branches": covered_branches,
        "branch_percent": percent(covered_branches, branches),
        "missing_lines": payload.get("missing_lines", []),
        "missing_branches": payload.get("missing_branches", []),
    }


def build_summary(payload: dict[str, Any], *, root: Path, threshold: float, status: str, message: str) -> dict[str, Any]:
    files = [
        file_summary(root, path, item)
        for path, item in sorted(payload.get("files", {}).items())
        if isinstance(item, dict) and normalize_path(root, path).startswith(SOURCE_PREFIX)
    ]
    expected = {path.relative_to(root).as_posix() for path in (root / SOURCE_PREFIX).rglob("*.py")}
    missing = expected - {item["path"] for item in files}
    if not expected or missing:
        raise RuntimeError("missing Python SDK coverage sources: " + ", ".join(sorted(missing)))
    statements = sum(item["num_statements"] for item in files)
    covered_lines = sum(item["covered_lines"] for item in files)
    branches = sum(item["num_branches"] for item in files)
    covered_branches = sum(item["covered_branches"] for item in files)
    return {
        "version": 1,
        "status": status,
        "test_level": "python_sdk",
        "scope": "python_sdk/beacon_test",
        "generated_at": utc_now(),
        "line_threshold": threshold,
        "line_percent": percent(covered_lines, statements) or 0.0,
        "branch_percent": percent(covered_branches, branches),
        "covered_lines": covered_lines,
        "total_lines": statements,
        "missed_lines": statements - covered_lines,
        "covered_branches": covered_branches,
        "total_branches": branches,
        "missed_branches": branches - covered_branches,
        "message": message,
        "files": files,
    }


def empty_summary(threshold: float, status: str, message: str) -> dict[str, Any]:
    return {
        "version": 1,
        "status": status,
        "test_level": "python_sdk",
        "scope": "python_sdk/beacon_test",
        "generated_at": utc_now(),
        "line_threshold": threshold,
        "line_percent": 0.0,
        "branch_percent": None,
        "covered_lines": 0,
        "total_lines": 0,
        "missed_lines": 0,
        "covered_branches": 0,
        "total_branches": 0,
        "missed_branches": 0,
        "message": message,
        "files": [],
    }


def write_artifacts(paths: Paths, summary: dict[str, Any]) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    suite = ET.Element(
        "testsuite",
        name="python-sdk-coverage",
        tests="1",
        failures="1" if summary["status"] == "failed" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname="coverage", name=CASE_ID)
    if summary["status"] == "failed":
        ET.SubElement(case, "failure", message=summary["message"]).text = summary["message"]
    ET.ElementTree(suite).write(paths.junit_path, encoding="utf-8", xml_declaration=True)


def print_summary(summary: dict[str, Any]) -> None:
    print(
        "TOTAL_PYSDK "
        f"{summary['covered_lines']}/{summary['total_lines']} "
        f"line={summary['line_percent']:.2f}% missed={summary['missed_lines']}"
    )
    for item in summary["files"]:
        print(
            f"{(item['line_percent'] or 0.0):6.2f}% "
            f"{item['covered_lines']:4d}/{item['num_statements']:<4d} "
            f"missed={len(item['missing_lines']):<3d} {item['path']}"
        )


def run_coverage(paths: Paths, threshold: float, tests: list[str]) -> dict[str, Any]:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.data_file.parent.mkdir(parents=True, exist_ok=True)
    for path in (paths.data_file, paths.raw_json_path, paths.xml_path, paths.summary_path):
        path.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--branch",
        "--source",
        str(paths.root / "python_sdk" / "beacon_test"),
        "--data-file",
        str(paths.data_file),
        "-m",
        "pytest",
        *tests,
    ]
    completed = run(command, cwd=paths.server_dir)
    paths.log_path.write_text(report_text(completed.stdout, paths.root), encoding="utf-8")
    print(completed.stdout, end="")
    if completed.returncode != 0:
        return empty_summary(threshold, "failed", f"pytest failed; full log {paths.log_path.name}")

    json_result = run(
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            "--data-file",
            str(paths.data_file),
            "-o",
            str(paths.raw_json_path),
        ],
        cwd=paths.server_dir,
    )
    raw_json = paths.raw_json_path.read_text(encoding="utf-8") if paths.raw_json_path.exists() else None
    if raw_json is not None:
        paths.raw_json_path.write_text(
            report_text(raw_json, paths.root), encoding="utf-8"
        )
    payload = json.loads(raw_json) if json_result.returncode == 0 and raw_json is not None else None
    if json_result.returncode != 0:
        paths.log_path.write_text(report_text(completed.stdout + json_result.stdout, paths.root), encoding="utf-8")
        return empty_summary(threshold, "failed", f"coverage json failed; full log {paths.log_path.name}")
    xml_result = run(
        [
            sys.executable,
            "-m",
            "coverage",
            "xml",
            "--data-file",
            str(paths.data_file),
            "-o",
            str(paths.xml_path),
        ],
        cwd=paths.server_dir,
    )
    if paths.xml_path.exists():
        paths.xml_path.write_text(
            report_text(paths.xml_path.read_text(encoding="utf-8"), paths.root), encoding="utf-8"
        )
    if xml_result.returncode != 0:
        paths.log_path.write_text(report_text(completed.stdout + json_result.stdout + xml_result.stdout, paths.root), encoding="utf-8")
        return empty_summary(threshold, "failed", f"coverage xml failed; full log {paths.log_path.name}")

    assert payload is not None
    summary = build_summary(payload, root=paths.root, threshold=threshold, status="passed", message="python sdk coverage passed")
    if summary["total_lines"] == 0:
        summary["status"] = "failed"
        summary["message"] = "no Python SDK coverage files found"
    elif summary["line_percent"] < threshold:
        summary["status"] = "failed"
        summary["message"] = f"line coverage {summary['line_percent']:.2f}% is below threshold {threshold:.2f}%"
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Python SDK coverage.")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--line-threshold", type=float, default=95.0)
    parser.add_argument("--tests", nargs="*", default=list(DEFAULT_TESTS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    paths = prepare_paths(root, (root / args.reports_dir).resolve())
    try:
        summary = run_coverage(paths, args.line_threshold, list(args.tests))
    except Exception as exc:  # noqa: BLE001
        summary = empty_summary(args.line_threshold, "failed", report_text(str(exc), paths.root))
        write_artifacts(paths, summary)
        print(f"python sdk coverage: FAIL - {exc}", file=sys.stderr)
        return 1
    write_artifacts(paths, summary)
    print_summary(summary)
    print(f"python sdk coverage: log {paths.log_path}")
    print(f"python sdk coverage: raw json {paths.raw_json_path}")
    print(f"python sdk coverage: xml {paths.xml_path}")
    print(f"python sdk coverage: summary {paths.summary_path}")
    print(f"python sdk coverage: junit {paths.junit_path}")
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
