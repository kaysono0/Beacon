"""Python case 元数据；执行由隔离 Runner 中的 BeaconSession 完成。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .target_session import BeaconSession


@dataclass(frozen=True)
class TestDefinition:
    case_id: str
    name: str
    platform: str
    devices: list[str] = field(default_factory=lambda: ["primary"])
    suite: str | None = None
    scenario_family: str | None = None
    implementation_status: str | None = None
    covered_capabilities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    blocked_category: str | None = None
    blocked_reason: str | None = None
    runnable_prerequisites: list[str] = field(default_factory=list)
    owner_layer: str | None = None
    token_bindings: list[tuple[str, str | int]] = field(default_factory=list)
    sdk_names: list[str] = field(default_factory=list)


def beacon_test(
    *,
    case_id: str,
    name: str,
    platform: str = "common",
    devices: list[str] | None = None,
    suite: str | None = None,
    scenario_family: str | None = None,
    implementation_status: str | None = None,
    covered_capabilities: list[str] | None = None,
    tags: list[str] | None = None,
    blocked_category: str | None = None,
    blocked_reason: str | None = None,
    runnable_prerequisites: list[str] | None = None,
    owner_layer: str | None = None,
    token_bindings: list[tuple[str, str | int]] | None = None,
    sdk_names: list[str] | None = None,
) -> Callable[[Callable[[BeaconSession], None]], Callable[[BeaconSession], None]]:
    definition = TestDefinition(
        case_id=case_id,
        name=name,
        platform=platform,
        devices=devices or ["primary"],
        suite=suite,
        scenario_family=scenario_family,
        implementation_status=implementation_status,
        covered_capabilities=covered_capabilities or [],
        tags=tags or [],
        blocked_category=blocked_category,
        blocked_reason=blocked_reason,
        runnable_prerequisites=runnable_prerequisites or [],
        owner_layer=owner_layer,
        token_bindings=token_bindings or [],
        sdk_names=sdk_names or [],
    )

    def decorate(func: Callable[[BeaconSession], None]) -> Callable[[BeaconSession], None]:
        setattr(func, "__beacon_test__", definition)
        return func

    return decorate
