"""Run C++ mac mock coverage and write stable summary artifacts."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CASE_ID = "COVERAGE-CPP-MOCK"
PRODUCTION_PREFIXES = ("agent_core/src/", "agents/mac/src/")


@dataclass(frozen=True)
class Paths:
    root: Path
    build_dir: Path
    reports_dir: Path
    profile_dir: Path
    profdata_path: Path
    summary_path: Path
    junit_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def prepare_paths(root: Path, build_dir: Path, reports_dir: Path) -> Paths:
    return Paths(
        root=root,
        build_dir=build_dir,
        reports_dir=reports_dir,
        profile_dir=build_dir / "profiles",
        profdata_path=build_dir / "coverage.profdata",
        summary_path=reports_dir / "cpp_mock.coverage-summary.json",
        junit_path=reports_dir / "cpp_mock.coverage.junit.xml",
    )


def reset_profile_dir(profile_dir: Path) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    for path in profile_dir.glob("*.profraw"):
        path.unlink()


def is_executable(path: Path) -> bool:
    try:
        return path.is_file() and bool(path.stat().st_mode & stat.S_IXUSR)
    except OSError:
        return False


def coverage_objects(build_dir: Path) -> list[Path]:
    objects: list[Path] = []
    for directory in (build_dir / "agent_core", build_dir / "agents" / "mac"):
        if not directory.exists():
            continue
        objects.extend(
            path
            for path in directory.glob("*")
            if is_executable(path) and not path.name.endswith((".dylib", ".a"))
        )
    return sorted(objects)


def export_coverage(paths: Paths, objects: list[Path]) -> dict[str, Any]:
    if not objects:
        raise RuntimeError("no C++ coverage executables found")
    command = [
        "xcrun",
        "llvm-cov",
        "export",
        "-format=text",
        f"-instr-profile={paths.profdata_path}",
        str(objects[0]),
    ]
    for path in objects[1:]:
        command.extend(["-object", str(path)])
    completed = subprocess.run(command, cwd=paths.root, check=True, text=True, stdout=subprocess.PIPE)
    return json.loads(completed.stdout)


def collect_file_summaries(root: Path, payload: dict[str, Any]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for item in payload["data"][0]["files"]:
        absolute = Path(item["filename"]).resolve()
        try:
            relative = absolute.relative_to(root).as_posix()
        except ValueError:
            continue
        if not relative.endswith(".cc") or not relative.startswith(PRODUCTION_PREFIXES):
            continue
        lines = item["summary"]["lines"]
        count = int(lines["count"])
        covered = int(lines["covered"])
        if count == 0:
            continue
        files.append(
            {
                "path": relative,
                "covered": covered,
                "count": count,
                "missed": count - covered,
                "percent": round(covered / count * 100, 2),
            }
        )
    return sorted(files, key=lambda item: (item["percent"], item["path"]))


def make_summary(files: list[dict[str, Any]], threshold: float, status: str, message: str) -> dict[str, Any]:
    covered = sum(item["covered"] for item in files)
    count = sum(item["count"] for item in files)
    line_percent = round(covered / count * 100, 2) if count else 0.0
    return {
        "version": 1,
        "status": status,
        "test_level": "cpp_mock",
        "scope": "agent_core/src + agents/mac/src production .cc",
        "generated_at": utc_now(),
        "line_threshold": threshold,
        "line_percent": line_percent,
        "covered_lines": covered,
        "total_lines": count,
        "missed_lines": count - covered,
        "message": message,
        "files": files,
    }


def write_artifacts(paths: Paths, summary: dict[str, Any]) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    suite = ET.Element("testsuite", name="cpp-mock-coverage", tests="1")
    suite.set("failures", "0" if summary["status"] == "passed" else "1")
    case = ET.SubElement(suite, "testcase", classname="coverage", name=CASE_ID)
    if summary["status"] != "passed":
        ET.SubElement(case, "failure", message=summary["message"]).text = summary["message"]
    ET.ElementTree(suite).write(paths.junit_path, encoding="utf-8", xml_declaration=True)


def print_summary(summary: dict[str, Any]) -> None:
    print(
        "TOTAL_CC "
        f"{summary['covered_lines']}/{summary['total_lines']} "
        f"line={summary['line_percent']:.2f}% missed={summary['missed_lines']}"
    )
    for item in summary["files"]:
        print(
            f"{item['percent']:6.2f}% "
            f"{item['covered']:4d}/{item['count']:<4d} "
            f"missed={item['missed']:<3d} {item['path']}"
        )


def merge_profiles(paths: Paths) -> None:
    profiles = sorted(paths.profile_dir.glob("*.profraw"))
    if not profiles:
        raise RuntimeError("no profraw files generated")
    run(["xcrun", "llvm-profdata", "merge", "-sparse", *map(str, profiles), "-o", str(paths.profdata_path)], cwd=paths.root)


def run_coverage(paths: Paths, threshold: float) -> dict[str, Any]:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            "cmake",
            "-S",
            ".",
            "-B",
            str(paths.build_dir),
            "-DCMAKE_BUILD_TYPE=Debug",
            "-DCMAKE_CXX_FLAGS=-fprofile-instr-generate -fcoverage-mapping",
            "-DCMAKE_C_FLAGS=-fprofile-instr-generate -fcoverage-mapping",
        ],
        cwd=paths.root,
    )
    run(["cmake", "--build", str(paths.build_dir)], cwd=paths.root)
    reset_profile_dir(paths.profile_dir)
    env = os.environ.copy()
    env["LLVM_PROFILE_FILE"] = str(paths.profile_dir / "%p.profraw")
    run(["ctest", "--test-dir", str(paths.build_dir), "--output-on-failure"], cwd=paths.root, env=env)
    merge_profiles(paths)
    files = collect_file_summaries(paths.root, export_coverage(paths, coverage_objects(paths.build_dir)))
    summary = make_summary(files, threshold, "passed", "cpp mock coverage passed")
    if summary["line_percent"] < threshold:
        summary["status"] = "failed"
        summary["message"] = f"line coverage {summary['line_percent']:.2f}% is below threshold {threshold:.2f}%"
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run C++ mac mock coverage and write summary artifacts.")
    parser.add_argument("--build-dir", default=".build/coverage/mock")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--line-threshold", type=float, default=95.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    paths = prepare_paths(root, root / args.build_dir, root / args.reports_dir)
    try:
        summary = run_coverage(paths, args.line_threshold)
    except Exception as exc:  # noqa: BLE001
        summary = make_summary([], args.line_threshold, "failed", str(exc))
        write_artifacts(paths, summary)
        print(f"cpp mock coverage: FAIL - {exc}", file=sys.stderr)
        return 1
    write_artifacts(paths, summary)
    print_summary(summary)
    print(f"cpp mock coverage: summary {paths.summary_path}")
    print(f"cpp mock coverage: junit {paths.junit_path}")
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
