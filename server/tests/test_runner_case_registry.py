"""IR-04 Runner case scope、binding 和 token 合同测试。"""

from __future__ import annotations

import pytest

from app.api.api_contracts import RunnerCaseResultRequest, RunnerStartedRequest
from app.devices.device_models import Device, DeviceSession
from app.devices.device_runtime import DeviceRegistry
from app.runs.python_native_models import NativeTestCase
from app.runs.runner_case_registry import (
    RunnerAuthorizationError,
    RunnerCaseContext,
    RunnerCaseMetadata,
    RunnerCaseRegistry,
    RunnerRoleBinding,
)


def _case_function(_: object) -> None:
    raise AssertionError("catalog discovery must not execute case functions")


def _native_case() -> NativeTestCase:
    return NativeTestCase(
        case_id="TC-RUNNER-SCOPE",
        name="runner scope",
        platform="macos",
        devices=["primary", "peer"],
        suite="target-runtime",
        scenario_family="runner",
        implementation_status="runnable",
        covered_capabilities=[],
        tags=[],
        source_path="test_cases/python/runner_scope.py",
        function_name="test_runner_scope",
        function=_case_function,
    )


def _binding(role: str, node_id: str, lease_id: str) -> RunnerRoleBinding:
    session = DeviceSession(
        device=Device(node_id=node_id, platform="macos", tags=[f"role:{role}"]),
        websocket=object(),
        lease_id=lease_id,
    )
    return RunnerRoleBinding.from_session(role, session)


def _context(*, expires_at_ms: int = 2_000) -> RunnerCaseContext:
    metadata = RunnerCaseMetadata.from_native_case(_native_case())
    return RunnerCaseContext(
        run_id="run-scope",
        metadata=metadata,
        bindings={
            "primary": _binding("primary", "node-primary", "lease-primary"),
            "peer": _binding("peer", "node-peer", "lease-peer"),
        },
        case_timeout_ms=10_000,
        token_expires_at_ms=expires_at_ms,
    )


@pytest.mark.anyio
async def test_IR04_catalog_fixes_source_function_and_declared_roles() -> None:
    registry = RunnerCaseRegistry([_native_case()], now_ms=lambda: 1_000)

    metadata = registry.require_metadata("TC-RUNNER-SCOPE")

    assert metadata.source_path == "test_cases/python/runner_scope.py"
    assert metadata.function_name == "test_runner_scope"
    assert metadata.device_roles == ("primary", "peer")
    with pytest.raises(KeyError):
        registry.require_metadata("TC-CLIENT-SUPPLIED")


@pytest.mark.anyio
async def test_IR04_token_authorizes_only_its_scope_and_is_not_rendered() -> None:
    registry = RunnerCaseRegistry([_native_case()], now_ms=lambda: 1_000, token_factory=lambda: b"x" * 32)
    context = _context()
    credential = await registry.register(context)

    authorized = await registry.authorize(credential.token, "run-scope", "TC-RUNNER-SCOPE")

    assert authorized is context
    assert credential.token not in repr(credential)
    with pytest.raises(RunnerAuthorizationError, match="scope_mismatch"):
        await registry.authorize(credential.token, "run-other", "TC-RUNNER-SCOPE")
    with pytest.raises(RunnerAuthorizationError, match="invalid_token"):
        await registry.authorize("server-token", "run-scope", "TC-RUNNER-SCOPE")


@pytest.mark.anyio
async def test_IR04_expired_and_revoked_tokens_fail_closed() -> None:
    clock = [1_000]
    registry = RunnerCaseRegistry([_native_case()], now_ms=lambda: clock[0])
    context = _context(expires_at_ms=1_100)
    credential = await registry.register(context)

    clock[0] = 1_101
    with pytest.raises(RunnerAuthorizationError, match="expired_token"):
        await registry.authorize(credential.token, context.run_id, context.case_id)

    clock[0] = 1_000
    fresh_context = RunnerCaseContext(
        run_id="run-fresh",
        metadata=context.metadata,
        bindings=context.bindings,
        case_timeout_ms=context.case_timeout_ms,
        token_expires_at_ms=2_000,
    )
    fresh = await registry.register(fresh_context)
    await registry.finish(fresh_context.run_id, fresh_context.case_id)
    with pytest.raises(RunnerAuthorizationError, match="revoked_token"):
        await registry.authorize(fresh.token, fresh_context.run_id, fresh_context.case_id)


@pytest.mark.anyio
async def test_IR07_supervisor_reads_started_and_result_without_granting_terminal_write() -> None:
    registry = RunnerCaseRegistry([_native_case()], now_ms=lambda: 1_000)
    context = _context()
    await registry.register(context)
    started = RunnerStartedRequest(runner_protocol_version=1, python_version="3.11", pid=123)
    result = RunnerCaseResultRequest(status="failed", failure_classification="python_assertion")

    assert await registry.protocol_snapshot(context) == (None, None)
    assert await registry.record_started(context, started)
    assert await registry.record_result(context, result)
    assert not await registry.record_result(context, result)
    snapshot_started, snapshot_result = await registry.protocol_snapshot(context)
    assert snapshot_started == started
    assert snapshot_result == result
    assert snapshot_result is not result


@pytest.mark.anyio
async def test_IR06_binding_snapshot_is_stable_without_target_step_counter() -> None:
    device_registry = DeviceRegistry()
    initial_session = DeviceSession(
        device=Device(node_id="node-primary", platform="macos", tags=["role:primary"]),
        websocket=object(),
        lease_id="lease-primary",
    )
    await device_registry.upsert(initial_session)
    context = RunnerCaseContext(
        run_id="run-scope",
        metadata=RunnerCaseMetadata.from_native_case(_native_case()),
        bindings={
            "primary": RunnerRoleBinding.from_session("primary", initial_session),
            "peer": _binding("peer", "node-peer", "lease-peer"),
        },
        case_timeout_ms=10_000,
        token_expires_at_ms=2_000,
    )
    original = context.binding("primary")
    await device_registry.upsert(
        DeviceSession(
            device=Device(node_id="node-primary", platform="macos", tags=["role:primary"]),
            websocket=object(),
            lease_id="new-lease",
        )
    )

    assert context.binding("primary") == original
    assert context.binding("primary").node_id == "node-primary"
    assert context.binding("primary").lease_id == "lease-primary"
    assert not hasattr(context, "next_step_id")
    with pytest.raises(KeyError):
        context.binding("undeclared")


def test_IR04_context_rejects_missing_or_extra_role_bindings() -> None:
    metadata = RunnerCaseMetadata.from_native_case(_native_case())

    with pytest.raises(ValueError, match="binding roles"):
        RunnerCaseContext(
            run_id="run-scope",
            metadata=metadata,
            bindings={"primary": _binding("primary", "node-primary", "lease-primary")},
            case_timeout_ms=10_000,
            token_expires_at_ms=2_000,
        )
