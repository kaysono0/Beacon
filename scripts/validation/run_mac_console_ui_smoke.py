#!/usr/bin/env python3
"""Run the Beacon Mac Test Console interactive launch smoke."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = ROOT / "scripts/dev/build_mac_console_app.sh"
APP_EXECUTABLE = "Contents/MacOS/BeaconMacTestConsole"
SMOKE_WAIT_SECONDS = 2.0
TERMINATE_TIMEOUT_SECONDS = 5.0
CONSOLE_ENV = {
    "BEACON_CONSOLE_SERVER_URL": "http://127.0.0.1:8000",
    "BEACON_AUTH_TOKEN": "local-test-token",
}


def build_app_bundle() -> Path:
    result = subprocess.run(
        ["sh", str(BUILD_SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stdout.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"Mac Console app build failed with exit code {result.returncode}")

    output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not output_lines:
        raise RuntimeError("Mac Console app build did not print an app bundle path")

    bundle_path = Path(output_lines[-1])
    if not bundle_path.is_absolute():
        bundle_path = ROOT / bundle_path
    return bundle_path


def app_executable(bundle_path: Path) -> Path:
    executable = bundle_path / APP_EXECUTABLE
    if not executable.is_file():
        raise RuntimeError(f"Mac Console app executable is missing: {executable}")
    return executable


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=TERMINATE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=TERMINATE_TIMEOUT_SECONDS)


def launch_and_check(executable: Path) -> None:
    env = os.environ.copy()
    env.update(CONSOLE_ENV)
    process = subprocess.Popen(
        [str(executable)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(SMOKE_WAIT_SECONDS)
        exit_code = process.poll()
        if exit_code is not None:
            stdout, stderr = process.communicate(timeout=TERMINATE_TIMEOUT_SECONDS)
            sys.stdout.write(stdout)
            sys.stderr.write(stderr)
            raise RuntimeError(f"Mac Console app exited early with code {exit_code}")
    finally:
        terminate_process(process)


def main() -> int:
    bundle_path = build_app_bundle()
    executable = app_executable(bundle_path)
    launch_and_check(executable)
    print(f"Mac Console interactive UI smoke passed: {bundle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
