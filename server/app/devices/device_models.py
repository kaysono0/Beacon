"""设备值类型与 transport 边界模型。

这些类型不管理注册、WebSocket 生命周期或持久化；那些职责归
`device_runtime`。`DeviceSession.websocket` 仅表示外部 transport。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


def _now_ms() -> int:
    return int(time.time() * 1000)


class DeviceSelector(BaseModel):
    platform: str | None = None
    node_id: str | None = None
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class Device(BaseModel):
    node_id: str
    platform: str = "unknown"
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    status: str = "online"
    last_seen_ms: int = Field(default_factory=_now_ms)


@dataclass
class DeviceSession:
    device: Device
    websocket: Any
    lease_id: str
    connected_at_ms: int = field(default_factory=_now_ms)


@dataclass
class SessionContext:
    node_id: str
    device: Device | None = None
    callbacks: dict[str, dict] = field(default_factory=dict)
    version: int = 1
