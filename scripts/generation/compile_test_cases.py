#!/usr/bin/env python3
"""编译 Beacon 测试用例的 CLI 入口。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.support.generate_report import main as generate_report_main
from scripts.generation.sdk_registry_compiler import compile_all_registries, write_registry_outputs
from scripts.generation.test_case_compiler import compile_all, write_outputs
from scripts.support.write_junit import main as write_junit_main


def _write_reports(status: str, detail: str) -> None:
    sys.argv = ["generate_report.py", status, "P0-PROTOCOL", detail]
    generate_report_main()
    sys.argv = ["write_junit.py", "reports/latest/report.junit.xml", "P0-PROTOCOL", status]
    write_junit_main()


def main() -> int:
    try:
        registries = compile_all_registries()
        write_registry_outputs(registries)
        cases = compile_all()
        write_outputs(cases)
        _write_reports("passed", "compile-test-cases")
        return 0
    except Exception as exc:
        Path("reports/latest").mkdir(parents=True, exist_ok=True)
        Path("reports/latest/protocol.json").write_text(
            json.dumps({"status": "failed", "error": str(exc)}, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_reports("failed", str(exc))
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
