"""Python-native 执行辅助函数。

本模块放置调用结果解码、运行参数解析和隔离声明解析逻辑，不持有 run 状态。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping


def decode_response_result(response: dict[str, Any]) -> Any:
    """解析 invoke response 中的 result，兼容单元素 list 包装。"""
    data = response.get("data", {})
    result = data.get("result", "{}")
    items = data.get("list", [])
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict) and "result" in first:
            result = first["result"]
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result
    return result


PlaceholderResolver = Callable[[dict[str, Any]], Any]


class RuntimeParamResolver:
    """解析运行期占位参数。

    控制面只认识"参数值恰好等于某个已注册占位符"这一形态，不认识任何 SDK 语义；
    每个占位符的取值来源由注册的 resolver 决定，SDK 专有实现放在 `app.sdk.sdk_extensions`。
    占位符让 token 等敏感值保持在环境层，避免 case 源码写入凭证。
    """

    def __init__(self, resolvers: Mapping[str, PlaceholderResolver] | None = None) -> None:
        self._resolvers: dict[str, PlaceholderResolver] = dict(resolvers or {})

    def resolve(self, params: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(params)
        for key, value in list(resolved.items()):
            if not isinstance(value, str):
                continue
            resolver = self._resolvers.get(value)
            if resolver is not None:
                resolved[key] = resolver(resolved)
        return resolved


RUNTIME_ISOLATION_TAG_PREFIX = "runtime-isolation:"


def declared_runtime_isolation(tags: Iterable[str]) -> bool | None:
    """从 case tag 读取 runtime isolation 声明；未声明或取值不认识时返回 None。"""
    for tag in tags:
        if not tag.startswith(RUNTIME_ISOLATION_TAG_PREFIX):
            continue
        value = tag[len(RUNTIME_ISOLATION_TAG_PREFIX) :]
        if value == "required":
            return True
        if value == "not-required":
            return False
    return None
