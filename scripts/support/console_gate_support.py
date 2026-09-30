"""Shared process and artifact helpers for SDK-specific Mac Console gates."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_gate_report(
    *,
    report_path: Path,
    junit_path: Path,
    junit_name: str,
    junit_classname: str,
    junit_case_name: str,
    run_id: str,
    expected_cases: set[str],
    status: str,
    message: str,
    base_extra: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    message = message.replace(str(report_path.parents[2]), "<workspace>").replace(str(Path.home()), "<home>")
    payload: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "started_at": now,
        "finished_at": now,
        "message": message,
        "expected_cases": sorted(expected_cases),
    }
    if base_extra:
        payload.update(base_extra)
    if extra:
        payload.update(extra)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    report_text = report_text.replace(str(report_path.parents[2]), "<workspace>")
    report_text = report_text.replace(str(Path.home()), "<home>")
    report_path.write_text(report_text, encoding="utf-8")
    write_junit(
        path=junit_path,
        suite_name=junit_name,
        classname=junit_classname,
        case_name=junit_case_name,
        status=status,
        message=message,
    )


def write_junit(
    *, path: Path, suite_name: str, classname: str, case_name: str, status: str, message: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suite = ET.Element(
        "testsuite",
        name=suite_name,
        tests="1",
        failures="1" if status == "failed" else "0",
        skipped="1" if status == "skipped" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname=classname, name=case_name)
    if status == "failed":
        ET.SubElement(case, "failure", message=message).text = message
    if status == "skipped":
        ET.SubElement(case, "skipped", message=message).text = message
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


async def wait_for_autorun_report(
    process: subprocess.Popen[str], report_path: Path, timeout_seconds: int
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if report_path.exists():
            return json.loads(report_path.read_text(encoding="utf-8"))
        if process.poll() is not None:
            break
        await asyncio.sleep(0.25)
    stdout, stderr = process.communicate(timeout=1) if process.poll() is not None else ("", "")
    detail = {
        "returncode": process.returncode,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }
    raise RuntimeError(f"mac console autorun report was not written: {detail}")


async def stop_console_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        await asyncio.to_thread(process.wait, 5)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()


async def run_autorun_round(
    *,
    base_url: str,
    round_index: int,
    run_cleanup: Callable[[str, int], Awaitable[dict[str, Any]]],
    launch_console: Callable[[str], subprocess.Popen[str]],
    wait_autorun: Callable[[subprocess.Popen[str]], Awaitable[dict[str, Any]]],
    verify_reports: Callable[[str, dict[str, Any]], Awaitable[Any]],
    stop_console: Callable[[subprocess.Popen[str]], Awaitable[None]],
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    cleanup = await run_cleanup(base_url, round_index)
    process = launch_console(base_url)
    try:
        autorun = await wait_autorun(process)
        reports = await verify_reports(base_url, autorun)
        return autorun, reports, cleanup
    finally:
        await stop_console(process)
