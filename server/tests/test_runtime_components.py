"""Server 运行时组件行为回归。

本文件覆盖 IT-SRV-REG-*、IT-SRV-CMD-*、IT-SRV-CBEVT-*、
IT-SRV-CTX/REC-*、IT-SRV-RUN-* 和 IT-SRV-MODEL-* 的核心行为。
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.reporting.evidence_runtime import AckTracker, Evidence, EvidenceStore, ResultCollector, canonical_target, create_error_packet
from app.devices.dispatch_runtime import CommandDispatcher, PacketBuilder
from app.devices.device_runtime import DeviceRegistry, SessionManager
from app.devices.device_models import DeviceSelector, SessionContext
from app.reporting.server_log_runtime import JsonlServerLogStore, ServerLogCollector
from app.runs.run_runtime import ServerRunRuntime
from app.devices.connection_diagnostics import ConnectionEventStore
from app.runs.test_models import StepResult, TestCase, TestRun, TestStep
from app.api.gateway import AgentGateway


@pytest.mark.anyio
async def test_IT_SRV_MODEL_runtime_components_share_registration():
    """设备、会话与结果组件共享注册事实。"""
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    websocket = FakeWebSocket()

    response = await manager.handle_register(websocket, register_packet("mac-entry"))

    assert response["common"]["action"] == "registerResponse"
    session = await registry.get("mac-entry")
    assert session is not None
    assert canonical_target({"sdk": "mock", "class_name": "Mock", "function": "join"}) == {
        "sdk": "mock",
        "class_name": "Mock",
        "function": "join",
    }


def target(function: str, *, sdk: str = "test_sdk", class_name: str = "TestClass", interface: str | None = None) -> dict:
    data = {"sdk": sdk, "class_name": class_name, "function": function}
    if interface:
        data["interface"] = interface
    return data


def event_target(
    function: str,
    *,
    sdk: str = "test_sdk",
    class_name: str = "TestDelegate",
    interface: str | None = "test_interface",
) -> dict:
    return target(function, sdk=sdk, class_name=class_name, interface=interface)


class FakeWebSocket:
    """记录下行协议包的测试 WebSocket。"""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._sent_condition = asyncio.Condition()

    async def send_json(self, packet: dict) -> None:
        async with self._sent_condition:
            self.sent.append(packet)
            self._sent_condition.notify_all()

    async def wait_for_sends(self, count: int, timeout: float = 1.0) -> None:
        async with self._sent_condition:
            try:
                await asyncio.wait_for(self._sent_condition.wait_for(lambda: len(self.sent) >= count), timeout)
            except asyncio.TimeoutError as error:
                raise AssertionError(f"expected {count} sends, observed {len(self.sent)}") from error


class FailingWebSocket(FakeWebSocket):
    """模拟 WebSocket send_json 失败。"""

    async def send_json(self, packet: dict) -> None:
        await super().send_json(packet)
        raise RuntimeError("socket closed")


class BlockingTransport:
    """在 send 返回前阻塞，用于覆盖 dispatch 的取消窗口。"""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.packet: dict | None = None

    async def send(self, websocket: FakeWebSocket, packet: dict) -> None:
        _ = websocket
        self.packet = packet
        self.entered.set()
        await asyncio.Future()


class AutoReplyWebSocket(FakeWebSocket):
    """收到下行命令后模拟 Agent 回包。"""

    def __init__(self, collector: ResultCollector) -> None:
        super().__init__()
        self._collector = collector

    async def send_json(self, packet: dict) -> None:
        await super().send_json(packet)
        function = packet["data"]["list"][0]["target"]["function"]
        code = 500 if function == "fail" else 0
        await self._collector.resolve(
            packet["data"]["node_id"],
            packet["common"]["op_id"],
            invoke_response(packet["common"]["op_id"], code),
        )


@pytest.mark.anyio
async def test_IT_SRV_CMD_protocol_invoke_preserves_recorder_operation_id_in_pending_and_wire_packet():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = AutoReplyWebSocket(collector)
    await manager.handle_register(websocket, register_packet("mac-protocol-op"))

    response = await dispatcher.send_protocol_invoke(
        "mac-protocol-op",
        [
            {
                "target": target("join"),
                "params": {"channel": "thin-tracer-room", "uid": 1011},
                "extra": {"run_id": "run-1", "case_id": "case-1", "step_id": "join"},
            }
        ],
        "op-recorder-owned",
        timeout_ms=5000,
    )

    assert websocket.sent[-1]["common"]["op_id"] == "op-recorder-owned"
    assert websocket.sent[-1]["data"]["list"][0]["params"] == '{"channel":"thin-tracer-room","uid":1011}'
    assert response["common"]["op_id"] == "op-recorder-owned"
    assert await run_runtime.pending_count_for_device("mac-protocol-op") == 0


@pytest.mark.anyio
async def test_IR05_bound_protocol_invoke_rejects_replaced_lease_before_pending_or_wire():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    first = FakeWebSocket()
    second = FakeWebSocket()
    await manager.handle_register(first, register_packet("mac-bound"))
    original = await registry.get("mac-bound")
    assert original is not None
    await manager.handle_register(second, register_packet("mac-bound"))

    response = await dispatcher.send_protocol_invoke(
        "mac-bound", [{"target": target("join"), "params": {}}], "op-old-case",
        expected_lease_id=original.lease_id,
    )

    assert response["data"]["code"] == 409
    assert await run_runtime.pending_count_for_device("mac-bound") == 0
    assert not any(packet["common"]["action"] == "invokeRequest" for packet in second.sent)


class EvidenceReplyWebSocket(FakeWebSocket):
    """模拟调用成功后 Agent 或采集模块写入 Evidence。"""

    def __init__(self, collector: ResultCollector, evidence: Evidence) -> None:
        super().__init__()
        self._collector = collector
        self._evidence = evidence

    async def send_json(self, packet: dict) -> None:
        await super().send_json(packet)
        await self._collector.resolve(
            packet["data"]["node_id"],
            packet["common"]["op_id"],
            invoke_response(packet["common"]["op_id"], 0),
        )
        await self._collector.record_evidence(self._evidence)


def register_packet(node_id: str, *, platform: str = "mac", tags: list[str] | None = None) -> dict:
    return {
        "common": {"action": "registerRequest", "op_id": f"op-register-{node_id}"},
        "data": {
            "node_id": node_id,
            "platform": platform,
            "group_id": "local",
            "tags": tags or ["smoke"],
            "capabilities": ["rtc.mock"],
        },
    }


def invoke_response(op_id: str, code: int = 0) -> dict:
    return {
        "common": {"action": "invokeResponse", "op_id": op_id},
        "data": {"code": code, "message": "ok" if code == 0 else "failed", "result": "{}"},
    }


@pytest.mark.anyio
async def test_IT_SRV_REG_01_registers_new_device_and_returns_response():
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    websocket = FakeWebSocket()

    response = await manager.handle_register(websocket, register_packet("mac-1"))

    assert response["common"]["action"] == "registerResponse"
    assert response["data"]["code"] == 0
    session = await registry.get("mac-1")
    assert session is not None
    assert session.device.node_id == "mac-1"
    assert response["data"]["lease_id"].startswith("lease-")
    assert session.lease_id == response["data"]["lease_id"]
    assert response["data"]["server_protocol_version"] == 1


@pytest.mark.anyio
async def test_IT_SRV_REG_01A_register_and_reconnect_return_protocol_hint():
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    websocket = FakeWebSocket()
    reconnect_websocket = FakeWebSocket()

    register = await manager.handle_register(websocket, register_packet("mac-1"))
    reconnect = await manager.handle_reconnect(
        reconnect_websocket,
        {"common": {"action": "reconnectRequest", "op_id": "op-reconnect"}, "data": {"node_id": "mac-1"}},
    )

    assert register["data"]["server_protocol_version"] == 1
    assert reconnect["data"]["server_protocol_version"] == 1
    assert reconnect["data"]["state"] == 1


@pytest.mark.anyio
async def test_IT_SRV_REG_01B_reconnect_without_context_records_restart_diagnostic():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)

    response = await manager.handle_reconnect(
        FakeWebSocket(),
        {"common": {"action": "reconnectRequest", "op_id": "op-reconnect"}, "data": {"node_id": "mac-1"}},
    )

    assert response["data"]["state"] == 0
    assert response["data"]["server_protocol_version"] == 1
    events = await diagnostics.summaries(node_id="mac-1", event_type="reconnect_requires_register")
    assert events and events[0]["reason"] == "missing session context"


@pytest.mark.anyio
async def test_IT_SRV_REG_02_duplicate_register_replaces_session_and_fails_old_pending():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    first_ws = FakeWebSocket()
    second_ws = FakeWebSocket()
    await manager.handle_register(first_ws, register_packet("mac-1"))
    first_session = await registry.get("mac-1")
    assert first_session is not None
    pending_task = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    op_id = first_ws.sent[-1]["common"]["op_id"]

    response = await manager.handle_register(second_ws, register_packet("mac-1"))
    result = await pending_task

    assert result["data"]["code"] == 408
    assert result["data"]["failure_classification"] == {
        "category": "dispatch_failure",
        "source": "connection",
        "reason": "stale_lease",
    }
    session = await registry.get("mac-1")
    assert session is not None
    assert session.websocket is second_ws
    assert session.lease_id == response["data"]["lease_id"]
    assert session.lease_id != first_session.lease_id
    late = await collector.resolve("mac-1", op_id, invoke_response(op_id))
    assert late is False
    events = await diagnostics.query(node_id="mac-1")
    assert [event.type for event in events] == [
        "registered",
        "duplicate_register_replaced",
        "pending_terminal",
        "registered",
    ]
    assert events[1].lease_id == first_session.lease_id
    assert events[1].reason == "duplicate register"
    assert events[2].op_id == op_id
    assert events[2].reason == "duplicate register"


@pytest.mark.anyio
async def test_IT_SRV_REG_02A_stale_unregister_does_not_remove_active_session_or_pending():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    first_ws = FakeWebSocket()
    second_ws = FakeWebSocket()
    await manager.handle_register(first_ws, register_packet("mac-1"))
    second_response = await manager.handle_register(second_ws, register_packet("mac-1"))
    task = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    op_id = second_ws.sent[-1]["common"]["op_id"]

    unregister = await manager.handle_unregister(
        first_ws,
        {"common": {"action": "unregisterRequest", "op_id": "op-stale-unregister"}, "data": {"node_id": "mac-1"}},
    )

    active_session = await registry.get("mac-1")
    assert unregister["data"]["code"] == 0
    assert active_session is not None
    assert active_session.websocket is second_ws
    assert active_session.lease_id == second_response["data"]["lease_id"]
    assert await manager.context("mac-1") is not None
    assert await collector.pending_count() == 1

    await gateway.handle_packet(
        second_ws,
        {
            "common": {"action": "invokeResponse", "op_id": op_id},
            "data": {"node_id": "mac-1", "lease_id": active_session.lease_id, "code": 0, "message": "ok"},
        },
    )
    result = await task

    assert result["data"]["message"] == "ok"
    assert await collector.pending_count() == 0
    events = await diagnostics.query(node_id="mac-1", event_type="stale_unregister_ignored")
    assert len(events) == 1
    assert events[0].lease_id == second_response["data"]["lease_id"]
    assert events[0].details["stale_lease_id"] != events[0].lease_id


@pytest.mark.anyio
async def test_IT_SRV_REG_02B_stale_lease_response_does_not_resolve_active_pending():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    first_ws = FakeWebSocket()
    second_ws = FakeWebSocket()
    first_response = await manager.handle_register(first_ws, register_packet("mac-1"))
    await manager.handle_register(second_ws, register_packet("mac-1"))
    task = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    op_id = second_ws.sent[-1]["common"]["op_id"]

    await gateway.handle_packet(
        first_ws,
        {
            "common": {"action": "invokeResponse", "op_id": op_id},
            "data": {"node_id": "mac-1", "lease_id": first_response["data"]["lease_id"], "code": 0, "message": "late stale"},
        },
    )
    assert await collector.pending_count() == 1
    await gateway.handle_packet(
        second_ws,
        {
            "common": {"action": "invokeResponse", "op_id": op_id},
            "data": {"node_id": "mac-1", "lease_id": (await registry.get("mac-1")).lease_id, "code": 0, "message": "ok"},
        },
    )
    result = await task

    assert result["data"]["message"] == "ok"
    assert await collector.pending_count() == 0
    rejected = await diagnostics.query(node_id="mac-1", event_type="upstream_response_rejected")
    assert len(rejected) == 1
    assert rejected[0].op_id == op_id
    assert rejected[0].lease_id == first_response["data"]["lease_id"]
    assert rejected[0].reason == "stale lease"


@pytest.mark.anyio
async def test_IT_SRV_REG_02C1_callback_response_cannot_complete_invoke_pending():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    register = await manager.handle_register(websocket, register_packet("mac-action-contract"))

    task = asyncio.create_task(dispatcher.send_invoke("mac-action-contract", [{"target": target("join")}]))
    await asyncio.sleep(0)
    op_id = websocket.sent[-1]["common"]["op_id"]
    lease_id = register["data"]["lease_id"]

    unsupported = await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "callbackResponse", "op_id": op_id},
            "data": {"node_id": "mac-action-contract", "lease_id": lease_id, "code": 0, "message": "installed"},
        },
    )
    assert unsupported is None
    assert not task.done()
    assert await collector.pending_count("mac-action-contract") == 1

    assert await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "invokeResponse", "op_id": op_id},
            "data": {"node_id": "mac-action-contract", "lease_id": lease_id, "code": 0, "message": "ok"},
        },
    ) is None
    assert (await task)["data"]["code"] == 0
    assert await collector.pending_count("mac-action-contract") == 0


@pytest.mark.anyio
async def test_IT_SRV_REG_02D_missing_lease_response_does_not_resolve_active_pending():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))
    task = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    op_id = websocket.sent[-1]["common"]["op_id"]
    active_session = await registry.get("mac-1")
    assert active_session is not None

    await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "invokeResponse", "op_id": op_id},
            "data": {"node_id": "mac-1", "code": 0, "message": "missing lease"},
        },
    )
    assert await collector.pending_count() == 1
    await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "invokeResponse", "op_id": op_id},
            "data": {"lease_id": active_session.lease_id, "code": 0, "message": "missing node"},
        },
    )
    assert await collector.pending_count() == 1
    await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "invokeResponse", "op_id": op_id},
            "data": {"node_id": "mac-1", "lease_id": active_session.lease_id, "code": 0, "message": "ok"},
        },
    )
    result = await task

    assert result["data"]["message"] == "ok"
    assert await collector.pending_count() == 0


@pytest.mark.anyio
async def test_IT_SRV_REG_03_unregister_removes_online_device():
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    response = await manager.handle_unregister(websocket, {"common": {"op_id": "op-unregister"}, "data": {"node_id": "mac-1"}})

    assert response["data"]["code"] == 0
    assert await registry.get("mac-1") is None


@pytest.mark.anyio
async def test_IT_SRV_REG_04_selector_node_id_picks_exact_device():
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    first_ws = FakeWebSocket()
    second_ws = FakeWebSocket()
    await manager.handle_register(first_ws, register_packet("mac-1", tags=["smoke"]))
    await manager.handle_register(second_ws, register_packet("mac-2", tags=["smoke", "real"]))

    selected = await registry.list(DeviceSelector(platform="mac", node_id="mac-2", tags=["real"]))

    assert [session.device.node_id for session in selected] == ["mac-2"]


@pytest.mark.anyio
async def test_IT_SRV_CMD_01_and_02_dispatch_creates_unique_pending_and_resolves_response():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    task = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    sent = websocket.sent[-1]
    assert sent["common"]["action"] == "invokeRequest"
    assert sent["common"]["op_id"].startswith("op-")
    assert sent["data"]["lease_id"].startswith("lease-")
    assert sent["data"]["sync"] is True
    assert sent["data"]["list"] == [{"target": target("join"), "params": "{}", "extra": "{}"}]
    assert "calls" not in sent["data"]

    await collector.resolve("mac-1", sent["common"]["op_id"], invoke_response(sent["common"]["op_id"]))
    result = await task

    assert result["data"]["code"] == 0
    assert result["common"]["op_id"] == sent["common"]["op_id"]


@pytest.mark.anyio
async def test_IT_SRV_CMD_02_resolve_matches_by_op_id_when_response_has_no_node_id():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))
    task = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    op_id = websocket.sent[-1]["common"]["op_id"]

    resolved = await collector.resolve("", op_id, invoke_response(op_id))
    result = await task

    assert resolved is True
    assert result["data"]["code"] == 0


@pytest.mark.anyio
async def test_IT_SRV_CMD_03_offline_device_returns_404():
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    dispatcher = CommandDispatcher(DeviceRegistry(), collector, run_runtime=run_runtime)

    result = await dispatcher.send_invoke("missing", [{"target": target("join")}], timeout_ms=10)

    assert result["data"]["code"] == 404


@pytest.mark.anyio
async def test_IT_SRV_CMD_04_request_timeout_returns_408_and_cleans_pending():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    result = await dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=1)

    assert result["data"]["code"] == 408
    assert result["data"]["failure_classification"] == {
        "category": "timeout",
        "source": "dispatch",
        "reason": "dispatch_timeout",
    }
    assert await collector.pending_count() == 0


@pytest.mark.anyio
async def test_IT_SRV_CMD_04D_cancelling_dispatch_cleans_pending_before_reraising():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-cancel"))

    task = asyncio.create_task(
        dispatcher.send_invoke("mac-cancel", [{"target": target("join")}], timeout_ms=10_000)
    )
    await asyncio.sleep(0)
    op_id = websocket.sent[-1]["common"]["op_id"]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await collector.pending_count() == 0
    assert await collector.resolve("mac-cancel", op_id, invoke_response(op_id)) is False


@pytest.mark.anyio
async def test_IT_SRV_CMD_04E_cancelling_dispatch_during_send_cleans_pending_before_reraising():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    transport = BlockingTransport()
    dispatcher = CommandDispatcher(registry, collector, transport=transport, run_runtime=run_runtime)
    await manager.handle_register(FakeWebSocket(), register_packet("mac-cancel-send"))

    task = asyncio.create_task(
        dispatcher.send_invoke("mac-cancel-send", [{"target": target("join")}], timeout_ms=10_000)
    )
    await transport.entered.wait()
    assert transport.packet is not None
    op_id = transport.packet["common"]["op_id"]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await collector.pending_count() == 0
    assert await collector.resolve("mac-cancel-send", op_id, invoke_response(op_id)) is False


@pytest.mark.anyio
async def test_IT_SRV_CMD_04A_pending_limit_rejects_without_sending_and_records_diagnostic():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime, max_pending_per_device=1)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    first = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    sent_count = len(websocket.sent)
    second = await dispatcher.send_invoke("mac-1", [{"target": target("joinAgain")}], timeout_ms=5000)

    assert second["data"]["code"] == 429
    assert len(websocket.sent) == sent_count
    events = await diagnostics.summaries(node_id="mac-1", event_type="pending_limit_rejected")
    assert events and events[0]["details"]["limit"] == 1

    await run_runtime.fail_pending_for_device("mac-1", "test cleanup")
    assert (await first)["data"]["code"] == 408


@pytest.mark.anyio
async def test_IT_SRV_CMD_04B_send_failure_completes_pending_and_records_diagnostic():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FailingWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    result = await dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000)

    assert result["data"]["code"] == 502
    assert result["data"]["failure_classification"] == {
        "category": "dispatch_failure",
        "source": "transport",
        "reason": "send_failure",
    }
    assert await collector.pending_count() == 0
    events = await diagnostics.summaries(node_id="mac-1", event_type="send_failed")
    assert events and events[0]["reason"] == "socket closed"
    terminals = await diagnostics.summaries(node_id="mac-1", event_type="pending_terminal")
    assert terminals and terminals[0]["reason"] == "send failure"


@pytest.mark.anyio
async def test_IT_SRV_CMD_04C_timeout_pending_terminal_keeps_trace_context():
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    registry = DeviceRegistry()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    result = await dispatcher.send_invoke(
        "mac-1",
        [
            {
                "target": target("join"),
                "extra": {
                    "run_id": "run-trace",
                    "case_id": "TC-PENDING-TERMINAL-TRACE",
                    "step_id": "join-timeout",
                },
            }
        ],
        timeout_ms=1,
    )

    assert result["data"]["code"] == 408
    events = await diagnostics.summaries(
        node_id="mac-1",
        event_type="pending_terminal",
        run_id="run-trace",
        case_id="TC-PENDING-TERMINAL-TRACE",
        step_id="join-timeout",
    )
    assert events and events[0]["reason"] == "request timeout"
    assert events[0]["details"] == {"action": "invokeRequest"}


@pytest.mark.anyio
async def test_IT_SRV_CMD_04D_send_failure_diagnostics_keep_trace_context():
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    registry = DeviceRegistry()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    await manager.handle_register(FailingWebSocket(), register_packet("mac-1"))

    result = await dispatcher.send_invoke(
        "mac-1",
        [
            {
                "target": target("join"),
                "extra": {
                    "run_id": "run-send-failure",
                    "case_id": "TC-SEND-FAILURE-TRACE",
                    "step_id": "join",
                },
            }
        ],
        timeout_ms=5000,
    )

    assert result["data"]["code"] == 502
    send_failed = await diagnostics.summaries(
        event_type="send_failed",
        run_id="run-send-failure",
        case_id="TC-SEND-FAILURE-TRACE",
        step_id="join",
    )
    pending_terminal = await diagnostics.summaries(
        event_type="pending_terminal",
        run_id="run-send-failure",
        case_id="TC-SEND-FAILURE-TRACE",
        step_id="join",
    )
    assert send_failed and send_failed[0]["reason"] == "socket closed"
    assert pending_terminal and pending_terminal[0]["reason"] == "send failure"


@pytest.mark.anyio
async def test_IT_SRV_CMD_05_pending_terminal_state_is_written_once():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))
    task = asyncio.create_task(dispatcher.send_invoke("mac-1", [{"target": target("join")}], timeout_ms=5000))
    await asyncio.sleep(0)
    op_id = websocket.sent[-1]["common"]["op_id"]

    await asyncio.gather(
        collector.fail_all_for_device("mac-1", "disconnect"),
        collector.resolve("mac-1", op_id, invoke_response(op_id)),
        collector.cancel(op_id),
    )
    result = await task

    assert result["data"]["code"] in {408, 499, 0}
    assert await collector.pending_count() == 0
    late = await collector.resolve("mac-1", op_id, invoke_response(op_id, 0))
    assert late is False


@pytest.mark.anyio
async def test_IT_SRV_HB_01_healthy_heartbeat_returns_response_without_persistent_noise():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    websocket = FakeWebSocket()
    register = await manager.handle_register(websocket, register_packet("mac-1"))
    lease_id = register["data"]["lease_id"]

    response = await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "heartbeatRequest", "op_id": "op-heartbeat"},
            "data": {"node_id": "mac-1", "lease_id": lease_id},
        },
    )

    assert response["common"]["action"] == "heartbeatResponse"
    assert response["data"]["code"] == 0
    assert response["data"]["server_time_ms"] > 0
    events = await diagnostics.summaries(node_id="mac-1", event_type="heartbeat_received")
    assert events == []


@pytest.mark.anyio
async def test_IT_SRV_CONN_DIAG_retention_caps_stored_events():
    diagnostics = ConnectionEventStore(max_events=2)

    await diagnostics.record("pending_terminal", "mac-1", op_id="op-1")
    await diagnostics.record("pending_terminal", "mac-1", op_id="op-2")
    await diagnostics.record("pending_terminal", "mac-1", op_id="op-3")

    events = await diagnostics.summaries(node_id="mac-1", event_type="pending_terminal")
    assert [event["op_id"] for event in events] == ["op-2", "op-3"]


@pytest.mark.anyio
async def test_IT_SRV_HB_02_stale_heartbeat_records_missed_diagnostic():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)

    response = await gateway.handle_packet(
        FakeWebSocket(),
        {
            "common": {"action": "heartbeatRequest", "op_id": "op-heartbeat-stale"},
            "data": {"node_id": "mac-1", "lease_id": "lease-stale"},
        },
    )

    assert response["common"]["action"] == "heartbeatResponse"
    assert response["data"]["code"] == 409
    events = await diagnostics.summaries(node_id="mac-1", event_type="heartbeat_missed")
    assert events and events[0]["reason"] == "stale lease"


@pytest.mark.anyio
async def test_IT_SRV_CBEVT_01_callback_event_is_recorded():
    collector = ResultCollector()
    packet = {
        "common": {"op_id": "op-event", "timestamp_ms": 123},
        "data": {
            "node_id": "mac-1",
            "run_id": "run-1",
            "case_id": "case-1",
            "step_id": "step-1",
            "event_target": event_target("onJoin"),
            "payload": {"uid": 1001},
            "callback_context": {
                "provider": "agora_rtc/rtc_engine",
                "originating_op_id": "op-origin-join",
                "resource_ref": "engine_1",
                "instance_id": "engine_1",
                "sequence": 7,
            },
        },
    }

    stored = await collector.record_callback_event(packet)
    evidence = (await collector.evidence_events("mac-1", event_target("onJoin")))[0]

    assert stored.data["event_target"] == event_target("onJoin")
    assert stored.data["callback_context"]["originating_op_id"] == "op-origin-join"
    assert stored.data["callback_context"]["resource_ref"] == "engine_1"
    assert (await collector.callback_events("mac-1"))[0].common["op_id"] == "op-event"
    assert evidence.type == "event"
    assert evidence.source == "callback"
    assert evidence.run_id == "run-1"
    assert evidence.case_id == "case-1"
    assert evidence.step_id == "step-1"
    assert evidence.node_id == "mac-1"
    assert evidence.target == event_target("onJoin")
    assert evidence.payload == {"uid": 1001}
    assert evidence.callback_context["originating_op_id"] == "op-origin-join"
    assert evidence.raw["data"]["callback_context"]["sequence"] == 7
    assert evidence.timestamp_ms == 123


@pytest.mark.anyio
async def test_IT_SRV_CBEVT_02_callback_event_dedupe_uses_event_node_and_lease():
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    packet = {
        "common": {"action": "callbackEventRequest", "op_id": "op-event", "timestamp_ms": 123},
        "data": {
            "node_id": "mac-1",
            "lease_id": "lease-active",
            "event_id": "evt-1",
            "event_target": event_target("onJoin"),
            "payload": {"uid": 1001},
            "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
        },
    }

    first = await run_runtime.ingest_callback_event(packet)
    duplicate = await run_runtime.ingest_callback_event(packet)
    same_event_new_lease = await run_runtime.ingest_callback_event(
        {**packet, "data": {**packet["data"], "lease_id": "lease-new"}}
    )
    events = await collector.callback_events("mac-1")

    assert first["receipt"]["recorded"] is True
    assert duplicate["receipt"]["duplicate"] is True
    assert same_event_new_lease["receipt"]["recorded"] is True
    assert [event.data["lease_id"] for event in events] == ["lease-active", "lease-new"]


@pytest.mark.anyio
async def test_IT_SRV_CBEVT_02B_gateway_rejects_schema_incomplete_callback_events():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    websocket = FakeWebSocket()
    register = await manager.handle_register(websocket, register_packet("mac-1"))
    base_data = {
        "node_id": "mac-1",
        "lease_id": register["data"]["lease_id"],
        "event_id": "evt-valid",
        "event_target": event_target("onJoin"),
        "payload": {"uid": 1001},
        "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
    }

    missing_event_id = await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "callbackEventRequest", "op_id": "op-missing-event-id", "timestamp_ms": 1},
            "data": {key: value for key, value in base_data.items() if key != "event_id"},
        },
    )
    missing_execution = await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "callbackEventRequest", "op_id": "op-missing-execution", "timestamp_ms": 1},
            "data": {key: value for key, value in base_data.items() if key != "callback_execution"},
        },
    )
    non_object_data = await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "callbackEventRequest", "op_id": "op-invalid-data", "timestamp_ms": 1},
            "data": [],
        },
    )

    assert missing_event_id is not None
    assert missing_event_id["data"]["code"] == 400
    assert missing_event_id["data"]["message"] == "invalid callback event: event_id"
    assert missing_execution is not None
    assert missing_execution["data"]["code"] == 0
    assert non_object_data is not None
    assert non_object_data["data"]["code"] == 400
    assert non_object_data["data"]["message"] == "invalid callback event: data"
    assert len(await collector.callback_events("mac-1")) == 1
    rejected = await diagnostics.query(event_type="callback_event_rejected")
    assert [event.reason for event in rejected] == ["invalid callback event"] * 2


@pytest.mark.anyio
async def test_IT_SRV_CBEVT_03_stale_callback_event_is_rejected_without_evidence():
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    first_ws = FakeWebSocket()
    second_ws = FakeWebSocket()
    first_response = await manager.handle_register(first_ws, register_packet("mac-1"))
    await manager.handle_register(second_ws, register_packet("mac-1"))

    response = await gateway.handle_packet(
        first_ws,
        {
            "common": {"action": "callbackEventRequest", "op_id": "op-stale-event"},
            "data": {
                "node_id": "mac-1",
                "lease_id": first_response["data"]["lease_id"],
                "event_id": "evt-stale",
                "event_target": event_target("onJoin"),
                "payload": {"uid": 1001},
                "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
            },
        },
    )

    assert response["data"]["code"] == 409
    assert response["data"]["receipt"] == {"received": True, "recorded": False, "duplicate": False, "evidence_id": ""}
    assert await collector.callback_events("mac-1") == []
    rejected = await diagnostics.query(node_id="mac-1", event_type="callback_event_rejected")
    assert len(rejected) == 1
    assert rejected[0].lease_id == first_response["data"]["lease_id"]
    assert rejected[0].reason == "stale lease"
    assert rejected[0].details["event_id"] == "evt-stale"


@pytest.mark.anyio
async def test_IT_SRV_CBEVT_04_missing_lease_callback_event_is_rejected_without_evidence():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime)
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    response = await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "callbackEventRequest", "op_id": "op-missing-lease-event"},
            "data": {
                "node_id": "mac-1",
                "event_id": "evt-missing-lease",
                "event_target": event_target("onJoin"),
                "payload": {"uid": 1001},
                "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
            },
        },
    )

    assert response["data"]["code"] == 400
    assert response["data"]["message"] == "missing lease"
    assert response["data"]["receipt"] == {"received": True, "recorded": False, "duplicate": False, "evidence_id": ""}
    assert await collector.callback_events("mac-1") == []

    missing_node = await gateway.handle_packet(
        websocket,
        {
            "common": {"action": "callbackEventRequest", "op_id": "op-missing-node-event"},
            "data": {
                "lease_id": "lease-any",
                "event_id": "evt-missing-node",
                "event_target": event_target("onJoin"),
                "payload": {"uid": 1001},
                "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
            },
        },
    )

    assert missing_node["data"]["code"] == 400
    assert missing_node["data"]["message"] == "missing lease"
    assert await collector.callback_events("") == []


@pytest.mark.anyio
async def test_IT_SRV_CTX_and_REC_session_context_controls_reconnect_state():
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    response = await manager.handle_reconnect(websocket, {"common": {"op_id": "op-reconnect"}, "data": {"node_id": "mac-1"}})
    assert response["data"]["state"] == 1

    await manager.clear_context("mac-1")
    response = await manager.handle_reconnect(websocket, {"common": {"op_id": "op-reconnect-2"}, "data": {"node_id": "mac-1"}})
    assert response["data"]["state"] == 0


@pytest.mark.anyio
async def test_IT_SRV_REC_reconnect_restores_online_session():
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))
    await manager.handle_disconnect(websocket)
    assert await registry.get("mac-1") is None

    reconnect_websocket = FakeWebSocket()
    response = await manager.handle_reconnect(
        reconnect_websocket,
        {"common": {"action": "reconnectRequest", "op_id": "op-reconnect"}, "data": {"node_id": "mac-1"}},
    )

    assert response["data"]["state"] == 1
    session = await registry.get("mac-1")
    assert session is not None
    assert session.lease_id == response["data"]["lease_id"]


@pytest.mark.anyio
async def test_IT_SRV_REC_unregister_clears_reconnect_context():
    registry = DeviceRegistry()
    collector = ResultCollector()
    manager = SessionManager(registry, ServerRunRuntime(collector))
    websocket = FakeWebSocket()
    await manager.handle_register(websocket, register_packet("mac-1"))

    await manager.handle_unregister(websocket, {"common": {"op_id": "op-unregister"}, "data": {"node_id": "mac-1"}})
    response = await manager.handle_reconnect(FakeWebSocket(), {"common": {"op_id": "op-reconnect"}, "data": {"node_id": "mac-1"}})

    assert response["data"]["state"] == 0


@pytest.mark.anyio
async def test_IT_SRV_LOG_03C_log_collector_uses_injected_store_for_ingest_query_and_dedupe():
    class RecordingLogStore:
        def __init__(self) -> None:
            self.events: list[dict] = []
            self.keys: set[tuple[str, str, str]] = set()
            self.append_count = 0
            self.list_count = 0

        async def contains(self, dedupe_key: tuple[str, str, str]) -> bool:
            return dedupe_key in self.keys

        async def append(self, event: dict, dedupe_key: tuple[str, str, str]) -> None:
            self.keys.add(dedupe_key)
            self.events.append(dict(event))
            self.append_count += 1

        async def list_events(self) -> list[dict]:
            self.list_count += 1
            return list(self.events)

    store = RecordingLogStore()
    log_collector = ServerLogCollector(store=store)

    stats = await log_collector.ingest(
        "mac-store",
        "lease-store",
        [
            {
                "event_id": "log-store-1",
                "timestamp_ms": 1200,
                "level": "error",
                "run_id": "run-log-store",
                "case_id": "case-store",
                "step_id": "step-store",
                "op_id": "op-store",
                "module": "agora",
                "event": "agora.join.failed",
                "message": "join failed",
                "error": 109,
                "extra": {},
            },
            {
                "event_id": "log-store-1",
                "timestamp_ms": 1200,
                "level": "error",
                "run_id": "run-log-store",
                "case_id": "case-store",
                "step_id": "step-store",
                "op_id": "op-store",
                "module": "agora",
                "event": "agora.join.failed",
                "message": "duplicate",
                "error": 109,
                "extra": {},
            },
        ],
    )
    events = await log_collector.query_by_trace("run-log-store", case_id="case-store", step_id="step-store", op_id="op-store")

    assert stats == {"accepted": 1, "duplicates": 1, "rejected": 0}
    assert store.append_count == 1
    assert store.list_count == 1
    assert [event["event_id"] for event in events] == ["log-store-1"]
    assert events[0]["node_id"] == "mac-store"
    assert events[0]["lease_id"] == "lease-store"


@pytest.mark.anyio
async def test_IT_SRV_LOG_03D_jsonl_log_store_survives_collector_rebuild(tmp_path):
    log_path = tmp_path / "server-logs.jsonl"
    first_collector = ServerLogCollector(store=JsonlServerLogStore(log_path))

    stats = await first_collector.ingest(
        "mac-jsonl",
        "lease-jsonl",
        [
            {
                "event_id": "log-jsonl-1",
                "timestamp_ms": 1300,
                "level": "error",
                "run_id": "run-log-jsonl",
                "case_id": "case-jsonl",
                "step_id": "step-jsonl",
                "op_id": "op-jsonl",
                "module": "agora",
                "event": "agora.join.failed",
                "message": "join failed",
                "error": 109,
                "extra": {"failure_category": "sdk_error"},
            }
        ],
    )

    rebuilt_collector = ServerLogCollector(store=JsonlServerLogStore(log_path))
    events = await rebuilt_collector.query_by_trace(
        "run-log-jsonl",
        case_id="case-jsonl",
        step_id="step-jsonl",
        op_id="op-jsonl",
        node_id="mac-jsonl",
        lease_id="lease-jsonl",
    )

    assert stats == {"accepted": 1, "duplicates": 0, "rejected": 0}
    assert log_path.exists()
    assert [event["event_id"] for event in events] == ["log-jsonl-1"]
    assert events[0]["extra"] == {"failure_category": "sdk_error"}


@pytest.mark.anyio
async def test_IT_SRV_LOG_03F_jsonl_log_store_skips_corrupt_lines_on_rebuild(tmp_path):
    log_path = tmp_path / "server-logs-with-corrupt-line.jsonl"
    valid_event = {
        "event_id": "log-jsonl-valid",
        "timestamp_ms": 1350,
        "level": "error",
        "node_id": "mac-jsonl-corrupt",
        "lease_id": "lease-jsonl-corrupt",
        "run_id": "run-log-jsonl-corrupt",
        "case_id": "case-jsonl-corrupt",
        "step_id": "step-jsonl-corrupt",
        "op_id": "op-jsonl-corrupt",
        "module": "agora",
        "event": "agora.join.failed",
        "message": "join failed",
        "error": 109,
        "extra": {"failure_category": "sdk_error"},
    }
    log_path.write_text(json.dumps(valid_event, sort_keys=True) + "\n{corrupt-jsonl\n", encoding="utf-8")

    rebuilt_collector = ServerLogCollector(store=JsonlServerLogStore(log_path))
    events = await rebuilt_collector.query_by_trace(
        "run-log-jsonl-corrupt",
        case_id="case-jsonl-corrupt",
        step_id="step-jsonl-corrupt",
        op_id="op-jsonl-corrupt",
        node_id="mac-jsonl-corrupt",
        lease_id="lease-jsonl-corrupt",
    )

    assert [event["event_id"] for event in events] == ["log-jsonl-valid"]


@pytest.mark.anyio
async def test_IT_SRV_LOG_03G_jsonl_log_store_rotates_by_size_and_reloads_rotated_file(tmp_path):
    log_path = tmp_path / "server-logs-rotating.jsonl"
    log_collector = ServerLogCollector(store=JsonlServerLogStore(log_path, max_bytes=1, max_rotated_files=1))
    events = [
        {
            "event_id": "log-jsonl-rotate-1",
            "timestamp_ms": 1360,
            "level": "error",
            "run_id": "run-log-jsonl-rotate",
            "case_id": "case-jsonl-rotate",
            "step_id": "step-jsonl-rotate",
            "op_id": "op-jsonl-rotate",
            "module": "agora",
            "event": "agora.join.failed",
            "message": "first failure",
        },
        {
            "event_id": "log-jsonl-rotate-2",
            "timestamp_ms": 1361,
            "level": "error",
            "run_id": "run-log-jsonl-rotate",
            "case_id": "case-jsonl-rotate",
            "step_id": "step-jsonl-rotate",
            "op_id": "op-jsonl-rotate",
            "module": "agora",
            "event": "agora.join.failed",
            "message": "second failure",
        },
    ]

    stats = await log_collector.ingest("mac-jsonl-rotate", "lease-jsonl-rotate", events)
    rebuilt_collector = ServerLogCollector(store=JsonlServerLogStore(log_path, max_bytes=1, max_rotated_files=1))
    reloaded = await rebuilt_collector.query_by_trace(
        "run-log-jsonl-rotate",
        case_id="case-jsonl-rotate",
        step_id="step-jsonl-rotate",
        op_id="op-jsonl-rotate",
        node_id="mac-jsonl-rotate",
        lease_id="lease-jsonl-rotate",
    )

    assert stats == {"accepted": 2, "duplicates": 0, "rejected": 0}
    assert log_path.with_suffix(log_path.suffix + ".1").exists()
    assert [event["event_id"] for event in reloaded] == ["log-jsonl-rotate-1", "log-jsonl-rotate-2"]


@pytest.mark.anyio
async def test_IT_SRV_LOG_03H_jsonl_log_store_filters_expired_events_on_rebuild(tmp_path):
    log_path = tmp_path / "server-logs-retention.jsonl"
    expired_event = {
        "event_id": "log-jsonl-expired",
        "timestamp_ms": 1000,
        "level": "error",
        "node_id": "mac-jsonl-retention",
        "lease_id": "lease-jsonl-retention",
        "run_id": "run-log-jsonl-retention",
        "case_id": "case-jsonl-retention",
        "step_id": "step-jsonl-retention",
        "op_id": "op-jsonl-retention",
        "module": "agora",
        "event": "agora.join.failed",
        "message": "expired failure",
    }
    retained_event = {
        **expired_event,
        "event_id": "log-jsonl-retained",
        "timestamp_ms": 5000,
        "message": "retained failure",
    }
    log_path.write_text(
        json.dumps(expired_event, sort_keys=True) + "\n" + json.dumps(retained_event, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    rebuilt_collector = ServerLogCollector(
        store=JsonlServerLogStore(log_path, retention_ms=1000, now_ms=5500)
    )
    events = await rebuilt_collector.query_by_trace(
        "run-log-jsonl-retention",
        case_id="case-jsonl-retention",
        step_id="step-jsonl-retention",
        op_id="op-jsonl-retention",
        node_id="mac-jsonl-retention",
        lease_id="lease-jsonl-retention",
    )

    assert [event["event_id"] for event in events] == ["log-jsonl-retained"]


@pytest.mark.anyio
async def test_IT_SRV_LOG_03I_jsonl_log_store_quarantines_corrupt_lines_on_rebuild(tmp_path):
    log_path = tmp_path / "server-logs-quarantine.jsonl"
    valid_event = {
        "event_id": "log-jsonl-quarantine-valid",
        "timestamp_ms": 1400,
        "level": "error",
        "node_id": "mac-jsonl-quarantine",
        "lease_id": "lease-jsonl-quarantine",
        "run_id": "run-log-jsonl-quarantine",
        "case_id": "case-jsonl-quarantine",
        "step_id": "step-jsonl-quarantine",
        "op_id": "op-jsonl-quarantine",
        "module": "agora",
        "event": "agora.join.failed",
        "message": "join failed",
    }
    log_path.write_text(
        json.dumps(valid_event, sort_keys=True) + "\n{corrupt-jsonl-for-quarantine\n",
        encoding="utf-8",
    )

    rebuilt_collector = ServerLogCollector(
        store=JsonlServerLogStore(log_path, quarantine_corrupt_lines=True)
    )
    events = await rebuilt_collector.query_by_trace(
        "run-log-jsonl-quarantine",
        case_id="case-jsonl-quarantine",
        step_id="step-jsonl-quarantine",
        op_id="op-jsonl-quarantine",
        node_id="mac-jsonl-quarantine",
        lease_id="lease-jsonl-quarantine",
    )

    assert [event["event_id"] for event in events] == ["log-jsonl-quarantine-valid"]
    assert log_path.with_suffix(log_path.suffix + ".corrupt").read_text(encoding="utf-8") == (
        "{corrupt-jsonl-for-quarantine\n"
    )


@pytest.mark.anyio
async def test_IT_SRV_LOG_03K_jsonl_log_store_skips_schema_invalid_records_on_rebuild(tmp_path):
    log_path = tmp_path / "server-logs-invalid-schema.jsonl"
    invalid_event = {
        "event_id": "log-jsonl-invalid-schema",
        "timestamp_ms": "not-an-int",
        "level": "error",
        "event": "agora.join.failed",
        "message": "invalid timestamp",
    }
    valid_event = {
        "event_id": "log-jsonl-valid-after-invalid",
        "timestamp_ms": 1500,
        "level": "error",
        "node_id": "mac-jsonl-schema",
        "lease_id": "lease-jsonl-schema",
        "run_id": "run-log-jsonl-schema",
        "case_id": "case-jsonl-schema",
        "step_id": "step-jsonl-schema",
        "op_id": "op-jsonl-schema",
        "event": "agora.join.failed",
        "message": "join failed",
    }
    log_path.write_text(
        json.dumps(invalid_event, sort_keys=True) + "\n" + json.dumps(valid_event, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    rebuilt_collector = ServerLogCollector(
        store=JsonlServerLogStore(log_path, quarantine_corrupt_lines=True)
    )
    events = await rebuilt_collector.query_by_trace(
        "run-log-jsonl-schema",
        case_id="case-jsonl-schema",
        step_id="step-jsonl-schema",
        op_id="op-jsonl-schema",
        node_id="mac-jsonl-schema",
        lease_id="lease-jsonl-schema",
        start_ms=1000,
        end_ms=2000,
    )

    assert [event["event_id"] for event in events] == ["log-jsonl-valid-after-invalid"]
    assert "not-an-int" in log_path.with_suffix(log_path.suffix + ".corrupt").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_10_jsonl_artifact_store_survives_rebuild(tmp_path):
    from app.reporting.artifact_runtime import JsonlArtifactStore

    store_path = tmp_path / "artifacts.jsonl"
    store = JsonlArtifactStore(store_path)
    artifact_id = await store.put(
        "mac-artifact-jsonl",
        "log",
        "reports/latest/logs/run-runtime-artifact/case.step.jsonl",
        {"run_id": "run-runtime-artifact", "case_id": "case", "step_id": "step"},
    )

    rebuilt = JsonlArtifactStore(store_path)
    artifacts = await rebuilt.query(
        run_id="run-runtime-artifact",
        case_id="case",
        step_id="step",
        node_id="mac-artifact-jsonl",
        artifact_type="log",
    )

    assert artifacts == [
        {
            "artifact_id": artifact_id,
            "node_id": "mac-artifact-jsonl",
            "artifact_type": "log",
            "path": "reports/latest/logs/run-runtime-artifact/case.step.jsonl",
            "metadata": {"run_id": "run-runtime-artifact", "case_id": "case", "step_id": "step"},
        }
    ]


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_10A_jsonl_artifact_store_skips_bad_records_on_rebuild(tmp_path):
    from app.reporting.artifact_runtime import JsonlArtifactStore

    store_path = tmp_path / "artifacts-with-bad-record.jsonl"
    store_path.write_text(
        "[1, 2, 3]\n"
        + json.dumps(
            {
                "artifact_id": "artifact-good",
                "node_id": "mac-artifact-jsonl",
                "artifact_type": "log",
                "path": "reports/latest/logs/run-artifact/good.jsonl",
                "metadata": {"run_id": "run-artifact"},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    rebuilt = JsonlArtifactStore(store_path)
    artifacts = await rebuilt.query(run_id="run-artifact", artifact_type="log")

    assert [artifact["artifact_id"] for artifact in artifacts] == ["artifact-good"]


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15C_jsonl_artifact_store_does_not_index_failed_writes(tmp_path):
    from app.reporting.artifact_runtime import JsonlArtifactStore

    blocked_parent = tmp_path / "runtime-state"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    store = JsonlArtifactStore(blocked_parent / "artifacts.jsonl")

    with pytest.raises(OSError):
        await store.put(
            "mac-artifact-jsonl",
            "log",
            "artifact://logs/run-artifact-jsonl/failure.jsonl",
            {"run_id": "run-artifact-jsonl", "case_id": "case-artifact-jsonl", "step_id": "step-artifact-jsonl"},
        )

    assert await store.query(run_id="run-artifact-jsonl") == []


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15D_jsonl_device_registry_does_not_publish_failed_writes(tmp_path):
    from app.devices.device_models import Device, DeviceSelector, DeviceSession
    from app.devices.device_runtime import DeviceRegistry, JsonlDeviceSessionStore

    blocked_parent = tmp_path / "runtime-state"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    registry = DeviceRegistry(store=JsonlDeviceSessionStore(blocked_parent / "device-sessions.jsonl"))

    with pytest.raises(OSError):
        await registry.upsert(
            DeviceSession(
                device=Device(node_id="mac-device-jsonl-failed-write", platform="mac"),
                websocket=FakeWebSocket(),
                lease_id="lease-device-jsonl-failed-write",
            )
        )

    assert await registry.list(DeviceSelector(node_id="mac-device-jsonl-failed-write")) == []


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15E_jsonl_device_registry_keeps_snapshot_after_failed_replacement(tmp_path):
    from app.devices.device_models import Device, DeviceSelector, DeviceSession
    from app.devices.device_runtime import DeviceRegistry, JsonlDeviceSessionStore

    state_dir = tmp_path / "runtime-state"
    store = JsonlDeviceSessionStore(state_dir / "device-sessions.jsonl")
    registry = DeviceRegistry(store=store)
    await registry.upsert(
        DeviceSession(
            device=Device(
                node_id="mac-device-jsonl-replace-failed",
                platform="mac",
                group_id="stable-group",
                tags=["stable-tag"],
            ),
            websocket=FakeWebSocket(),
            lease_id="lease-device-jsonl-original",
        )
    )
    (state_dir / "device-sessions.jsonl").unlink()
    state_dir.rmdir()
    state_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError):
        await registry.upsert(
            DeviceSession(
                device=Device(
                    node_id="mac-device-jsonl-replace-failed",
                    platform="ios",
                    group_id="failed-group",
                    tags=["failed-tag"],
                ),
                websocket=FakeWebSocket(),
                lease_id="lease-device-jsonl-replacement",
            )
        )

    retained = await registry.list(DeviceSelector(platform="mac", group_id="stable-group", tags=["stable-tag"]))
    assert [session.lease_id for session in retained] == ["lease-device-jsonl-original"]
    assert await registry.list(DeviceSelector(platform="ios", group_id="failed-group", tags=["failed-tag"])) == []


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_15F_jsonl_device_registry_keeps_session_after_failed_remove(tmp_path):
    from app.devices.device_models import Device, DeviceSelector, DeviceSession
    from app.devices.device_runtime import DeviceRegistry, JsonlDeviceSessionStore

    state_dir = tmp_path / "runtime-state"
    store = JsonlDeviceSessionStore(state_dir / "device-sessions.jsonl")
    registry = DeviceRegistry(store=store)
    await registry.upsert(
        DeviceSession(
            device=Device(node_id="mac-device-jsonl-remove-failed", platform="mac"),
            websocket=FakeWebSocket(),
            lease_id="lease-device-jsonl-remove-failed",
        )
    )
    (state_dir / "device-sessions.jsonl").unlink()
    state_dir.rmdir()
    state_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError):
        await registry.remove("mac-device-jsonl-remove-failed")

    retained = await registry.list(DeviceSelector(node_id="mac-device-jsonl-remove-failed"))
    assert [session.device.node_id for session in retained] == ["mac-device-jsonl-remove-failed"]


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_11_jsonl_device_session_store_survives_rebuild(tmp_path):
    from app.devices.device_runtime import DeviceRegistry, JsonlDeviceSessionStore, SessionManager

    store_path = tmp_path / "device-sessions.jsonl"
    store = JsonlDeviceSessionStore(store_path)
    registry = DeviceRegistry(store=store)
    manager = SessionManager(registry, ServerRunRuntime(ResultCollector()), store=store)
    await manager.handle_register(FakeWebSocket(), register_packet("mac-device-jsonl", tags=["role:primary"]))

    rebuilt_store = JsonlDeviceSessionStore(store_path)
    rebuilt_registry = DeviceRegistry(store=rebuilt_store)
    rebuilt_manager = SessionManager(
        rebuilt_registry,
        ServerRunRuntime(ResultCollector()),
        store=rebuilt_store,
    )
    await rebuilt_manager.load_contexts_from_store()

    sessions = await rebuilt_registry.list(DeviceSelector(node_id="mac-device-jsonl"))
    reconnect = await rebuilt_manager.handle_reconnect(
        FakeWebSocket(),
        {
            "common": {"action": "reconnectRequest", "op_id": "op-reconnect-jsonl"},
            "data": {"node_id": "mac-device-jsonl"},
        },
    )

    assert sessions == []
    assert reconnect["data"]["state"] == 1
    reconnected = await rebuilt_registry.list(DeviceSelector(node_id="mac-device-jsonl"))
    assert [session.device.node_id for session in reconnected] == ["mac-device-jsonl"]
    assert reconnected[0].device.status == "online"


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_11A_jsonl_device_session_store_skips_bad_records_on_rebuild(tmp_path):
    from app.devices.device_runtime import JsonlDeviceSessionStore

    store_path = tmp_path / "device-sessions-with-bad-record.jsonl"
    store_path.write_text(
        "42\n"
        + json.dumps(
            {
                "kind": "device",
                "op": "upsert",
                "device": {"node_id": "mac-bad-device", "platform": 10},
            },
            sort_keys=True,
        )
        + "\n"
        + json.dumps(
            {
                "kind": "device",
                "op": "upsert",
                "device": {"node_id": "mac-device-jsonl", "platform": "mac"},
            },
            sort_keys=True,
        )
        + "\n"
        + json.dumps(
            {
                "kind": "context",
                "op": "upsert",
                "node_id": "mac-bad-version",
                "device": {"node_id": "mac-bad-version", "platform": "mac"},
                "callbacks": {},
                "version": "bad-version",
            },
            sort_keys=True,
        )
        + "\n"
        + json.dumps(
            {
                "kind": "context",
                "op": "upsert",
                "node_id": "mac-context-jsonl",
                "device": {"node_id": "mac-context-jsonl", "platform": "mac"},
                "callbacks": {},
                "version": 1,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    store = JsonlDeviceSessionStore(store_path)
    devices = await store.load_devices()
    contexts = await store.load_contexts()

    assert [device.node_id for device in devices] == ["mac-device-jsonl"]
    assert [context.node_id for context in contexts] == ["mac-context-jsonl"]
    assert "bad-version" in store_path.with_suffix(".jsonl.corrupt").read_text(encoding="utf-8")


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_12_jsonl_test_run_store_survives_rebuild(tmp_path):
    from app.runs.test_run_store import JsonlTestRunStore

    store_path = tmp_path / "test-runs.jsonl"
    collector = ResultCollector()
    runtime = ServerRunRuntime(collector, JsonlTestRunStore(store_path))
    run = TestRun(
        run_id="run-runtime-jsonl",
        status="queued",
        selector=DeviceSelector(),
        cases=[
            TestCase(
                case_id="case-runtime-jsonl",
                name="runtime jsonl",
                steps=[TestStep(step_id="step-runtime-jsonl")],
            )
        ],
    )
    await runtime.create_run(run)
    await runtime.start_run(run.run_id, [])
    await runtime.record_step_result(
        run.run_id,
        StepResult(case_id="case-runtime-jsonl", step_id="step-runtime-jsonl", status="failed"),
    )
    await runtime.finish_run(run.run_id, "failed", 123)

    rebuilt_runtime = ServerRunRuntime(collector, JsonlTestRunStore(store_path))

    restored = await rebuilt_runtime.get_run("run-runtime-jsonl")
    assert restored is not None
    assert restored.status == "failed"
    assert restored.results[0].step_id == "step-runtime-jsonl"


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_12A_jsonl_test_run_store_skips_bad_records_on_rebuild(tmp_path):
    from app.runs.test_run_store import JsonlTestRunStore

    store_path = tmp_path / "test-runs-with-bad-record.jsonl"
    run = TestRun(
        run_id="run-valid-jsonl",
        status="passed",
        selector=DeviceSelector(),
        cases=[],
    )
    store_path.write_text("[1, 2, 3]\n" + run.model_dump_json() + "\n", encoding="utf-8")

    rebuilt = JsonlTestRunStore(store_path)

    assert await rebuilt.get("run-valid-jsonl") is not None


@pytest.mark.anyio
async def test_E2E_LOG_03_local_jsonl_logs_can_replay_after_reconnect(tmp_path: Path):
    log_collector = ServerLogCollector()
    local_log_path = tmp_path / "beacon-agent-mac-reconnect.jsonl"
    offline_events = [
        {
            "event_id": "log-reconnect-offline-1",
            "timestamp_ms": 1500,
            "level": "warn",
            "run_id": "run-reconnect-replay",
            "case_id": "TC-LOG-RECONNECT-REPLAY",
            "step_id": "disconnect-window",
            "op_id": "op-reconnect-replay",
            "module": "link",
            "event": "link.reconnect.start",
            "message": "agent disconnected, buffering logs locally",
            "extra": {"attempt": 1, "owner_layer": "transport"},
        },
        {
            "event_id": "log-reconnect-offline-2",
            "timestamp_ms": 1600,
            "level": "info",
            "run_id": "run-reconnect-replay",
            "case_id": "TC-LOG-RECONNECT-REPLAY",
            "step_id": "disconnect-window",
            "op_id": "op-reconnect-replay",
            "module": "link",
            "event": "link.reconnect.success",
            "message": "agent reconnected, replaying local logs",
            "extra": {"attempt": 1, "owner_layer": "transport"},
        },
    ]
    local_log_path.write_text("\n".join(json.dumps(event, sort_keys=True) for event in offline_events) + "\n")

    replayed_events = [json.loads(line) for line in local_log_path.read_text(encoding="utf-8").splitlines()]
    stats = await log_collector.ingest("mac-reconnect", "lease-after-reconnect", replayed_events)
    logs = await log_collector.query_by_trace(
        "run-reconnect-replay",
        case_id="TC-LOG-RECONNECT-REPLAY",
        step_id="disconnect-window",
        op_id="op-reconnect-replay",
    )

    assert stats == {"accepted": 2, "duplicates": 0, "rejected": 0}
    assert local_log_path.exists()
    assert [event["event"] for event in logs] == ["link.reconnect.start", "link.reconnect.success"]
    assert {event["lease_id"] for event in logs} == {"lease-after-reconnect"}


@pytest.mark.anyio
async def test_IT_SRV_GATEWAY_handles_callback_event_packet_directly():
    registry = DeviceRegistry()
    collector = ResultCollector()
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    gateway = AgentGateway(manager, collector, run_runtime=run_runtime)
    websocket = FakeWebSocket()
    register_response = await manager.handle_register(websocket, register_packet("mac-1"))
    packet = {
        "common": {"action": "callbackEventRequest", "op_id": "op-gateway-event", "timestamp_ms": 1},
        "data": {
            "node_id": "mac-1",
            "lease_id": register_response["data"]["lease_id"],
            "event_id": "evt-op-gateway-event",
            "event_target": event_target("onJoin"),
            "payload": {},
            "callback_execution": {
                "defer_matched": True,
                "defer_executed": True,
                "call_results": [
                    {"target": target("snapshot"), "resource_ref": "engine_1", "error": 0, "message": "ok", "return_value": "{}"}
                ],
            },
        },
    }

    response = await gateway.handle_packet(websocket, packet)

    assert response["common"]["action"] == "callbackEventResponse"
    assert response["data"]["event_id"] == "evt-op-gateway-event"
    assert response["data"]["receipt"] == {
        "received": True,
        "recorded": True,
        "duplicate": False,
        "evidence_id": "evt-op-gateway-event",
    }
    assert "call_results" not in response["data"]
    assert "defer_matched" not in response["data"]
    assert (await collector.callback_events("mac-1"))[0].common["op_id"] == "op-gateway-event"


@pytest.mark.anyio
async def test_IT_SRV_RESULT_lifecycle_modules_are_independent():
    ack_tracker = AckTracker()
    event_store = EvidenceStore()
    pending = await ack_tracker.create_pending("mac-1", "op-ack", "invokeRequest", 1000)
    packet = {"common": {"action": "invokeResponse", "op_id": "op-ack"}, "data": {"code": 0, "message": "ok"}}

    assert await ack_tracker.resolve("mac-1", "op-ack", packet)
    assert await pending.future == packet
    await event_store.record_callback_event({"common": {"op_id": "op-event"}, "data": {"node_id": "mac-1", "event_target": event_target("onJoin")}})

    assert await ack_tracker.pending_count() == 0
    assert (await event_store.callback_events("mac-1"))[0].data["event_target"] == event_target("onJoin")


def test_IT_SRV_CMD_packet_builder_owns_wire_shape():
    builder = PacketBuilder()

    invoke = builder.invoke_request("mac-1", "lease-1", "op-invoke", [{"target": target("join"), "params": {"uid": 1}}])
    assert invoke["common"]["action"] == "invokeRequest"
    assert invoke["data"]["lease_id"] == "lease-1"
    assert invoke["data"]["list"] == [{"target": target("join"), "params": '{"uid":1}', "extra": "{}"}]


def test_IT_SRV_MODEL_01_and_02_context_models_are_separate_and_keep_definition():
    context = SessionContext(node_id="mac-1")
    context.callbacks["defer-1"] = {"key": "onJoin", "calls": []}

    assert context.node_id == "mac-1"
    assert context.callbacks["defer-1"]["key"] == "onJoin"


def test_error_packet_uses_protocol_error_shape():
    packet = create_error_packet("invokeResponse", "op-1", 404, "device offline")

    assert packet["common"]["action"] == "invokeResponse"
    assert packet["data"] == {"code": 404, "message": "device offline", "result": "{}"}


def test_UT_TARGET_CONTRACT_01_python_matches_shared_fixtures():
    import json
    from pathlib import Path

    from app.common.target_contract import TargetContractError, normalize_target, target_key

    fixture_path = Path(__file__).resolve().parents[2] / "test_cases/target_contract/targets.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    for case in cases:
        if case["valid"]:
            normalized = normalize_target(case["input"], case["profile"])
            assert normalized == case["normalized"], case["id"]
            assert target_key(normalized) == case["key"], case["id"]
        else:
            try:
                normalize_target(case["input"], case["profile"])
            except TargetContractError as exc:
                assert str(exc) == case["error"], case["id"]
            else:
                raise AssertionError(f"{case['id']} should have failed")


def test_UT_TARGET_CONTRACT_02_canonical_target_matches_contract():
    from app.reporting.evidence_runtime import canonical_target
    from app.common.target_contract import normalize_target

    target = {
        "sdk": "agora_rtc",
        "interface": "rtc_engine",
        "class_name": "AgoraRtcEngineKit",
        "function": "joinChannel",
    }

    assert canonical_target(target) == normalize_target(target, "call")


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_01_ingests_callback_event_and_returns_receipt():
    from app.runs.run_runtime import ServerRunRuntime

    collector = ResultCollector()
    runtime = ServerRunRuntime(collector)
    packet = {
        "common": {"action": "callbackEventRequest", "op_id": "op-runtime-event", "timestamp_ms": 1},
        "data": {
            "node_id": "mac-1",
            "event_id": "evt-runtime-1",
            "event_target": event_target("onJoin"),
            "payload": {"uid": 1001},
            "callback_context": {
                "provider": "agora_rtc/rtc_engine",
                "resource_ref": "engine_1",
                "instance_id": "engine_1",
                "sequence": 7,
            },
            "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
        },
    }

    receipt = await runtime.ingest_callback_event(packet)

    assert receipt["event_id"] == "evt-runtime-1"
    assert receipt["receipt"]["received"] is True
    assert receipt["receipt"]["recorded"] is True
    assert receipt["receipt"]["duplicate"] is False
    assert receipt["receipt"]["evidence_id"] == "evt-runtime-1"
    events = await collector.callback_events("mac-1")
    assert events[0].data["callback_context"]["resource_ref"] == "engine_1"


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_02_resolve_pending_completes_request():
    collector = ResultCollector()
    runtime = ServerRunRuntime(collector)
    registry = DeviceRegistry()
    session_manager = SessionManager(registry, runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=runtime)
    ws = FakeWebSocket()
    node_id = "mac-resolve"
    op_id = "op-runtime-resolve"
    await session_manager.handle_register(ws, register_packet(node_id))

    task = asyncio.create_task(
        dispatcher.send_protocol_invoke(node_id, [{"target": target("join")}], op_id, timeout_ms=5000)
    )
    await ws.wait_for_sends(1)

    assert await runtime.pending_count_for_device(node_id) == 1
    assert await runtime.resolve_pending(node_id, op_id, invoke_response(op_id)) is True

    response = await task
    assert response["common"]["op_id"] == op_id
    assert response["data"]["code"] == 0
    assert await runtime.pending_count_for_device(node_id) == 0


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_03_timeout_pending_marks_request_expired():
    """Test that timeout_pending properly expires a pending request."""
    from app.runs.run_runtime import ServerRunRuntime

    collector = ResultCollector()
    runtime = ServerRunRuntime(collector)
    registry = DeviceRegistry()
    session_manager = SessionManager(registry, runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=runtime)

    # Register a device first
    ws = FakeWebSocket()
    await session_manager.handle_register(ws, register_packet("mac-timeout"))

    # Create pending request with very short timeout
    result = await dispatcher.send_invoke("mac-timeout", [{"target": target("join")}], timeout_ms=1)

    # Should timeout and return 408
    assert result["data"]["code"] == 408
    pending_after = await collector.pending_count()
    assert pending_after == 0  # Pending should be cleaned up


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_04_fail_pending_for_device_clears_all_requests():
    """Test that fail_pending_for_device fails all pending requests for a device."""
    from app.runs.run_runtime import ServerRunRuntime

    collector = ResultCollector()
    runtime = ServerRunRuntime(collector)
    registry = DeviceRegistry()
    session_manager = SessionManager(registry, runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=runtime)

    # Register device
    ws = FakeWebSocket()
    await session_manager.handle_register(ws, register_packet("mac-fail"))

    # Create multiple pending requests
    tasks = [
        asyncio.create_task(dispatcher.send_invoke("mac-fail", [{"target": target("join")}], timeout_ms=5000))
        for _ in range(3)
    ]
    await asyncio.sleep(0.01)

    pending_before = await collector.pending_count()
    assert pending_before == 3

    # Fail all pending requests via ServerRunRuntime
    await runtime.fail_pending_for_device("mac-fail", "test failure")

    pending_after = await collector.pending_count()
    assert pending_after == 0

    # All tasks should complete with error
    for task in tasks:
        result = await task
        assert result["data"]["code"] != 0  # Should be error


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_05_cancel_pending_removes_single_request():
    collector = ResultCollector()
    runtime = ServerRunRuntime(collector)
    registry = DeviceRegistry()
    session_manager = SessionManager(registry, runtime)
    dispatcher = CommandDispatcher(registry, collector, run_runtime=runtime)
    ws = FakeWebSocket()
    node_id = "mac-cancel"
    cancelled_op_id = "op-runtime-cancelled"
    resolved_op_id = "op-runtime-resolved"
    await session_manager.handle_register(ws, register_packet(node_id))

    cancelled_task = asyncio.create_task(
        dispatcher.send_protocol_invoke(node_id, [{"target": target("join")}], cancelled_op_id, timeout_ms=5000)
    )
    resolved_task = asyncio.create_task(
        dispatcher.send_protocol_invoke(node_id, [{"target": target("leave")}], resolved_op_id, timeout_ms=5000)
    )
    await ws.wait_for_sends(2)

    assert await runtime.pending_count_for_device(node_id) == 2
    assert await runtime.cancel_pending(cancelled_op_id, reason="test cancellation", code=499) is True

    cancelled_response = await cancelled_task
    assert cancelled_response["common"]["op_id"] == cancelled_op_id
    assert cancelled_response["data"]["code"] == 499
    assert await runtime.pending_count_for_device(node_id) == 1

    assert await runtime.resolve_pending(node_id, resolved_op_id, invoke_response(resolved_op_id)) is True
    resolved_response = await resolved_task
    assert resolved_response["common"]["op_id"] == resolved_op_id
    assert resolved_response["data"]["code"] == 0
    assert await runtime.pending_count_for_device(node_id) == 0


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_06_record_evidence_writes_event():
    """Test that record_evidence properly writes evidence to store."""
    from app.reporting.evidence_runtime import Evidence
    from app.runs.run_runtime import ServerRunRuntime
    from dataclasses import asdict

    collector = ResultCollector()
    runtime = ServerRunRuntime(collector)

    # Create evidence with required source field
    evidence = Evidence(
        type="event",
        source="test",
        node_id="mac-evidence",
        target={"sdk": "mock", "class_name": "Mock", "function": "onJoin"},
        payload={"uid": 123},
        timestamp_ms=1000,
        run_id="run-test",
        case_id="case-test",
        step_id="step-test",
    )

    # Record via ServerRunRuntime
    recorded = await runtime.record_evidence(evidence)

    assert recorded is not None

    # Verify evidence was stored
    events = await collector.evidence_events("mac-evidence", run_id="run-test")
    assert len(events) >= 1
    # Find our event
    found = any(e.payload.get("uid") == 123 for e in events)
    assert found


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_07_duplicate_event_is_deduplicated():
    """Test that duplicate callback events are deduplicated."""
    from app.runs.run_runtime import ServerRunRuntime

    collector = ResultCollector()
    runtime = ServerRunRuntime(collector)

    packet = {
        "common": {"action": "callbackEventRequest", "op_id": "op-dup", "timestamp_ms": 1},
        "data": {
            "node_id": "mac-dup",
            "event_id": "evt-dup-1",
            "event_target": event_target("onJoin"),
            "payload": {},
            "callback_execution": {"defer_matched": False, "defer_executed": False, "call_results": []},
        },
    }

    # First ingestion
    receipt1 = await runtime.ingest_callback_event(packet)
    assert receipt1["receipt"]["recorded"] is True
    assert receipt1["receipt"]["duplicate"] is False

    # Second ingestion (same event_id)
    receipt2 = await runtime.ingest_callback_event(packet)
    assert receipt2["receipt"]["recorded"] is False
    assert receipt2["receipt"]["duplicate"] is True

    # Should only have one evidence
    events = await collector.evidence_events("mac-dup")
    assert len(events) == 1


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_08_dispatcher_creates_and_times_out_pending_via_run_runtime():
    from app.runs.run_runtime import ServerRunRuntime

    class SpyRuntime(ServerRunRuntime):
        def __init__(self, collector: ResultCollector) -> None:
            super().__init__(collector)
            self.created: list[tuple[str, str, str, int]] = []
            self.timed_out: list[str] = []

        async def create_pending(self, node_id: str, op_id: str, action: str, timeout_ms: int, **trace):
            self.created.append((node_id, op_id, action, timeout_ms))
            return await super().create_pending(node_id, op_id, action, timeout_ms, **trace)

        async def timeout_pending(self, op_id: str) -> bool:
            self.timed_out.append(op_id)
            return await super().timeout_pending(op_id)

    registry = DeviceRegistry()
    collector = ResultCollector()
    runtime = SpyRuntime(collector)
    manager = SessionManager(registry, runtime)
    await manager.handle_register(FakeWebSocket(), register_packet("mac-runtime-1"))
    dispatcher = CommandDispatcher(registry, collector, run_runtime=runtime)

    result = await dispatcher.send_invoke("mac-runtime-1", [{"target": target("join")}], timeout_ms=1)

    assert result["data"]["code"] == 408
    assert runtime.created and runtime.created[0][0] == "mac-runtime-1"
    assert runtime.timed_out == [runtime.created[0][1]]


@pytest.mark.anyio
async def test_IT_SRV_RUNTIME_09_gateway_resolves_invoke_response_via_run_runtime():
    from app.runs.run_runtime import ServerRunRuntime

    class SpyRuntime(ServerRunRuntime):
        def __init__(self, collector: ResultCollector) -> None:
            super().__init__(collector)
            self.resolved: list[tuple[str, str]] = []

        async def resolve_pending(self, node_id: str, op_id: str, packet: dict[str, object]) -> bool:
            self.resolved.append((node_id, op_id))
            return await super().resolve_pending(node_id, op_id, packet)

    collector = ResultCollector()
    runtime = SpyRuntime(collector)
    manager = SessionManager(DeviceRegistry(), runtime)
    register_response = await manager.handle_register(FakeWebSocket(), register_packet("mac-1"))
    gateway = AgentGateway(manager, collector, runtime)

    response = await gateway.handle_packet(
        None,
        {
            "common": {"action": "invokeResponse", "op_id": "op-runtime-ack"},
            "data": {"node_id": "mac-1", "lease_id": register_response["data"]["lease_id"], "code": 0},
        },
    )

    assert response is None
    assert runtime.resolved == [("mac-1", "op-runtime-ack")]
