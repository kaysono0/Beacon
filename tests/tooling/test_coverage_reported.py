"""验证 Server coverage 摘要 wrapper 的纯转换合同。"""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "scripts/coverage" / "run_coverage_reported.py"


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_coverage_reported", RUNNER_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_coverage_reported"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_IT_SRV_COVERAGE_01_summary_identifies_low_server_app_files() -> None:
    runner = _load_runner_module()
    coverage_payload = {
        "totals": {
            "num_statements": 110,
            "covered_lines": 88,
            "num_branches": 20,
            "covered_branches": 10,
        },
        "files": {
            "app/covered.py": {
                "summary": {
                    "num_statements": 100,
                    "covered_lines": 90,
                    "num_branches": 20,
                    "covered_branches": 18,
                },
                "missing_lines": [7],
                "missing_branches": [],
            },
            "app/weak.py": {
                "summary": {
                    "num_statements": 10,
                    "covered_lines": 3,
                    "num_branches": 4,
                    "covered_branches": 1,
                },
                "missing_lines": [4, 5, 6, 7, 8, 9, 10],
                "missing_branches": [[3, 4], [3, 5], [8, 9]],
            },
            "app/__init__.py": {
                "summary": {"num_statements": 1, "covered_lines": 0},
                "missing_lines": [1],
            },
            "tests/test_weak.py": {
                "summary": {"num_statements": 10, "covered_lines": 0},
                "missing_lines": list(range(1, 11)),
            },
        },
    }

    summary = runner.build_summary(
        coverage_payload,
        source_head="a" * 40,
        status="passed",
        line_threshold=70.0,
        branch_threshold=50.0,
    )

    assert summary["status"] == "passed"
    assert summary["source_head"] == "a" * 40
    assert summary["scope"] == "server/app"
    assert summary["totals"]["line_percent"] == 80.0
    assert summary["totals"]["branch_percent"] == 50.0
    assert [item["path"] for item in summary["files"]] == [
        "server/app/__init__.py",
        "server/app/covered.py",
        "server/app/weak.py",
    ]
    assert summary["low_coverage_files"] == [
        {
            "path": "server/app/weak.py",
            "num_statements": 10,
            "covered_lines": 3,
            "line_percent": 30.0,
            "num_branches": 4,
            "covered_branches": 1,
            "branch_percent": 25.0,
            "missing_lines": [4, 5, 6, 7, 8, 9, 10],
            "missing_branches": [[3, 4], [3, 5], [8, 9]],
        }
    ]


def test_IT_SRV_COVERAGE_02_summary_handles_branchless_files() -> None:
    runner = _load_runner_module()

    summary = runner.build_summary(
        {
            "totals": {"num_statements": 1, "covered_lines": 1},
            "files": {
                "app/model.py": {
                    "summary": {"num_statements": 1, "covered_lines": 1},
                    "missing_lines": [],
                }
            },
        },
        source_head="a" * 40,
        status="passed",
        line_threshold=70.0,
        branch_threshold=50.0,
    )

    assert summary["totals"]["branch_percent"] is None
    assert summary["files"][0]["branch_percent"] is None
    assert summary["low_coverage_files"] == []


def test_IT_SRV_COVERAGE_03_failure_artifacts_replace_stale_success(tmp_path: Path) -> None:
    runner = _load_runner_module()
    paths = runner.CoveragePaths(
        cwd=tmp_path,
        reports_dir=tmp_path,
        data_file=tmp_path / ".coverage.server",
        junit_path=tmp_path / "server.coverage.junit.xml",
        log_path=tmp_path / "server.coverage.pytest.log",
        json_path=tmp_path / "server.coverage.json",
        xml_path=tmp_path / "server.coverage.xml",
        summary_path=tmp_path / "server.coverage-summary.json",
    )
    for path in (paths.junit_path, paths.json_path, paths.xml_path, paths.summary_path):
        path.write_text("stale success\n", encoding="utf-8")

    runner._invalidate_previous_artifacts(paths)
    runner._ensure_failure_junit(paths.junit_path, "IT-SRV-COVERAGE", "pytest coverage run failed")

    assert not paths.json_path.exists()
    assert not paths.xml_path.exists()
    assert not paths.summary_path.exists()
    root = ET.parse(paths.junit_path).getroot()
    assert root.attrib["failures"] == "1"
    assert root.find("testcase/failure") is not None


def test_IT_SRV_COVERAGE_04_artifact_failure_overwrites_success_junit(tmp_path: Path) -> None:
    runner = _load_runner_module()
    junit_path = tmp_path / "server.coverage.junit.xml"
    runner._write_failure_junit(junit_path, "OLD-SUCCESS-SHAPE", "old")
    junit_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" failures="0" errors="0">
  <testcase classname="coverage" name="pytest passed" />
</testsuite>
""",
        encoding="utf-8",
    )

    runner._write_failure_junit(junit_path, "IT-SRV-COVERAGE-ARTIFACTS", "coverage artifact generation failed")

    root = ET.parse(junit_path).getroot()
    assert root.attrib["failures"] == "1"
    testcase = root.find("testcase")
    assert testcase is not None
    assert testcase.attrib["name"] == "IT-SRV-COVERAGE-ARTIFACTS"
