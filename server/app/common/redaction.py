"""Server 侧共享脱敏策略。

占位符与 Agent Core 的 `logging::kRedactedValue` 一致，都是 `<redacted>`。
两侧按 ADR-020 的做法各自实现、共享同一份策略语义：敏感字段名集合、
`key=value` 与 `Bearer` 文本形态、以及本机用户路径形态。
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "<redacted>"

# 结构化日志里按字段名整值抹除的敏感键；比较前先小写。
SENSITIVE_LOG_FIELDS = frozenset(
    {
        "token",
        "secret",
        "password",
        "authorization",
        "api_key",
        "app_cert",
        "app_certificate",
        "agora_app_cert",
        "agora_app_id",
    }
)

# 自由文本里命中即整值抹除的标记；比较前先小写。
_SECRET_TEXT_MARKERS = (
    "token=",
    "bearer ",
    "authorization",
    "secret",
    "password",
    "api_key",
    "app_cert",
    "agora_app_id",
)

_LOCAL_PATH_PATTERNS = (
    re.compile(r"/Users/[^\s,:;\"']+(?:/[^\s,:;\"']*)?"),
    re.compile(r"\$HOME(?:/[^\s,:;\"']*)?"),
)


def redact_local_paths(value: str) -> str:
    """替换日志和报告中的本机用户路径。"""

    redacted = value
    for pattern in _LOCAL_PATH_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def redact_log_value(value: Any) -> Any:
    """递归脱敏日志 message 与 extra。

    先按字段名抹除结构化敏感值，再对剩余字符串做敏感文本判定，
    最后才替换本机路径，避免路径替换破坏敏感文本的匹配形态。
    """

    if isinstance(value, dict):
        return {
            key: (REDACTED if key.lower() in SENSITIVE_LOG_FIELDS else redact_log_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_log_value(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _SECRET_TEXT_MARKERS):
            return REDACTED
        return redact_local_paths(value)
    return value
