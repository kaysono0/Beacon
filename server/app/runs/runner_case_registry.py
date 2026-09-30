"""Runner case catalog、不可变执行上下文和短期凭证。

`RunnerCaseRegistry` 只保存受信任源码发现出的 case metadata、role binding
快照和 token digest。明文 token 只返回给后续 Runner Supervisor，不进入日志、
报告或 HTTP 响应。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from app.api.api_contracts import RunnerCaseResultRequest, RunnerSourceLocation, RunnerStartedRequest
from app.devices.device_models import DeviceSession
from app.runs.python_native_models import NativeTestCase


class RunnerAuthorizationError(PermissionError):
    """Runner credential 无效、越权、过期或已撤销。"""


class RunnerRegistrationError(ValueError):
    """Runner case context 不能安全登记。"""


class RunnerProtocolConflictError(ValueError):
    """started/result 的同一 scope 重放了不同 body。"""


@dataclass(frozen=True)
class RunnerCaseMetadata:
    """只从受信任 case catalog 获得的 Runner 加载信息。"""

    case_id: str
    name: str
    platform: str
    device_roles: tuple[str, ...]
    source_path: str
    function_name: str
    suite: str
    implementation_status: str

    @classmethod
    def from_native_case(cls, case: NativeTestCase) -> RunnerCaseMetadata:
        """去掉函数对象，只保留 Runner 可以加载的固定 metadata。"""

        return cls(
            case_id=case.case_id,
            name=case.name,
            platform=case.platform,
            device_roles=tuple(case.devices),
            source_path=case.source_path,
            function_name=case.function_name,
            suite=case.suite,
            implementation_status=case.implementation_status,
        )


@dataclass(frozen=True)
class RunnerRoleBinding:
    """某个声明角色在 case 启动时固化的 node/lease。"""

    device_role: str
    node_id: str
    lease_id: str

    @classmethod
    def from_session(cls, device_role: str, session: DeviceSession) -> RunnerRoleBinding:
        """从当前在线 session 复制值，不保留可变 registry 引用。"""

        return cls(device_role=device_role, node_id=session.device.node_id, lease_id=session.lease_id)


class RunnerCaseContext:
    """单个 case 的不可变 scope。"""

    def __init__(
        self,
        *,
        run_id: str,
        metadata: RunnerCaseMetadata,
        bindings: Mapping[str, RunnerRoleBinding],
        case_timeout_ms: int,
        token_expires_at_ms: int,
    ) -> None:
        if not run_id:
            raise ValueError("run_id must be non-empty")
        if case_timeout_ms < 1 or token_expires_at_ms < 0:
            raise ValueError("case timeout and token expiry must be positive")
        copied = dict(bindings)
        if set(copied) != set(metadata.device_roles):
            raise ValueError("binding roles must exactly match case metadata")
        if any(role != binding.device_role for role, binding in copied.items()):
            raise ValueError("binding role key must match binding value")
        self.run_id = run_id
        self.metadata = metadata
        self.bindings: Mapping[str, RunnerRoleBinding] = MappingProxyType(copied)
        self.case_timeout_ms = case_timeout_ms
        self.token_expires_at_ms = token_expires_at_ms

    @property
    def case_id(self) -> str:
        return self.metadata.case_id

    def binding(self, device_role: str) -> RunnerRoleBinding:
        """返回已固化 role binding；未声明角色 fail closed。"""

        return self.bindings[device_role]

    def validate_source(self, source: RunnerSourceLocation) -> None:
        """拒绝 Runner 用 body 覆盖 Catalog 固定的源码入口。"""

        if (source.path, source.function) != (self.metadata.source_path, self.metadata.function_name):
            raise RunnerAuthorizationError("source_scope_mismatch")

@dataclass(frozen=True)
class RunnerCredential:
    """只交给 Runner Supervisor 的明文 credential。"""

    token: str = field(repr=False)
    expires_at_ms: int


@dataclass
class _Registration:
    context: RunnerCaseContext
    token_digest: bytes
    revoked: bool = False
    started_fingerprint: str | None = None
    result_fingerprint: str | None = None
    started_request: RunnerStartedRequest | None = None
    result_request: RunnerCaseResultRequest | None = None


class RunnerCaseRegistry:
    """共享 case catalog、scope authorization 和 credential lifecycle。"""

    def __init__(
        self,
        cases: list[NativeTestCase],
        *,
        now_ms: Callable[[], int],
        token_factory: Callable[[], bytes] | None = None,
    ) -> None:
        metadata = [RunnerCaseMetadata.from_native_case(case) for case in cases]
        if len({item.case_id for item in metadata}) != len(metadata):
            raise RunnerRegistrationError("duplicate case metadata")
        self._catalog = {item.case_id: item for item in metadata}
        self._now_ms = now_ms
        self._token_factory = token_factory or (lambda: secrets.token_bytes(32))
        self._registrations: dict[tuple[str, str], _Registration] = {}
        self._lock = asyncio.Lock()

    def require_metadata(self, case_id: str) -> RunnerCaseMetadata:
        """只按 case ID 返回 catalog 固定 metadata。"""

        return self._catalog[case_id]

    async def register(self, context: RunnerCaseContext) -> RunnerCredential:
        """登记 case scope，Server 只保留 256-bit opaque token 的 digest。"""

        if self.require_metadata(context.case_id) != context.metadata:
            raise RunnerRegistrationError("context metadata does not match catalog")
        if context.token_expires_at_ms <= self._now_ms():
            raise RunnerRegistrationError("token expiry must be in the future")
        token_bytes = self._token_factory()
        if len(token_bytes) != 32:
            raise RunnerRegistrationError("runner token must contain 256 bits")
        token = base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode("ascii")
        registration = _Registration(context=context, token_digest=_token_digest(token))
        scope = (context.run_id, context.case_id)
        async with self._lock:
            if scope in self._registrations:
                raise RunnerRegistrationError("runner case scope is already registered")
            self._registrations[scope] = registration
        return RunnerCredential(token=token, expires_at_ms=context.token_expires_at_ms)

    async def authorize(self, token: str, run_id: str, case_id: str) -> RunnerCaseContext:
        """校验 token digest、path scope、expiry 和 revoke 状态。"""

        digest = _token_digest(token)
        async with self._lock:
            matched = next(
                (
                    registration
                    for registration in self._registrations.values()
                    if hmac.compare_digest(registration.token_digest, digest)
                ),
                None,
            )
            if matched is None:
                raise RunnerAuthorizationError("invalid_token")
            if matched.revoked:
                raise RunnerAuthorizationError("revoked_token")
            if matched.context.token_expires_at_ms <= self._now_ms():
                raise RunnerAuthorizationError("expired_token")
            if (matched.context.run_id, matched.context.case_id) != (run_id, case_id):
                raise RunnerAuthorizationError("scope_mismatch")
            return matched.context

    async def finish(self, run_id: str, case_id: str) -> None:
        """幂等撤销 case credential，保留 digest 以区分 revoked。"""

        async with self._lock:
            registration = self._registrations.get((run_id, case_id))
            if registration is not None:
                registration.revoked = True

    async def record_started(self, context: RunnerCaseContext, request: RunnerStartedRequest) -> bool:
        """幂等保存 Runner handshake；不同 body fail closed。"""

        return await self._record_protocol_body(context, "started_fingerprint", request)

    async def record_result(self, context: RunnerCaseContext, request: RunnerCaseResultRequest) -> bool:
        """幂等保存 Runner 候选结果；source 必须匹配 Catalog。"""

        if request.source is not None:
            context.validate_source(request.source)
        return await self._record_protocol_body(context, "result_fingerprint", request)

    async def protocol_snapshot(
        self, context: RunnerCaseContext,
    ) -> tuple[RunnerStartedRequest | None, RunnerCaseResultRequest | None]:
        """仅供 Supervisor 读取候选协议事实，不授予 Runner 写终态权限。"""

        async with self._lock:
            registration = self._registrations.get((context.run_id, context.case_id))
            if registration is None or registration.context is not context:
                raise RunnerAuthorizationError("unregistered_context")
            started = registration.started_request
            result = registration.result_request
            return (
                started.model_copy(deep=True) if started is not None else None,
                result.model_copy(deep=True) if result is not None else None,
            )

    async def _record_protocol_body(
        self,
        context: RunnerCaseContext,
        field_name: str,
        request: RunnerStartedRequest | RunnerCaseResultRequest,
    ) -> bool:
        fingerprint = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
        async with self._lock:
            registration = self._registrations.get((context.run_id, context.case_id))
            if registration is None or registration.context is not context:
                raise RunnerAuthorizationError("unregistered_context")
            existing = getattr(registration, field_name)
            if existing is None:
                setattr(registration, field_name, fingerprint)
                if isinstance(request, RunnerStartedRequest):
                    registration.started_request = request.model_copy(deep=True)
                else:
                    registration.result_request = request.model_copy(deep=True)
                return True
            if existing != fingerprint:
                raise RunnerProtocolConflictError(f"{field_name} body conflict")
            return False


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()
