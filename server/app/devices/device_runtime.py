"""Server 设备注册和会话运行时。

`DeviceRegistry` 保存当前在线连接事实，支持按 platform/group/tag/node_id 筛选。
`SessionManager` 保存 WebSocket 到 node_id 的映射和可恢复 `SessionContext`。
两者分离是为了让断线清理在线连接时，不误删后续 reconnect 需要的上下文。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.common.config import CONFIG
from app.devices.device_models import Device, DeviceSelector, DeviceSession, SessionContext
from app.reporting.evidence_runtime import connection_failure_classification, now_ms
from app.common.errors import DeviceNotFoundError, SessionExpiredError, ValidationError
from app.common.interfaces import DeviceRegistryProtocol, SessionManagerProtocol


class JsonlDeviceSessionStore:
    """设备快照和可恢复 SessionContext 的 JSONL 存储。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    async def upsert_device(self, device: Device) -> None:
        self._append({"kind": "device", "op": "upsert", "device": device.model_dump()})

    async def remove_device(self, node_id: str) -> None:
        self._append({"kind": "device", "op": "remove", "node_id": node_id})

    async def upsert_context(self, context: SessionContext) -> None:
        self._append(
            {
                "kind": "context",
                "op": "upsert",
                "node_id": context.node_id,
                "device": context.device.model_dump() if context.device is not None else None,
                "callbacks": context.callbacks,
                "version": context.version,
            }
        )

    async def remove_context(self, node_id: str) -> None:
        self._append({"kind": "context", "op": "remove", "node_id": node_id})

    async def load_devices(self) -> list[Device]:
        latest: dict[str, Device | None] = {}
        for record, line in self._records():
            if record.get("kind") != "device":
                continue
            device_data = record.get("device")
            node_id = record.get("node_id")
            if not isinstance(node_id, str) and isinstance(device_data, dict):
                node_id = device_data.get("node_id")
            if not isinstance(node_id, str):
                continue
            if record.get("op") == "remove":
                latest[node_id] = None
            elif isinstance(record.get("device"), dict):
                try:
                    latest[node_id] = Device.model_validate(record["device"]).model_copy(update={"status": "offline"})
                except PydanticValidationError:
                    self._quarantine_bad_line(line)
            else:
                self._quarantine_bad_line(line)
        return [device for device in latest.values() if device is not None]

    async def load_contexts(self) -> list[SessionContext]:
        latest: dict[str, SessionContext | None] = {}
        for record, line in self._records():
            if record.get("kind") != "context":
                continue
            node_id = record.get("node_id")
            if not isinstance(node_id, str):
                continue
            if record.get("op") == "remove":
                latest[node_id] = None
                continue
            device_data = record.get("device")
            callbacks = record.get("callbacks", {})
            if not isinstance(callbacks, dict):
                self._quarantine_bad_line(line)
                continue
            try:
                device = (
                    Device.model_validate(device_data).model_copy(update={"status": "offline"})
                    if isinstance(device_data, dict)
                    else None
                )
                version = int(record.get("version", 1))
            except (PydanticValidationError, TypeError, ValueError):
                self._quarantine_bad_line(line)
                continue
            latest[node_id] = SessionContext(node_id=node_id, device=device, callbacks=callbacks, version=version)
        return [context for context in latest.values() if context is not None]

    def _append(self, record: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _records(self) -> list[tuple[dict[str, Any], str]]:
        if not self._path.exists():
            return []
        records = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                self._quarantine_bad_line(line)
                continue
            if not isinstance(record, dict):
                self._quarantine_bad_line(line)
                continue
            records.append((record, line))
        return records

    def _quarantine_bad_line(self, line: str) -> None:
        corrupt_path = self._path.with_suffix(self._path.suffix + ".corrupt")
        corrupt_path.parent.mkdir(parents=True, exist_ok=True)
        with corrupt_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")


class DeviceRegistry(DeviceRegistryProtocol):
    """持有当前在线设备池。

    本类只管理 DeviceSession 的注册、查询、筛选和移除。
    重连恢复依据由 SessionManager 的 SessionContext 单独持有。

    Implements DeviceRegistryProtocol for dependency inversion.
    """

    def __init__(self, store: JsonlDeviceSessionStore | None = None) -> None:
        self._sessions: dict[str, DeviceSession] = {}
        # Indexes for fast filtering
        self._by_platform: dict[str, set[str]] = {}  # platform -> set of node_ids
        self._by_group: dict[str, set[str]] = {}  # group_id -> set of node_ids
        self._by_tag: dict[str, set[str]] = {}  # tag -> set of node_ids
        self._lock = asyncio.Lock()
        self._store = store

    async def upsert(self, session: DeviceSession, *, persist: bool = True) -> DeviceSession | None:
        """注册或替换在线 session，并同步维护筛选索引。"""
        async with self._lock:
            node_id = session.device.node_id
            old = self._sessions.get(node_id)
            if persist and self._store is not None:
                await self._store.upsert_device(session.device)

            # Remove from old indexes if updating
            if old is not None:
                old_platform = old.device.platform
                old_group = old.device.group_id
                old_tags = old.device.tags

                if old_platform in self._by_platform:
                    self._by_platform[old_platform].discard(node_id)
                if old_group and old_group in self._by_group:
                    self._by_group[old_group].discard(node_id)
                for tag in old_tags:
                    if tag in self._by_tag:
                        self._by_tag[tag].discard(node_id)

            # 先移除旧索引再加入新索引，避免重复注册后 selector 命中过期 session。
            self._sessions[node_id] = session

            platform = session.device.platform
            if platform not in self._by_platform:
                self._by_platform[platform] = set()
            self._by_platform[platform].add(node_id)

            group_id = session.device.group_id
            if group_id:
                if group_id not in self._by_group:
                    self._by_group[group_id] = set()
                self._by_group[group_id].add(node_id)

            for tag in session.device.tags:
                if tag not in self._by_tag:
                    self._by_tag[tag] = set()
                self._by_tag[tag].add(node_id)
            return old

    async def get(self, node_id: str) -> DeviceSession | None:
        """按 node_id 读取当前在线 session。"""
        async with self._lock:
            return self._sessions.get(node_id)

    async def get_or_raise(self, node_id: str) -> DeviceSession:
        """按 node_id 读取在线 session，不存在时抛出结构化错误。"""
        session = await self.get(node_id)
        if session is None:
            raise DeviceNotFoundError(node_id)
        return session

    async def list(self, selector: DeviceSelector | None = None) -> list[DeviceSession]:
        """按 selector 列出在线 session。

        有 platform/group/node_id 条件时优先走索引；只有 tag 或空 selector 时才退回扫描。
        """
        if selector is None:
            async with self._lock:
                return list(self._sessions.values())

        if selector.node_id:
            async with self._lock:
                session = self._sessions.get(selector.node_id)
            if session is None:
                return []
            device = session.device
            required_tags = set(selector.tags)
            if selector.platform and device.platform != selector.platform:
                return []
            if selector.group_id and device.group_id != selector.group_id:
                return []
            if required_tags and not required_tags.issubset(set(device.tags)):
                return []
            return [session]

        # Use indexes to narrow down candidate set
        async with self._lock:
            # Start with the most selective index
            candidate_ids: set[str] | None = None

            # Platform filter (usually most selective)
            if selector.platform and selector.platform in self._by_platform:
                candidate_ids = self._by_platform[selector.platform].copy()

            # Group filter
            if selector.group_id and selector.group_id in self._by_group:
                group_ids = self._by_group[selector.group_id]
                if candidate_ids is None:
                    candidate_ids = group_ids.copy()
                else:
                    candidate_ids &= group_ids

            # If we have candidates from indexes, fetch sessions
            if candidate_ids is not None:
                # Filter by tags (need to check each candidate)
                required_tags = set(selector.tags)
                result = []
                for node_id in candidate_ids:
                    if node_id in self._sessions:
                        session = self._sessions[node_id]
                        # Check tags
                        if required_tags and not required_tags.issubset(set(session.device.tags)):
                            continue
                        result.append(session)
                return result

            # No selective indexes available, fall back to full scan
            sessions = list(self._sessions.values())

        # Apply filters without holding lock
        result = []
        required_tags = set(selector.tags)
        for session in sessions:
            device = session.device
            if selector.platform and device.platform != selector.platform:
                continue
            if selector.group_id and device.group_id != selector.group_id:
                continue
            if required_tags and not required_tags.issubset(set(device.tags)):
                continue
            result.append(session)
        return result

    async def remove(self, node_id: str) -> None:
        """移除在线 session，并清理所有反向索引。"""
        async with self._lock:
            session = self._sessions.get(node_id)
            if session is not None:
                if self._store is not None:
                    await self._store.remove_device(node_id)
                self._sessions.pop(node_id, None)

                # Remove from platform index
                platform = session.device.platform
                if platform in self._by_platform:
                    self._by_platform[platform].discard(node_id)

                # Remove from group index
                group_id = session.device.group_id
                if group_id and group_id in self._by_group:
                    self._by_group[group_id].discard(node_id)

                # Remove from tag indexes
                for tag in session.device.tags:
                    if tag in self._by_tag:
                        self._by_tag[tag].discard(node_id)

    async def load_from_store(self) -> None:
        """DeviceRegistry 只表示在线连接；离线快照不恢复为可执行 session。"""
        return


class SessionManager(SessionManagerProtocol):
    """维护 WebSocket 会话和可恢复上下文。

    DeviceRegistry 保存在线连接事实；SessionManager 保存 WebSocket 到 node_id
    的映射，以及 reconnect 需要的 SessionContext。

    Implements SessionManagerProtocol for dependency inversion.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        run_runtime: Any,
        store: JsonlDeviceSessionStore | None = None,
    ) -> None:
        from app.reporting.evidence_runtime import new_op_id

        self._registry = registry
        self._run_runtime = run_runtime
        self._contexts: dict[str, SessionContext] = {}
        self._websocket_nodes: dict[int, str] = {}
        self._websocket_leases: dict[int, str] = {}
        self._lock = asyncio.Lock()
        self._new_op_id = new_op_id
        self._store = store

    def _new_lease_id(self) -> str:
        return f"lease-{uuid.uuid4().hex}"

    async def handle_register(self, websocket: Any, packet: dict) -> dict:
        """处理 registerRequest 并返回 registerResponse。

        同 node_id 重复注册时，新连接生效，旧 pending request 进入终态。

        Raises:
            ValidationError: If required fields (node_id) are missing.
        """
        data = packet.get("data", {})
        node_id = data.get("node_id")
        if not node_id:
            raise ValidationError("node_id", "must be provided in registerRequest")

        device = Device(
            node_id=node_id,
            platform=data.get("platform", "unknown"),
            group_id=data.get("group_id"),
            tags=data.get("tags", []),
            capabilities=data.get("capabilities", []),
        )
        lease_id = self._new_lease_id()
        async with self._lock:
            self._websocket_nodes[id(websocket)] = node_id
            self._websocket_leases[id(websocket)] = lease_id
            context = self._contexts.setdefault(node_id, SessionContext(node_id=node_id))
            context.device = device
            if self._store is not None:
                await self._store.upsert_context(context)
        old = await self._registry.upsert(DeviceSession(device=device, websocket=websocket, lease_id=lease_id))
        if old is not None:
            await self._run_runtime.record_connection_event(
                "duplicate_register_replaced",
                node_id,
                lease_id=old.lease_id,
                reason="duplicate register",
                details={"new_lease_id": lease_id},
            )
            await self._run_runtime.fail_pending_for_device(
                node_id,
                "duplicate register",
                failure_classification=connection_failure_classification("stale_lease"),
            )
        await self._run_runtime.record_connection_event("registered", node_id, lease_id=lease_id)
        return self._response(
            "registerResponse",
            packet,
            {
                "code": 0,
                "message": "ok",
                "state": 1,
                "lease_id": lease_id,
                "server_protocol_version": CONFIG.server_protocol_version,
            },
        )

    async def handle_reconnect(self, websocket: Any, packet: dict) -> dict:
        """根据 SessionContext 判断 reconnectResponse.state。"""
        node_id = packet.get("data", {}).get("node_id", "")
        session: DeviceSession | None = None
        lease_id = self._new_lease_id()
        async with self._lock:
            context = self._contexts.get(node_id)
            state = 1 if context is not None and context.device is not None else 0
            if state and context is not None and context.device is not None:
                self._websocket_nodes[id(websocket)] = node_id
                self._websocket_leases[id(websocket)] = lease_id
                device = context.device.model_copy(update={"status": "online", "last_seen_ms": now_ms()})
                context.device = device
                session = DeviceSession(device=device, websocket=websocket, lease_id=lease_id)
                if self._store is not None:
                    await self._store.upsert_context(context)
        if session is not None:
            old = await self._registry.upsert(session)
            if old is not None:
                await self._run_runtime.record_connection_event(
                    "duplicate_register_replaced",
                    node_id,
                    lease_id=old.lease_id,
                    reason="reconnect",
                    details={"new_lease_id": lease_id},
                )
                await self._run_runtime.fail_pending_for_device(
                    node_id,
                    "reconnect",
                    failure_classification=connection_failure_classification("stale_lease"),
                )
            await self._run_runtime.record_connection_event("reconnected", node_id, lease_id=lease_id)
        elif node_id:
            await self._run_runtime.record_connection_event(
                "reconnect_requires_register",
                node_id,
                reason="missing session context",
            )
        data = {"code": 0, "message": "ok", "state": state, "server_protocol_version": CONFIG.server_protocol_version}
        if state:
            data["lease_id"] = lease_id
        return self._response("reconnectResponse", packet, data)

    async def handle_unregister(self, websocket: Any, packet: dict) -> dict:
        """处理 unregisterRequest。

        unregister 会删除可恢复上下文；普通 disconnect 只删除在线 session。
        """
        async with self._lock:
            mapped_node_id = self._websocket_nodes.pop(id(websocket), None)
            mapped_lease_id = self._websocket_leases.pop(id(websocket), None)
        node_id = packet.get("data", {}).get("node_id") or mapped_node_id
        if node_id:
            session = await self._registry.get(node_id)
            if session is not None and mapped_lease_id and session.lease_id != mapped_lease_id:
                await self._run_runtime.record_connection_event(
                    "stale_unregister_ignored",
                    node_id,
                    lease_id=session.lease_id,
                    reason="stale lease",
                    details={"stale_lease_id": mapped_lease_id},
                )
                return self._response("unregisterResponse", packet, {"code": 0, "message": "ok"})
            await self._registry.remove(node_id)
            await self._run_runtime.fail_pending_for_device(
                node_id,
                "unregister",
                failure_classification=connection_failure_classification("disconnect"),
            )
            await self._run_runtime.record_connection_event("unregistered", node_id, lease_id=mapped_lease_id or "", reason="unregister")
            async with self._lock:
                self._contexts.pop(node_id, None)
                if self._store is not None:
                    await self._store.remove_context(node_id)
        return self._response("unregisterResponse", packet, {"code": 0, "message": "ok"})

    async def handle_disconnect(self, websocket: Any) -> None:
        """处理 WebSocket 断开。

        disconnect 是该设备所有 pending request 的终态路径。
        """
        async with self._lock:
            node_id = self._websocket_nodes.pop(id(websocket), None)
            lease_id = self._websocket_leases.pop(id(websocket), None)
        if node_id:
            session = await self._registry.get(node_id)
            if session is not None and lease_id and session.lease_id != lease_id:
                await self._run_runtime.record_connection_event(
                    "stale_disconnect_ignored",
                    node_id,
                    lease_id=session.lease_id,
                    reason="stale lease",
                    details={"stale_lease_id": lease_id},
                )
                return
            await self._registry.remove(node_id)
            await self._run_runtime.fail_pending_for_device(
                node_id,
                "disconnect",
                failure_classification=connection_failure_classification("disconnect"),
            )
            await self._run_runtime.record_connection_event("disconnected", node_id, lease_id=lease_id or "", reason="disconnect")

    async def is_active_lease(self, node_id: str, lease_id: str) -> bool:
        """判断上行 packet 是否来自当前有效连接租约。"""
        session = await self._registry.get(node_id)
        return session is not None and session.lease_id == lease_id

    async def store_callback(self, node_id: str, callback_id: str, definition: dict) -> None:
        """把 callback 安装定义放入可恢复上下文。"""
        async with self._lock:
            context = self._contexts.setdefault(node_id, SessionContext(node_id=node_id))
            context.callbacks[callback_id] = definition
            if self._store is not None:
                await self._store.upsert_context(context)

    async def context(self, node_id: str) -> SessionContext | None:
        """读取设备的可恢复上下文。"""
        async with self._lock:
            return self._contexts.get(node_id)

    async def clear_context(self, node_id: str) -> None:
        """显式清理可恢复上下文。"""
        async with self._lock:
            self._contexts.pop(node_id, None)
            if self._store is not None:
                await self._store.remove_context(node_id)

    async def load_contexts_from_store(self) -> None:
        """恢复可重连 SessionContext；不创建 WebSocket 在线连接。"""
        if self._store is None:
            return
        async with self._lock:
            for context in await self._store.load_contexts():
                self._contexts[context.node_id] = context

    def _response(self, action: str, request: dict, data: dict) -> dict:
        return {
            "common": {
                "action": action,
                "op_id": request.get("common", {}).get("op_id", self._new_op_id()),
                "timestamp_ms": now_ms(),
            },
            "data": data,
        }
