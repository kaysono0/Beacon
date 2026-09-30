"""Runner 单次 Native 调用的鉴权后执行边界。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from typing import Any

from app.api.api_contracts import (
    ResourceReference,
    RunnerCallRequest,
    RunnerCallResponse,
    RunnerCallbackRegistrationRequest,
    RunnerCallbackRegistrationResponse,
)
from app.reporting.evidence_runtime import now_ms
from app.common.errors import RunStateTransitionError
from app.common.interfaces import CommandDispatcherProtocol
from app.observations.observation_models import ObservationInput
from app.observations.observation_service import ObservationService
from app.runs.python_native_runtime import RuntimeParamResolver, decode_response_result
from app.common.redaction import redact_log_value
from app.runs.run_runtime import ServerRunRuntime
from app.runs.runner_case_registry import RunnerAuthorizationError, RunnerCaseContext
from app.sdk.sdk_registry import SDKRegistry


class RunCallConflictError(ValueError):
    """同一 operation ID 对应不同请求体。"""


class RunCallService:
    """验证后只调度一次，重复请求共享同一个执行任务。"""

    def __init__(
        self,
        dispatcher: CommandDispatcherProtocol,
        sdk_registry: SDKRegistry,
        param_resolver: RuntimeParamResolver,
        run_runtime: ServerRunRuntime,
        observation_service: ObservationService,
    ) -> None:
        self._dispatcher = dispatcher
        self._sdk_registry = sdk_registry
        self._param_resolver = param_resolver
        self._run_runtime = run_runtime
        self._observations = observation_service
        self._operations: dict[tuple[str, str, str], tuple[str, asyncio.Task[RunnerCallResponse]]] = {}
        self._registrations: dict[tuple[str, str, str], tuple[str, asyncio.Task[RunnerCallbackRegistrationResponse]]] = {}
        self._resources: dict[str, tuple[RunnerCaseContext, ResourceReference, str]] = {}
        self._closed_cases: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def execute(self, context: RunnerCaseContext, request: RunnerCallRequest) -> RunnerCallResponse:
        """先校验 scope，再按 operation ID 幂等执行或等待原任务。"""

        context.validate_source(request.source)
        try:
            binding = context.binding(request.device_role)
        except KeyError:
            raise RunnerAuthorizationError("role_scope_mismatch") from None
        if request.resource_ref is not None:
            reference = request.resource_ref
            if (reference.run_id, reference.case_id, reference.device_role) != (
                context.run_id,
                context.case_id,
                request.device_role,
            ):
                raise RunnerAuthorizationError("resource_scope_mismatch")
            issued = self._resources.get(reference.resource_id)
            if issued is None or issued[0] is not context or issued[1] != reference:
                raise RunnerAuthorizationError("resource_not_issued")
            target_type = self._sdk_registry.resource_type_for_target(
                request.target.model_dump(mode="python", exclude_none=True)
            )
            if target_type != reference.resource_type:
                raise RunnerAuthorizationError("resource_type_mismatch")
        body = json.dumps(
            request.model_dump(mode="json", by_alias=True, exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        key = (context.run_id, context.case_id, request.operation_id)
        async with self._lock:
            if (context.run_id, context.case_id) in self._closed_cases:
                raise RunnerAuthorizationError("case_scope_closed")
            existing = self._operations.get(key)
            if existing is not None:
                if existing[0] != body:
                    raise RunCallConflictError("operation body conflict")
                task = existing[1]
            else:
                task = asyncio.create_task(self._execute_once(context, request, binding.node_id, binding.lease_id))
                self._operations[key] = (body, task)
        try:
            return await asyncio.shield(task)
        except RunStateTransitionError:
            async with self._lock:
                if self._operations.get(key, (None, None))[1] is task:
                    self._operations.pop(key)
            raise

    async def register_callback(
        self, context: RunnerCaseContext, request: RunnerCallbackRegistrationRequest
    ) -> RunnerCallbackRegistrationResponse:
        """按注册 ID 只安装一次回调触发的 Native 操作。"""
        context.validate_source(request.source)
        try:
            binding = context.binding(request.device_role)
        except KeyError:
            raise RunnerAuthorizationError("role_scope_mismatch") from None
        body = json.dumps(request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
        key = (context.run_id, context.case_id, request.registration_id)
        async with self._lock:
            if (context.run_id, context.case_id) in self._closed_cases:
                raise RunnerAuthorizationError("case_scope_closed")
            existing = self._registrations.get(key)
            if existing is not None:
                if existing[0] != body:
                    raise RunCallConflictError("callback registration body conflict")
                task = existing[1]
            else:
                task = asyncio.create_task(self._register_callback_once(context, request, binding.node_id, binding.lease_id))
                self._registrations[key] = (body, task)
        return await asyncio.shield(task)

    async def _register_callback_once(
        self,
        context: RunnerCaseContext,
        request: RunnerCallbackRegistrationRequest,
        node_id: str,
        lease_id: str,
    ) -> RunnerCallbackRegistrationResponse:
        started_at_ms = now_ms()
        await self._run_runtime.reserve_call(context.run_id)
        try:
            event_target = request.event_target.model_dump(mode="python", exclude_none=True)
            error = self._sdk_registry.observation_match_error("event", event_target, {})
            calls: list[dict[str, Any]] = []
            if error is None:
                for item in request.calls:
                    target = item.target.model_dump(mode="python", exclude_none=True)
                    try:
                        params = self._param_resolver.resolve(item.params)
                        validation_error = self._sdk_registry.validate_invoke(target, params)
                    except (ValueError, KeyError) as exc:
                        validation_error = {"message": type(exc).__name__}
                        params = {}
                    if validation_error is not None:
                        error = str(validation_error["message"])
                        break
                    calls.append({"target": target, "params": params})
            if error is None:
                packet = await self._dispatcher.install_protocol_callback(
                    node_id,
                    [{"event_target": event_target, "repeat": request.repeat, "call_elements": calls}],
                    request.registration_id,
                    request.timeout_ms,
                    expected_lease_id=lease_id,
                )
                data = packet.get("data", {})
                if packet.get("common", {}).get("op_id") != request.registration_id:
                    data = {"code": 502, "message": "callback response registration id mismatch"}
                code = int(data.get("code", 502))
                message = str(data.get("message", "callback registration failed"))
            else:
                code, message = 422, error
            finished_at_ms = now_ms()
            response = RunnerCallbackRegistrationResponse(
                registration_id=request.registration_id,
                device_role=request.device_role,
                node_id=node_id,
                code=code,
                message=str(redact_log_value(message)),
                started_at_ms=started_at_ms,
                finished_at_ms=finished_at_ms,
            )
            observation_id = hashlib.sha256(
                json.dumps([context.case_id, request.registration_id], separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            await self._observations.ingest(
                ObservationInput.model_validate(
                    {
                        "observation_id": "callback-registration:" + observation_id,
                        "kind": "operation",
                        "run_id": context.run_id,
                        "case_id": context.case_id,
                        "operation_id": request.registration_id,
                        "device_role": request.device_role,
                        "node_id": node_id,
                        "lease_id": lease_id,
                        "source": "run_call_service",
                        "target": request.event_target.model_dump(mode="python", by_alias=True, exclude_none=True),
                        "payload": {
                            "operation_type": "callback_registration",
                            "request_id": request.registration_id,
                            "outcome": "succeeded" if code == 0 else "failed",
                            "code": code,
                            "message": response.message,
                            "source": request.source.model_dump(mode="python"),
                            "started_at_ms": started_at_ms,
                            "finished_at_ms": finished_at_ms,
                            "duration_ms": max(0, finished_at_ms - started_at_ms),
                        },
                        "timestamp_ms": finished_at_ms,
                    }
                )
            )
            return response
        finally:
            await self._run_runtime.release_call(context.run_id)

    async def finish_case(self, context: RunnerCaseContext) -> None:
        """关闭 case admission，等待已接纳的调用写完事实，再丢弃映射。"""

        scope = (context.run_id, context.case_id)
        async with self._lock:
            self._closed_cases.add(scope)
            tasks: list[asyncio.Task[Any]] = [task for key, (_, task) in self._operations.items() if key[:2] == scope]
            tasks.extend(task for key, (_, task) in self._registrations.items() if key[:2] == scope)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            for key in [key for key in self._operations if key[:2] == scope]:
                del self._operations[key]
            for key in [key for key in self._registrations if key[:2] == scope]:
                del self._registrations[key]
            for resource_id, (owner, _, _) in list(self._resources.items()):
                if owner is context:
                    del self._resources[resource_id]

    async def _execute_once(
        self,
        context: RunnerCaseContext,
        request: RunnerCallRequest,
        node_id: str,
        lease_id: str,
    ) -> RunnerCallResponse:
        """依次校验、下发、整理响应和写入事实；整个过程占用同一个 run 调用名额。"""
        started_at_ms = now_ms()
        await self._run_runtime.reserve_call(context.run_id)
        try:
            call, validation_error, resource_type = self._prepare_native_call(context, request)
            created_resource_id = call.get("store_as")
            if validation_error is None:
                data, result = await self._dispatch_native_call(request, node_id, lease_id, call)
            else:
                data, result = validation_error, None
            response = self._build_call_response(
                context, request, node_id, data, result, resource_type, created_resource_id, started_at_ms
            )
            await self._record_call_observation(context, request, lease_id, response, code=data.get("code", 0))
            # 事实写入成功后才发布资源映射；后续调用不能使用尚未完成记录的资源。
            if response.resource_ref is not None and created_resource_id is not None:
                self._resources[created_resource_id] = (context, response.resource_ref, created_resource_id)
            return response
        finally:
            await self._run_runtime.release_call(context.run_id)

    def _prepare_native_call(
        self, context: RunnerCaseContext, request: RunnerCallRequest
    ) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
        """返回 Native 调用、校验错误和资源类型；校验失败时不构造下发内容。"""
        target = request.target.model_dump(mode="python", exclude_none=True)
        native_extra: dict[str, Any] = {}
        try:
            params = self._param_resolver.resolve(request.params)
            extra_candidate = params.pop("_extra", None)
            if extra_candidate is not None:
                if not isinstance(extra_candidate, dict) or {"run_id", "case_id", "device_role"} & extra_candidate.keys():
                    raise ValueError("invalid native extra")
                native_extra = extra_candidate
            validation_error = self._sdk_registry.validate_invoke(target, params, native_extra)
        except (ValueError, KeyError) as error:
            validation_error = {"code": 422, "message": type(error).__name__, "failure_classification": {"category": "validation"}}
            params = {}
        resource_type = self._sdk_registry.resource_type_for_target(target) if request.create_resource else None
        if request.create_resource and resource_type is None:
            validation_error = {"code": 422, "message": "target cannot create resource", "failure_classification": {"category": "validation"}}
        if validation_error is not None:
            return {}, validation_error, resource_type
        created_resource_id = secrets.token_urlsafe(32) if request.create_resource else None
        call: dict[str, Any] = {
            "target": target,
            "params": params,
            "extra": {**native_extra, "run_id": context.run_id, "case_id": context.case_id, "device_role": request.device_role},
        }
        if request.resource_ref is not None:
            call["resource_ref"] = self._resources[request.resource_ref.resource_id][2]
        if created_resource_id is not None:
            call["store_as"] = created_resource_id
        return call, None, resource_type

    async def _dispatch_native_call(
        self, request: RunnerCallRequest, node_id: str, lease_id: str, call: dict[str, Any]
    ) -> tuple[dict[str, Any], Any]:
        """只下发一次；响应身份错误和传输异常都转换为可记录的调用失败。"""
        try:
            packet = await self._dispatcher.send_protocol_invoke(
                node_id,
                [call],
                request.operation_id,
                request.timeout_ms,
                expected_lease_id=lease_id,
            )
            data = packet.get("data", {})
            if packet.get("common", {}).get("op_id") != request.operation_id:
                data = {"code": 502, "message": "invoke response operation id mismatch", "failure_classification": {"category": "response_id_mismatch"}}
            result = decode_response_result(packet) if data.get("code", 0) == 0 else None
        except (OSError, TimeoutError):
            data = {"code": 502, "message": "invoke transport failure", "failure_classification": {"category": "transport_failure"}}
            result = None
        return data, result

    def _build_call_response(
        self,
        context: RunnerCaseContext,
        request: RunnerCallRequest,
        node_id: str,
        data: dict[str, Any],
        result: Any,
        resource_type: str | None,
        created_resource_id: str | None,
        started_at_ms: int,
    ) -> RunnerCallResponse:
        """整理脱敏结果与失败分类；仅成功的资源创建调用返回 Server 资源引用。"""
        code = data.get("code", 0)
        classification = data.get("failure_classification")
        safe_message = str(redact_log_value(str(data.get("message", "ok"))))
        safe_classification = redact_log_value(classification) if isinstance(classification, dict) else None
        category = safe_classification.get("category") if isinstance(safe_classification, dict) else None
        if category is None:
            category = {401: "sdk_error", 402: "environment", 404: "runtime_dependency", 488: "unsupported"}.get(code)
        finished_at_ms = now_ms()
        issued_reference = None
        if code == 0 and created_resource_id is not None and resource_type is not None:
            issued_reference = ResourceReference(
                resource_id=created_resource_id,
                run_id=context.run_id,
                case_id=context.case_id,
                device_role=request.device_role,
                resource_type=resource_type,
            )
        return RunnerCallResponse(
            operation_id=request.operation_id,
            device_role=request.device_role,
            node_id=node_id,
            code=code,
            message=safe_message,
            result=result,
            resource_ref=issued_reference,
            failure_classification=category,
            started_at_ms=started_at_ms,
            finished_at_ms=finished_at_ms,
        )

    async def _record_call_observation(
        self, context: RunnerCaseContext, request: RunnerCallRequest, lease_id: str, response: RunnerCallResponse, *, code: Any
    ) -> None:
        """记录本次 call 的 operation 事实，不把独立 callback 归因到该调用。"""
        # 保留原始 code；HTTP 响应模型的类型转换不能把异常 Native 响应提升为成功事实。
        await self._observations.ingest(
            ObservationInput.model_validate(
                {
                    "observation_id": "call:" + hashlib.sha256(
                        json.dumps([context.case_id, request.operation_id], separators=(",", ":")).encode("utf-8")
                    ).hexdigest(),
                    "kind": "operation",
                    "run_id": context.run_id,
                    "case_id": context.case_id,
                    "operation_id": request.operation_id,
                    "device_role": request.device_role,
                    "node_id": response.node_id,
                    "lease_id": lease_id,
                    "source": "run_call_service",
                    "target": request.target.model_dump(mode="python", by_alias=True, exclude_none=True),
                    "payload": {
                        "operation_type": "call",
                        "request_id": request.operation_id,
                        "outcome": "succeeded" if code == 0 else "failed",
                        "code": code,
                        "message": response.message,
                        "failure_classification": response.failure_classification,
                        "source": request.source.model_dump(mode="python"),
                        "started_at_ms": response.started_at_ms,
                        "finished_at_ms": response.finished_at_ms,
                        "duration_ms": max(0, response.finished_at_ms - response.started_at_ms),
                    },
                    "timestamp_ms": response.finished_at_ms,
                }
            )
        )
