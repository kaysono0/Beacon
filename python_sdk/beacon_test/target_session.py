"""Runner 注入的同步 Python 作者入口，按当前 run、case 和设备角色访问 Server。

call 等待即时调用结果；query/wait 读取独立 Observation。
Native callback 后续操作由 register_callback 安装，不能由一次 wait 代替。
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Generic, TypeVar
from uuid import uuid4

import httpx


T = TypeVar("T")
HTTP_GRACE_S = 2.0


class BeaconError(Exception):
    """目标运行时框架错误。"""


class AuthoringError(BeaconError):
    pass


class RunnerProtocolError(BeaconError):
    pass


class TransportError(BeaconError):
    pass


class ServerUnavailableError(TransportError):
    pass


class DispatchTimeoutError(TransportError):
    pass


class ResourceScopeError(BeaconError):
    pass


class ObservationTimeoutError(BeaconError):
    pass


@dataclass(frozen=True)
class ResourceRef:
    resource_id: str
    run_id: str
    case_id: str
    device_role: str
    resource_type: str


@dataclass(frozen=True)
class CallResult(Generic[T]):
    operation_id: str
    device_role: str
    node_id: str
    code: int
    message: str
    value: T | None
    resource: ResourceRef | None
    failure_classification: str | None
    started_at_ms: int
    finished_at_ms: int


class NativeCallError(BeaconError):
    def __init__(self, result: CallResult[Any]) -> None:
        self.result = result
        super().__init__(f"Native call failed: {result.code} {result.message}")


class UnsupportedCallError(NativeCallError):
    pass


@dataclass(frozen=True)
class ObservationRecord:
    cursor: int
    observation_id: str
    kind: str
    run_id: str
    case_id: str
    step_id: str | None
    operation_id: str | None
    device_role: str
    node_id: str
    lease_id: str
    source: str
    target: dict[str, Any]
    payload: dict[str, Any]
    callback_execution: dict[str, Any] | None
    timestamp_ms: int
    ingested_at_ms: int


class BeaconSession:
    """持有当前用例的 run/case、角色声明、认证信息和 HTTP client。

    作者通过本会话调用 Native 或观察事实；设备绑定与事实存储由 Server 管理。
    """

    def __init__(
        self,
        *,
        base_url: str,
        run_id: str,
        case_id: str,
        run_token: str,
        device_roles: set[str] | frozenset[str],
        source_path: str,
        source_function: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.run_id = run_id
        self.case_id = case_id
        self._token = run_token
        self._roles = frozenset(device_roles)
        self._source_path = source_path
        self._source_function = source_function
        self._client = http_client or httpx.Client(base_url=base_url)
        self._owns_client = http_client is None
        self._path = f"/api/v1/runner/runs/{run_id}/cases/{case_id}"

    def __enter__(self) -> BeaconSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """仅关闭本会话自行创建的 HTTP client；注入的 client 由调用方管理。"""
        if self._owns_client:
            self._client.close()

    def device(self, role: str) -> DeviceFacade:
        self._require_role(role)
        return DeviceFacade(self, role)

    def _require_role(self, role: str) -> None:
        if role not in self._roles:
            raise AuthoringError(f"undeclared device role: {role}")

    def _source(self) -> dict[str, Any]:
        frame = inspect.currentframe()
        try:
            while frame is not None:
                frame = frame.f_back
                if frame is None:
                    break
                if not frame.f_code.co_filename.startswith(__file__.rsplit("/", 1)[0] + "/"):
                    return {"path": self._source_path, "line": frame.f_lineno, "function": self._source_function}
        finally:
            del frame
        return {"path": self._source_path, "line": 1, "function": self._source_function}

    def _request(self, method: str, suffix: str, *, timeout_s: float, **kwargs: Any) -> Any:
        if timeout_s <= 0:
            raise AuthoringError("timeout_s must be positive")
        headers = {"Authorization": f"Bearer {self._token}"}
        headers.update(kwargs.pop("headers", {}))
        try:
            response = self._client.request(method, self._path + suffix, headers=headers, timeout=timeout_s + HTTP_GRACE_S, **kwargs)
        except httpx.TimeoutException as exc:
            raise DispatchTimeoutError("Runner HTTP request timed out") from exc
        except httpx.TransportError as exc:
            raise ServerUnavailableError("Runner Server unavailable") from exc
        if response.status_code == 408 and suffix == "/waits":
            raise ObservationTimeoutError("observation wait timed out")
        if response.status_code >= 400:
            raise RunnerProtocolError(f"Runner HTTP {response.status_code}: {response.text}")
        try:
            return response.json()
        except ValueError as exc:
            raise RunnerProtocolError("Runner returned invalid JSON") from exc

    def call(
        self,
        role: str,
        target: dict[str, Any],
        params: dict[str, Any],
        *,
        check: bool = True,
        timeout_s: float = 5.0,
        resource: ResourceRef | None = None,
        create_resource: bool = False,
    ) -> CallResult[Any]:
        """立即下发一次调用，并同步返回结果，不等待 SDK callback。

        默认非零 code 抛 NativeCallError（488 为 UnsupportedCallError）；
        check=False 返回非零结果供断言；本地角色/资源检查、HTTP 传输和协议错误仍抛异常。
        """
        self._require_role(role)
        if resource is not None and (resource.run_id, resource.case_id, resource.device_role) != (self.run_id, self.case_id, role):
            raise ResourceScopeError("resource belongs to another run, case or role")
        operation_id = str(uuid4())
        body = {
            "operation_id": operation_id,
            "device_role": role,
            "target": target,
            "params": params,
            "resource_ref": vars(resource) if resource else None,
            "create_resource": create_resource,
            "timeout_ms": max(1, round(timeout_s * 1000)),
            "source": self._source(),
        }
        data = self._request("POST", "/calls", timeout_s=timeout_s, json=body, headers={"Idempotency-Key": operation_id})
        try:
            if data["operation_id"] != operation_id or data["device_role"] != role:
                raise RunnerProtocolError("Runner call response identity mismatch")
            result = CallResult(
                operation_id=operation_id,
                device_role=role,
                node_id=data["node_id"],
                code=data["code"],
                message=data["message"],
                value=data["result"],
                resource=ResourceRef(**data["resource_ref"]) if data.get("resource_ref") else None,
                failure_classification=data.get("failure_classification"),
                started_at_ms=data["started_at_ms"],
                finished_at_ms=data["finished_at_ms"],
            )
        except (KeyError, TypeError) as exc:
            raise RunnerProtocolError("invalid Runner call response") from exc
        if check and result.code != 0:
            error = UnsupportedCallError if result.code == 488 else NativeCallError
            raise error(result)
        return result

    def register_callback(
        self,
        *,
        role: str,
        event_target: dict[str, Any],
        calls: list[dict[str, Any]],
        repeat: int = 1,
        check: bool = True,
        timeout_s: float = 5.0,
    ) -> CallResult[None]:
        """安装 SDK callback 匹配后由 Agent 执行的 Native 操作链。

        返回值仅表示安装结果；实际执行结果见 Observation.callback_execution。
        repeat 是匹配触发次数，默认一次；-1 持续匹配直到 Agent reset 或清空注册。
        仅关闭 Server case 作用域不会撤销 Native 注册，清理由 Supervisor 的 reset 编排负责。
        check=False 仅关闭安装结果的非零 code 检查，其他错误仍抛异常。
        """
        self._require_role(role)
        if repeat != -1 and repeat < 1:
            raise AuthoringError("repeat must be -1 or >= 1")
        if not calls:
            raise AuthoringError("callback calls must be non-empty")
        registration_id = str(uuid4())
        body = {
            "registration_id": registration_id,
            "device_role": role,
            "event_target": event_target,
            "calls": calls,
            "repeat": repeat,
            "timeout_ms": max(1, round(timeout_s * 1000)),
            "source": self._source(),
        }
        data = self._request(
            "POST", "/callbacks", timeout_s=timeout_s, json=body, headers={"Idempotency-Key": registration_id}
        )
        try:
            if data["registration_id"] != registration_id or data["device_role"] != role:
                raise RunnerProtocolError("Runner callback response identity mismatch")
            result = CallResult[None](
                operation_id=registration_id,
                device_role=role,
                node_id=data["node_id"],
                code=data["code"],
                message=data["message"],
                value=None,
                resource=None,
                failure_classification=None,
                started_at_ms=data["started_at_ms"],
                finished_at_ms=data["finished_at_ms"],
            )
        except (KeyError, TypeError) as exc:
            raise RunnerProtocolError("invalid Runner callback response") from exc
        if check and result.code != 0:
            raise NativeCallError(result)
        return result

    def query_observations(
        self, *, role: str, kind: str, target: dict[str, Any], match: dict[str, Any] | None = None, after_cursor: int = 0
    ) -> list[ObservationRecord]:
        """返回当前作用域内已保存的匹配事实，无匹配时返回空列表。

        after_cursor 只保留 cursor 更大的事实；查询不会等待新事实或消费已有事实。
        """
        self._require_role(role)
        if after_cursor < 0:
            raise AuthoringError("after_cursor must be non-negative")
        params = {"device_role": role, "kind": kind, **_target_params(target), "match": json.dumps(match or {}), "after_cursor": after_cursor}
        data = self._request("GET", "/observations", timeout_s=5.0, params=params)
        try:
            return [_observation(item) for item in data]
        except (KeyError, TypeError) as exc:
            raise RunnerProtocolError("invalid Runner observations response") from exc

    def wait_observation(
        self,
        *,
        role: str,
        kind: str,
        target: dict[str, Any],
        match: dict[str, Any] | None = None,
        after_cursor: int | None = None,
        timeout_s: float = 5.0,
    ) -> ObservationRecord:
        """同步等到一条匹配事实；默认可命中已有事实。

        after_cursor 只接受 cursor 更大的事实，不建立事实与某次 call 的因果关系。
        Server 等待到期抛 ObservationTimeoutError，HTTP 请求超时抛 DispatchTimeoutError。
        """
        self._require_role(role)
        if after_cursor is not None and after_cursor < 0:
            raise AuthoringError("after_cursor must be non-negative")
        wait_id = str(uuid4())
        body = {
            "wait_id": wait_id,
            "device_role": role,
            "kind": kind,
            "target": target,
            "match": match or {},
            "after_cursor": after_cursor,
            "timeout_ms": max(1, round(timeout_s * 1000)),
            "source": self._source(),
        }
        data = self._request("POST", "/waits", timeout_s=timeout_s, json=body, headers={"Idempotency-Key": wait_id})
        try:
            return _observation(data)
        except (KeyError, TypeError) as exc:
            raise RunnerProtocolError("invalid Runner wait response") from exc


class DeviceFacade:
    """持有会话和设备角色，按 SDK 名称创建生成的 typed facade。

    本类不持有 Native SDK 实例，设备选择与 lease 校验由 Server 完成。
    """

    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def __getattr__(self, name: str) -> Any:
        from .generated import FACADES

        sdk = "agora_rtc" if name == "agora" else name
        if sdk not in FACADES:
            raise AttributeError(name)
        return FACADES[sdk](self._session, self._role)


class ObservationHandle:
    """持有会话、角色和 target，供 generated facade 查询或等待事实。

    作者侧 callback 是 event 的别名；本句柄不安装 Native callback 后续操作。
    """

    def __init__(self, session: BeaconSession, role: str, kind: str, target: dict[str, Any]) -> None:
        self._session = session
        self._role = role
        self._kind = "event" if kind == "callback" else kind
        self._target = target

    def query(self, *, match: dict[str, Any] | None = None, after_cursor: int = 0) -> list[ObservationRecord]:
        return self._session.query_observations(role=self._role, kind=self._kind, target=self._target, match=match, after_cursor=after_cursor)

    def wait(self, *, match: dict[str, Any] | None = None, after_cursor: int | None = None, timeout_s: float = 5.0) -> ObservationRecord:
        return self._session.wait_observation(role=self._role, kind=self._kind, target=self._target, match=match, after_cursor=after_cursor, timeout_s=timeout_s)


def _target_params(target: dict[str, Any]) -> dict[str, Any]:
    params = {"class": target.get("class_name"), "sdk": target["sdk"], "interface": target["interface"], "function": target.get("function"), "name": target.get("name")}
    return {key: value for key, value in params.items() if value is not None}


def _observation(data: dict[str, Any]) -> ObservationRecord:
    return ObservationRecord(
        cursor=data["cursor"], observation_id=data["observation_id"], kind=data["kind"],
        run_id=data["run_id"], case_id=data["case_id"], step_id=data.get("step_id"), operation_id=data.get("operation_id"),
        device_role=data["device_role"], node_id=data["node_id"], lease_id=data["lease_id"], source=data["source"],
        target=data["target"], payload=data["payload"], callback_execution=data.get("callback_execution"),
        timestamp_ms=data["timestamp_ms"], ingested_at_ms=data["ingested_at_ms"],
    )
