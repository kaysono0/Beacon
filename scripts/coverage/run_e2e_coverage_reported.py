#!/usr/bin/env python3
"""在 coverage.py 下运行 Beacon Mock E2E 并写入标准化 artifact。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Beacon Mock E2E with Server coverage.")
    parser.add_argument("--script", default="scripts/validation/run_e2e_mock_tests.py")
    parser.add_argument("--source", default="server/app")
    parser.add_argument("--reports-dir", default="reports/latest")
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


def _write_summary(
    path: Path,
    *,
    source_head: str,
    status: str,
    payload: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    totals = payload.get("totals", {}) if isinstance(payload, dict) else {}
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "status": status,
                "scope": "server/app",
                "test_level": "mock_e2e",
                "source_head": source_head,
                "totals": totals,
                **({"error": error} if error else {}),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = _parse_args()
    repo_root = Path.cwd()
    try:
        source_head = _git_head(repo_root)
    except ValueError as exc:
        print(f"mock e2e coverage: FAIL - {exc}", file=sys.stderr)
        return 1
    reports_dir = (repo_root / args.reports_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_path = reports_dir / ".coverage.server.e2e-mock"
    json_path = reports_dir / "server.e2e-mock.coverage.json"
    summary_path = reports_dir / "server.e2e-mock.coverage-summary.json"
    log_path = reports_dir / "server.e2e-mock.coverage.log"
    for path in (data_path, json_path, summary_path):
        path.unlink(missing_ok=True)

    completed = _run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            "--branch",
            "--source",
            args.source,
            "--data-file",
            str(data_path),
            args.script,
        ],
        repo_root,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        _write_summary(
            summary_path,
            source_head=source_head,
            status="failed",
            error="Mock E2E coverage run failed",
        )
        print(f"mock e2e coverage: FAIL - full log {log_path}", file=sys.stderr)
        return completed.returncode

    artifact = _run(
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            "--data-file",
            str(data_path),
            "-o",
            str(json_path),
        ],
        repo_root,
    )
    if artifact.returncode != 0:
        _write_summary(
            summary_path,
            source_head=source_head,
            status="failed",
            error="Mock E2E coverage artifact generation failed",
        )
        log_path.write_text(completed.stdout + artifact.stdout, encoding="utf-8")
        print(artifact.stdout, file=sys.stderr)
        return artifact.returncode

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["source_head"] = source_head
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_summary(summary_path, source_head=source_head, status="passed", payload=payload)
    print(f"mock e2e coverage: PASS - summary {summary_path}")
    print(f"mock e2e coverage: full log {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
