"""Protocol interfaces for Beacon runtime module abstraction.

This module defines typing.Protocol interfaces that enable dependency inversion
and improve testability. All runtime classes should implement their corresponding
protocol interface.

Key Protocols:
    DeviceRegistryProtocol: Interface for device registration and querying.
    EvidenceStoreProtocol: Interface for evidence storage and retrieval.
    CommandDispatcherProtocol: Interface for command dispatch to devices.
    SessionManagerProtocol: Interface for WebSocket session management.

Usage:
    >>> from app.common.interfaces import DeviceRegistryProtocol
    >>> class MockRegistry(DeviceRegistryProtocol):
    ...     async def upsert(self, session): ...
    ...     async def get(self, node_id): ...
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.devices.device_models import DeviceSelector, DeviceSession
    from app.runs.test_models import TestRun


class TestRunReaderProtocol(Protocol):
    """TestRun 快照的只读异步接口。"""

    async def get_run(self, run_id: str) -> TestRun | None: ...


class TestRunStoreProtocol(Protocol):
    """TestRun 快照存储的最小异步接口。"""

    async def put(self, run: TestRun) -> None: ...

    async def get(self, run_id: str) -> TestRun | None: ...

    async def list_runs(self, limit: int) -> list[TestRun]: ...


class DeviceRegistryProtocol(Protocol):
    """Interface for device registry operations.

    This protocol defines the contract for managing connected devices,
    including registration, lookup, filtering, and removal.

    Implementations must be thread-safe for concurrent access.
    """

    async def upsert(self, session: DeviceSession) -> DeviceSession | None:
        """Register or update a device session.

        Args:
            session: DeviceSession object containing device metadata and websocket.

        Returns:
            Previous session if replaced, None otherwise.
        """
        ...

    async def get(self, node_id: str) -> DeviceSession | None:
        """Get device session by node_id.

        Args:
            node_id: Unique device identifier.

        Returns:
            DeviceSession if found, None otherwise.
        """
        ...

    async def list(self, selector: DeviceSelector | None = None) -> list[DeviceSession]:
        """List device sessions with optional filtering.

        Args:
            selector: DeviceSelector with platform/group_id/tags filters.

        Returns:
            List of matching DeviceSession objects.
        """
        ...

    async def remove(self, node_id: str) -> None:
        """Remove device session by node_id.

        Args:
            node_id: Unique device identifier to remove.
        """
        ...


class EvidenceStoreProtocol(Protocol):
    """Interface for evidence storage operations.

    This protocol defines the contract for storing and retrieving
    normalized runtime evidence for test assertions and reports.

    Implementations must support concurrent access.
    """

    async def record_callback_event(self, packet: dict) -> Any:
        """Record a callback event from agent.

        Args:
            packet: callbackEventRequest packet containing event data.

        Returns:
            StoredEvent object with recorded event.
        """
        ...

    async def callback_events(self, node_id: str) -> list[Any]:
        """Retrieve all callback events for a device.

        Args:
            node_id: Device identifier to query events for.

        Returns:
            List of StoredEvent objects.
        """
        ...

    async def record_evidence(self, evidence: Any) -> Any:
        """Record generic evidence (event/metric/state/artifact/log).

        Args:
            evidence: Evidence object with type, payload, and metadata.

        Returns:
            Normalized Evidence object after storage.
        """
        ...

    async def evidence_events(
        self,
        node_id: str,
        target: dict | None = None,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[Any]:
        """Query evidence events with filters.

        Args:
            node_id: Device identifier.
            target: Optional target filter (sdk/interface/class/function).
            run_id: Optional test run ID filter.
            case_id: Optional test case ID filter.
            step_id: Optional test step ID filter.

        Returns:
            List of matching Evidence objects.
        """
        ...

    async def evidence_by_type(
        self,
        node_id: str,
        evidence_type: str,
        target: dict | None = None,
        *,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
    ) -> list[Any]:
        """Query normalized evidence by type.

        Args:
            node_id: Device identifier.
            evidence_type: Evidence type ('event', 'metric', 'state', 'artifact', or 'log').
            target: Optional target filter.
            run_id: Optional test run ID filter.
            case_id: Optional test case ID filter.
            step_id: Optional test step ID filter.

        Returns:
            List of matching Evidence objects.
        """
        ...


class CommandDispatcherProtocol(Protocol):
    """Interface for command dispatch operations.

    This protocol defines the contract for sending commands to devices
    and installing callback defers.

    Implementations handle packet construction, transport, and pending
    request tracking.
    """

    async def send_invoke(self, node_id: str, calls: list[dict], timeout_ms: int | None = None) -> dict:
        """Dispatch invokeRequest to device.

        Args:
            node_id: Target device identifier.
            calls: List of CallData objects to execute.
            timeout_ms: Request timeout in milliseconds.

        Returns:
            Response packet from agent or error packet on failure.
        """
        ...

    async def send_protocol_invoke(
        self,
        node_id: str,
        calls: list[dict],
        op_id: str,
        timeout_ms: int | None = None,
        *,
        expected_lease_id: str | None = None,
    ) -> dict:
        """Dispatch invokeRequest with a recorder-owned operation ID."""
        ...

    async def install_callback(self, node_id: str, defers: list[dict], timeout_ms: int | None = None) -> dict:
        """Install callback defer on device.

        Args:
            node_id: Target device identifier.
            defers: List of DeferDescriptor objects to install.
            timeout_ms: Request timeout in milliseconds.

        Returns:
            Response packet from agent or error packet on failure.
        """
        ...

    async def install_protocol_callback(
        self,
        node_id: str,
        defers: list[dict],
        registration_id: str,
        timeout_ms: int,
        *,
        expected_lease_id: str,
    ) -> dict:
        """Install one Runner-owned callback registration on the bound lease."""
        ...


class SessionManagerProtocol(Protocol):
    """Interface for session management.

    This protocol defines the contract for managing WebSocket sessions,
    handling register/reconnect/unregister flows, and maintaining
    recoverable session context.
    """

    async def handle_register(self, websocket: Any, packet: dict) -> dict:
        """Handle device registration request.

        Args:
            websocket: WebSocket connection object.
            packet: registerRequest packet.

        Returns:
            registerResponse packet.
        """
        ...

    async def handle_reconnect(self, websocket: Any, packet: dict) -> dict:
        """Handle device reconnection request.

        Args:
            websocket: WebSocket connection object.
            packet: reconnectRequest packet.

        Returns:
            reconnectResponse packet with state indicator.
        """
        ...

    async def handle_unregister(self, websocket: Any, packet: dict) -> dict:
        """Handle device unregistration request.

        Args:
            websocket: WebSocket connection object.
            packet: unregisterRequest packet.

        Returns:
            unregisterResponse packet.
        """
        ...

    async def handle_disconnect(self, websocket: Any) -> None:
        """Handle WebSocket disconnection.

        Cleans up session and fails all pending requests for the device.

        Args:
            websocket: WebSocket connection that disconnected.
        """
        ...

    async def is_active_lease(self, node_id: str, lease_id: str) -> bool:
        """Return whether lease_id is the current active lease for node_id."""
        ...

    async def store_callback(self, node_id: str, key: str, definition: dict) -> None:
        """Store callback defer definition in session context.

        Args:
            node_id: Device identifier.
            key: Unique callback key (e.g., op_id:index).
            definition: DeferDescriptor definition.
        """
        ...
