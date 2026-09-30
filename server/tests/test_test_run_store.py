import pytest

from app.devices.device_models import DeviceSelector
from app.runs.test_models import TestCase, TestRun, TestStep
from app.runs.test_run_store import JsonlTestRunStore, MemoryTestRunStore


def sample_run() -> TestRun:
    return TestRun(
        run_id="run-snapshot",
        status="queued",
        selector=DeviceSelector(),
        cases=[TestCase(case_id="case-snapshot", name="snapshot", steps=[TestStep(step_id="step-snapshot")])],
    )


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15_memory_run_store_isolates_snapshots() -> None:
    store = MemoryTestRunStore()
    source = sample_run()
    await store.put(source)

    source.status = "failed"
    restored = await store.get(source.run_id)

    assert restored is not None
    assert restored.status == "queued"

    restored.status = "passed"
    restored_again = await store.get(source.run_id)

    assert restored_again is not None
    assert restored_again.status == "queued"


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15A_jsonl_run_store_does_not_cache_failed_writes(tmp_path) -> None:
    blocked_parent = tmp_path / "runtime-state"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    store = JsonlTestRunStore(blocked_parent / "test-runs.jsonl")
    run = sample_run()

    with pytest.raises(OSError):
        await store.put(run)

    assert await store.get(run.run_id) is None


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15B_jsonl_run_store_keeps_last_snapshot_after_failed_update(tmp_path) -> None:
    state_dir = tmp_path / "runtime-state"
    store = JsonlTestRunStore(state_dir / "test-runs.jsonl")
    run = sample_run()
    await store.put(run)

    (state_dir / "test-runs.jsonl").unlink()
    state_dir.rmdir()
    state_dir.write_text("not a directory", encoding="utf-8")
    run.status = "failed"

    with pytest.raises(OSError):
        await store.put(run)

    restored = await store.get(run.run_id)
    assert restored is not None
    assert restored.status == "queued"


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15C_memory_store_lists_runs_newest_first() -> None:
    store = MemoryTestRunStore()
    for run_id, created_at_ms in [("run-old", 100), ("run-new", 300), ("run-mid", 200)]:
        await store.put(
            TestRun(run_id=run_id, status="queued", selector=DeviceSelector(), cases=[], created_at_ms=created_at_ms)
        )

    listed = await store.list_runs(2)

    assert [run.run_id for run in listed] == ["run-new", "run-mid"]
    listed[0].status = "mutated"
    restored = await store.get("run-new")
    assert restored is not None
    assert restored.status == "queued"


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15D_jsonl_store_lists_replayed_runs_newest_first(tmp_path) -> None:
    state_dir = tmp_path / "runtime-state"
    store = JsonlTestRunStore(state_dir / "test-runs.jsonl")
    for run_id, created_at_ms in [("run-old", 100), ("run-new", 300)]:
        await store.put(
            TestRun(run_id=run_id, status="queued", selector=DeviceSelector(), cases=[], created_at_ms=created_at_ms)
        )

    replayed = JsonlTestRunStore(state_dir / "test-runs.jsonl")

    assert [run.run_id for run in await replayed.list_runs(10)] == ["run-new", "run-old"]
