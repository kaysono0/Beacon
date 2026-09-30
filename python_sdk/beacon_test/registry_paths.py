"""SDK Registry 编译产物目录的唯一解析入口。"""

from __future__ import annotations

import os
from pathlib import Path

REGISTRY_DIR_ENV = "BEACON_SDK_REGISTRY_DIR"

# 仓库内布局下的默认位置；SDK 被安装到 site-packages 时用 REGISTRY_DIR_ENV 覆盖。
_PACKAGED_DEFAULT = Path(__file__).resolve().parents[2] / "sdk_registry" / "compiled"


def default_registry_dir() -> Path:
    """编译产物的仓库内位置，不受 REGISTRY_DIR_ENV 影响；写入方必须用它。"""
    return _PACKAGED_DEFAULT


def registry_dir() -> Path:
    override = os.environ.get(REGISTRY_DIR_ENV, "").strip()
    if override:
        # 立即绝对化：调用方 chdir 或把路径传给子进程后，解析结果不再漂移。
        return Path(os.path.abspath(os.path.expanduser(override)))
    return _PACKAGED_DEFAULT
