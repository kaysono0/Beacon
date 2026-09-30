"""验证真实后端覆盖率不会因缺文件或截断统计范围而虚高。"""

import pytest

from scripts.coverage import run_cpp_agora_real_coverage as agora
from scripts.coverage import run_cpp_volcengine_real_coverage as volcengine
from scripts.coverage.cpp_real_coverage_support import prepare_paths


@pytest.mark.parametrize("runner", [agora, volcengine])
def test_IT_REAL_COVERAGE_01_full_file_counts_include_uncovered_tail(tmp_path, runner):
    paths = prepare_paths(tmp_path, tmp_path / "build", tmp_path / "reports", "test")
    payload = {"data": [{"files": [{
        "filename": str(tmp_path / runner.BACKEND_SOURCE),
        "summary": {"lines": {"covered": 1, "count": 2}},
    }, {
        "filename": str(tmp_path / "agents/mac/src/video/synthetic_video_clip.mm"),
        "summary": {"lines": {"covered": 2, "count": 2}},
    }]}]}
    files = runner.collect_file_summaries(paths, payload)
    summary = runner.make_summary(files, 95, "passed", "probe") if runner is agora else runner.make_summary(
        files, 95, "passed", "probe", test_level="cpp_real", scope="probe",
    )
    assert summary["line_percent"] == summary["raw_line_percent"] == 75.0
    assert summary["total_lines"] == summary["raw_total_lines"] == 4
    assert files[0]["scope"] == "full_file"
    assert files[0]["excluded_line_ranges"] == []


@pytest.mark.parametrize("runner", [agora, volcengine])
@pytest.mark.parametrize("count", [None, 0])
def test_IT_REAL_COVERAGE_02_missing_backend_cannot_be_hidden_by_covered_helper(tmp_path, runner, count):
    paths = prepare_paths(tmp_path, tmp_path / "build", tmp_path / "reports", "test")
    records = [{"filename": str(tmp_path / "agents/mac/src/video/synthetic_video_clip.mm"), "summary": {"lines": {"covered": 100, "count": 100}}}]
    if count is not None:
        records.append({"filename": str(tmp_path / runner.BACKEND_SOURCE), "summary": {"lines": {"covered": 0, "count": count}}})
    with pytest.raises(RuntimeError, match="missing or empty required coverage sources"):
        runner.collect_file_summaries(paths, {"data": [{"files": records}]})


@pytest.mark.parametrize("runner", [agora, volcengine])
def test_IT_REAL_COVERAGE_03_missing_video_source_is_not_silently_omitted(tmp_path, runner):
    paths = prepare_paths(tmp_path, tmp_path / "build", tmp_path / "reports", "test")
    payload = {"data": [{"files": [{
        "filename": str(tmp_path / runner.BACKEND_SOURCE), "summary": {"lines": {"covered": 100, "count": 100}},
    }]}]}
    with pytest.raises(RuntimeError, match="missing or empty required coverage sources.*synthetic_video_clip"):
        runner.collect_file_summaries(paths, payload)
