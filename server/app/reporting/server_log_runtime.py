"""服务端日志存储、查询与 Observation 接入。"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.observations.observation_ingress import log_observation
from app.observations.observation_service import ObservationService
from app.common.redaction import redact_log_value


class MemoryServerLogStore:
    """ServerLogCollector 的默认内存存储实现。"""

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._dedupe_keys: set[tuple[str, str, str]] = set()
        self._lock = asyncio.Lock()

    async def contains(self, dedupe_key: tuple[str, str, str]) -> bool:
        async with self._lock:
            return dedupe_key in self._dedupe_keys

    async def append(self, event: dict, dedupe_key: tuple[str, str, str]) -> None:
        async with self._lock:
            self._dedupe_keys.add(dedupe_key)
            self._events.append(dict(event))

    async def list_events(self) -> list[dict]:
        async with self._lock:
            return [dict(event) for event in self._events]


class JsonlServerLogStore:
    """最小 JSONL 日志存储，用于保留 Server 日志事件。"""

    def __init__(
        self,
        path: str | Path,
        max_bytes: int = 0,
        max_rotated_files: int = 0,
        retention_ms: int = 0,
        quarantine_corrupt_lines: bool = False,
        now_ms: int | None = None,
    ) -> None:
        self._path = Path(path)
        self._max_bytes = max(0, max_bytes)
        self._max_rotated_files = max(0, max_rotated_files)
        self._retention_ms = max(0, retention_ms)
        self._quarantine_corrupt_lines = quarantine_corrupt_lines
        self._now_ms = now_ms
        self._events: list[dict] = []
        self._dedupe_keys: set[tuple[str, str, str]] = set()
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        for path in self._load_paths():
            self._load_file(path)

    def _load_paths(self) -> list[Path]:
        rotated = [self._rotated_path(index) for index in range(self._max_rotated_files, 0, -1)]
        return [path for path in rotated + [self._path] if path.exists()]

    def _load_file(self, path: Path) -> None:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    self._quarantine_corrupt_line(path, line)
                    continue
                if not isinstance(event, dict):
                    self._quarantine_corrupt_line(path, line)
                    continue
                if not _is_valid_log_event(event):
                    self._quarantine_corrupt_line(path, line)
                    continue
                if self._is_expired(event):
                    continue
                dedupe_key = self._dedupe_key(event)
                self._dedupe_keys.add(dedupe_key)
                self._events.append(event)

    def _dedupe_key(self, event: dict) -> tuple[str, str, str]:
        return (str(event.get("event_id", "")), str(event.get("node_id", "")), str(event.get("lease_id", "")))

    def _is_expired(self, event: dict) -> bool:
        if self._retention_ms <= 0:
            return False
        timestamp = event.get("timestamp_ms")
        if not isinstance(timestamp, (int, float)):
            return False
        return timestamp < self._current_time_ms() - self._retention_ms

    def _current_time_ms(self) -> int:
        if self._now_ms is not None:
            return self._now_ms
        return int(time.time() * 1000)

    def _quarantine_corrupt_line(self, source_path: Path, line: str) -> None:
        if not self._quarantine_corrupt_lines:
            return
        quarantine_path = self._corrupt_path(source_path)
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

    async def contains(self, dedupe_key: tuple[str, str, str]) -> bool:
        async with self._lock:
            return dedupe_key in self._dedupe_keys

    async def append(self, event: dict, dedupe_key: tuple[str, str, str]) -> None:
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            record = dict(event)
            line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            self._rotate_if_needed(len(line.encode("utf-8")))
            with self._path.open("a", encoding="utf-8") as file:
                file.write(line)
            self._dedupe_keys.add(dedupe_key)
            self._events.append(record)

    async def list_events(self) -> list[dict]:
        async with self._lock:
            return [dict(event) for event in self._events]

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if self._max_bytes <= 0 or not self._path.exists() or self._path.stat().st_size == 0:
            return
        if self._path.stat().st_size + incoming_bytes <= self._max_bytes:
            return
        if self._max_rotated_files <= 0:
            self._path.unlink()
            return
        oldest = self._rotated_path(self._max_rotated_files)
        if oldest.exists():
            oldest.unlink()
        for index in range(self._max_rotated_files - 1, 0, -1):
            source = self._rotated_path(index)
            if source.exists():
                source.replace(self._rotated_path(index + 1))
        self._path.replace(self._rotated_path(1))

    def _rotated_path(self, index: int) -> Path:
        return Path(f"{self._path}.{index}")

    def _corrupt_path(self, source_path: Path) -> Path:
        return Path(f"{source_path}.corrupt")


class ServerLogCollector:
    """服务端日志收集器。

    Phase 1 默认使用内存 store 保存事件，查询接口保持与后续持久化实现兼容。
    """

    def __init__(
        self,
        store: Any | None = None,
        observation_service: ObservationService | None = None,
    ) -> None:
        self._store = store or MemoryServerLogStore()
        self._observation_service = observation_service
        self._lock = asyncio.Lock()

    async def ingest(self, node_id: str, lease_id: str, events: list[dict]) -> dict:
        stats = {"accepted": 0, "duplicates": 0, "rejected": 0}
        async with self._lock:
            for raw_event in events:
                if not _is_valid_log_event(raw_event):
                    stats["rejected"] += 1
                    continue
                event = dict(raw_event)
                if not event.get("node_id"):
                    event["node_id"] = node_id
                if not event.get("lease_id"):
                    event["lease_id"] = lease_id
                dedupe_key = (event["event_id"], event["node_id"], event["lease_id"])
                if await self._store.contains(dedupe_key):
                    stats["duplicates"] += 1
                    continue
                event["message"] = redact_log_value(event.get("message", ""))
                event["extra"] = redact_log_value(event.get("extra", {}))
                if self._observation_service is not None:
                    await self._observation_service.ingest(log_observation(event))
                await self._store.append(event, dedupe_key)
                stats["accepted"] += 1
        return stats

    async def query_by_trace(
        self,
        run_id: str,
        case_id: str | None = None,
        step_id: str | None = None,
        op_id: str | None = None,
        node_id: str | None = None,
        lease_id: str | None = None,
        start_ms: int = 0,
        end_ms: int = 2**63 - 1,
    ) -> list[dict]:
        events = await self._store.list_events()
        return [
            event
            for event in events
            if event.get("run_id") == run_id
            and (case_id is None or event.get("case_id") == case_id)
            and (step_id is None or event.get("step_id") == step_id)
            and (op_id is None or event.get("op_id") == op_id)
            and (node_id is None or event.get("node_id") == node_id)
            and (lease_id is None or event.get("lease_id") == lease_id)
            and start_ms <= event.get("timestamp_ms", 0) <= end_ms
        ]

    async def query_window(self, node_id: str, start_ms: int, end_ms: int) -> list[dict]:
        events = await self._store.list_events()
        return [event for event in events if event.get("node_id") == node_id and start_ms <= event.get("timestamp_ms", 0) <= end_ms]


def _is_valid_log_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    for field in ("event_id", "timestamp_ms", "level", "event", "message"):
        if event.get(field) in (None, ""):
            return False
    return isinstance(event.get("timestamp_ms"), int)
