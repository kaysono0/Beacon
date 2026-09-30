"""Contract tests for IR-00 artifacts; none activate the target runtime."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.api.api_contracts import (  # noqa: E402
    ObservationInput,
    ObservationPage,
    ObservationRecord,
    RunnerCallRequest,
    RunnerCaseResultRequest,
    RunnerStartedRequest,
)
from scripts.validation.check_target_runtime_architecture import validate_invariant_catalog, violations  # noqa: E402
from scripts.validation.inventory_target_runtime import collect_inventory  # noqa: E402
from scripts.support.target_runtime_control import (  # noqa: E402
    DEPENDENCIES,
    WORK_PACKAGES,
    ControlArtifactError,
    advance_checkpoint,
    amend_completed_manifest,
    load_checkpoint,
    manifest_reference,
    select_next_package,
    unlocked_packages,
    validate_manifest,
)


def _source() -> dict[str, object]:
    return {"path": "test_cases/python/example.py", "line": 7, "function": "test_example"}


def _target() -> dict[str, str]:
    return {"sdk": "agora_rtc", "interface": "rtc_engine", "class": "AgoraRtcEngineKit", "function": "joinChannel"}


def _manifest(status: str = "passed") -> dict[str, object]:
    return {"schema_version": 1, "work_package": "IR-00", "status": status, "baseline_commit": "base", "verified_commit": None, "diff_digest": "0" * 64, "production_entry_changed": False, "changed_files": [], "invariants": [], "verification": [{"command": "check", "exit_code": 0, "result": "passed"}], "exit_criteria": [{"result": "passed"}], "skipped": [], "not_run": [], "blockers": [], "dirty_files_preserved": [], "next_allowed_packages": ["IR-01", "IR-04"]}


def test_IR00_DTO_round_trip_and_token_scope_shape():
    assert RunnerStartedRequest(runner_protocol_version=1, python_version="3.11", pid=42).pid == 42
    call = RunnerCallRequest.model_validate({"operation_id": "op", "device_role": "primary", "target": _target(), "source": _source()})
    assert call.model_dump(by_alias=True)["target"]["class"] == "AgoraRtcEngineKit"
    observation = ObservationRecord.model_validate({"observation_id": "obs", "kind": "event", "run_id": "run", "case_id": "case", "device_role": "primary", "node_id": "node", "lease_id": "lease", "source": "native_agent", "target": _target(), "timestamp_ms": 1, "cursor": 1, "ingested_at_ms": 2})
    assert ObservationPage(items=[observation], next_cursor=1, has_more=False).items[0].cursor == 1
    with pytest.raises(Exception):
        RunnerCallRequest.model_validate({"operation_id": "op", "device_role": "primary", "node_id": "forbidden", "target": _target(), "source": _source()})
    with pytest.raises(Exception):
        ObservationInput.model_validate({"observation_id": "obs"})
    with pytest.raises(Exception):
        RunnerCaseResultRequest(status="passed", failure_classification="unknown")


def test_IR10_inventory_reports_cutover_catalog_without_old_runtime_references():
    inventory = collect_inventory()
    assert inventory["source_file_count"] == 26
    assert inventory["active_case_count"] == 59
    assert inventory["dsl_counts"] == {
        "ctx.step": 0,
        "ctx.expect": 0,
        "cleanup_step": 0,
        "dynamic_sdk": 0,
    }
    assert all(not paths for paths in inventory["legacy_references"].values())


def test_IR10_completion_updates_production_cutover_state(tmp_path: Path):
    state = load_checkpoint(ROOT / "tests/fixtures/target_runtime_execution_state.yaml")
    state["active_package"] = "IR-10"
    state["status"] = "in_progress"
    state["baseline_commit"] = "base"
    state["completed_packages"] = [f"IR-{number:02d}" for number in range(10)]
    state["production_runtime"] = "recorder_thin_executor"
    state["production_cutover_completed"] = False
    manifest = _manifest()
    manifest["work_package"] = "IR-10"
    manifest["next_allowed_packages"] = ["IR-11"]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    completed = advance_checkpoint(
        state,
        status="completed",
        manifest_path=manifest_path,
        manifest_path_reference="reports/target-runtime/IR-10/execution-manifest.json",
    )

    assert completed["production_runtime"] == "immediate_remote_control"
    assert completed["production_cutover_completed"] is True
    assert completed["target_endpoint_enabled"] is False

    amended_manifest = {**manifest, "verified_commit": "corrected"}
    manifest_path.write_text(json.dumps(amended_manifest), encoding="utf-8")
    amended = amend_completed_manifest(
        completed,
        manifest_path=manifest_path,
        manifest_path_reference="reports/target-runtime/IR-10/execution-manifest.json",
        updated_at="later",
    )
    assert amended["completed_packages"] == completed["completed_packages"]
    assert amended["latest_manifest"]["sha256"] != completed["latest_manifest"]["sha256"]
    with pytest.raises(ControlArtifactError):
        amend_completed_manifest(
            {**completed, "status": "in_progress"},
            manifest_path=manifest_path,
            manifest_path_reference="reports/target-runtime/IR-10/execution-manifest.json",
            updated_at="later",
        )


def test_IR00_checkpoint_and_manifest_fail_closed(tmp_path: Path):
    state_path = ROOT / "tests/fixtures/target_runtime_execution_state.yaml"
    state = load_checkpoint(state_path)
    state["active_package"] = "IR-00"
    state["status"] = "not_started"
    state["baseline_commit"] = None
    state["completed_packages"] = []
    running = advance_checkpoint(state, status="in_progress", baseline_commit="base")
    with pytest.raises(ControlArtifactError):
        advance_checkpoint(running, status="completed")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    assert advance_checkpoint(
        running,
        status="completed",
        manifest_path=manifest_path,
        manifest_path_reference="reports/target-runtime/IR-00/execution-manifest.json",
    )["status"] == "completed"
    broken = _manifest()
    broken["exit_criteria"] = [{"result": "failed"}]
    with pytest.raises(ControlArtifactError):
        validate_manifest(broken)
    broken = _manifest()
    broken["verification"] = [{"command": "check", "exit_code": 1, "result": "passed"}]
    with pytest.raises(ControlArtifactError):
        validate_manifest(broken)
    broken = _manifest()
    broken["verification"] = [{"command": "check", "exit_code": 0, "result": "skipped"}]
    with pytest.raises(ControlArtifactError):
        validate_manifest(broken)
    broken = _manifest()
    broken["verification"] = []
    with pytest.raises(ControlArtifactError):
        validate_manifest(broken)
    unsafe = _manifest()
    unsafe["not_run"] = [{"reason": "/Users/example/local-secret"}]
    with pytest.raises(ControlArtifactError):
        validate_manifest(unsafe)
    conflict = dict(state)
    conflict["status"] = "verification_failed"
    conflict["baseline_commit"] = "other"
    with pytest.raises(ControlArtifactError):
        advance_checkpoint(conflict, status="in_progress", baseline_commit="base")
    repository_manifest = ROOT / "reports/target-runtime/IR-00/execution-manifest.json"
    assert manifest_reference(state_path, repository_manifest) == "reports/target-runtime/IR-00/execution-manifest.json"
    private_state_path = ROOT / ".private/docs/architecture/execution_state.yaml"
    assert manifest_reference(private_state_path, repository_manifest) == "reports/target-runtime/IR-00/execution-manifest.json"
    with pytest.raises(ControlArtifactError):
        manifest_reference(state_path, tmp_path / "outside.json")
    with pytest.raises(ControlArtifactError):
        manifest_reference(private_state_path, tmp_path / "outside.json")
    with pytest.raises(ControlArtifactError):
        manifest_reference(tmp_path / "outside.yaml", repository_manifest)


def test_IR00_dependency_graph_covers_every_package_and_unlocks_only_successors():
    assert set(DEPENDENCIES) == set(WORK_PACKAGES)
    assert unlocked_packages(["IR-00"]) == ["IR-01", "IR-04"]
    assert unlocked_packages(["IR-00", "IR-01"]) == ["IR-02", "IR-04"]
    completed = load_checkpoint(ROOT / "tests/fixtures/target_runtime_execution_state.yaml")
    completed["status"] = "completed"
    completed["completed_packages"] = ["IR-00"]
    selected = select_next_package(completed, next_package="IR-01", updated_at="now")
    assert selected["active_package"] == "IR-01"
    assert selected["status"] == "not_started"
    assert selected["baseline_commit"] is None
    with pytest.raises(ControlArtifactError):
        select_next_package(completed, next_package="IR-02")
    completed["status"] = "in_progress"
    with pytest.raises(ControlArtifactError):
        select_next_package(completed, next_package="IR-01")


def test_IR00_guard_is_read_only_and_rejects_forbidden_surface(tmp_path: Path):
    assert not violations(ROOT)
    (tmp_path / "server/app").mkdir(parents=True)
    (tmp_path / "python_sdk/beacon_test").mkdir(parents=True)
    (tmp_path / "server/app/example.py").write_text("class AsyncBeaconSession: pass", encoding="utf-8")
    (tmp_path / "server/app/test_run_entry.py").write_text("PythonNativeExecutor", encoding="utf-8")
    assert validate_invariant_catalog(tmp_path) == ["INVARIANT-CATALOG missing invariant catalog"]
    assert any(item.startswith("INV-001") for item in violations(tmp_path))
    (tmp_path / "server/app/example.py").unlink()
    generated = tmp_path / "python_sdk/beacon_test/generated"
    generated.mkdir()
    (generated / "facade.py").write_text("async def join(): pass", encoding="utf-8")
    assert any(item.startswith("INV-001") for item in violations(tmp_path))
    (generated / "facade.py").unlink()
    (tmp_path / "python_sdk/beacon_test/target_session.py").write_text('PATH = "/api/v1/sdk/call"', encoding="utf-8")
    assert any(item.startswith("INV-002") for item in violations(tmp_path))


@pytest.mark.parametrize("relative,source", [
    ("python_sdk/beacon_test/client.py", ""),
    ("python_sdk/beacon_test/models.pyi", ""),
    ("server/app/main.py", 'PATH = "/api/v1/devices/{node_id}/commands"'),
    ("server/app/main.py", 'PATH = "/api/v1/devices/{node_id}/callbacks"'),
    ("python_sdk/beacon_test/registry_facade.py", ""),
    ("server/app/old_runtime.py", "class TestOrchestrator: pass"),
    ("server/app/old_runtime.py", "class AssertionEngine: pass"),
    ("scripts/old_gate.py", "from beacon_test import BeaconTestClient"),
    ("scripts/old_gate.py", "from beacon_test import (\n    BeaconTestClient,\n)"),
    ("scripts/old_gate.py", "import beacon_test.client as legacy"),
])
def test_single_call_path_guard_rejects_retired_clients_and_execution(relative, source, tmp_path):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert any(item.startswith("INV-010") for item in violations(tmp_path))
