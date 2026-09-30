"""Generated from sdk_registry/compiled; do not edit by hand."""

from __future__ import annotations

from typing import Any, Literal
from beacon_test.target_session import BeaconSession, CallResult, ObservationHandle, ResourceRef

class BeaconSystemFacade:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def clock(self) -> BeaconSystemClockInterface:
        return BeaconSystemClockInterface(self._session, self._role)

    @property
    def network_condition(self) -> BeaconSystemNetworkConditionInterface:
        return BeaconSystemNetworkConditionInterface(self._session, self._role)

    @property
    def video_host(self) -> BeaconSystemVideoHostInterface:
        return BeaconSystemVideoHostInterface(self._session, self._role)


class BeaconSystemClockInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def wait_in_ms(self, *, ms: int, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['ms'] = ms
        return self._session.call(self._role, {'class_name': 'SystemClock', 'function': 'waitInMs', 'interface': 'clock', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)


class BeaconSystemNetworkConditionInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def apply_impairment(self, *, profile: str, duration_ms: int | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['profile'] = profile
        if duration_ms is not None:
            params['duration_ms'] = duration_ms
        return self._session.call(self._role, {'class_name': 'NetworkCondition', 'function': 'applyImpairment', 'interface': 'network_condition', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def get_condition_state(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'NetworkCondition', 'function': 'getConditionState', 'interface': 'network_condition', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def reset_impairment(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'NetworkCondition', 'function': 'resetImpairment', 'interface': 'network_condition', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)


class BeaconSystemVideoHostInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def focus(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'VideoHost', 'function': 'focus', 'interface': 'video_host', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def hide(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'VideoHost', 'function': 'hide', 'interface': 'video_host', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def rearrange(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'VideoHost', 'function': 'rearrange', 'interface': 'video_host', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def show(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'VideoHost', 'function': 'show', 'interface': 'video_host', 'sdk': 'beacon_system'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)
