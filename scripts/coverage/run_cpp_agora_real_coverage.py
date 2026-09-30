"""Run Objective-C++ mac real backend coverage and write stable artifacts."""

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
from time import time as unix_time
from typing import Any


CASE_ID = "COVERAGE-CPP-REAL"
DEFAULT_LINE_THRESHOLD = 95.0
PRODUCTION_PREFIXES = ("agents/mac/src/",)
PRODUCTION_SUFFIXES = (".mm",)
REQUIRED_ENV = ("AGORA_MAC_SDK_ROOT", "AGORA_APP_ID", "AGORA_APP_CERT")
REAL_TEST_PATTERN = "BRIDGE-MAC-REAL|IT-AGORA"
BACKEND_SOURCE = "agents/mac/src/vendors/agora/rtc_backend_real.mm"

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.coverage.cpp_real_coverage_support import collect_file_summaries as collect_full_file_summaries  # noqa: E402


@dataclass(frozen=True)
class Paths:
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


def prepare_paths(root: Path, build_dir: Path, reports_dir: Path) -> Paths:
    return Paths(
        root=root,
        build_dir=build_dir,
        reports_dir=reports_dir,
        profile_dir=build_dir / "profiles",
        profdata_path=build_dir / "coverage.profdata",
        summary_path=reports_dir / "cpp_real.coverage-summary.json",
        junit_path=reports_dir / "cpp_real.coverage.junit.xml",
        ctest_log_path=reports_dir / "cpp_real.ctest.log",
        ctest_junit_path=reports_dir / "cpp_real.ctest.junit.xml",
    )


def missing_real_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def agora_framework_exists() -> bool:
    sdk_root = os.environ.get("AGORA_MAC_SDK_ROOT")
    if not sdk_root:
        return False
    root = Path(sdk_root)
    if (root / "AgoraRtcKit.framework").exists():
        return True
    return any((root / "AgoraRtcKit.xcframework").glob("*/AgoraRtcKit.framework"))


def agora_dyld_framework_path() -> str:
    sdk_root = os.environ.get("AGORA_MAC_SDK_ROOT")
    if not sdk_root:
        return ""
    root = Path(sdk_root)
    if (root / "AgoraRtcKit.framework").exists():
        return str(root)
    slice_dirs = sorted(
        {
            str(path)
            for pattern in ("*.xcframework/macos-*", "*.xcframework/*-macos*")
            for path in root.glob(pattern)
            if path.is_dir()
        }
    )
    return ":".join(slice_dirs)


def configure_rtc_token(root: Path) -> None:
    """正式 gate 总是现场签发：环境里预设的 token 可能是过期的旧值，
    静默复用会让门禁拿到与凭证不一致的 token（本机已因静态 token 过期复现过一次）。"""
    expire_at = int(unix_time()) + 3600
    token = subprocess.check_output(
        [
            "uv",
            "run",
            "--python",
            "3.11",
            "--extra",
            "agora",
            "python",
            "-c",
            (
                "from agora_token_builder import RtcTokenBuilder;"
                "import os,sys;"
                "sys.stdout.write(RtcTokenBuilder.buildTokenWithUid("
                "os.environ['AGORA_APP_ID'], os.environ['AGORA_APP_CERT'], 'real-smoke', 1001, 1, "
                f"{expire_at}))"
            ),
        ],
        cwd=root / "server",
        text=True,
    )
    os.environ["AGORA_RTC_TOKEN"] = token


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
    candidates = [
        build_dir / "agents" / "mac" / "mac_real_adapter_test",
    ]
    return [path for path in candidates if is_executable(path)]


def export_coverage(paths: Paths, objects: list[Path]) -> dict[str, Any]:
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


def collect_file_summaries(paths: Paths, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return collect_full_file_summaries(
        paths, payload,
        production_prefixes=PRODUCTION_PREFIXES,
        production_suffixes=PRODUCTION_SUFFIXES,
        required_sources=(BACKEND_SOURCE, "agents/mac/src/video/synthetic_video_clip.mm"),
    )


def make_summary(files: list[dict[str, Any]], threshold: float, status: str, message: str) -> dict[str, Any]:
    covered = sum(item["covered"] for item in files)
    count = sum(item["count"] for item in files)
    raw_covered = sum(item.get("raw_covered", item["covered"]) for item in files)
    raw_count = sum(item.get("raw_count", item["count"]) for item in files)
    line_percent = round(covered / count * 100, 2) if count else 0.0
    raw_line_percent = round(raw_covered / raw_count * 100, 2) if raw_count else 0.0
    return {
        "version": 1,
        "status": status,
        "test_level": "cpp_real",
        "scope": "agents/mac/src production .mm full files",
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


def write_artifacts(paths: Paths, summary: dict[str, Any]) -> None:
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    suite = ET.Element(
        "testsuite",
        name="cpp-real-coverage",
        tests="1",
        failures="1" if summary["status"] == "failed" else "0",
        skipped="1" if summary["status"] == "skipped" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname="coverage", name=CASE_ID)
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


def merge_profiles(paths: Paths) -> None:
    profiles = sorted(paths.profile_dir.glob("*.profraw"))
    if not profiles:
        raise RuntimeError("no profraw files generated")
    run(["xcrun", "llvm-profdata", "merge", "-sparse", *map(str, profiles), "-o", str(paths.profdata_path)], cwd=paths.root)


def report_text(value: str, root: Path) -> str:
    return value.replace(str(root), ".").replace(str(Path.home()), "~")


def run_real_ctest(paths: Paths, env: dict[str, str]) -> None:
    command = [
        "ctest",
        "--test-dir",
        str(paths.build_dir),
        "-R",
        REAL_TEST_PATTERN,
        "--output-on-failure",
        "--output-junit",
        str(paths.ctest_junit_path),
    ]
    print("+ " + " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=paths.root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    paths.ctest_log_path.write_text(report_text(completed.stdout, paths.root), encoding="utf-8")
    if paths.ctest_junit_path.exists():
        paths.ctest_junit_path.write_text(
            report_text(paths.ctest_junit_path.read_text(encoding="utf-8"), paths.root), encoding="utf-8"
        )
    print(completed.stdout, end="")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, command, output=completed.stdout)


def run_coverage(paths: Paths, threshold: float) -> dict[str, Any]:
    missing = missing_real_env()
    if missing:
        return make_summary([], threshold, "skipped", "missing real mac sdk environment: " + ",".join(missing))
    if not agora_framework_exists():
        return make_summary([], threshold, "skipped", "missing AgoraRtcKit.framework under AGORA_MAC_SDK_ROOT")

    configure_rtc_token(paths.root)
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
            "-DCMAKE_OBJCXX_FLAGS=-fprofile-instr-generate -fcoverage-mapping",
        ],
        cwd=paths.root,
    )
    run(["cmake", "--build", str(paths.build_dir), "--target", "mac_real_adapter_test"], cwd=paths.root)
    reset_profile_dir(paths.profile_dir)
    env = os.environ.copy()
    env["LLVM_PROFILE_FILE"] = str(paths.profile_dir / "%p.profraw")
    dyld_framework_path = agora_dyld_framework_path()
    if dyld_framework_path:
        existing = env.get("DYLD_FRAMEWORK_PATH", "")
        env["DYLD_FRAMEWORK_PATH"] = f"{dyld_framework_path}:{existing}" if existing else dyld_framework_path
    run_real_ctest(paths, env)
    merge_profiles(paths)
    objects = coverage_objects(paths.build_dir)
    files = collect_file_summaries(paths, export_coverage(paths, objects))
    if not files:
        raise RuntimeError("no Objective-C++ production .mm coverage files found")
    summary = make_summary(files, threshold, "passed", "cpp real coverage passed")
    if summary["line_percent"] < threshold:
        summary["status"] = "failed"
        summary["message"] = f"line coverage {summary['line_percent']:.2f}% is below threshold {threshold:.2f}%"
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Objective-C++ mac real backend coverage.")
    parser.add_argument("--build-dir", default=".build/coverage/agora-real")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--line-threshold", type=float, default=DEFAULT_LINE_THRESHOLD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    paths = prepare_paths(root, root / args.build_dir, root / args.reports_dir)
    try:
        summary = run_coverage(paths, args.line_threshold)
    except Exception as exc:  # noqa: BLE001
        summary = make_summary([], args.line_threshold, "failed", report_text(str(exc), paths.root))
        write_artifacts(paths, summary)
        print(f"cpp real coverage: FAIL - {exc}", file=sys.stderr)
        return 1
    write_artifacts(paths, summary)
    print_summary(summary)
    print(f"cpp real coverage: summary {paths.summary_path}")
    print(f"cpp real coverage: junit {paths.junit_path}")
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
