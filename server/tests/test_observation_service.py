"""IR-01 Observation 核心模块合同测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.common.config import ServerConfig
from app.main import create_observation_store
from app.observations.observation_models import ObservationInput, ObservationQuery
from app.observations.observation_service import (
    ObservationService,
    ObservationWaitCancelledError,
    ObservationWaitTimeoutError,
)
from app.observations.observation_store import JsonlObservationStore, MemoryObservationStore, ObservationConflictError


def _item(
    observation_id: str,
    *,
    kind: str = "event",
    run_id: str = "run-1",
    case_id: str = "case-1",
    function: str | None = "joinChannel",
    name: str | None = None,
    payload: dict | None = None,
    operation_id: str | None = "op-1",
) -> ObservationInput:
    target = {"sdk": " agora_rtc ", "interface": " rtc_engine "}
    if function is not None:
        target["class"] = " AgoraRtcEngineKit "
        target["function"] = f" {function} "
    if name is not None:
        target["name"] = f" {name} "
    return ObservationInput.model_validate(
        {
            "observation_id": observation_id,
            "kind": kind,
            "run_id": run_id,
            "case_id": case_id,
            "step_id": "step-1",
            "operation_id": operation_id,
            "device_role": "primary",
            "node_id": "mac-1",
            "lease_id": "lease-1",
            "source": "native_agent",
            "target": target,
            "payload": payload or {},
            "timestamp_ms": 100,
        }
    )


@pytest.mark.anyio
async def test_IR01_ingest_supports_six_kinds_and_run_local_cursors() -> None:
    service = ObservationService(now_ms=lambda: 200)
    kinds = ("event", "state", "metric", "log", "artifact", "connection")

    first_run = [await service.ingest(_item(f"obs-{kind}", kind=kind)) for kind in kinds]
    other_run = await service.ingest(_item("obs-event", run_id="run-2"))

    assert [record.kind for record in first_run] == list(kinds)
    assert [record.cursor for record in first_run] == [1, 2, 3, 4, 5, 6]
    assert other_run.cursor == 1
    assert all(record.ingested_at_ms == 200 for record in [*first_run, other_run])
    with pytest.raises(ValidationError):
        _item("invalid-kind", kind="unknown")
    with pytest.raises(ValidationError):
        _item("invalid-target", function=None, name=None)
    with pytest.raises(ValidationError):
        _item("invalid-payload", payload={"value": object()})


@pytest.mark.anyio
async def test_IR01_deduplicates_exact_body_and_rejects_conflict() -> None:
    ticks = iter((200, 300, 400))
    service = ObservationService(now_ms=lambda: next(ticks))
    item = _item("obs-1", payload={"state": "connected"})

    first = await service.ingest(item)
    duplicate = await service.ingest(item)

    assert duplicate == first
    with pytest.raises(ObservationConflictError, match="conflicts"):
        await service.ingest(_item("obs-1", payload={"state": "failed"}))
    assert [record.cursor for record in await service.query(ObservationQuery(run_id="run-1"))] == [1]


@pytest.mark.anyio
async def test_IR01_canonicalizes_target_redacts_payload_and_returns_copies() -> None:
    service = ObservationService(now_ms=lambda: 200)
    record = await service.ingest(
        _item(
            "obs-1",
            payload={
                "state": "connected",
                "token": "plain-token",
                "nested": {"apiKey": "plain-key", "message": "Bearer secret-token"},
            },
        )
    )

    assert record.target.model_dump(by_alias=True, exclude_none=True) == {
        "sdk": "agora_rtc",
        "interface": "rtc_engine",
        "class": "AgoraRtcEngineKit",
        "function": "joinChannel",
    }
    assert record.payload == {
        "state": "connected",
        "token": "<redacted>",
        "nested": {"apiKey": "<redacted>", "message": "<redacted>"},
    }
    record.payload["state"] = "mutated"
    stored = await service.query(ObservationQuery(run_id="run-1"))
    assert stored[0].payload["state"] == "connected"


@pytest.mark.anyio
async def test_IR01_query_and_latest_state_projection_preserve_raw_facts() -> None:
    service = ObservationService(now_ms=lambda: 200)
    await service.ingest(_item("event", payload={"state": "connecting"}))
    await service.ingest(
        _item(
            "state-1",
            kind="state",
            function=None,
            name="connection_state_changed",
            payload={"state": "connecting"},
        )
    )
    latest = await service.ingest(
        _item(
            "state-2",
            kind="state",
            function=None,
            name="connection_state_changed",
            payload={"state": "connected"},
        )
    )
    await service.ingest(_item("other-run", run_id="run-2", payload={"state": "connected"}))

    query = ObservationQuery.model_validate(
        {
            "run_id": "run-1",
            "kinds": ["state"],
            "target": {
                "sdk": "agora_rtc",
                "interface": "rtc_engine",
                "name": "connection_state_changed",
            },
            "match": {"state": "connected"},
            "after_cursor": 1,
        }
    )
    assert await service.query(query) == [latest]
    assert await service.latest_state(query.model_copy(update={"match": {}})) == latest
    raw_states = await service.query(ObservationQuery(run_id="run-1", kinds=frozenset({"state"})))
    assert [record.payload["state"] for record in raw_states] == ["connecting", "connected"]


@pytest.mark.anyio
async def test_IR06_operation_fact_does_not_replace_native_latest_state() -> None:
    service = ObservationService(now_ms=lambda: 200)
    state = await service.ingest(
        _item("native-state", kind="state", function=None, name="connection", payload={"state": "connected"})
    )
    operation = await service.ingest(
        _item("call-result", kind="operation", function=None, name="connection", payload={"outcome": "failed"})
    )

    assert operation.cursor > state.cursor
    assert await service.latest_state(ObservationQuery(run_id="run-1")) == state


@pytest.mark.anyio
@pytest.mark.parametrize("backend", ["memory", "jsonl"])
async def test_IR01_memory_and_jsonl_have_matching_query_semantics(tmp_path: Path, backend: str) -> None:
    store = MemoryObservationStore() if backend == "memory" else JsonlObservationStore(tmp_path / "observations.jsonl")
    service = ObservationService(store, now_ms=lambda: 200)
    await service.ingest(_item("obs-1", payload={"value": 0}))
    await service.ingest(_item("obs-2", payload={"value": 1}))

    if backend == "jsonl":
        service = ObservationService(JsonlObservationStore(tmp_path / "observations.jsonl"), now_ms=lambda: 300)
        assert (await service.ingest(_item("obs-1", payload={"value": 0}))).cursor == 1

    records = await service.query(ObservationQuery(run_id="run-1", match={"value": 0}))
    assert [(record.observation_id, record.cursor, record.payload) for record in records] == [
        ("obs-1", 1, {"value": 0})
    ]


@pytest.mark.anyio
async def test_IR06_jsonl_reloads_pre_correction_record_without_correlation(tmp_path: Path) -> None:
    path = tmp_path / "observations.jsonl"
    service = ObservationService(JsonlObservationStore(path), now_ms=lambda: 200)
    original = await service.ingest(_item("legacy-event"))
    old_shape = {**original.model_dump(mode="json", by_alias=True), "correlation": None}
    path.write_text(json.dumps(old_shape) + "\n", encoding="utf-8")

    restored = ObservationService(JsonlObservationStore(path), now_ms=lambda: 300)
    records = await restored.query(ObservationQuery(run_id="run-1"))
    assert len(records) == 1
    assert records[0].observation_id == "legacy-event"
    assert "correlation" not in records[0].model_dump()

    path.write_text(json.dumps({**old_shape, "correlation": "strong"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid observation JSONL line"):
        JsonlObservationStore(path)


@pytest.mark.anyio
async def test_IR01_concurrent_ingest_assigns_unique_monotonic_cursors() -> None:
    service = ObservationService(now_ms=lambda: 200)
    records = await asyncio.gather(*(service.ingest(_item(f"obs-{index}")) for index in range(100)))
    cursors = sorted(record.cursor for record in records)

    assert cursors == list(range(1, 101))
    queried = await service.query(ObservationQuery(run_id="run-1"))
    assert [record.cursor for record in queried] == cursors


@pytest.mark.anyio
async def test_IR03_wait_finds_existing_and_future_observations_without_polling() -> None:
    service = ObservationService(now_ms=lambda: 200)
    existing = await service.ingest(_item("existing", payload={"state": "connected"}))
    query = ObservationQuery(run_id="run-1", match={"state": "connected"})

    assert await service.wait(query, timeout_ms=20) == existing

    future_query = ObservationQuery(run_id="run-1", match={"state": "failed"})
    waiter = asyncio.create_task(service.wait(future_query, timeout_ms=100))
    await asyncio.sleep(0)
    future = await service.ingest(_item("future", payload={"state": "failed"}))

    assert await waiter == future


@pytest.mark.anyio
async def test_IR03_wait_times_out_and_run_cancellation_wakes_waiters() -> None:
    service = ObservationService(now_ms=lambda: 200)
    query = ObservationQuery(run_id="run-1")

    with pytest.raises(ObservationWaitTimeoutError, match="timed out"):
        await service.wait(query, timeout_ms=1)

    waiter = asyncio.create_task(service.wait(query, timeout_ms=1000))
    await asyncio.sleep(0)
    await service.cancel_waits("run-1")

    with pytest.raises(ObservationWaitCancelledError, match="cancelled"):
        await waiter


@pytest.mark.anyio
async def test_IR06_wait_cursor_filters_freshness_without_operation_attribution() -> None:
    service = ObservationService(now_ms=lambda: 200)
    await service.ingest(_item("before", payload={"state": "connected"}, operation_id="op-target"))
    strong = await service.ingest(_item("strong", payload={"state": "connected"}, operation_id="op-target"))
    await service.ingest(_item("wrong-operation", payload={"state": "connected"}, operation_id="op-other"))
    temporal = await service.ingest(_item("temporal", payload={"state": "connected"}, operation_id=None))

    fresh_match = await service.wait(
        ObservationQuery(
            run_id="run-1",
            after_cursor=1,
            match={"state": "connected"},
        ),
        timeout_ms=20,
    )
    next_match = await service.wait(
        ObservationQuery(
            run_id="run-1",
            after_cursor=strong.cursor,
            match={"state": "connected"},
        ),
        timeout_ms=20,
    )

    assert fresh_match.observation_id == strong.observation_id
    assert next_match.observation_id == "wrong-operation"
    assert "correlation" not in fresh_match.model_dump()
    assert "correlation" not in next_match.model_dump()
    assert temporal.cursor > next_match.cursor


@pytest.mark.anyio
async def test_IR03_page_filters_kinds_preserves_cursor_and_isolates_runs() -> None:
    service = ObservationService(now_ms=lambda: 200)
    await service.ingest(_item("event-1"))
    state = await service.ingest(_item("state-1", kind="state", function=None, name="connection"))
    await service.ingest(_item("event-2"))
    await service.ingest(_item("other-run", run_id="run-2"))

    first = await service.page(run_id="run-1", after_cursor=0, limit=1)
    filtered = await service.page(
        run_id="run-1",
        after_cursor=0,
        limit=2,
        kinds=frozenset({"state"}),
    )
    empty = await service.page(run_id="run-1", after_cursor=3, limit=2)

    assert [item.observation_id for item in first.items] == ["event-1"]
    assert first.next_cursor == 1
    assert first.has_more is True
    assert [item.observation_id for item in filtered.items] == [state.observation_id]
    assert filtered.next_cursor == state.cursor
    assert filtered.has_more is False
    assert empty.items == []
    assert empty.next_cursor == 3
    assert empty.has_more is False


def test_IR01_main_constructs_memory_and_opt_in_jsonl_store(tmp_path: Path) -> None:
    assert isinstance(create_observation_store(ServerConfig(server_runtime_store="memory")), MemoryObservationStore)
    jsonl = create_observation_store(
        ServerConfig(server_runtime_store="jsonl", server_runtime_jsonl_dir=str(tmp_path))
    )
    assert isinstance(jsonl, JsonlObservationStore)
    with pytest.raises(ValueError, match="unsupported server runtime store"):
        create_observation_store(ServerConfig(server_runtime_store="sqlite"))


@pytest.mark.anyio
@pytest.mark.parametrize("jsonl", [False, True])
async def test_latest_state_isolated_between_runs_with_same_case_and_target(tmp_path, jsonl) -> None:
    store = JsonlObservationStore(tmp_path / "observations.jsonl") if jsonl else MemoryObservationStore()
    service = ObservationService(store)
    first = await service.ingest(_item("state", kind="state", run_id="run-a", payload={"state": "connected"}))
    await service.ingest(_item("state", kind="state", run_id="run-b", payload={"state": "failed"}))

    assert await service.latest_state(ObservationQuery(run_id="run-a")) == first
    assert await service.latest_state(ObservationQuery(run_id="missing")) is None
    if jsonl:
        restored = ObservationService(JsonlObservationStore(tmp_path / "observations.jsonl"))
        assert await restored.latest_state(ObservationQuery(run_id="run-a")) == first
