"""Standardized exception hierarchy for Beacon server.

This module defines a structured exception hierarchy that enables consistent
error handling across all runtime modules. All business exceptions inherit
from BeaconError and carry error codes, messages, and optional details.

Key Exceptions:
    BeaconError: Base exception for all Beacon errors.
    DeviceNotFoundError: Raised when a device is not found in registry.
    SessionExpiredError: Raised when a session has expired or is invalid.
    ValidationError: Raised when input validation fails.
    CommandDispatchError: Raised when command dispatch to device fails.
    EvidenceStoreError: Raised when evidence storage operations fail.

Usage:
    >>> from app.common.errors import DeviceNotFoundError
    >>> try:
    ...     device = await registry.get("missing-device")
    ...     if device is None:
    ...         raise DeviceNotFoundError("missing-device")
    ... except DeviceNotFoundError as e:
    ...     logger.error(f"Device lookup failed: {e}")

    >>> # Structured error details
    >>> error = ValidationError("channel", "must be non-empty string")
    >>> print(error.code)  # BeaconErrorCode.BAD_REQUEST
    >>> print(error.details)  # {"field": "channel", "reason": "..."}

Design Principles:
    - No bare Exception usage in production code
    - All exceptions carry structured error codes
    - Error details enable precise debugging and reporting
    - Exception hierarchy maps to HTTP/protocol error codes
"""
from enum import IntEnum
from typing import Any, Optional


class BeaconErrorCode(IntEnum):
    """Standardized error codes for Beacon server.

    These codes align with protocol error codes and HTTP status codes
    where applicable.
    """
    OK = 0
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 402
    NOT_FOUND = 404
    REQUEST_TIMEOUT = 408
    UNSUPPORTED = 488
    INTERNAL_ERROR = 500
    SERVICE_UNAVAILABLE = 503


class BeaconError(Exception):
    """Base exception for all Beacon server errors.

    All business exceptions should inherit from this class to enable
    consistent error handling, logging, and reporting.

    Attributes:
        code: Standardized error code from BeaconErrorCode enum.
        message: Human-readable error description.
        details: Optional dictionary with structured error context.

    Example:
        >>> error = BeaconError(BeaconErrorCode.INTERNAL_ERROR, "unexpected failure")
        >>> str(error)
        '[INTERNAL_ERROR] unexpected failure'
    """

    def __init__(
        self,
        code: BeaconErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code.name}] {message}")

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for JSON serialization.

        Returns:
            Dictionary with code, message, and details fields.
        """
        return {
            "code": int(self.code),
            "message": self.message,
            "details": self.details
        }


class RunStateTransitionError(BeaconError):
    """Raised when a test run lifecycle operation is not allowed."""

    def __init__(self, run_id: str, current_status: str | None, requested_operation: str):
        super().__init__(
            code=BeaconErrorCode.BAD_REQUEST,
            message=f"Run state transition rejected: {requested_operation}",
            details={
                "run_id": run_id,
                "current_status": current_status,
                "requested_operation": requested_operation,
            },
        )
        self.run_id = run_id
        self.current_status = current_status
        self.requested_operation = requested_operation


class DeviceNotFoundError(BeaconError):
    """Raised when a device is not found in the registry.

    This exception indicates that the requested node_id does not exist
    in the DeviceRegistry or the device is offline.

    Attributes:
        node_id: The device identifier that was not found.

    Example:
        >>> raise DeviceNotFoundError("device-mac-001")
    """

    def __init__(self, node_id: str):
        super().__init__(
            code=BeaconErrorCode.NOT_FOUND,
            message=f"Device not found: {node_id}",
            details={"node_id": node_id}
        )
        self.node_id = node_id


class SessionExpiredError(BeaconError):
    """Raised when a session has expired or become invalid.

    This exception indicates that the WebSocket session is no longer
    valid due to timeout, disconnection, or context invalidation.

    Attributes:
        session_id: The session identifier that expired.
        node_id: Optional device identifier associated with the session.

    Example:
        >>> raise SessionExpiredError("session-123", "device-mac-001")
    """

    def __init__(self, session_id: str, node_id: str | None = None):
        details = {"session_id": session_id}
        if node_id:
            details["node_id"] = node_id

        super().__init__(
            code=BeaconErrorCode.REQUEST_TIMEOUT,
            message=f"Session expired: {session_id}",
            details=details
        )
        self.session_id = session_id
        self.node_id = node_id


class ValidationError(BeaconError):
    """Raised when input validation fails.

    This exception indicates that provided parameters, configuration,
    or request data failed validation checks.

    Attributes:
        field: The field name that failed validation.
        reason: Description of why validation failed.

    Example:
        >>> raise ValidationError("channel", "must be non-empty string")
    """

    def __init__(self, field: str, reason: str):
        super().__init__(
            code=BeaconErrorCode.BAD_REQUEST,
            message=f"Validation failed for {field}: {reason}",
            details={"field": field, "reason": reason}
        )
        self.field = field
        self.reason = reason


class CommandDispatchError(BeaconError):
    """Raised when command dispatch to device fails.

    This exception indicates that a command could not be sent to the
    target device due to network issues, device offline, or timeout.

    Attributes:
        node_id: Target device identifier.
        action: Command action that failed (e.g., "invokeRequest").
        timeout_ms: Optional timeout value if failure was due to timeout.

    Example:
        >>> raise CommandDispatchError("device-001", "invokeRequest", timeout_ms=5000)
    """

    def __init__(self, node_id: str, action: str, timeout_ms: int | None = None):
        details: dict[str, Any] = {
            "node_id": node_id,
            "action": action
        }
        if timeout_ms:
            details["timeout_ms"] = timeout_ms

        message = f"Command dispatch failed: {action} to {node_id}"
        if timeout_ms:
            message += f" (timeout: {timeout_ms}ms)"

        super().__init__(
            code=BeaconErrorCode.REQUEST_TIMEOUT,
            message=message,
            details=details
        )
        self.node_id = node_id
        self.action = action
        self.timeout_ms = timeout_ms


class EvidenceStoreError(BeaconError):
    """Raised when evidence storage operations fail.

    This exception indicates that recording or querying evidence
    encountered an internal error.

    Attributes:
        operation: The operation that failed (e.g., "record", "query").
        evidence_type: Optional type of evidence involved.

    Example:
        >>> raise EvidenceStoreError("record", "event")
    """

    def __init__(self, operation: str, evidence_type: str | None = None):
        details = {"operation": operation}
        if evidence_type:
            details["evidence_type"] = evidence_type

        message = f"Evidence store {operation} failed"
        if evidence_type:
            message += f" for {evidence_type}"

        super().__init__(
            code=BeaconErrorCode.INTERNAL_ERROR,
            message=message,
            details=details
        )
        self.operation = operation
        self.evidence_type = evidence_type


class AuthenticationError(BeaconError):
    """Raised when authentication fails.

    This exception indicates that the provided authentication token
    is missing, invalid, or expired.

    Example:
        >>> raise AuthenticationError("invalid token")
    """

    def __init__(self, reason: str):
        super().__init__(
            code=BeaconErrorCode.UNAUTHORIZED,
            message=f"Authentication failed: {reason}",
            details={"reason": reason}
        )
        self.reason = reason


class UnsupportedError(BeaconError):
    """Raised when a feature or capability is not supported.

    This exception indicates that the requested operation targets
    an unsupported SDK method, interface, or platform.

    Attributes:
        feature: Description of the unsupported feature.
        sdk: Optional SDK name.
        target: Optional target specification.

    Example:
        >>> raise UnsupportedError("method not declared in registry", sdk="agora_rtc")
    """

    def __init__(self, feature: str, sdk: str | None = None, target: dict | None = None):
        details: dict[str, Any] = {"feature": feature}
        if sdk:
            details["sdk"] = sdk
        if target:
            details["target"] = target

        super().__init__(
            code=BeaconErrorCode.UNSUPPORTED,
            message=f"Unsupported: {feature}",
            details=details
        )
        self.feature = feature
        self.sdk = sdk
        self.target = target
