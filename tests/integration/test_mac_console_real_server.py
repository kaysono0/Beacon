"""统一真实 Console 启动拓扑测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BEACON_AUTH_TOKEN", "test-token")

from scripts.dev.run_mac_console_real_server import agora_roles_for_unified_server  # noqa: E402


def test_unified_server_starts_every_declared_agora_role() -> None:
    roles = agora_roles_for_unified_server()

    assert {"primary", "peer", "peer_b"} <= set(roles)
    assert {f"segment_{index}" for index in range(1, 9)} <= set(roles)
