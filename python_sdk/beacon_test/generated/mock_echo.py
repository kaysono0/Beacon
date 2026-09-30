"""Generated from sdk_registry/compiled; do not edit by hand."""

from __future__ import annotations

from typing import Any, Literal
from beacon_test.target_session import BeaconSession, CallResult, ObservationHandle, ResourceRef

class MockEchoFacade:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def echo(self) -> MockEchoEchoInterface:
        return MockEchoEchoInterface(self._session, self._role)


class MockEchoEchoInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def echo(self, *, message: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['message'] = message
        return self._session.call(self._role, {'class_name': 'EchoService', 'function': 'echo', 'interface': 'echo', 'sdk': 'mock_echo'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def echo_with_callback(self, *, message: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['message'] = message
        return self._session.call(self._role, {'class_name': 'EchoService', 'function': 'echoWithCallback', 'interface': 'echo', 'sdk': 'mock_echo'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_echo_received(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'EchoDelegate', 'function': 'onEchoReceived', 'interface': 'echo', 'sdk': 'mock_echo'})

    def get_last_echo(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'EchoService', 'function': 'getLastEcho', 'interface': 'echo', 'sdk': 'mock_echo'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def get_last_echo_observations(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'state', {'class_name': 'EchoService', 'function': 'getLastEcho', 'interface': 'echo', 'sdk': 'mock_echo'})
