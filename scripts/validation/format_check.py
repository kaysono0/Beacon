#!/usr/bin/env python3
"""仓库基础格式检查。

只检查文本文件的尾随空白和末尾换行，并把结果写入 reports/latest。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


TEXT_SUFFIXES = {".h", ".cc", ".py", ".toml", ".json", ".yaml", ".yml", ".md", ""}


def main() -> int:
    failures: list[str] = []
    tracked_files = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for item in tracked_files:
        path = Path(item)
        if path.parts[:2] == ("docs", "achieve") or path.name == ".DS_Store":
            continue
        if not path.exists():
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            failures.append(f"{path}: missing trailing newline")
        for index, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                failures.append(f"{path}:{index}: trailing whitespace")

    latest = Path("reports/latest")
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "format.json").write_text(
        json.dumps({"status": "failed" if failures else "passed", "failures": failures}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
