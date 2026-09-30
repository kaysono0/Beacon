"""协议 wire 字段的稳定 JSON 编码。

Server、registry/test-case 编译器和 Python 作者层共用这一份实现：
wire 上的 `params`、`extra`、`return_value` 必须是 JSON 字符串，
而作者侧可能直接传字符串，也可能传 dict/list。
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json(value: Any) -> str:
    """把 wire 字段稳定转换为 JSON 字符串。

    字符串入参视为已编码：只校验它是合法 JSON 后原样透传，避免二次编码
    把 `{"a":1}` 变成 `"{\\"a\\":1}"`。
    """

    if isinstance(value, str):
        json.loads(value)
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
