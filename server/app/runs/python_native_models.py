"""Python case catalog metadata shared by Server and Runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class NativeTestCase:
    """Discovered Python case metadata and its source entry point."""

    case_id: str
    name: str
    platform: str
    devices: list[str]
    suite: str
    scenario_family: str
    implementation_status: str
    covered_capabilities: list[str]
    tags: list[str]
    source_path: str
    function_name: str
    function: Callable[[Any], None] = field(repr=False, compare=False)
    blocked_category: str = ""
    blocked_reason: str = ""
    runnable_prerequisites: list[str] = field(default_factory=list)
    owner_layer: str = ""
    token_bindings: list[tuple[str, str | int]] = field(default_factory=list)
    sdk_names: list[str] = field(default_factory=list)
