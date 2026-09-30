#!/usr/bin/env python3
"""运行 pytest 并把完整输出写入 reports/latest 日志。

该脚本用于 agent/CI 友好的 quiet gate：终端只打印摘要和失败尾部，
完整 stdout/stderr 保存在日志文件，避免成功路径刷出大量 pytest 输出。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


SUMMARY_RE = re.compile(r"=+\s*(?P<summary>[^=\n]*(?:passed|failed|error|errors|skipped|warning|warnings)[^=\n]*)\s*=+")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pytest with concise console output and full report log.")
    parser.add_argument("--cwd", default=".", help="Command working directory.")
    parser.add_argument("--log", required=True, help="Path for full stdout/stderr log.")
    parser.add_argument("--name", default="pytest", help="Human-readable gate name.")
    parser.add_argument("--failure-tail", type=int, default=120, help="Number of log lines to print on failure.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run after --.")
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("missing command after --")
    return args


def _summary(output: str) -> str:
    matches = list(SUMMARY_RE.finditer(output))
    if matches:
        return " ".join(matches[-1].group("summary").split())
    for line in reversed(output.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            return line.strip()
    return "no pytest summary found"


def _tail(output: str, limit: int) -> str:
    lines = output.splitlines()
    return "\n".join(lines[-limit:])


def main() -> int:
    args = _parse_args()
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    completed = subprocess.run(
        args.command,
        cwd=args.cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = completed.stdout
    log_path.write_text(
        output.replace(str(Path.cwd()), ".").replace(str(Path.home()), "~"), encoding="utf-8"
    )

    summary = _summary(output)
    if completed.returncode == 0:
        print(f"{args.name}: PASS - {summary}")
        print(f"{args.name}: full log {log_path}")
        return 0

    print(f"{args.name}: FAIL - {summary}", file=sys.stderr)
    print(f"{args.name}: full log {log_path}", file=sys.stderr)
    tail = _tail(output, args.failure_tail)
    if tail:
        print(f"{args.name}: last {args.failure_tail} log lines:", file=sys.stderr)
        print(tail, file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
