"""火山引擎真实后端的 Objective-C++ 覆盖率门禁。

要求 SDK 根（`VOLCENGINE_MAC_SDK_ROOT`）与其中的 `VolcEngineRTC.framework`；缺失时写 skipped
产物并 exit 0。覆盖率统计生产 `.mm` 完整文件；必需后端缺失或没有可执行行时失败。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.coverage.cpp_real_coverage_support import (  # noqa: E402
    collect_file_summaries as collect_full_file_summaries,
    export_coverage,
    is_executable,
    make_summary,
    merge_profiles,
    prepare_paths,
    print_summary,
    reset_profile_dir,
    run,
    run_ctest,
    write_artifacts,
)


CASE_ID = "COVERAGE-CPP-VOLCENGINE-REAL"
DEFAULT_LINE_THRESHOLD = 95.0
ARTIFACT_PREFIX = "cpp_volcengine_real"
PRODUCTION_PREFIXES = ("agents/mac/src/",)
PRODUCTION_SUFFIXES = (".mm",)
REQUIRED_ENV = ("VOLCENGINE_MAC_SDK_ROOT", "VOLCENGINE_RTC_ID", "VOLCENGINE_RTC_APPKEY")
# 四条用例全部纳入：引擎生命周期、夹具与未声明能力、真实 join/leave（真 app id + 现场签发 token）。
TEST_PATTERN = "VOLCENGINE-REAL"
TEST_TARGET = "mac_real_volcengine_adapter_test"
BACKEND_SOURCE = "agents/mac/src/vendors/volcengine/rtc_backend_real_volcengine.mm"


def collect_file_summaries(paths, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return collect_full_file_summaries(
        paths, payload,
        production_prefixes=PRODUCTION_PREFIXES,
        production_suffixes=PRODUCTION_SUFFIXES,
        required_sources=(BACKEND_SOURCE, "agents/mac/src/video/synthetic_video_clip.mm"),
    )


def missing_real_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def sdk_root() -> Path | None:
    value = os.environ.get("VOLCENGINE_MAC_SDK_ROOT")
    return Path(value) if value else None


def framework_exists(root: Path | None) -> bool:
    return root is not None and (root / "VolcEngineRTC.framework").exists()


def quarantine_offenders(root: Path) -> list[str]:
    """带 com.apple.quarantine 的条目会让 dyld 拒绝加载 framework，先给出明确错误而不是让进程 abort。"""
    completed = subprocess.run(
        ["xattr", "-l", str(root)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    offenders = [str(root)] if "com.apple.quarantine" in completed.stdout else []
    framework = root / "VolcEngineRTC.framework"
    if framework.exists():
        probe = subprocess.run(
            ["xattr", "-l", str(framework)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if "com.apple.quarantine" in probe.stdout:
            offenders.append(str(framework))
    return offenders


def coverage_objects(build_dir: Path, executable_name: str) -> list[Path]:
    candidate = build_dir / "agents" / "mac" / executable_name
    return [candidate] if is_executable(candidate) else []


def configure_rtc_token() -> None:
    """用 vendored 官方 builder 为本轮 gate 签发 room token（不落盘、不打印）。

    正式 gate 总是现场签发：环境里预设的 token 可能是过期的旧值，静默复用会让门禁
    拿到与凭证不一致的 token（Agora 侧已因静态 token 过期复现过一次）。
    """
    app_id = os.environ["VOLCENGINE_RTC_ID"]
    app_key = os.environ["VOLCENGINE_RTC_APPKEY"]
    room_id = os.environ.get("VOLCENGINE_RTC_ROOM_ID") or "beacon-volcengine-l1-room"
    user_id = os.environ.get("VOLCENGINE_RTC_USER_ID") or "beacon-user-001"
    script = (
        "import sys, time; sys.path.insert(0, 'server');"
        "from vendor.volcengine_rtc_token import AccessToken;"
        f"expire = int(time.time()) + 3600;"
        f"t = AccessToken.AccessToken({app_id!r}, {app_key!r}, {room_id!r}, {user_id!r});"
        "t.add_privilege(AccessToken.PrivSubscribeStream, expire);"
        "t.add_privilege(AccessToken.PrivPublishStream, expire);"
        "t.expire_time(expire); print(t.serialize())"
    )
    token = subprocess.check_output([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2], text=True).strip()
    if not token:
        raise RuntimeError("failed to mint a Volcengine room token")
    os.environ["VOLCENGINE_RTC_TOKEN"] = token


def run_coverage(paths, threshold: float) -> dict[str, Any]:
    missing = missing_real_env()
    if missing:
        return make_summary([], threshold, "skipped", "missing real mac sdk environment: " + ",".join(missing),
                            test_level="cpp_real", scope="agents/mac/src production .mm full files (volcengine)")
    root = sdk_root()
    if not framework_exists(root):
        return make_summary([], threshold, "skipped",
                            "missing VolcEngineRTC.framework under VOLCENGINE_MAC_SDK_ROOT",
                            test_level="cpp_real", scope="agents/mac/src production .mm full files (volcengine)")
    assert root is not None
    offenders = quarantine_offenders(root)
    if offenders:
        raise RuntimeError(
            "SDK entries still carry com.apple.quarantine, dyld will refuse them: "
            + ", ".join(offenders)
            + " (fix: find . -print0 | xargs -0 xattr -d com.apple.quarantine)"
        )

    configure_rtc_token()
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
    run(["cmake", "--build", str(paths.build_dir), "--target", TEST_TARGET], cwd=paths.root)
    reset_profile_dir(paths.profile_dir)
    env = os.environ.copy()
    env["LLVM_PROFILE_FILE"] = str(paths.profile_dir / "%p.profraw")
    run_ctest(paths, env, TEST_PATTERN)
    merge_profiles(paths)
    objects = coverage_objects(paths.build_dir, TEST_TARGET)
    files = collect_file_summaries(
        paths,
        export_coverage(paths, objects),
    )
    if not files:
        raise RuntimeError("no Objective-C++ production .mm coverage files found")
    summary = make_summary(files, threshold, "passed", "cpp volcengine real coverage passed",
                           test_level="cpp_real", scope="agents/mac/src production .mm full files (volcengine)")
    if summary["line_percent"] < threshold:
        summary["status"] = "failed"
        summary["message"] = f"line coverage {summary['line_percent']:.2f}% is below threshold {threshold:.2f}%"
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Volcengine macOS real backend coverage gate.")
    parser.add_argument("--build-dir", default=".build/coverage/volcengine-real")
    parser.add_argument("--reports-dir", default="reports/latest")
    parser.add_argument("--line-threshold", type=float, default=DEFAULT_LINE_THRESHOLD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    paths = prepare_paths(root, root / args.build_dir, root / args.reports_dir, ARTIFACT_PREFIX)
    try:
        summary = run_coverage(paths, args.line_threshold)
    except Exception as exc:  # noqa: BLE001
        summary = make_summary([], args.line_threshold, "failed", str(exc),
                               test_level="cpp_real", scope="agents/mac/src production .mm full files (volcengine)")
        write_artifacts(paths, summary, case_id=CASE_ID, suite_name="cpp-volcengine-real-coverage")
        print(f"cpp volcengine real coverage: FAIL - {exc}", file=sys.stderr)
        return 1
    write_artifacts(paths, summary, case_id=CASE_ID, suite_name="cpp-volcengine-real-coverage")
    print_summary(summary)
    print(f"cpp volcengine real coverage: summary {paths.summary_path}")
    print(f"cpp volcengine real coverage: junit {paths.junit_path}")
    return 1 if summary["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
