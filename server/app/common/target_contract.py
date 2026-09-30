"""Target Contract 校验、规范化和 canonical key。"""

from __future__ import annotations

import json
from typing import Any, Literal

TargetProfile = Literal["call", "callback", "registry", "assertion", "evidence", "system", "wire_compat"]

TARGET_FIELDS = {"sdk", "interface", "class_name", "function", "overload"}
KEY_FIELDS = ("class_name", "function", "interface", "overload", "sdk")


class TargetContractError(ValueError):
    pass


def normalize_target(target: dict[str, Any], profile: TargetProfile) -> dict[str, str]:
    if not isinstance(target, dict):
        raise TargetContractError("target must be an object")
    # 未知字段按字段名排序报告：C++ 侧 jsoncpp getMemberNames() 返回排序结果，两侧必须命中同一个字段。
    for field in sorted(target):
        if field not in TARGET_FIELDS:
            raise TargetContractError(f"target contains unknown field: {field}")
    normalized: dict[str, str] = {}
    # 校验顺序固定为 sdk/class_name/function/interface/overload，与 C++ 侧同一顺序。
    for field in ("sdk", "class_name", "function"):
        value = target.get(field)
        if not isinstance(value, str) or not value:
            raise TargetContractError(f"target.{field} must be a non-empty string")
        normalized[field] = value
    # 可选字段显式出现时必须是字符串；null 与空串一律拒绝，否则 Agent 会拒收控制面已放行的 target。
    for field in ("interface", "overload"):
        if field not in target:
            continue
        value = target[field]
        if not isinstance(value, str) or not value:
            raise TargetContractError(f"target.{field} must be a non-empty string")
        normalized[field] = value
    if _requires_interface(profile) and "interface" not in normalized:
        raise TargetContractError(f"target.interface is required for SDK {profile}")
    return normalized


def normalize_call_target(target: dict[str, Any]) -> dict[str, str]:
    return normalize_target(target, "call")


def normalize_event_target(target: dict[str, Any]) -> dict[str, str]:
    return normalize_target(target, "callback")


def normalize_wire_target(target: dict[str, Any]) -> dict[str, str]:
    return normalize_target(target, "wire_compat")


def target_key(target: dict[str, Any]) -> str:
    normalized = {field: target[field] for field in KEY_FIELDS if field in target and target[field]}
    return json.dumps(normalized, separators=(",", ":"), sort_keys=True)


def _requires_interface(profile: TargetProfile) -> bool:
    # ADR-020：interface 是否必填只由 profile 决定，这里不认识任何具体 SDK 名字。
    return profile in {"call", "callback", "registry"}
