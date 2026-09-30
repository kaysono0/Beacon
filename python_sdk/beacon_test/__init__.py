"""beacon_test 公共导出。

session/authoring 按需加载：仅需路径解析或模型定义的调用方
不再被迫安装 httpx（见 REGISTRY_05I）。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .authoring import beacon_test
    from .target_session import BeaconSession, CallResult, NativeCallError, ObservationRecord, ResourceRef

_EXPORT_SOURCES = {
    "beacon_test": "authoring",
    "BeaconSession": "target_session",
    "CallResult": "target_session",
    "NativeCallError": "target_session",
    "ObservationRecord": "target_session",
    "ResourceRef": "target_session",
}


def __getattr__(name: str):
    source = _EXPORT_SOURCES.get(name)
    if source is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f".{source}", __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "BeaconSession",
    "CallResult",
    "NativeCallError",
    "ObservationRecord",
    "ResourceRef",
    "beacon_test",
]
