#!/usr/bin/env python3
"""Run mypy with concise console output and durable artifacts."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run mypy and write log plus JUnit artifacts.")
    parser.add_argument("--cwd", default=".", help="Command working directory.")
    parser.add_argument("--log", required=True, help="Path for complete mypy output.")
    parser.add_argument("--junit", required=True, help="Path for JUnit XML output.")
    parser.add_argument("--failure-tail", type=int, default=80, help="Number of log lines to print on failure.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --.")
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("missing command after --")
    return args


def _summary(output: str, returncode: int) -> str:
    for line in reversed(output.splitlines()):
        if line.startswith("Success:") or line.startswith("Found "):
            return line.strip()
    return "mypy passed" if returncode == 0 else "mypy failed without summary"


def _tail(output: str, limit: int) -> str:
    return "\n".join(output.splitlines()[-limit:])


def _sanitize_xml_text(value: str) -> str:
    def is_valid(character: str) -> bool:
        codepoint = ord(character)
        return (
            character in "\t\n\r"
            or 0x20 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        )

    return "".join(character if is_valid(character) else "\ufffd" for character in value)


def _write_junit(path: Path, status: str, message: str, output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    failures = "0" if status == "passed" else "1"
    suite = ET.Element("testsuite", name="server-mypy", tests="1", failures=failures)
    case = ET.SubElement(suite, "testcase", classname="server-mypy", name="TYPE-SRV-MYPY")
    if status != "passed":
        ET.SubElement(case, "failure", message=_sanitize_xml_text(message)).text = _sanitize_xml_text(output)

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        ET.ElementTree(suite).write(temporary_path, encoding="utf-8", xml_declaration=True)
        ET.parse(temporary_path)
        temporary_path.replace(path)
    finally:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)


def _artifacts_valid(log_path: Path, junit_path: Path) -> bool:
    if not log_path.exists() or not junit_path.exists():
        return False
    try:
        ET.parse(junit_path)
    except (OSError, ET.ParseError):
        return False
    return True


def main() -> int:
    args = _parse_args()
    log_path = Path(args.log)
    junit_path = Path(args.junit)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        for artifact_path in (junit_path, log_path):
            artifact_path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"server mypy: FAIL - cannot invalidate report artifacts: {exc}", file=sys.stderr)
        return 2

    try:
        completed = subprocess.run(
            args.command,
            cwd=args.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output = completed.stdout
        returncode = completed.returncode
    except OSError as exc:
        output = f"failed to start mypy command: {exc}\n"
        returncode = 2
    summary = _summary(output, returncode)
    status = "passed" if returncode == 0 else "failed"
    try:
        log_path.write_text(output, encoding="utf-8")
        _write_junit(junit_path, status, summary, output)
    except (OSError, UnicodeError, ET.ParseError) as exc:
        with suppress(OSError):
            junit_path.unlink(missing_ok=True)
        print(f"server mypy: FAIL - cannot write report artifacts: {exc}", file=sys.stderr)
        return 2

    if not _artifacts_valid(log_path, junit_path):
        print("server mypy: FAIL - missing or invalid report artifacts", file=sys.stderr)
        return 2

    if returncode == 0:
        print(f"server mypy: PASS - {summary}")
        print(f"server mypy: full log {log_path}")
        print(f"server mypy: junit {junit_path}")
        return 0

    print(f"server mypy: FAIL - {summary}", file=sys.stderr)
    print(f"server mypy: full log {log_path}", file=sys.stderr)
    print(f"server mypy: junit {junit_path}", file=sys.stderr)
    tail = _tail(output, args.failure_tail)
    if tail:
        print(f"server mypy: last {args.failure_tail} log lines:", file=sys.stderr)
        print(tail, file=sys.stderr)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
