"""Generated from sdk_registry/compiled; do not edit by hand."""

from __future__ import annotations

from typing import Any, Literal
from beacon_test.target_session import BeaconSession, CallResult, ObservationHandle, ResourceRef

class MockComplexSdkFacade:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def artifacts(self) -> MockComplexSdkArtifactsInterface:
        return MockComplexSdkArtifactsInterface(self._session, self._role)

    @property
    def control(self) -> MockComplexSdkControlInterface:
        return MockComplexSdkControlInterface(self._session, self._role)

    @property
    def diagnostics(self) -> MockComplexSdkDiagnosticsInterface:
        return MockComplexSdkDiagnosticsInterface(self._session, self._role)

    @property
    def metrics(self) -> MockComplexSdkMetricsInterface:
        return MockComplexSdkMetricsInterface(self._session, self._role)

    @property
    def session(self) -> MockComplexSdkSessionInterface:
        return MockComplexSdkSessionInterface(self._session, self._role)


class MockComplexSdkArtifactsInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def latest_snapshot(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'artifact', {'class_name': 'MockComplexArtifacts', 'function': 'latestSnapshot', 'interface': 'artifacts', 'sdk': 'mock_complex_sdk'})


class MockComplexSdkControlInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def reset_value(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'MockComplexControl', 'function': 'resetValue', 'interface': 'control', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)


class MockComplexSdkDiagnosticsInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def value_applied(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'log', {'class_name': 'MockComplexDiagnostics', 'function': 'valueApplied', 'interface': 'diagnostics', 'sdk': 'mock_complex_sdk'})


class MockComplexSdkMetricsInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def applied_count(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'metric', {'class_name': 'MockComplexMetrics', 'function': 'appliedCount', 'interface': 'metrics', 'sdk': 'mock_complex_sdk'})


class MockComplexSdkSessionInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def apply_value(self, *, value: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['value'] = value
        return self._session.call(self._role, {'class_name': 'MockComplexSession', 'function': 'applyValue', 'interface': 'session', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def configure_value(self, *, value: str, options: dict[str, Any], check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['value'] = value
        params['options'] = options
        return self._session.call(self._role, {'class_name': 'MockComplexSession', 'function': 'configureValue', 'interface': 'session', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def describe_value(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'MockComplexSession', 'function': 'describeValue', 'interface': 'session', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def ensure_value(self, *, value: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['value'] = value
        return self._session.call(self._role, {'class_name': 'MockComplexSession', 'function': 'ensureValue', 'interface': 'session', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def reject_value(self, *, reason: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['reason'] = reason
        return self._session.call(self._role, {'class_name': 'MockComplexSession', 'function': 'rejectValue', 'interface': 'session', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def set_parameter_matrix(self, *, profile: Literal['strict', 'relaxed'], display_name: str | None, labels: dict[str, str], file_ref: dict[str, Any], attempts: int = 2, optional_note: str | None = None, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['profile'] = profile
        params['display_name'] = display_name
        params['labels'] = labels
        params['file_ref'] = file_ref
        params['attempts'] = attempts
        if optional_note is not None:
            params['optional_note'] = optional_note
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'MockComplexSession', 'function': 'setParameterMatrix', 'interface': 'session', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_parameter_matrix_set(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'MockComplexSessionObserver', 'function': 'onParameterMatrixSet', 'interface': 'session', 'sdk': 'mock_complex_sdk'})

    @property
    def on_value_applied(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'MockComplexSessionObserver', 'function': 'onValueApplied', 'interface': 'session', 'sdk': 'mock_complex_sdk'})

    def get_last_applied_value(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'MockComplexSession', 'function': 'getLastAppliedValue', 'interface': 'session', 'sdk': 'mock_complex_sdk'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def get_last_applied_value_observations(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'state', {'class_name': 'MockComplexSession', 'function': 'getLastAppliedValue', 'interface': 'session', 'sdk': 'mock_complex_sdk'})
