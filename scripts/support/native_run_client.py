"""Wait for a production immediate run to reach a Server terminal state."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


async def wait_run(
    client: httpx.AsyncClient,
    base_url: str,
    run_id: str,
    headers: dict[str, str],
    *,
    timeout_s: float = 240,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = await client.get(f"{base_url}/api/v1/console/test-runs/{run_id}", headers=headers)
        response.raise_for_status()
        run = response.json()["run"]
        if run["status"] in {"passed", "failed", "cancelled"}:
            return run
        await asyncio.sleep(0.25)
    raise TimeoutError(f"test run {run_id} did not reach a terminal state")
