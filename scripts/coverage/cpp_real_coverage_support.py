"""Objective-C++ 真实后端覆盖率脚本的共享实现（vendor 无关部分）。

各 vendor 的 gate 脚本负责提供自己的 SDK 探测、构建目标、ctest 选择、必需统计源文件与产物名；
本模块只保留收集与汇总逻辑，避免每个 vendor 复制一份覆盖率数学。
"""

from __future__ import annotations

import json
import stat
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CoveragePaths:
    root: Path
    build_dir: Path
    reports_dir: Path
    profile_dir: Path
    profdata_path: Path
    summary_path: Path
    junit_path: Path
    ctest_log_path: Path
    ctest_junit_path: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def prepare_paths(root: Path, build_dir: Path, reports_dir: Path, artifact_prefix: str) -> CoveragePaths:
    return CoveragePaths(
        root=root,
        build_dir=build_dir,
        reports_dir=reports_dir,
        profile_dir=build_dir / "profiles",
        profdata_path=build_dir / "coverage.profdata",
        summary_path=reports_dir / f"{artifact_prefix}.coverage-summary.json",
        junit_path=reports_dir / f"{artifact_prefix}.coverage.junit.xml",
        ctest_log_path=reports_dir / f"{artifact_prefix}.ctest.log",
        ctest_junit_path=reports_dir / f"{artifact_prefix}.ctest.junit.xml",
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


def export_coverage(paths: CoveragePaths, objects: list[Path]) -> dict[str, Any]:
    if not objects:
        raise RuntimeError("no Objective-C++ real coverage executables found")
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


def collect_file_summaries(
    paths: CoveragePaths,
    payload: dict[str, Any],
    *,
    production_prefixes: tuple[str, ...],
    production_suffixes: tuple[str, ...],
    required_sources: tuple[str, ...],
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for item in payload["data"][0]["files"]:
        absolute = Path(item["filename"]).resolve()
        try:
            relative = absolute.relative_to(paths.root).as_posix()
        except ValueError:
            continue
        if not relative.endswith(production_suffixes) or not relative.startswith(production_prefixes):
            continue
        lines = item["summary"]["lines"]
        covered, count = int(lines["covered"]), int(lines["count"])
        if not 0 <= covered <= count:
            raise RuntimeError(f"invalid coverage counts for {relative}")
        if count == 0:
            continue
        files.append({
            "path": relative,
            "scope": "full_file",
            "excluded_line_ranges": [],
            "covered": covered,
            "count": count,
            "missed": count - covered,
            "percent": round(covered / count * 100, 2),
            "raw_covered": covered,
            "raw_count": count,
            "raw_missed": count - covered,
            "raw_percent": round(covered / count * 100, 2),
        })
    measured = {item["path"] for item in files}
    missing = set(required_sources) - measured
    if missing:
        raise RuntimeError("missing or empty required coverage sources: " + ", ".join(sorted(missing)))
    return sorted(files, key=lambda item: (item["percent"], item["path"]))


def make_summary(
    files: list[dict[str, Any]],
    threshold: float,
    status: str,
    message: str,
    *,
    test_level: str,
    scope: str,
) -> dict[str, Any]:
    covered = sum(item["covered"] for item in files)
    count = sum(item["count"] for item in files)
    raw_covered = sum(item.get("raw_covered", item["covered"]) for item in files)
    raw_count = sum(item.get("raw_count", item["count"]) for item in files)
    line_percent = round(covered / count * 100, 2) if count else 0.0
    raw_line_percent = round(raw_covered / raw_count * 100, 2) if raw_count else 0.0
    return {
        "version": 1,
        "status": status,
        "test_level": test_level,
        "scope": scope,
        "generated_at": utc_now(),
        "line_threshold": threshold,
        "threshold_metric": "line_percent and raw_line_percent count full production files without exclusions",
        "line_percent": line_percent,
        "raw_line_percent": raw_line_percent,
        "covered_lines": covered,
        "total_lines": count,
        "missed_lines": count - covered,
        "raw_covered_lines": raw_covered,
        "raw_total_lines": raw_count,
        "raw_missed_lines": raw_count - raw_covered,
        "message": message,
        "files": files,
    }


def write_artifacts(paths: CoveragePaths, summary: dict[str, Any], *, case_id: str, suite_name: str) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    suite = ET.Element(
        "testsuite",
        name=suite_name,
        tests="1",
        failures="1" if summary["status"] == "failed" else "0",
        skipped="1" if summary["status"] == "skipped" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname="coverage", name=case_id)
    if summary["status"] == "failed":
        ET.SubElement(case, "failure", message=summary["message"]).text = summary["message"]
    if summary["status"] == "skipped":
        ET.SubElement(case, "skipped", message=summary["message"]).text = summary["message"]
    ET.ElementTree(suite).write(paths.junit_path, encoding="utf-8", xml_declaration=True)


def print_summary(summary: dict[str, Any]) -> None:
    print(
        "TOTAL_MM "
        f"{summary['covered_lines']}/{summary['total_lines']} "
        f"line={summary['line_percent']:.2f}% "
        f"raw={summary['raw_line_percent']:.2f}% missed={summary['missed_lines']}"
    )
    for item in summary["files"]:
        print(
            f"{item['percent']:6.2f}% "
            f"{item['covered']:4d}/{item['count']:<4d} "
            f"raw={item['raw_percent']:6.2f}% "
            f"missed={item['missed']:<3d} {item['path']}"
        )


def merge_profiles(paths: CoveragePaths) -> None:
    profiles = sorted(paths.profile_dir.glob("*.profraw"))
    if not profiles:
        raise RuntimeError("no profraw files generated")
    run(["xcrun", "llvm-profdata", "merge", "-sparse", *map(str, profiles), "-o", str(paths.profdata_path)], cwd=paths.root)


def run_ctest(paths: CoveragePaths, env: dict[str, str], pattern: str) -> None:
    command = [
        "ctest",
        "--test-dir",
        str(paths.build_dir),
        "-R",
        pattern,
        "--output-on-failure",
        "--output-junit",
        str(paths.ctest_junit_path),
    ]
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=paths.root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.ctest_log_path.write_text(completed.stdout, encoding="utf-8")
    print(completed.stdout, end="")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command, output=completed.stdout)
