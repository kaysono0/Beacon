#!/usr/bin/env python3
"""合并 Mock E2E 与全量 Server coverage，生成分层测试证据。

本脚本只转换两个 coverage.py JSON artifact，不运行测试、不修改源码。
全量 coverage 决定哪些生产路径完全未测试；Mock E2E coverage 用于区分
已经过端到端链路证明的代码和仅由较低层测试执行的代码。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build layered Server test evidence from coverage artifacts.")
    parser.add_argument("--e2e", default="reports/latest/server.e2e-mock.coverage.json")
    parser.add_argument("--all", dest="all_tests", default="reports/latest/server.coverage.json")
    parser.add_argument("--output", default="reports/latest/server.test-evidence-map.json")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} top-level JSON is not an object")
    if not isinstance(payload.get("files"), dict):
        raise ValueError(f"{path} files is not an object")
    return payload


def _server_path(path: str) -> str:
    if path.startswith("server/"):
        return path
    if path.startswith("app/"):
        return f"server/{path}"
    return path


def _normalized_files(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = payload["files"]
    assert isinstance(files, dict)
    return {
        _server_path(str(path)): item
        for path, item in files.items()
        if isinstance(item, dict) and _server_path(str(path)).startswith("server/app/")
    }


def _validate_coverage(payload: dict[str, Any], label: str) -> dict[str, dict[str, Any]]:
    meta = payload.get("meta")
    if not isinstance(meta, dict) or meta.get("branch_coverage") is not True:
        raise ValueError(f"{label} coverage did not enable branch coverage")
    raw_files = payload.get("files")
    assert isinstance(raw_files, dict)
    for raw_path, raw_item in raw_files.items():
        path = _server_path(str(raw_path))
        if path.startswith("server/app/") and not isinstance(raw_item, dict):
            raise ValueError(f"{label} coverage has invalid file entry for {path}")
    files = _normalized_files(payload)
    if not files:
        raise ValueError(f"{label} coverage has no server/app files")
    line_keys = ("executed_lines", "missing_lines")
    branch_keys = ("executed_branches", "missing_branches")
    for path, item in files.items():
        for key in line_keys:
            value = item.get(key)
            if not isinstance(value, list) or any(
                not isinstance(line, int) or isinstance(line, bool) or line <= 0
                for line in value
            ):
                raise ValueError(f"{label} coverage has invalid {key} for {path}")
        for key in branch_keys:
            value = item.get(key)
            if not isinstance(value, list) or any(
                not isinstance(branch, list)
                or len(branch) != 2
                or any(not isinstance(line, int) or isinstance(line, bool) for line in branch)
                for branch in value
            ):
                raise ValueError(f"{label} coverage has invalid {key} for {path}")
        executed_lines = _lines(item, "executed_lines")
        missing_lines = _lines(item, "missing_lines")
        executed_branches = _branches(item, "executed_branches")
        missing_branches = _branches(item, "missing_branches")
        if len(executed_lines) != len(item["executed_lines"]) or len(missing_lines) != len(item["missing_lines"]):
            raise ValueError(f"{label} coverage has duplicate line entries for {path}")
        if len(executed_branches) != len(item["executed_branches"]) or len(missing_branches) != len(
            item["missing_branches"]
        ):
            raise ValueError(f"{label} coverage has duplicate branch entries for {path}")
        if executed_lines & missing_lines:
            raise ValueError(f"{label} coverage has overlapping executed/missing lines for {path}")
        if executed_branches & missing_branches:
            raise ValueError(f"{label} coverage has overlapping executed/missing branches for {path}")
    return files


def _lines(item: dict[str, Any], key: str) -> set[int]:
    value = item.get(key, [])
    if not isinstance(value, list):
        return set()
    return {line for line in value if isinstance(line, int) and not isinstance(line, bool)}


def _branches(item: dict[str, Any], key: str) -> set[tuple[int, int]]:
    value = item.get(key, [])
    if not isinstance(value, list):
        return set()
    branches: set[tuple[int, int]] = set()
    for branch in value:
        if (
            isinstance(branch, list)
            and len(branch) == 2
            and all(isinstance(line, int) and not isinstance(line, bool) for line in branch)
        ):
            branches.add((branch[0], branch[1]))
    return branches


def _branch_list(branches: set[tuple[int, int]]) -> list[list[int]]:
    return [[start, end] for start, end in sorted(branches)]


def _file_evidence(path: str, e2e: dict[str, Any], all_tests: dict[str, Any]) -> dict[str, Any]:
    all_executed_lines = _lines(all_tests, "executed_lines")
    all_missing_lines = _lines(all_tests, "missing_lines")
    executable_lines = all_executed_lines | all_missing_lines
    e2e_lines = _lines(e2e, "executed_lines") & executable_lines
    untested_lines = all_missing_lines - e2e_lines
    e2e_branches = _branches(e2e, "executed_branches")
    all_branches = _branches(all_tests, "executed_branches")
    untested_branches = _branches(all_tests, "missing_branches") - e2e_branches
    return {
        "path": path,
        "e2e_covered_lines": sorted(e2e_lines),
        "lower_level_only_lines": sorted(all_executed_lines - e2e_lines),
        "untested_lines": sorted(untested_lines),
        "e2e_covered_branches": _branch_list(e2e_branches),
        "lower_level_only_branches": _branch_list(all_branches - e2e_branches),
        "untested_branches": _branch_list(untested_branches),
    }


def build_payload(e2e_payload: dict[str, Any], all_tests_payload: dict[str, Any]) -> dict[str, Any]:
    """构造稳定的分层测试证据 artifact。"""

    source_head = e2e_payload.get("source_head")
    if (
        not isinstance(source_head, str)
        or len(source_head) != 40
        or all_tests_payload.get("source_head") != source_head
    ):
        raise ValueError("coverage inputs do not share one valid source_head")
    e2e_files = _validate_coverage(e2e_payload, "Mock E2E")
    all_files = _validate_coverage(all_tests_payload, "all-tests")
    if set(e2e_files) != set(all_files):
        raise ValueError("coverage inputs have different server/app file sets")
    for path in e2e_files:
        e2e_line_universe = _lines(e2e_files[path], "executed_lines") | _lines(
            e2e_files[path],
            "missing_lines",
        )
        all_line_universe = _lines(all_files[path], "executed_lines") | _lines(
            all_files[path],
            "missing_lines",
        )
        e2e_branch_universe = _branches(e2e_files[path], "executed_branches") | _branches(
            e2e_files[path],
            "missing_branches",
        )
        all_branch_universe = _branches(all_files[path], "executed_branches") | _branches(
            all_files[path],
            "missing_branches",
        )
        if e2e_line_universe != all_line_universe or e2e_branch_universe != all_branch_universe:
            raise ValueError(f"coverage inputs have different executable universe for {path}")
    files = [
        _file_evidence(path, e2e_files.get(path, {}), all_tests)
        for path, all_tests in sorted(all_files.items())
        if not path.endswith("/__init__.py")
    ]
    return {
        "version": 1,
        "status": "passed",
        "scope": "server/app",
        "source_head": source_head,
        "layers": ["mock_e2e", "all_tests"],
        "summary": {
            "files": len(files),
            "e2e_covered_lines": sum(len(item["e2e_covered_lines"]) for item in files),
            "lower_level_only_lines": sum(len(item["lower_level_only_lines"]) for item in files),
            "untested_lines": sum(len(item["untested_lines"]) for item in files),
            "untested_branches": sum(len(item["untested_branches"]) for item in files),
        },
        "files": files,
    }


def main() -> int:
    args = _parse_args()
    e2e_path = Path(args.e2e)
    all_tests_path = Path(args.all_tests)
    output_path = Path(args.output)
    try:
        payload = build_payload(_load_json(e2e_path), _load_json(all_tests_path))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        payload = {
            "version": 1,
            "status": "failed",
            "scope": "server/app",
            "error": str(exc),
            "layers": ["mock_e2e", "all_tests"],
            "summary": {},
            "files": [],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2 if args.pretty or args.output else None, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
