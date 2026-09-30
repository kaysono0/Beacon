"""SDK 覆盖率摘要必须统计源目录全部文件，不能信任扩大后的外部 totals。"""

import pytest

from scripts.coverage.run_python_sdk_coverage import build_summary


def test_IT_PYSDK_COVERAGE_01_totals_only_include_sdk_sources(tmp_path):
    sdk = tmp_path / "python_sdk/beacon_test"
    sdk.mkdir(parents=True)
    (sdk / "session.py").write_text("pass\n")
    summary = build_summary({
        "totals": {"covered_lines": 100, "num_statements": 100},
        "files": {
            str(sdk / "session.py"): {"summary": {"covered_lines": 1, "num_statements": 2}},
            str(tmp_path / "tests/padding.py"): {"summary": {"covered_lines": 99, "num_statements": 99}},
        },
    }, root=tmp_path, threshold=95, status="passed", message="probe")
    assert summary["line_percent"] == 50.0
    assert summary["covered_lines"] == 1 and summary["total_lines"] == 2


def test_IT_PYSDK_COVERAGE_02_omitted_production_file_fails(tmp_path):
    sdk = tmp_path / "python_sdk/beacon_test"
    sdk.mkdir(parents=True)
    (sdk / "not_imported.py").write_text("pass\n")
    with pytest.raises(RuntimeError, match="missing Python SDK coverage sources.*not_imported.py"):
        build_summary({"totals": {"covered_lines": 100, "num_statements": 100}, "files": {}},
                      root=tmp_path, threshold=95, status="passed", message="probe")
