"""连接态用例须在常驻引擎下重复执行，且不能掩盖真实回调超时。"""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python_sdk"))

from beacon_test.runner import _load_case  # noqa: E402


class StatefulEngine:
    """仅首次创建产生连接回调；会话清理后引擎仍可存活。"""

    def __init__(self, loaded, emit_connection=True):
        self.loaded = loaded
        self.emit_connection = emit_connection
        self.connected_event = False
        self.on_connection_state_changed = self

    def create_rtc_engine(self, **kwargs):
        self.connected_event = not self.loaded and self.emit_connection
        self.loaded = True
        return SimpleNamespace(code=0)

    def destroy_rtc_engine(self):
        self.loaded = False
        self.connected_event = False
        return SimpleNamespace(code=0)

    def wait(self, *, match, timeout_s):
        assert match == {"state": 3}
        if not self.connected_event:
            raise TimeoutError("未收到新建引擎的连接回调")


def _run_case(engine):
    device = SimpleNamespace(volcengine_rtc=SimpleNamespace(byte_rtc_engine=engine))
    session = SimpleNamespace(device=lambda role: device)
    case = _load_case(ROOT, "test_cases/python/volcengine/volcengine_l1_cases.py",
                      "test_volcengine_connection_state")
    case(session)


@pytest.mark.parametrize("loaded", [False, True])
def test_VOLCENGINE_CONNECTION_case_is_independent_of_prior_engine(loaded):
    engine = StatefulEngine(loaded)
    for _ in range(2):
        _run_case(engine)
        assert not engine.loaded


def test_VOLCENGINE_CONNECTION_missing_callback_fails_and_releases_engine():
    engine = StatefulEngine(True, emit_connection=False)
    with pytest.raises(TimeoutError):
        _run_case(engine)
    assert not engine.loaded
