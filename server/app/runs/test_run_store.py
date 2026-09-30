"""Test run persistence implementations."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from app.common.interfaces import TestRunStoreProtocol
from app.runs.test_models import TestRun


def _newest_first(runs: Iterable[TestRun], limit: int) -> list[TestRun]:
    """按创建时间倒序返回隔离快照；同毫秒时用 run_id 保证顺序稳定。"""
    ordered = sorted(runs, key=lambda run: (-run.created_at_ms, run.run_id))
    return [run.model_copy(deep=True) for run in ordered[:limit]]


class MemoryTestRunStore:
    """提供隔离快照的内存 TestRun 存储。"""

    def __init__(self) -> None:
        self._runs: dict[str, TestRun] = {}
        self._lock = asyncio.Lock()

    async def put(self, run: TestRun) -> None:
        async with self._lock:
            self._runs[run.run_id] = run.model_copy(deep=True)

    async def get(self, run_id: str) -> TestRun | None:
        async with self._lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run is not None else None

    async def list_runs(self, limit: int) -> list[TestRun]:
        async with self._lock:
            return _newest_first(self._runs.values(), limit)


class JsonlTestRunStore:
    """TestRun JSONL 存储，保存 run 的最新快照。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._runs: dict[str, TestRun] = {}
        self._load()

    async def put(self, run: TestRun) -> None:
        snapshot = run.model_copy(deep=True)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(snapshot.model_dump_json() + "\n")
        self._runs[snapshot.run_id] = snapshot

    async def get(self, run_id: str) -> TestRun | None:
        run = self._runs.get(run_id)
        return run.model_copy(deep=True) if run is not None else None

    async def list_runs(self, limit: int) -> list[TestRun]:
        return _newest_first(self._runs.values(), limit)

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                run = TestRun.model_validate_json(line)
            except ValueError:
                self._quarantine_bad_line(line)
                continue
            self._runs[run.run_id] = run

    def _quarantine_bad_line(self, line: str) -> None:
        quarantine_path = Path(f"{self._path}.corrupt")
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
