"""Generated synchronous Runner SDK facades."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from beacon_test.target_session import BeaconSession

from .agora_rtc import AgoraRtcFacade
from .beacon_system import BeaconSystemFacade
from .mock_complex_sdk import MockComplexSdkFacade
from .mock_echo import MockEchoFacade
from .volcengine_rtc import VolcengineRtcFacade
from .zego_express import ZegoExpressFacade

__all__ = ['AgoraRtcFacade', 'BeaconSystemFacade', 'MockComplexSdkFacade', 'MockEchoFacade', 'VolcengineRtcFacade', 'ZegoExpressFacade']

FACADES: dict[str, Callable[[BeaconSession, str], object]] = {
    'agora_rtc': AgoraRtcFacade,
    'beacon_system': BeaconSystemFacade,
    'mock_complex_sdk': MockComplexSdkFacade,
    'mock_echo': MockEchoFacade,
    'volcengine_rtc': VolcengineRtcFacade,
    'zego_express': ZegoExpressFacade,
}
