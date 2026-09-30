#!/usr/bin/env python3
"""写入单用例 JUnit XML。

用于 C++ 或脚本型验证失败时补齐 reports/latest 的机器可读诊断。
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    path = Path(sys.argv[1])
    case_id = sys.argv[2]
    status = sys.argv[3] if len(sys.argv) > 3 else "passed"
    path.parent.mkdir(parents=True, exist_ok=True)

    suite = ET.Element("testsuite", name=case_id, tests="1", failures="0" if status == "passed" else "1")
    case = ET.SubElement(suite, "testcase", classname=case_id, name=case_id)
    if status != "passed":
        ET.SubElement(case, "failure", message=status).text = status
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
