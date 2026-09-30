"""Server-side helpers for writing structured diagnostic log events."""

from __future__ import annotations

import uuid
from typing import Any

from app.reporting.evidence_runtime import now_ms

SERVER_LOG_LEASE_ID = "server-process"
SERVER_LOG_NODE_ID = "beacon-server"


async def record_server_log(
    log_collector: Any,
    *,
    event: str,
    message: str,
    run_id: str = "",
    case_id: str = "",
    step_id: str = "",
    op_id: str = "",
    level: str = "info",
    error_code: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write one structured server diagnostic event through the log collector."""
    ingest = getattr(log_collector, "ingest", None)
    if ingest is None:
        return
    await ingest(
        SERVER_LOG_NODE_ID,
        SERVER_LOG_LEASE_ID,
        [
            {
                "event_id": f"server-log-{uuid.uuid4().hex}",
                "timestamp_ms": now_ms(),
                "level": level,
                "node_id": SERVER_LOG_NODE_ID,
                "lease_id": SERVER_LOG_LEASE_ID,
                "run_id": run_id,
                "case_id": case_id,
                "step_id": step_id,
                "op_id": op_id,
                "module": "server",
                "event": event,
                "message": message,
                "error": error_code,
                "extra": extra or {},
            }
        ],
    )
