"""Observation 的唯一校验、脱敏、去重和查询 interface。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from copy import deepcopy
from typing import Any, Callable

from app.observations.observation_models import (
    ObservationInput,
    ObservationKind,
    ObservationPage,
    ObservationQuery,
    ObservationRecord,
    ObservationTarget,
)
from app.observations.observation_store import MemoryObservationStore, ObservationStore


REDACTED = "<redacted>"
SENSITIVE_KEY = re.compile(r"(?:authorization|token|password|secret|api[_-]?key|app[_-]?(?:key|cert))", re.IGNORECASE)
BEARER_VALUE = re.compile(r"\bbearer\s+\S+", re.IGNORECASE)
MAX_PAGE_SIZE = 500


class ObservationWaitTimeoutError(TimeoutError):
    """在指定时间内没有出现匹配的 Observation。"""


class ObservationWaitCancelledError(RuntimeError):
    """run 取消后唤醒并终止对应的 Observation wait。"""


class ObservationService:
    """隐藏 canonical target、脱敏、存储和 latest-state 投影。"""

    def __init__(
        self,
        store: ObservationStore | None = None,
        *,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._store = store or MemoryObservationStore()
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._conditions: dict[str, asyncio.Condition] = {}
        self._cancelled_runs: set[str] = set()

    async def ingest(self, item: ObservationInput) -> ObservationRecord:
        prepared = item.model_copy(
            update={
                "target": ObservationTarget.model_validate(
                    item.target.model_dump(mode="python", by_alias=True, exclude_none=True)
                ),
                "payload": _redact(deepcopy(item.payload)),
                "callback_execution": _redact(deepcopy(item.callback_execution)),
            },
            deep=True,
        )
        record = await self._store.append(prepared, ingested_at_ms=self._now_ms())
        condition = self._condition(item.run_id)
        async with condition:
            condition.notify_all()
        return record

    async def query(self, query: ObservationQuery) -> list[ObservationRecord]:
        return await self._store.query(query)

    async def latest_state(self, query: ObservationQuery) -> ObservationRecord | None:
        states = await self._store.latest_states(query.model_copy(update={"kinds": frozenset({"state"})}))
        return states[-1] if states else None

    async def wait(self, query: ObservationQuery, timeout_ms: int) -> ObservationRecord:
        """先检查已有事实，再无轮询地等待后续 ingest 唤醒。"""

        if timeout_ms < 1:
            raise ValueError("timeout_ms must be at least 1")
        condition = self._condition(query.run_id)
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        async with condition:
            while True:
                self._raise_if_cancelled(query.run_id)
                records = await self.query(query)
                if records:
                    return records[0]
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise ObservationWaitTimeoutError(f"observation wait timed out for run {query.run_id!r}")
                try:
                    await asyncio.wait_for(condition.wait(), timeout=remaining)
                except TimeoutError as error:
                    raise ObservationWaitTimeoutError(
                        f"observation wait timed out for run {query.run_id!r}"
                    ) from error

    async def cancel_waits(self, run_id: str) -> None:
        """把 run 标记为取消并立即唤醒它的全部 wait。"""

        condition = self._condition(run_id)
        async with condition:
            self._cancelled_runs.add(run_id)
            condition.notify_all()

    async def page(
        self,
        *,
        run_id: str,
        after_cursor: int,
        limit: int,
        kinds: frozenset[ObservationKind] | None = None,
    ) -> ObservationPage:
        """返回供 Console 增量读取的稳定 cursor page。"""

        if after_cursor < 0:
            raise ValueError("after_cursor must be non-negative")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        records = await self.query(
            ObservationQuery(run_id=run_id, after_cursor=after_cursor, kinds=kinds)
        )
        items = records[:limit]
        return ObservationPage(
            items=items,
            next_cursor=items[-1].cursor if items else after_cursor,
            has_more=len(records) > limit,
        )

    def _condition(self, run_id: str) -> asyncio.Condition:
        condition = self._conditions.get(run_id)
        if condition is None:
            condition = asyncio.Condition()
            self._conditions[run_id] = condition
        return condition

    def _raise_if_cancelled(self, run_id: str) -> None:
        if run_id in self._cancelled_runs:
            raise ObservationWaitCancelledError(f"observation wait cancelled for run {run_id!r}")


def _redact(value: Any, *, key: str | None = None) -> Any:
    if key is not None and SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {item_key: _redact(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if key == "return_value" and isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if parsed is not None:
            cleaned = _redact(parsed)
            if cleaned != parsed:
                return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str) and BEARER_VALUE.search(value):
        return REDACTED
    return value
