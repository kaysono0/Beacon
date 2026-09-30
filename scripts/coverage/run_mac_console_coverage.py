#!/usr/bin/env python3
"""Run Mac Test Console Swift coverage and write stable artifacts."""

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


CASE_ID = "COVERAGE-MAC-CONSOLE"
PACKAGE_PATH = "apps/mac_test_console"
SOURCE_PREFIX = "apps/mac_test_console/Sources/BeaconMacTestConsole/"
THRESHOLD_EXCLUDED_PREFIXES = (SOURCE_PREFIX + "Views/",)
THRESHOLD_EXCLUDED_FILES = (SOURCE_PREFIX + "BeaconMacTestConsoleApp.swift",)
THRESHOLD_SCOPE = (
    "apps/mac_test_console/Sources/BeaconMacTestConsole production logic .swift "
    "(excluding SwiftUI app/view shell)"
)


@dataclass(frozen=True)
class Paths:
    root: Path
    package_dir: Path
    reports_dir: Path
    log_path: Path
    raw_json_path: Path
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
        package_dir=root / PACKAGE_PATH,
        reports_dir=reports_dir,
        log_path=reports_dir / "mac_console.coverage.log",
        raw_json_path=reports_dir / "mac_console.coverage.json",
        summary_path=reports_dir / "mac_console.coverage-summary.json",
        junit_path=reports_dir / "mac_console.coverage.junit.xml",
    )


def swiftpm_coverage_json(package_dir: Path) -> Path:
    candidates = sorted(
        package_dir.glob(".build/*/debug/codecov/BeaconMacTestConsole.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("SwiftPM coverage JSON not found under apps/mac_test_console/.build/*/debug/codecov")
    return candidates[0]


def file_summaries(root: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for item in payload["data"][0]["files"]:
        absolute = Path(item["filename"]).resolve()
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError:
            continue
        if not relative.startswith(SOURCE_PREFIX) or not relative.endswith(".swift"):
            continue
        lines = item["summary"]["lines"]
        count = int(lines["count"])
        covered = int(lines["covered"])
        if count == 0:
            continue
        excluded_reason = threshold_exclusion_reason(relative)
        files.append(
            {
                "path": relative,
                "covered": covered,
                "count": count,
                "missed": count - covered,
                "percent": round(covered / count * 100, 2),
                "excluded_from_threshold": excluded_reason is not None,
                "threshold_exclusion_reason": excluded_reason,
            }
        )
    return sorted(files, key=lambda item: (item["percent"], item["path"]))


def threshold_exclusion_reason(path: str) -> str | None:
    if path in THRESHOLD_EXCLUDED_FILES:
        return "SwiftUI app entry is exercised by app launch/UI smoke, not XCTest line gate"
    if path.startswith(THRESHOLD_EXCLUDED_PREFIXES):
        return "SwiftUI view rendering shell is reported as raw coverage but excluded from stable logic threshold"
    return None


def make_summary(files: list[dict[str, Any]], threshold: float, status: str, message: str) -> dict[str, Any]:
    threshold_files = [item for item in files if not item["excluded_from_threshold"]]
    covered = sum(item["covered"] for item in threshold_files)
    count = sum(item["count"] for item in threshold_files)
    line_percent = round(covered / count * 100, 2) if count else 0.0
    raw_covered = sum(item["covered"] for item in files)
    raw_count = sum(item["count"] for item in files)
    return {
        "version": 1,
        "status": status,
        "test_level": "mac_console",
        "scope": THRESHOLD_SCOPE,
        "threshold_metric": "line_percent over non-excluded production logic Swift files",
        "generated_at": utc_now(),
        "line_threshold": threshold,
        "line_percent": line_percent,
        "covered_lines": covered,
        "total_lines": count,
        "missed_lines": count - covered,
        "raw_scope": "apps/mac_test_console/Sources/BeaconMacTestConsole production .swift",
        "raw_line_percent": round(raw_covered / raw_count * 100, 2) if raw_count else 0.0,
        "raw_covered_lines": raw_covered,
        "raw_total_lines": raw_count,
        "raw_missed_lines": raw_count - raw_covered,
        "message": message,
        "files": files,
    }


def write_artifacts(paths: Paths, summary: dict[str, Any]) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    suite = ET.Element(
        "testsuite",
        name="mac-console-coverage",
        tests="1",
        failures="1" if summary["status"] == "failed" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname="coverage", name=CASE_ID)
    if summary["status"] == "failed":
        ET.SubElement(case, "failure", message=summary["message"]).text = summary["message"]
    ET.ElementTree(suite).write(paths.junit_path, encoding="utf-8", xml_declaration=True)


def print_summary(summary: dict[str, Any]) -> None:
    print(
        "THRESHOLD_SWIFT "
        f"{summary['covered_lines']}/{summary['total_lines']} "
        f"line={summary['line_percent']:.2f}% missed={summary['missed_lines']}"
    )
    print(
        "RAW_SWIFT "
        f"{summary['raw_covered_lines']}/{summary['raw_total_lines']} "
        f"line={summary['raw_line_percent']:.2f}% missed={summary['raw_missed_lines']}"
    )
    for item in summary["files"]:
        marker = " excluded" if item["excluded_from_threshold"] else ""
        print(
            f"{item['percent']:6.2f}% "
            f"{item['covered']:4d}/{item['count']:<4d} "
            f"missed={item['missed']:<3d} {item['path']}{marker}"
        )


def run_coverage(paths: Paths, threshold: float) -> dict[str, Any]:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    completed = run(["swift", "test", "--package-path", PACKAGE_PATH, "--enable-code-coverage"], cwd=paths.root)
    paths.log_path.write_text(report_text(completed.stdout, paths.root), encoding="utf-8")
    print(completed.stdout, end="")
    if completed.returncode != 0:
        return make_summary([], threshold, "failed", f"swift test failed; full log {paths.log_path.name}")

    coverage_json = swiftpm_coverage_json(paths.package_dir)
    payload = json.loads(coverage_json.read_text(encoding="utf-8"))
    files = file_summaries(paths.root, payload)
    # 原始 SwiftPM 产物留在 .build；上传目录仅保留路径相对化的 JSON 投影。
    paths.raw_json_path.write_text(
        report_text(json.dumps(payload, indent=2, sort_keys=True), paths.root) + "\n",
        encoding="utf-8",
    )
    if not files:
        raise RuntimeError("no Mac Test Console production Swift coverage files found")
    if not any(not item["excluded_from_threshold"] for item in files):
        raise RuntimeError("no Mac Test Console threshold Swift coverage files found")
    summary = make_summary(files, threshold, "passed", "mac console coverage passed")
    if summary["line_percent"] < threshold:
        summary["status"] = "failed"
        summary["message"] = f"line coverage {summary['line_percent']:.2f}% is below threshold {threshold:.2f}%"
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mac Test Console Swift coverage.")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--line-threshold", type=float, default=0.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    paths = prepare_paths(root, root / args.reports_dir)
    try:
        summary = run_coverage(paths, args.line_threshold)
    except Exception as exc:  # noqa: BLE001
        summary = make_summary([], args.line_threshold, "failed", report_text(str(exc), paths.root))
        write_artifacts(paths, summary)
        print(f"mac console coverage: FAIL - {exc}", file=sys.stderr)
        return 1
    write_artifacts(paths, summary)
    print_summary(summary)
    print(f"mac console coverage: log {paths.log_path}")
    print(f"mac console coverage: raw json {paths.raw_json_path}")
    print(f"mac console coverage: summary {paths.summary_path}")
    print(f"mac console coverage: junit {paths.junit_path}")
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
