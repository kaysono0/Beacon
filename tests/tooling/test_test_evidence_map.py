"""验证 Mock E2E 与全量 coverage 的分层证据转换。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/coverage" / "build_test_evidence_map.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_test_evidence_map", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_test_evidence_map"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _coverage(executed: list[int], missing: list[int], branches: list[list[int]], missing_branches: list[list[int]]) -> dict:
    return {
        "source_head": "a" * 40,
        "meta": {"branch_coverage": True},
        "files": {
            "app/example.py": {
                "executed_lines": executed,
                "missing_lines": missing,
                "executed_branches": branches,
                "missing_branches": missing_branches,
            }
        },
        "totals": {},
    }


def test_IT_TEST_EVIDENCE_01_classifies_e2e_lower_level_and_untested_paths() -> None:
    evidence = _load_module()

    payload = evidence.build_payload(
        _coverage([1, 2], [3, 4, 5], [[2, 3]], [[2, 4], [4, 5]]),
        _coverage([1, 2, 3, 4], [5], [[2, 3], [2, 4]], [[4, 5]]),
    )

    assert payload["status"] == "passed"
    assert payload["source_head"] == "a" * 40
    assert payload["summary"] == {
        "files": 1,
        "e2e_covered_lines": 2,
        "lower_level_only_lines": 2,
        "untested_lines": 1,
        "untested_branches": 1,
    }
    assert payload["files"] == [
        {
            "path": "server/app/example.py",
            "e2e_covered_lines": [1, 2],
            "lower_level_only_lines": [3, 4],
            "untested_lines": [5],
            "e2e_covered_branches": [[2, 3]],
            "lower_level_only_branches": [[2, 4]],
            "untested_branches": [[4, 5]],
        }
    ]


def test_IT_TEST_EVIDENCE_02_cli_fails_closed_on_missing_artifact(tmp_path: Path) -> None:
    output_path = tmp_path / "test-evidence-map.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--e2e",
            str(tmp_path / "missing-e2e.json"),
            "--all",
            str(tmp_path / "missing-all.json"),
            "--output",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["files"] == []


def test_IT_TEST_EVIDENCE_03_e2e_execution_is_not_also_classified_untested() -> None:
    evidence = _load_module()

    payload = evidence.build_payload(
        _coverage([5], [1], [[5, 6]], []),
        _coverage([1], [5], [], [[5, 6]]),
    )

    item = payload["files"][0]
    assert item["e2e_covered_lines"] == [5]
    assert item["untested_lines"] == []
    assert item["e2e_covered_branches"] == [[5, 6]]
    assert item["untested_branches"] == []


def test_IT_TEST_EVIDENCE_04_invalid_or_different_file_sets_fail_closed() -> None:
    evidence = _load_module()
    valid = _coverage([1], [], [], [])

    try:
        evidence.build_payload(
            {
                "source_head": "a" * 40,
                "meta": {"branch_coverage": True},
                "files": {"app/example.py": "bad"},
            },
            valid,
        )
    except ValueError as exc:
        assert str(exc) == "Mock E2E coverage has invalid file entry for server/app/example.py"
    else:
        raise AssertionError("invalid file payload was accepted")

    other = {
        "source_head": "a" * 40,
        "meta": {"branch_coverage": True},
        "files": {
            "app/other.py": {
                "executed_lines": [1],
                "missing_lines": [],
                "executed_branches": [],
                "missing_branches": [],
            }
        }
    }
    try:
        evidence.build_payload(valid, other)
    except ValueError as exc:
        assert str(exc) == "coverage inputs have different server/app file sets"
    else:
        raise AssertionError("different file sets were accepted")


def test_IT_TEST_EVIDENCE_05_requires_branch_mode_and_matching_executable_universe() -> None:
    evidence = _load_module()
    valid = _coverage([1], [2], [[1, 2]], [])
    no_branches = _coverage([1], [2], [[1, 2]], [])
    no_branches["meta"]["branch_coverage"] = False

    try:
        evidence.build_payload(no_branches, valid)
    except ValueError as exc:
        assert str(exc) == "Mock E2E coverage did not enable branch coverage"
    else:
        raise AssertionError("coverage without branch mode was accepted")

    different_universe = _coverage([1], [3], [[1, 3]], [])
    try:
        evidence.build_payload(valid, different_universe)
    except ValueError as exc:
        assert str(exc) == "coverage inputs have different executable universe for server/app/example.py"
    else:
        raise AssertionError("coverage from a different executable universe was accepted")


def test_IT_TEST_EVIDENCE_06_rejects_overlapping_executed_and_missing_sets() -> None:
    evidence = _load_module()
    overlap = _coverage([1], [1], [], [])

    try:
        evidence.build_payload(overlap, overlap)
    except ValueError as exc:
        assert str(exc) == "Mock E2E coverage has overlapping executed/missing lines for server/app/example.py"
    else:
        raise AssertionError("overlapping coverage classifications were accepted")


def test_IT_TEST_EVIDENCE_07_requires_matching_source_heads() -> None:
    evidence = _load_module()
    e2e = _coverage([1], [], [], [])
    all_tests = _coverage([1], [], [], [])
    all_tests["source_head"] = "b" * 40

    try:
        evidence.build_payload(e2e, all_tests)
    except ValueError as exc:
        assert str(exc) == "coverage inputs do not share one valid source_head"
    else:
        raise AssertionError("coverage from different source commits was accepted")
