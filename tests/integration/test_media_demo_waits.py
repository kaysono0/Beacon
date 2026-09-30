"""演示等待留在 Runner，不能占住 Native Agent 的清理通道。"""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python_sdk"))

from beacon_test.runner import _load_case  # noqa: E402


class PreparedMediaSession:
    """提供进入展示阶段的前置事实；禁止把展示等待下发到 Agent。"""

    def __getattr__(self, name):
        return self

    def __call__(self, *args, **kwargs):
        return SimpleNamespace(code=0, value={"state": "connected"})

    def device(self, role):
        return self

    def is_joined(self):
        return SimpleNamespace(value=False)

    def wait(self, **kwargs):
        return SimpleNamespace(cursor=1, payload={"width": 960, "height": 400, "received_bitrate": 1})

    def wait_in_ms(self, **kwargs):
        raise AssertionError("播放等待占住 Native Agent，Cancel 无法及时清理")


@pytest.mark.parametrize(("module", "function", "seconds"), [
    ("agora_legacy_cleanup_cases", "test_tc_mac_agora_real_join_leave_state", [10]),
    ("agora_media_player_case", "test_tc_mac_agora_1v1_media_player_pause_resume", [10, 10, 10]),
    ("agora_audio_playback_case", "test_tc_mac_agora_1v1_audio_playback_mute_recover", [10, 10, 10]),
    ("agora_bidirectional_video_cases", "test_tc_mac_agora_1v1_remote_video_rendered", [10]),
    ("agora_bidirectional_video_cases", "test_tc_mac_agora_1v1_remote_video_synth_peer", [10]),
    ("agora_grid_media_player_cases", "test_tc_mac_agora_4_grid_camera_media_segments", [10]),
    ("agora_grid_media_player_cases", "test_tc_mac_agora_9_grid_camera_media_segments", [10]),
])
def test_MEDIA_DEMO_wait_leaves_native_cleanup_channel_free(monkeypatch, module, function, seconds):
    case = _load_case(ROOT, f"test_cases/python/agora/{module}.py", function)
    waits = []

    monkeypatch.setitem(case.__globals__, "sleep", waits.append)
    case(PreparedMediaSession())
    assert waits == seconds
