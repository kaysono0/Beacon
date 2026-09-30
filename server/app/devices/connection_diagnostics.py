"""Server WebSocket 连接诊断事件流。

本模块保存连接生命周期、stale 拒绝和 pending 终态诊断。
这些事实独立于 SDK callback Evidence，用于测试报告和失败排查。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.common import CONFIG
from app.observations.observation_ingress import connection_observation
from app.observations.observation_service import ObservationService


def now_ms() -> int:
    """返回当前毫秒时间戳。"""
    return int(time.time() * 1000)


@dataclass(frozen=True)
class ConnectionEvent:
    """单条连接诊断事件。"""

    type: str
    node_id: str
    lease_id: str = ""
    op_id: str = ""
    reason: str = ""
    run_id: str | None = None
    case_id: str | None = None
    step_id: str | None = None
    timestamp_ms: int = field(default_factory=now_ms)
    details: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """返回可写入报告的脱敏摘要。"""
        data: dict[str, Any] = {
            "type": self.type,
            "node_id": self.node_id,
            "timestamp_ms": self.timestamp_ms,
        }
        for key in ("lease_id", "op_id", "reason", "run_id", "case_id", "step_id"):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.details:
            data["details"] = dict(self.details)
        return data


class ConnectionEventStore:
    """内存态连接诊断事件存储。"""

    def __init__(
        self,
        max_events: int | None = None,
        observation_service: ObservationService | None = None,
    ) -> None:
        self._max_events = CONFIG.connection_diagnostics_max_events if max_events is None else max_events
        self._observation_service = observation_service
        self._events: list[ConnectionEvent] = []
        self._lock = asyncio.Lock()

    async def record(
        self,
        event_type: str,
        node_id: str,
        *,
        lease_id: str = "",
        op_id: str = "",
        reason: str = "",
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ConnectionEvent:
        """记录一条连接诊断事件。"""
        event = ConnectionEvent(
            type=event_type,
            node_id=node_id,
            lease_id=lease_id,
            op_id=op_id,
            reason=reason,
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
            details=details or {},
        )
        if self._observation_service is not None:
            await self._observation_service.ingest(
                connection_observation(event.summary(), f"connection:{uuid.uuid4().hex}")
            )
        async with self._lock:
            self._events.append(event)
            if self._max_events > 0 and len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]
        return event

    async def query(
        self,
        *,
        node_id: str | None = None,
        event_type: str | None = None,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[ConnectionEvent]:
        """按设备、事件类型或 trace 上下文查询诊断事件。"""
        async with self._lock:
            events = list(self._events)
        return [
            event
            for event in events
            if (node_id is None or event.node_id == node_id)
            and (event_type is None or event.type == event_type)
            and (run_id is None or event.run_id == run_id)
            and (case_id is None or event.case_id == case_id)
            and (step_id is None or event.step_id == step_id)
        ]

    async def summaries(
        self,
        *,
        node_id: str | None = None,
        event_type: str | None = None,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回报告可消费的诊断事件摘要。"""
        events = await self.query(
            node_id=node_id,
            event_type=event_type,
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
        )
        return [event.summary() for event in events]
