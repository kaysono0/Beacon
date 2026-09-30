"""校验 Registry、generated facade、Server Target Contract 与 provider handler 的 target 一致性。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from app.common.target_contract import TargetContractError, normalize_call_target, normalize_target, target_key

TargetConsistencyCode = Literal[
    "invalid_handler_target",
    "missing_facade_target",
    "missing_handler",
    "mismatched_interface",
    "mismatched_class_function",
    "unsupported_target",
    "server_rejected_target",
]


@dataclass(frozen=True)
class TargetConsistencyIssue:
    """描述一个可定位的 target 跨层漂移。"""

    code: TargetConsistencyCode
    target: dict[str, Any]
    message: str


class TargetConsistencyError(ValueError):
    """当任一 target 无法贯穿声明、校验和 handler 路径时抛出。"""

    def __init__(self, issues: Iterable[TargetConsistencyIssue]) -> None:
        self.issues = tuple(issues)
        message = "; ".join(f"{issue.code}: {issue.message}" for issue in self.issues)
        super().__init__(message)


def assert_target_consistency(
    *,
    registry_rows: Iterable[Mapping[str, Any]],
    emitted_targets: Iterable[Mapping[str, Any]],
    provider_handler_targets: Iterable[Mapping[str, Any]],
    platform: str,
) -> None:
    """确保 facade 发出的 target 可由 Server 接受并由目标平台 handler 路由。

    Args:
        registry_rows: SDK Registry Artifact 的 contract matrix 行。
        emitted_targets: generated facade 实际记录的 invoke target。
        provider_handler_targets: Agent 运行时已注册的 invoke target。
        platform: 用于筛选 provider mapping 的平台名。

    Raises:
        TargetConsistencyError: 任一 target 存在跨层漂移。
    """

    issues = check_target_consistency(
        registry_rows=registry_rows,
        emitted_targets=emitted_targets,
        provider_handler_targets=provider_handler_targets,
        platform=platform,
    )
    if issues:
        raise TargetConsistencyError(issues)


def check_target_consistency(
    *,
    registry_rows: Iterable[Mapping[str, Any]],
    emitted_targets: Iterable[Mapping[str, Any]],
    provider_handler_targets: Iterable[Mapping[str, Any]],
    platform: str,
) -> tuple[TargetConsistencyIssue, ...]:
    """返回所有 target consistency 问题，空元组表示一致。"""

    rows = list(registry_rows)
    emitted = list(emitted_targets)
    registry_targets = [_normalize_registry_target(row) for row in rows]
    registry_by_key = {target_key(target): target for target in registry_targets}
    emitted_keys, emitted_issues = _normalize_emitted_targets(emitted, registry_targets, registry_by_key)
    issues = list(emitted_issues)
    if not emitted_issues:
        issues.extend(_missing_facade_target_issues(rows, emitted_keys, platform))
    handler_keys, handler_issues = _normalize_handler_targets(provider_handler_targets)
    issues.extend(handler_issues)
    issues.extend(_missing_handler_issues(rows, handler_keys, platform))
    return tuple(issues)


def _normalize_registry_target(row: Mapping[str, Any]) -> dict[str, str]:
    target = row.get("target", {})
    return normalize_target(dict(target) if isinstance(target, Mapping) else target, "registry")


def _call_target_key(target: Mapping[str, Any]) -> str:
    return target_key(normalize_call_target(dict(target)))


def _normalize_handler_targets(
    targets: Iterable[Mapping[str, Any]],
) -> tuple[set[str], list[TargetConsistencyIssue]]:
    keys = set()
    issues = []
    for target in targets:
        raw_target = dict(target)
        try:
            keys.add(_call_target_key(raw_target))
        except TargetContractError as exc:
            issues.append(TargetConsistencyIssue("invalid_handler_target", raw_target, str(exc)))
    return keys, issues


def _normalize_emitted_targets(
    targets: Iterable[Mapping[str, Any]],
    registry_targets: list[dict[str, str]],
    registry_by_key: dict[str, dict[str, str]],
) -> tuple[set[str], list[TargetConsistencyIssue]]:
    keys = set()
    issues = []
    for target in targets:
        raw_target = dict(target)
        try:
            normalized = normalize_call_target(raw_target)
        except TargetContractError as exc:
            issues.append(TargetConsistencyIssue("server_rejected_target", raw_target, str(exc)))
            continue
        key = target_key(normalized)
        if key in registry_by_key:
            keys.add(key)
            continue
        issues.append(_undeclared_emitted_target_issue(raw_target, normalized, registry_targets))
    return keys, issues


def _undeclared_emitted_target_issue(
    raw_target: dict[str, Any],
    normalized: Mapping[str, str],
    registry_targets: list[dict[str, str]],
) -> TargetConsistencyIssue:
    if any(_same_handler_without_interface(normalized, registered) for registered in registry_targets):
        return TargetConsistencyIssue("mismatched_interface", raw_target, "facade interface differs from registry")
    if any(_same_provider_scope(normalized, registered) for registered in registry_targets):
        return TargetConsistencyIssue(
            "mismatched_class_function",
            raw_target,
            "facade class_name or function differs from registry",
        )
    return TargetConsistencyIssue("unsupported_target", raw_target, "facade target is not declared by registry")


def _same_handler_without_interface(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    fields = ("sdk", "class_name", "function", "overload")
    return all(left.get(field) == right.get(field) for field in fields) and left.get("interface") != right.get("interface")


def _same_provider_scope(left: Mapping[str, str], right: Mapping[str, str]) -> bool:
    return left.get("sdk") == right.get("sdk") and left.get("interface") == right.get("interface")


def _missing_facade_target_issues(
    rows: Iterable[Mapping[str, Any]],
    emitted_keys: set[str],
    platform: str,
) -> list[TargetConsistencyIssue]:
    issues = []
    for row in rows:
        if row.get("kind") not in {"call", "state"} or not _requires_handler(row, platform):
            continue
        target = _normalize_registry_target(row)
        if target_key(target) not in emitted_keys:
            issues.append(
                TargetConsistencyIssue(
                    "missing_facade_target",
                    target,
                    "registry runnable target was not emitted by facade",
                )
            )
    return issues


def _missing_handler_issues(
    rows: Iterable[Mapping[str, Any]],
    handler_keys: set[str],
    platform: str,
) -> list[TargetConsistencyIssue]:
    issues = []
    for row in rows:
        if row.get("kind") not in {"call", "state"} or not _requires_handler(row, platform):
            continue
        target = _normalize_registry_target(row)
        if target_key(target) not in handler_keys:
            issues.append(TargetConsistencyIssue("missing_handler", target, f"no registered handler for platform {platform}"))
    return issues


def _requires_handler(row: Mapping[str, Any], platform: str) -> bool:
    mappings = row.get("provider_mappings", [])
    return any(
        mapping.get("platform") == platform
        and mapping.get("status") == "supported"
        and bool(mapping.get("provider"))
        for mapping in mappings
        if isinstance(mapping, Mapping)
    )
