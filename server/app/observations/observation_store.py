"""Observation 原始事实的内存与 JSONL 存储 adapter。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from app.observations.observation_models import ObservationInput, ObservationQuery, ObservationRecord


class ObservationConflictError(ValueError):
    """同一 run 内 observation ID 对应了不同 canonical body。"""


class ObservationStore(Protocol):
    async def append(self, item: ObservationInput, *, ingested_at_ms: int) -> ObservationRecord: ...

    async def query(self, query: ObservationQuery) -> list[ObservationRecord]: ...

    async def latest_states(self, query: ObservationQuery) -> list[ObservationRecord]: ...


class MemoryObservationStore:
    """按 run 分配单调 cursor，并保存不可变 Observation 快照。"""

    def __init__(self) -> None:
        self._records: dict[str, list[ObservationRecord]] = {}
        self._by_id: dict[tuple[str, str], ObservationRecord] = {}
        self._latest_state: dict[tuple[str, str, str, str], ObservationRecord] = {}
        self._lock = asyncio.Lock()

    async def append(self, item: ObservationInput, *, ingested_at_ms: int) -> ObservationRecord:
        async with self._lock:
            existing, record = self._prepare_append(item, ingested_at_ms=ingested_at_ms)
            if existing:
                return record.model_copy(deep=True)
            self._commit(record)
            return record.model_copy(deep=True)

    async def query(self, query: ObservationQuery) -> list[ObservationRecord]:
        async with self._lock:
            records = list(self._records.get(query.run_id, ()))
        return [record.model_copy(deep=True) for record in records if _matches(record, query)]

    async def latest_states(self, query: ObservationQuery) -> list[ObservationRecord]:
        async with self._lock:
            records = list(self._latest_state.values())
        matched = [record for record in records if _matches(record, query)]
        return [record.model_copy(deep=True) for record in sorted(matched, key=lambda item: item.cursor)]

    def _prepare_append(
        self,
        item: ObservationInput,
        *,
        ingested_at_ms: int,
    ) -> tuple[bool, ObservationRecord]:
        key = (item.run_id, item.observation_id)
        existing = self._by_id.get(key)
        if existing is not None:
            if _record_body(existing) != _input_body(item):
                raise ObservationConflictError(
                    f"observation_id {item.observation_id!r} conflicts within run {item.run_id!r}"
                )
            return True, existing
        cursor = len(self._records.get(item.run_id, ())) + 1
        return False, ObservationRecord.model_validate(
            {**item.model_dump(mode="python", by_alias=True), "cursor": cursor, "ingested_at_ms": ingested_at_ms}
        )

    def _commit(self, record: ObservationRecord) -> None:
        stored = record.model_copy(deep=True)
        self._records.setdefault(stored.run_id, []).append(stored)
        self._by_id[(stored.run_id, stored.observation_id)] = stored
        if stored.kind == "state":
            self._latest_state[_state_key(stored)] = stored


class JsonlObservationStore(MemoryObservationStore):
    """追加写 JSONL，并在构造时重建与内存实现一致的索引。"""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._load()

    async def append(self, item: ObservationInput, *, ingested_at_ms: int) -> ObservationRecord:
        async with self._lock:
            existing, record = self._prepare_append(item, ingested_at_ms=ingested_at_ms)
            if existing:
                return record.model_copy(deep=True)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json(by_alias=True) + "\n")
                handle.flush()
            self._commit(record)
            return record.model_copy(deep=True)

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line_number, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                body = json.loads(line)
                if isinstance(body, dict) and body.get("correlation") is None:
                    body.pop("correlation", None)
                record = ObservationRecord.model_validate(body)
            except Exception as error:
                raise ValueError(f"invalid observation JSONL line {line_number}") from error
            expected_cursor = len(self._records.get(record.run_id, ())) + 1
            if record.cursor != expected_cursor or (record.run_id, record.observation_id) in self._by_id:
                raise ValueError(f"invalid observation sequence at JSONL line {line_number}")
            self._commit(record)


def _input_body(item: ObservationInput) -> str:
    return json.dumps(item.model_dump(mode="json", by_alias=True), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _record_body(record: ObservationRecord) -> str:
    return _input_body(
        ObservationInput.model_validate(
            record.model_dump(mode="python", by_alias=True, exclude={"cursor", "ingested_at_ms"})
        )
    )


def _target_key(record: ObservationRecord) -> str:
    return json.dumps(
        record.target.model_dump(mode="json", by_alias=True, exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _state_key(record: ObservationRecord) -> tuple[str, str, str, str]:
    return (record.run_id, record.case_id, record.device_role, _target_key(record))


def _matches(record: ObservationRecord, query: ObservationQuery) -> bool:
    if record.run_id != query.run_id:
        return False
    if record.cursor <= query.after_cursor:
        return False
    if query.case_id is not None and record.case_id != query.case_id:
        return False
    if query.device_role is not None and record.device_role != query.device_role:
        return False
    if query.node_id is not None and record.node_id != query.node_id:
        return False
    if query.lease_id is not None and record.lease_id != query.lease_id:
        return False
    if query.kinds is not None and record.kind not in query.kinds:
        return False
    if query.target is not None and record.target != query.target:
        return False
    return all(_payload_value(record.payload, key) == value for key, value in query.match.items())


def _payload_value(payload: Mapping[str, object], dotted_key: str) -> object:
    current: object = payload
    for part in dotted_key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current
