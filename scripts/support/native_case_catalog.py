"""Expose immediate Python case metadata to local validation scripts."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def load_cases(prefix: str | None = None) -> list[dict[str, Any]]:
    server_path = str(ROOT / "server")
    if server_path not in sys.path:
        sys.path.insert(0, server_path)
    from app.runs.python_native_registry import PythonNativeRegistry

    registry = PythonNativeRegistry.discover(ROOT / "test_cases/python", repo_root=ROOT)
    return [
        {key: value for key, value in vars(case).items() if key != "function"}
        for case in registry.cases
        if prefix is None or case.case_id.startswith(prefix)
    ]
