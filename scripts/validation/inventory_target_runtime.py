"""Read-only inventory of active Python cases and legacy authoring-runtime references."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

from app.runs.python_native_registry import PythonNativeRegistry  # noqa: E402


def collect_inventory(root: Path = ROOT) -> dict[str, object]:
    """Return stable active-case and legacy-module facts without modifying the repository."""

    case_root = root / "test_cases/python"
    registry = PythonNativeRegistry.discover(case_root, repo_root=root)
    source_files = sorted(case_root.rglob("*.py"))
    dsl_counts = {"ctx.step": 0, "ctx.expect": 0, "cleanup_step": 0, "dynamic_sdk": 0}
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "ctx":
                if node.func.attr in {"step", "expect"}:
                    dsl_counts[f"ctx.{node.func.attr}"] += 1
                elif node.func.attr == "cleanup_step":
                    dsl_counts["cleanup_step"] += 1
            if node.func.attr == "sdk":
                dsl_counts["dynamic_sdk"] += 1
    terms = ("ProtocolOperationRecorder", "ThinProtocolExecutor", "BeaconNativeContext", "BeaconTestClient", "BeaconTestSession", "RegistryBackedSDK", "TestOrchestrator", "AssertionEngine")
    references: dict[str, list[str]] = {term: [] for term in terms}
    for directory in (root / "server/app", root / "python_sdk/beacon_test"):
        for path in directory.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            for term in terms:
                if term in content:
                    references[term].append(str(path.relative_to(root)))
    return {
        "source_file_count": len(source_files),
        "active_case_count": len(registry.cases),
        "case_ids": sorted(case.case_id for case in registry.cases),
        "dsl_counts": dsl_counts,
        "legacy_references": references,
    }


if __name__ == "__main__":
    print(json.dumps(collect_inventory(), ensure_ascii=False, indent=2))
