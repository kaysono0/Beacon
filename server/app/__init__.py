"""Server 应用包。

`python_sdk` 不是 server 的声明依赖，而是同仓库内的兄弟目录，因此在这里统一
把它加入 import path：`app.*` 任意模块都可以直接 import `beacon_test`，
不必依赖「某个模块先被 import」这种隐式顺序。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PYTHON_SDK_ROOT = Path(__file__).resolve().parents[2] / "python_sdk"
if str(_PYTHON_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_SDK_ROOT))
