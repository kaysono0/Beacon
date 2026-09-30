#!/usr/bin/env python3
"""运行 Server pytest coverage 并写入标准化报告产物。

覆盖率结果是自动债务识别信号，不是第一版硬门禁。pytest 或 coverage
工具本身失败会返回非零；低覆盖文件只写入 summary 供 Evidence Gap Radar
消费。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Server pytest with coverage artifacts.")
    parser.add_argument("--cwd", default="server", help="Server package working directory.")
    parser.add_argument("--source", default="app", help="Coverage source package relative to cwd.")
    parser.add_argument("--tests", nargs="+", default=["tests"], help="Pytest test paths relative to cwd.")
    parser.add_argument("--reports-dir", default="reports/latest", help="Repository report artifact directory.")
    parser.add_argument("--line-threshold", type=float, default=70.0, help="Advisory low line coverage threshold.")
    parser.add_argument("--branch-threshold", type=float, default=50.0, help="Advisory low branch coverage threshold.")
    return parser.parse_args()


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _git_head(repo_root: Path) -> str:
    completed = _run(["git", "rev-parse", "--verify", "HEAD"], repo_root)
    head = completed.stdout.strip()
    if completed.returncode != 0 or len(head) != 40:
        raise ValueError("coverage source HEAD is unavailable")
    return head


@dataclass(frozen=True)
class CoveragePaths:
    cwd: Path
    reports_dir: Path
    data_file: Path
    junit_path: Path
    log_path: Path
    json_path: Path
    xml_path: Path
    summary_path: Path


def _coverage_paths(args: argparse.Namespace) -> CoveragePaths:
    repo_root = Path.cwd()
    reports_dir = (repo_root / args.reports_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    return CoveragePaths(
        cwd=(repo_root / args.cwd).resolve(),
        reports_dir=reports_dir,
        data_file=reports_dir / ".coverage.server",
        junit_path=reports_dir / "server.coverage.junit.xml",
        log_path=reports_dir / "server.coverage.pytest.log",
        json_path=reports_dir / "server.coverage.json",
        xml_path=reports_dir / "server.coverage.xml",
        summary_path=reports_dir / "server.coverage-summary.json",
    )


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _server_path(path: str) -> str:
    return path if path.startswith("server/") else f"server/{path}"


def _file_summary(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary", {})
    num_statements = int(summary.get("num_statements", 0) or 0)
    covered_lines = int(summary.get("covered_lines", 0) or 0)
    num_branches = int(summary.get("num_branches", 0) or 0)
    covered_branches = int(summary.get("covered_branches", 0) or 0)
    return {
        "path": _server_path(path),
        "num_statements": num_statements,
        "covered_lines": covered_lines,
        "line_percent": _percent(covered_lines, num_statements),
        "num_branches": num_branches,
        "covered_branches": covered_branches,
        "branch_percent": _percent(covered_branches, num_branches),
        "missing_lines": payload.get("missing_lines", []),
        "missing_branches": payload.get("missing_branches", []),
    }


def _is_low_coverage_file(item: dict[str, Any], line_threshold: float, branch_threshold: float) -> bool:
    if item["path"].endswith("/__init__.py") or item["num_statements"] == 0:
        return False
    line_percent = item.get("line_percent")
    branch_percent = item.get("branch_percent")
    return (line_percent is not None and line_percent < line_threshold) or (
        branch_percent is not None and branch_percent < branch_threshold
    )


def build_summary(
    coverage_payload: dict[str, Any],
    *,
    source_head: str,
    status: str,
    line_threshold: float,
    branch_threshold: float,
) -> dict[str, Any]:
    """把 coverage.py JSON 转为 Beacon 稳定摘要。"""

    files_payload = coverage_payload.get("files", {})
    files = [
        _file_summary(path, payload)
        for path, payload in sorted(files_payload.items())
        if isinstance(payload, dict) and path.startswith("app/")
    ]
    low_coverage_files = [
        item for item in files if _is_low_coverage_file(item, line_threshold, branch_threshold)
    ]
    totals = coverage_payload.get("totals", {})
    num_statements = int(totals.get("num_statements", 0) or 0)
    covered_lines = int(totals.get("covered_lines", 0) or 0)
    num_branches = int(totals.get("num_branches", 0) or 0)
    covered_branches = int(totals.get("covered_branches", 0) or 0)
    return {
        "version": 1,
        "status": status,
        "scope": "server/app",
        "source_head": source_head,
        "thresholds": {
            "line_percent": line_threshold,
            "branch_percent": branch_threshold,
        },
        "totals": {
            "num_statements": num_statements,
            "covered_lines": covered_lines,
            "line_percent": _percent(covered_lines, num_statements),
            "num_branches": num_branches,
            "covered_branches": covered_branches,
            "branch_percent": _percent(covered_branches, num_branches),
        },
        "files": files,
        "low_coverage_files": low_coverage_files[:10],
    }


def _write_failed_summary(
    reports_dir: Path,
    message: str,
    line_threshold: float,
    branch_threshold: float,
    source_head: str,
) -> None:
    payload = {
        "version": 1,
        "status": "failed",
        "scope": "server/app",
        "source_head": source_head,
        "thresholds": {
            "line_percent": line_threshold,
            "branch_percent": branch_threshold,
        },
        "error": message,
        "totals": {},
        "files": [],
        "low_coverage_files": [],
    }
    (reports_dir / "server.coverage-summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _invalidate_previous_artifacts(paths: CoveragePaths) -> None:
    for path in (paths.junit_path, paths.json_path, paths.xml_path, paths.summary_path):
        path.unlink(missing_ok=True)


def _write_failure_junit(path: Path, test_id: str, message: str) -> None:
    testsuite = ET.Element("testsuite", name="server-coverage", tests="1", failures="1", errors="0")
    testcase = ET.SubElement(testsuite, "testcase", classname="coverage", name=test_id)
    failure = ET.SubElement(testcase, "failure", message=message)
    failure.text = message
    ET.ElementTree(testsuite).write(path, encoding="utf-8", xml_declaration=True)


def _ensure_failure_junit(path: Path, test_id: str, message: str) -> None:
    if path.exists():
        return
    _write_failure_junit(path, test_id, message)


def _run_pytest_coverage(args: argparse.Namespace, paths: CoveragePaths) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--branch",
        "--source",
        args.source,
        "--data-file",
        str(paths.data_file),
        "-m",
        "pytest",
        *args.tests,
        "--junitxml",
        str(paths.junit_path),
    ]
    completed = _run(command, paths.cwd)
    paths.log_path.write_text(completed.stdout, encoding="utf-8")
    return completed


def _run_coverage_artifact_commands(paths: CoveragePaths) -> subprocess.CompletedProcess[str] | None:
    commands = [
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            "--data-file",
            str(paths.data_file),
            "-o",
            str(paths.json_path),
        ],
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
    ]
    for command in commands:
        completed = _run(command, paths.cwd)
        if completed.returncode != 0:
            return completed
    return None


def _write_passed_summary(args: argparse.Namespace, paths: CoveragePaths, source_head: str) -> dict[str, Any]:
    coverage_payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
    coverage_payload["source_head"] = source_head
    paths.json_path.write_text(
        json.dumps(coverage_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = build_summary(
        coverage_payload,
        source_head=source_head,
        status="passed",
        line_threshold=args.line_threshold,
        branch_threshold=args.branch_threshold,
    )
    paths.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    args = _parse_args()
    try:
        source_head = _git_head(Path.cwd())
    except ValueError as exc:
        print(f"server coverage: FAIL - {exc}", file=sys.stderr)
        return 1
    paths = _coverage_paths(args)
    _invalidate_previous_artifacts(paths)
    completed = _run_pytest_coverage(args, paths)
    if completed.returncode != 0:
        message = "pytest coverage run failed"
        _write_failed_summary(
            paths.reports_dir,
            "pytest coverage run failed",
            args.line_threshold,
            args.branch_threshold,
            source_head,
        )
        _ensure_failure_junit(paths.junit_path, "IT-SRV-COVERAGE", message)
        print(f"server coverage: FAIL - pytest failed; full log {paths.log_path}", file=sys.stderr)
        return completed.returncode

    artifact_failure = _run_coverage_artifact_commands(paths)
    if artifact_failure is not None:
        message = "coverage artifact generation failed"
        _write_failed_summary(
            paths.reports_dir,
            message,
            args.line_threshold,
            args.branch_threshold,
            source_head,
        )
        _write_failure_junit(paths.junit_path, "IT-SRV-COVERAGE-ARTIFACTS", message)
        print(artifact_failure.stdout, file=sys.stderr)
        return artifact_failure.returncode

    summary = _write_passed_summary(args, paths, source_head)
    print(
        "server coverage: PASS - "
        f"line={summary['totals'].get('line_percent')}% "
        f"branch={summary['totals'].get('branch_percent')}% "
        f"low_files={len(summary['low_coverage_files'])}"
    )
    print(f"server coverage: summary {paths.summary_path}")
    print(f"server coverage: full log {paths.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
