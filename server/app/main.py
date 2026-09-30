"""Beacon Server HTTP 与 WebSocket 入口。

本文件只装配 FastAPI 路由和内存控制面实例。
业务状态、协议终态和报告分别由对应的运行时组件负责。
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator, cast

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import JsonValue, ValidationError

from app.api.api_contracts import (
    ConsoleRunDetailResponse,
    ConsoleRunHistoryResponse,
    ConsoleSDKCapabilitiesResponse,
    ConsoleTestCasesResponse,
    RunnerCaseResultRequest,
    RunnerCallRequest,
    RunnerCallResponse,
    RunnerCallbackRegistrationRequest,
    RunnerCallbackRegistrationResponse,
    RunnerStartedRequest,
    RunnerTarget,
    RunnerWaitRequest,
    TestRunCreateRequest,
)
from app.api.auth import require_auth
from app.common.config import CONFIG, ServerConfig
from app.reporting.artifact_runtime import ArtifactStore, JsonlArtifactStore
from app.devices.dispatch_runtime import CommandDispatcher
from app.devices.connection_diagnostics import ConnectionEventStore
from app.devices.device_runtime import DeviceRegistry, JsonlDeviceSessionStore, SessionManager
from app.devices.device_models import DeviceSelector
from app.reporting.server_log_runtime import JsonlServerLogStore, ServerLogCollector
from app.runs.test_run_store import JsonlTestRunStore
from app.reporting.reporting import ReportGenerator
from app.reporting.evidence_runtime import ResultCollector
from app.api.console_api import (
    run_detail_payload,
    run_history_payload,
    sdk_capabilities_payload,
    test_cases_payload,
)
from app.api.gateway import AgentGateway
from app.api.models import ProtectedSmokeResponse, StatusResponse
from app.observations.observation_models import (
    ObservationInput,
    ObservationKind,
    ObservationPage,
    ObservationQuery,
    ObservationRecord,
    ObservationTarget,
)
from app.observations.observation_service import ObservationService, ObservationWaitCancelledError, ObservationWaitTimeoutError
from app.observations.observation_store import JsonlObservationStore, MemoryObservationStore, ObservationStore
from app.runs.python_native_registry import PythonNativeRegistry
from app.runs.python_native_runtime import RuntimeParamResolver
from app.sdk.sdk_extensions import SDK_PARAM_RESOLVERS, SDK_RUNNER_ENVIRONMENT_NAMES
from app.runs.run_call_service import RunCallConflictError, RunCallService
from app.runs.run_runtime import ObservationWaitConflictError, ServerRunRuntime
from app.runs.runner_case_registry import (
    RunnerAuthorizationError,
    RunnerCaseContext,
    RunnerCaseRegistry,
    RunnerProtocolConflictError,
)
from app.runs.runner_process import RunnerProcessManager
from app.runs.runner_supervisor import RunnerSupervisor, TargetRunSelectionError
from app.common.redaction import redact_log_value
from app.sdk.sdk_extensions import SDK_TEST_ENDPOINTS
from app.sdk.sdk_registry import SDKRegistry
from app.runs.test_models import TestRun
from app.reporting.evidence_runtime import now_ms
from app.common.errors import RunStateTransitionError

from beacon_test.registry_paths import registry_dir


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await registry.load_from_store()
    await session_manager.load_contexts_from_store()
    await runner_supervisor.reconcile_interrupted_runs()
    yield


app = FastAPI(title="Beacon Server", version="0.1.0-p0", lifespan=lifespan)
runner_router = APIRouter()
OBSERVATION_KINDS = frozenset({"event", "state", "metric", "log", "artifact", "connection"})


def create_server_log_collector(
    config: ServerConfig,
    observation_service: ObservationService | None = None,
) -> ServerLogCollector:
    store = config.server_log_store.strip().lower()
    if store == "jsonl":
        return ServerLogCollector(
            store=JsonlServerLogStore(
                config.server_log_jsonl_path,
                max_bytes=config.server_log_jsonl_max_bytes,
                max_rotated_files=config.server_log_jsonl_max_files,
                retention_ms=config.server_log_jsonl_retention_ms,
                quarantine_corrupt_lines=config.server_log_jsonl_quarantine_corrupt,
            ),
            observation_service=observation_service,
        )
    if store in {"", "memory"}:
        return ServerLogCollector(observation_service=observation_service)
    raise ValueError(f"unsupported server log store: {config.server_log_store}")


def create_runtime_stores(
    config: ServerConfig,
    observation_service: ObservationService | None = None,
) -> tuple[
    JsonlDeviceSessionStore | None,
    JsonlTestRunStore | None,
    ArtifactStore,
]:
    store = config.server_runtime_store.strip().lower()
    if store in {"", "memory"}:
        return None, None, ArtifactStore(observation_service=observation_service)
    if store == "jsonl":
        base_dir = Path(config.server_runtime_jsonl_dir)
        return (
            JsonlDeviceSessionStore(base_dir / "device-sessions.jsonl"),
            JsonlTestRunStore(base_dir / "test-runs.jsonl"),
            JsonlArtifactStore(base_dir / "artifacts.jsonl", observation_service=observation_service),
        )
    raise ValueError(f"unsupported server runtime store: {config.server_runtime_store}")


def create_observation_store(config: ServerConfig) -> ObservationStore:
    """构造尚未接入 producer/consumer 的 target Observation store。"""

    store = config.server_runtime_store.strip().lower()
    if store in {"", "memory"}:
        return MemoryObservationStore()
    if store == "jsonl":
        return JsonlObservationStore(Path(config.server_runtime_jsonl_dir) / "observations.jsonl")
    raise ValueError(f"unsupported server runtime store: {config.server_runtime_store}")


def _report_log_dir(config: ServerConfig = CONFIG) -> Path:
    return Path(config.report_dir) / "logs"


def _report_log_artifact_path(artifact_uri: str, config: ServerConfig = CONFIG) -> str:
    relative_path = artifact_uri.removeprefix("artifact://logs/")
    return str(_report_log_dir(config) / relative_path)


# Phase 1 使用进程内单例保存运行态；后续持久化实现应替换这些组件实例。
observation_store = create_observation_store(CONFIG)
observation_service = ObservationService(observation_store)
device_session_store, test_run_store, artifact_store = create_runtime_stores(CONFIG, observation_service)
registry = DeviceRegistry(store=device_session_store)
connection_diagnostics = ConnectionEventStore(observation_service=observation_service)
collector = ResultCollector(connection_diagnostics=connection_diagnostics)
run_runtime = ServerRunRuntime(collector, test_run_store, observation_service)
session_manager = SessionManager(registry, run_runtime, store=device_session_store)
dispatcher = CommandDispatcher(registry, collector, session_manager, run_runtime=run_runtime)
sdk_registry = SDKRegistry.load_from(registry_dir())
run_call_service = RunCallService(
    dispatcher,
    sdk_registry,
    RuntimeParamResolver(SDK_PARAM_RESOLVERS),
    run_runtime,
    observation_service,
)
repo_root = Path(__file__).resolve().parents[2]
native_source_root = repo_root / "test_cases/python"
native_cases = PythonNativeRegistry.discover(native_source_root).cases
runner_case_registry = RunnerCaseRegistry(
    native_cases,
    now_ms=now_ms,
)
log_collector = create_server_log_collector(CONFIG, observation_service)
runner_supervisor = RunnerSupervisor(
    cases=native_cases,
    device_registry=registry,
    run_runtime=run_runtime,
    case_registry=runner_case_registry,
    call_service=run_call_service,
    process_manager=RunnerProcessManager(
        runner_case_registry,
        repo_root=repo_root,
        base_url=os.environ.get("BEACON_TARGET_RUNNER_BASE_URL", f"http://127.0.0.1:{CONFIG.default_port}"),
        log_collector=log_collector,
        case_environment={name: os.environ[name] for name in SDK_RUNNER_ENVIRONMENT_NAMES if name in os.environ},
    ),
    dispatcher=dispatcher,
    observation_service=observation_service,
    log_collector=log_collector,
    case_timeout_ms=CONFIG.target_case_timeout_ms,
    token_grace_ms=CONFIG.target_token_grace_ms,
    reset_timeout_ms=CONFIG.target_reset_timeout_ms,
)
report_generator = ReportGenerator(run_runtime, collector, log_collector, _report_log_dir(CONFIG), observation_service)
agent_gateway = AgentGateway(session_manager, collector, run_runtime, log_collector)


@app.get("/api/v1/status", response_model=StatusResponse)
def status() -> StatusResponse:
    return StatusResponse(service="beacon-server", status="ok", version="0.1.0-p0")


@app.get(
    "/api/v1/console/sdk-capabilities",
    response_model=ConsoleSDKCapabilitiesResponse,
    dependencies=[Depends(require_auth)],
)
def console_sdk_capabilities() -> dict:
    return sdk_capabilities_payload(sdk_registry)


@app.get(
    "/api/v1/console/test-cases",
    response_model=ConsoleTestCasesResponse,
    dependencies=[Depends(require_auth)],
)
def console_test_cases() -> dict:
    return test_cases_payload(Path(__file__).resolve().parents[2])


# 历史清单限量：默认值够 Console 一屏回看，上限防止单次响应无界增长。
RUN_HISTORY_DEFAULT_LIMIT = 50
RUN_HISTORY_MAX_LIMIT = 200


@app.get(
    "/api/v1/console/test-runs",
    response_model=ConsoleRunHistoryResponse,
    dependencies=[Depends(require_auth)],
)
async def console_run_history(
    limit: int = Query(default=RUN_HISTORY_DEFAULT_LIMIT, ge=1, le=RUN_HISTORY_MAX_LIMIT),
) -> dict:
    return await run_history_payload(run_runtime, limit, log_collector)


@app.get(
    "/api/v1/console/test-runs/{run_id}",
    response_model=ConsoleRunDetailResponse,
    dependencies=[Depends(require_auth)],
)
async def console_run_detail(run_id: str) -> dict:
    try:
        return await run_detail_payload(run_id, run_runtime, report_generator, log_collector, observation_service)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None


@app.get(
    "/api/v1/test-runs/{run_id}/observations",
    response_model=ObservationPage,
    dependencies=[Depends(require_auth)],
)
async def test_run_observations(
    run_id: str,
    after_cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    kinds: str | None = None,
) -> ObservationPage:
    """按 run-local cursor 返回 Console Observation 增量页。"""

    parsed_kinds: frozenset[ObservationKind] | None = None
    if kinds is not None:
        requested = frozenset(item.strip() for item in kinds.split(",") if item.strip())
        invalid = requested - OBSERVATION_KINDS
        if not requested or invalid:
            raise HTTPException(status_code=422, detail="invalid observation kinds")
        parsed_kinds = cast(frozenset[ObservationKind], requested)
    return await observation_service.page(
        run_id=run_id,
        after_cursor=after_cursor,
        limit=limit,
        kinds=parsed_kinds,
    )


async def require_runner_context(
    run_id: str,
    case_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> RunnerCaseContext:
    """只接受当前 path scope 的短期 Runner token。"""

    scheme, separator, token = (authorization or "").partition(" ")
    if scheme != "Bearer" or not separator or not token:
        raise HTTPException(status_code=401, detail="missing runner token")
    try:
        return await runner_case_registry.authorize(token, run_id, case_id)
    except RunnerAuthorizationError:
        raise HTTPException(status_code=403, detail="runner authorization rejected") from None


def _runner_binding(context: RunnerCaseContext, device_role: str):
    try:
        return context.binding(device_role)
    except KeyError:
        raise HTTPException(status_code=403, detail="runner role is outside case scope") from None


def _runner_match(raw_match: str | None) -> dict[str, JsonValue]:
    if raw_match in (None, ""):
        return {}
    try:
        decoded = json.loads(raw_match)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="invalid observation match") from error
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=422, detail="invalid observation match")
    return cast(dict[str, JsonValue], decoded)


def _validate_runner_observation(
    kind: str,
    target: RunnerTarget,
    match: dict[str, JsonValue],
) -> ObservationTarget:
    try:
        observation_target = ObservationTarget.model_validate(
            target.model_dump(mode="python", by_alias=True, exclude_none=True)
        )
    except ValidationError as validation_error:
        raise HTTPException(status_code=422, detail="invalid observation target") from validation_error
    target_dict = target.model_dump(mode="python", exclude_none=True)
    registry_error = sdk_registry.observation_match_error(kind, target_dict, match)
    if registry_error is not None:
        raise HTTPException(status_code=422, detail=registry_error)
    return observation_target


@runner_router.post("/api/v1/runner/runs/{run_id}/cases/{case_id}/started")
async def runner_case_started(
    payload: RunnerStartedRequest,
    context: Annotated[RunnerCaseContext, Depends(require_runner_context)],
) -> dict[str, object]:
    try:
        accepted = await runner_case_registry.record_started(context, payload)
    except RunnerProtocolConflictError:
        raise HTTPException(status_code=409, detail="runner started body conflict") from None
    return {"status": "accepted", "duplicate": not accepted}


@runner_router.post("/api/v1/runner/runs/{run_id}/cases/{case_id}/calls", response_model=RunnerCallResponse)
async def runner_call(
    payload: RunnerCallRequest,
    context: Annotated[RunnerCaseContext, Depends(require_runner_context)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunnerCallResponse:
    if idempotency_key != payload.operation_id:
        raise HTTPException(status_code=409, detail="operation idempotency key mismatch")
    try:
        return await run_call_service.execute(context, payload)
    except RunnerAuthorizationError:
        raise HTTPException(status_code=403, detail="runner call scope rejected") from None
    except RunCallConflictError:
        raise HTTPException(status_code=409, detail="runner call body conflict") from None
    except RunStateTransitionError:
        raise HTTPException(status_code=409, detail="runner run is not active") from None


@runner_router.post("/api/v1/runner/runs/{run_id}/cases/{case_id}/callbacks", response_model=RunnerCallbackRegistrationResponse)
async def runner_register_callback(
    payload: RunnerCallbackRegistrationRequest,
    context: Annotated[RunnerCaseContext, Depends(require_runner_context)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunnerCallbackRegistrationResponse:
    if idempotency_key != payload.registration_id:
        raise HTTPException(status_code=409, detail="registration idempotency key mismatch")
    try:
        return await run_call_service.register_callback(context, payload)
    except RunnerAuthorizationError:
        raise HTTPException(status_code=403, detail="runner callback scope rejected") from None
    except RunCallConflictError:
        raise HTTPException(status_code=409, detail="runner callback body conflict") from None
    except RunStateTransitionError:
        raise HTTPException(status_code=409, detail="runner run is not active") from None


@runner_router.post("/api/v1/runner/runs/{run_id}/cases/{case_id}/waits", response_model=ObservationRecord)
async def runner_wait_observation(
    payload: RunnerWaitRequest,
    context: Annotated[RunnerCaseContext, Depends(require_runner_context)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ObservationRecord:
    if idempotency_key != payload.wait_id:
        raise HTTPException(status_code=409, detail="wait idempotency key mismatch")
    try:
        context.validate_source(payload.source)
    except RunnerAuthorizationError:
        raise HTTPException(status_code=403, detail="runner source is outside case scope") from None
    binding = _runner_binding(context, payload.device_role)
    _validate_runner_observation(payload.kind, payload.target, payload.match)
    try:
        return await run_runtime.wait_for_observation(
            context.run_id,
            context.case_id,
            payload,
            node_id=binding.node_id,
            lease_id=binding.lease_id,
        )
    except ObservationWaitConflictError:
        raise HTTPException(status_code=409, detail="observation wait body conflict") from None
    except ObservationWaitTimeoutError:
        raise HTTPException(status_code=408, detail="observation wait timed out") from None
    except ObservationWaitCancelledError:
        raise HTTPException(status_code=409, detail="observation wait cancelled") from None


@runner_router.get("/api/v1/runner/runs/{run_id}/cases/{case_id}/observations", response_model=list[ObservationRecord])
async def runner_query_observations(
    context: Annotated[RunnerCaseContext, Depends(require_runner_context)],
    device_role: str,
    kind: ObservationKind,
    sdk: str,
    interface: str,
    class_name: str | None = Query(default=None, alias="class"),
    function: str | None = None,
    name: str | None = None,
    match: str | None = None,
    after_cursor: int = Query(default=0, ge=0),
) -> list[ObservationRecord]:
    binding = _runner_binding(context, device_role)
    target = RunnerTarget.model_validate(
        {
            "sdk": sdk,
            "interface": interface,
            "class": class_name,
            "function": function,
            "name": name,
        }
    )
    decoded_match = _runner_match(match)
    observation_target = _validate_runner_observation(kind, target, decoded_match)
    query = ObservationQuery(
        run_id=context.run_id,
        case_id=context.case_id,
        device_role=device_role,
        kinds=frozenset({kind}),
        target=observation_target,
        match=decoded_match,
        after_cursor=after_cursor,
    )
    return await run_runtime.query_observations(
        context.run_id,
        context.case_id,
        query,
        node_id=binding.node_id,
        lease_id=binding.lease_id,
    )


@runner_router.post("/api/v1/runner/runs/{run_id}/cases/{case_id}/result")
async def runner_case_result(
    payload: RunnerCaseResultRequest,
    context: Annotated[RunnerCaseContext, Depends(require_runner_context)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    if payload.source is None:
        raise HTTPException(status_code=422, detail="runner result source is required")
    try:
        context.validate_source(payload.source)
    except RunnerAuthorizationError:
        raise HTTPException(status_code=403, detail="runner source is outside case scope") from None
    if payload.failure_classification in ("python_assertion", "import_error", "python_exception"):
        if not payload.diagnostic_traceback or payload.timestamp_ms is None:
            raise HTTPException(status_code=422, detail="runner failure diagnostic is required")
    try:
        accepted = await runner_case_registry.record_result(context, payload)
    except RunnerAuthorizationError:
        raise HTTPException(status_code=403, detail="runner source is outside case scope") from None
    except RunnerProtocolConflictError:
        raise HTTPException(status_code=409, detail="runner result body conflict") from None
    if payload.diagnostic_traceback is not None:
        token = (authorization or "").partition(" ")[2]
        safe_traceback = str(redact_log_value(payload.diagnostic_traceback.replace(token, "<redacted>")))
        await observation_service.ingest(ObservationInput(
            observation_id=f"runner-diagnostic:{context.run_id}:{context.case_id}",
            kind="log", run_id=context.run_id, case_id=context.case_id,
            device_role="runner", node_id="beacon-server", lease_id="server-process",
            source="python_runner",
            target=ObservationTarget.model_validate({
                "sdk": "beacon_system", "interface": "runtime", "class": "PythonRunner", "function": "executeCase",
            }),
            payload={
                "failure_classification": payload.failure_classification,
                "source": payload.source.model_dump() if payload.source is not None else None,
                "traceback": safe_traceback,
            },
            timestamp_ms=payload.timestamp_ms if payload.timestamp_ms is not None else 0,
        ))
    return {"status": "accepted", "duplicate": not accepted}


app.include_router(runner_router)


@app.get("/api/v1/protected-smoke", response_model=ProtectedSmokeResponse, dependencies=[Depends(require_auth)])
def protected_smoke() -> ProtectedSmokeResponse:
    return ProtectedSmokeResponse(status="ok")


# SDK 专有测试端点由装配层声明，控制面只按声明挂载并统一附加鉴权。
def _mount_sdk_test_endpoints(fastapi_app: FastAPI) -> None:
    for endpoint in SDK_TEST_ENDPOINTS:
        fastapi_app.add_api_route(
            endpoint.path,
            endpoint.handler,
            methods=[endpoint.method],
            response_model=endpoint.response_model,
            dependencies=[Depends(require_auth)],
            name=endpoint.name,
        )


_mount_sdk_test_endpoints(app)


@app.get("/api/v1/devices", dependencies=[Depends(require_auth)])
async def list_devices(
    platform: str | None = None,
    group_id: str | None = None,
    tags: list[str] = Query(default_factory=list),
) -> dict:
    selector = DeviceSelector(platform=platform, group_id=group_id, tags=tags)
    sessions = await registry.list(selector)
    return {"devices": [session.device.model_dump() for session in sessions]}


@app.post("/api/v1/test-runs", response_model=TestRun, dependencies=[Depends(require_auth)])
async def create_test_run(payload: TestRunCreateRequest) -> TestRun:
    try:
        selector = DeviceSelector.model_validate(payload.selector)
        return await runner_supervisor.create_run(payload.case_ids, selector)
    except (TargetRunSelectionError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/test-runs/{run_id}/cancel", response_model=TestRun, dependencies=[Depends(require_auth)])
async def cancel_test_run(run_id: str) -> dict:
    try:
        run = await run_runtime.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        requested = await run_runtime.request_cancellation(run_id)
        assert requested is not None
        return requested.model_dump()
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None


@app.get("/api/v1/test-runs/{run_id}/report", dependencies=[Depends(require_auth)])
async def get_run_report(run_id: str) -> dict:
    try:
        report = (await report_generator.generate(run_id, "json")).model_dump()
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None
    await _index_report_log_artifacts(report)
    return report


@app.get("/api/v1/test-runs/{run_id}/junit", dependencies=[Depends(require_auth)])
async def get_run_junit(run_id: str) -> Response:
    try:
        junit = await report_generator.generate_junit(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found") from None
    return Response(content=junit, media_type="application/xml")


@app.post("/api/v1/logs/ingest", dependencies=[Depends(require_auth)])
async def ingest_logs(payload: dict) -> dict:
    node_id = payload.get("node_id")
    lease_id = payload.get("lease_id")
    events = payload.get("events", [])
    if not node_id or not lease_id or not isinstance(events, list):
        raise HTTPException(status_code=400, detail="invalid log ingest payload")
    stats = await log_collector.ingest(node_id, lease_id, events)
    return {"status": "ok", **stats}


@app.get("/api/v1/test-runs/{run_id}/logs", dependencies=[Depends(require_auth)])
async def get_run_logs(
    run_id: str,
    case_id: str | None = None,
    step_id: str | None = None,
    op_id: str | None = None,
    node_id: str | None = None,
    lease_id: str | None = None,
    start_ms: int = 0,
    end_ms: int = 2**63 - 1,
) -> dict:
    return {
        "events": await log_collector.query_by_trace(
            run_id,
            case_id,
            step_id,
            op_id,
            node_id,
            lease_id,
            start_ms=start_ms,
            end_ms=end_ms,
        )
    }


@app.get("/api/v1/devices/{node_id}/logs", dependencies=[Depends(require_auth)])
async def get_device_logs(node_id: str, start_ms: int = 0, end_ms: int = 2**63 - 1) -> dict:
    return {"events": await log_collector.query_window(node_id, start_ms, end_ms)}


@app.post("/api/v1/artifacts", dependencies=[Depends(require_auth)])
async def put_artifact(payload: dict) -> dict:
    artifact_id = await artifact_store.put(payload["node_id"], payload["artifact_type"], payload["path"], payload.get("metadata", {}))
    return {"artifact_id": artifact_id}


@app.get("/api/v1/artifacts", dependencies=[Depends(require_auth)])
async def query_artifacts(
    run_id: str | None = None,
    case_id: str | None = None,
    step_id: str | None = None,
    node_id: str | None = None,
    artifact_type: str | None = None,
) -> dict:
    return {
        "artifacts": await artifact_store.query(
            run_id=run_id,
            case_id=case_id,
            step_id=step_id,
            node_id=node_id,
            artifact_type=artifact_type,
        )
    }


@app.get("/api/v1/artifacts/{artifact_id}", dependencies=[Depends(require_auth)])
async def get_artifact(artifact_id: str) -> dict:
    try:
        return await artifact_store.get(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="artifact not found") from None


async def _index_report_log_artifacts(report: dict) -> None:
    run_id = report.get("run_id")
    if not isinstance(run_id, str):
        return
    for case_result in report.get("case_results", []):
        if not isinstance(case_result, dict):
            continue
        case_id = case_result.get("case_id")
        step_id = case_result.get("step_id")
        node_id = case_result.get("node_id") or ""
        if not isinstance(case_id, str) or not isinstance(step_id, str):
            continue
        for artifact_uri in case_result.get("log_artifacts", []):
            if not isinstance(artifact_uri, str) or not artifact_uri.startswith(f"artifact://logs/{run_id}/"):
                continue
            path = _report_log_artifact_path(artifact_uri)
            existing = await artifact_store.query(
                run_id=run_id,
                case_id=case_id,
                step_id=step_id,
                node_id=node_id,
                artifact_type="log",
            )
            if any(item.get("path") == path for item in existing):
                continue
            await artifact_store.put(
                node_id,
                "log",
                path,
                {"run_id": run_id, "case_id": case_id, "step_id": step_id},
            )


@app.post("/api/v1/test/faults/disconnect")
async def inject_disconnect_fault(payload: dict, _: None = Depends(require_auth)) -> dict:
    """test-mode 故障注入入口。

    该接口必须同时满足认证和环境变量开关，避免普通运行环境暴露测试能力。
    """
    if os.environ.get("BEACON_ENABLE_TEST_ENDPOINTS") != "true":
        raise HTTPException(status_code=404, detail="not found")
    node_id = payload.get("node_id")
    if node_id:
        await registry.remove(node_id)
        await run_runtime.fail_pending_for_device(node_id, "fault disconnect")
    return {"status": "ok"}


@app.websocket("/api/v1/agent/ws")
async def agent_websocket(websocket: WebSocket) -> None:
    """Agent WebSocket Gateway。

    只负责鉴权、消息分派和断连收尾；具体状态变化委托给 Phase 1 组件。
    """
    token = os.environ.get("BEACON_AUTH_TOKEN")
    provided = websocket.headers.get("authorization")
    query_token = websocket.query_params.get("token")
    if not token or (provided != f"Bearer {token}" and query_token != token):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            packet = await websocket.receive_json()
            response = await agent_gateway.handle_packet(websocket, packet)
            if response is not None:
                await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
    finally:
        # WebSocket 生命周期结束后必须统一走 disconnect 收尾 pending request。
        await session_manager.handle_disconnect(websocket)
