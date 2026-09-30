"""现有 producer 到统一 ObservationInput 的兼容映射。"""

from __future__ import annotations

from typing import Any

from app.observations.observation_models import ObservationInput


UNSCOPED_RUN = "__unscoped__"
UNSCOPED_CASE = "__unscoped__"
UNBOUND_ROLE = "unbound"
UNKNOWN_NODE = "unknown"
UNKNOWN_LEASE = "unscoped"


def callback_observation(packet: dict[str, Any]) -> ObservationInput:
    common = packet.get("common", {})
    data = packet.get("data", {})
    node_id = _text(data.get("node_id"), UNKNOWN_NODE)
    lease_id = _text(data.get("lease_id"), UNKNOWN_LEASE)
    event_id = _text(data.get("event_id"), "unknown")
    return ObservationInput.model_validate(
        {
            "observation_id": f"callback:{node_id}:{lease_id}:{event_id}",
            "kind": "event",
            "run_id": _text(data.get("run_id"), UNSCOPED_RUN),
            "case_id": _text(data.get("case_id"), UNSCOPED_CASE),
            "step_id": None,
            "operation_id": None,
            "device_role": _text(data.get("device_role"), UNBOUND_ROLE),
            "node_id": node_id,
            "lease_id": lease_id,
            "source": "native_agent",
            "target": _callback_target(data["event_target"]),
            "payload": data.get("payload", {}),
            "callback_execution": data.get("callback_execution"),
            "timestamp_ms": _timestamp(common.get("timestamp_ms")),
        }
    )


def log_observation(event: dict[str, Any]) -> ObservationInput:
    node_id = _text(event.get("node_id"), UNKNOWN_NODE)
    lease_id = _text(event.get("lease_id"), UNKNOWN_LEASE)
    event_id = _text(event.get("event_id"), "unknown")
    return ObservationInput.model_validate(
        {
            "observation_id": f"log:{node_id}:{lease_id}:{event_id}",
            "kind": "log",
            "run_id": _text(event.get("run_id"), UNSCOPED_RUN),
            "case_id": _text(event.get("case_id"), UNSCOPED_CASE),
            "step_id": _optional_text(event.get("step_id")),
            "operation_id": _optional_text(event.get("op_id")),
            "device_role": _text(event.get("device_role"), UNBOUND_ROLE),
            "node_id": node_id,
            "lease_id": lease_id,
            "source": "agent_log",
            "target": {"sdk": "beacon", "interface": "diagnostics", "name": "log"},
            "payload": event,
            "timestamp_ms": _timestamp(event.get("timestamp_ms")),
        }
    )


def artifact_observation(artifact: dict[str, Any]) -> ObservationInput:
    metadata = artifact.get("metadata", {})
    node_id = _text(artifact.get("node_id"), UNKNOWN_NODE)
    artifact_id = _text(artifact.get("artifact_id"), "unknown")
    artifact_type = _text(artifact.get("artifact_type"), "unknown")
    return ObservationInput.model_validate(
        {
            "observation_id": artifact_id,
            "kind": "artifact",
            "run_id": _text(metadata.get("run_id"), UNSCOPED_RUN),
            "case_id": _text(metadata.get("case_id"), UNSCOPED_CASE),
            "step_id": _optional_text(metadata.get("step_id")),
            "operation_id": _optional_text(metadata.get("op_id")),
            "device_role": _text(metadata.get("device_role"), UNBOUND_ROLE),
            "node_id": node_id,
            "lease_id": _text(metadata.get("lease_id"), UNKNOWN_LEASE),
            "source": "artifact_ingress",
            "target": {"sdk": "beacon", "interface": "artifact", "name": artifact_type},
            "payload": artifact,
            "timestamp_ms": _timestamp(metadata.get("timestamp_ms")),
        }
    )


def connection_observation(event: dict[str, Any], observation_id: str) -> ObservationInput:
    event_type = _text(event.get("type"), "unknown")
    return ObservationInput.model_validate(
        {
            "observation_id": observation_id,
            "kind": "connection",
            "run_id": _text(event.get("run_id"), UNSCOPED_RUN),
            "case_id": _text(event.get("case_id"), UNSCOPED_CASE),
            "step_id": _optional_text(event.get("step_id")),
            "operation_id": _optional_text(event.get("op_id")),
            "device_role": _text(event.get("device_role"), UNBOUND_ROLE),
            "node_id": _text(event.get("node_id"), UNKNOWN_NODE),
            "lease_id": _text(event.get("lease_id"), UNKNOWN_LEASE),
            "source": "server_connection",
            "target": {"sdk": "beacon", "interface": "connection", "name": event_type},
            "payload": event,
            "timestamp_ms": _timestamp(event.get("timestamp_ms")),
        }
    )


def _text(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value.strip() else fallback


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _timestamp(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _callback_target(value: dict[str, Any]) -> dict[str, Any]:
    target = dict(value)
    target.setdefault("interface", "legacy")
    return target
