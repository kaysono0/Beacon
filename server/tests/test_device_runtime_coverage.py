import json

import pytest

from app.devices.connection_diagnostics import ConnectionEventStore
from app.devices.device_models import Device, DeviceSelector, DeviceSession, SessionContext
from app.devices.device_runtime import DeviceRegistry, JsonlDeviceSessionStore, SessionManager
from app.reporting.evidence_runtime import ResultCollector
from app.runs.run_runtime import ServerRunRuntime


class FakeWebSocket:
    async def send_json(self, packet: dict) -> None:
        _ = packet


def _register_packet(node_id: str, *, platform: str = "mac", tags: list[str] | None = None) -> dict:
    return {
        "common": {"action": "registerRequest", "op_id": f"op-register-{node_id}"},
        "data": {"node_id": node_id, "platform": platform, "tags": tags or []},
    }


@pytest.mark.anyio
async def test_IT_SRV_DEVICE_RUNTIME_01_jsonl_recovery_applies_removes_and_quarantines_bad_contexts(tmp_path) -> None:
    store_path = tmp_path / "device-sessions.jsonl"
    store_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "device",
                        "op": "upsert",
                        "device": {"node_id": "device-removed", "platform": "mac"},
                    },
                    sort_keys=True,
                ),
                json.dumps({"kind": "device", "op": "remove", "node_id": "device-removed"}, sort_keys=True),
                json.dumps({"kind": "device", "op": "upsert"}, sort_keys=True),
                json.dumps(
                    {
                        "kind": "context",
                        "op": "upsert",
                        "node_id": "context-removed",
                        "device": {"node_id": "context-removed", "platform": "mac"},
                        "callbacks": {},
                    },
                    sort_keys=True,
                ),
                json.dumps({"kind": "context", "op": "remove", "node_id": "context-removed"}, sort_keys=True),
                json.dumps(
                    {
                        "kind": "context",
                        "op": "upsert",
                        "node_id": "context-bad-callbacks",
                        "device": {"node_id": "context-bad-callbacks", "platform": "mac"},
                        "callbacks": ["not", "an", "object"],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "kind": "context",
                        "op": "upsert",
                        "node_id": "context-valid",
                        "device": {"node_id": "context-valid", "platform": "mac"},
                        "callbacks": {"cb-1": {"target": "joined"}},
                        "version": 2,
                    },
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    store = JsonlDeviceSessionStore(store_path)

    devices = await store.load_devices()
    contexts = await store.load_contexts()

    assert devices == []
    assert [context.node_id for context in contexts] == ["context-valid"]
    assert contexts[0].callbacks == {"cb-1": {"target": "joined"}}
    corrupt = store_path.with_suffix(".jsonl.corrupt").read_text(encoding="utf-8")
    assert '"callbacks": ["not", "an", "object"]' in corrupt
    assert '"op": "upsert"' in corrupt


@pytest.mark.anyio
async def test_IT_SRV_DEVICE_RUNTIME_02_registry_selectors_preserve_index_and_fallback_filters() -> None:
    registry = DeviceRegistry()
    await registry.upsert(
        DeviceSession(
            device=Device(node_id="device-primary", platform="mac", group_id="group-a", tags=["role:primary"]),
            websocket=FakeWebSocket(),
            lease_id="lease-primary",
        )
    )
    await registry.upsert(
        DeviceSession(
            device=Device(node_id="device-peer", platform="mac", group_id="group-b", tags=["role:peer"]),
            websocket=FakeWebSocket(),
            lease_id="lease-peer",
        )
    )

    assert await registry.list(DeviceSelector(node_id="device-primary", platform="ios")) == []
    assert await registry.list(DeviceSelector(node_id="device-primary", group_id="group-b")) == []
    assert await registry.list(DeviceSelector(node_id="device-primary", tags=["role:peer"])) == []
    assert [
        session.device.node_id
        for session in await registry.list(DeviceSelector(group_id="group-a", tags=["role:primary"]))
    ] == ["device-primary"]
    assert await registry.list(DeviceSelector(group_id="group-a", tags=["role:peer"])) == []
    assert await registry.list(DeviceSelector(platform="android")) == []
    assert await registry.list(DeviceSelector(tags=["missing-tag"])) == []


@pytest.mark.anyio
async def test_IT_SRV_DEVICE_RUNTIME_03_stale_disconnect_keeps_active_session_and_pending() -> None:
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    run_runtime = ServerRunRuntime(collector)
    manager = SessionManager(registry, run_runtime)
    first_ws = FakeWebSocket()
    second_ws = FakeWebSocket()
    await manager.handle_register(first_ws, _register_packet("device-stale"))
    second_response = await manager.handle_register(second_ws, _register_packet("device-stale"))
    await run_runtime.create_pending("device-stale", "op-active", "invokeRequest", 5000)

    await manager.handle_disconnect(first_ws)

    active_session = await registry.get("device-stale")
    assert active_session is not None
    assert active_session.websocket is second_ws
    assert active_session.lease_id == second_response["data"]["lease_id"]
    assert await run_runtime.pending_count_for_device("device-stale") == 1
    events = await diagnostics.query(node_id="device-stale", event_type="stale_disconnect_ignored")
    assert len(events) == 1
    assert events[0].lease_id == second_response["data"]["lease_id"]
    assert events[0].details["stale_lease_id"] != events[0].lease_id


@pytest.mark.anyio
async def test_IT_SRV_DEVICE_RUNTIME_04_registry_replaces_indexes_and_persists_removes(tmp_path) -> None:
    store = JsonlDeviceSessionStore(tmp_path / "device-sessions.jsonl")
    registry = DeviceRegistry(store=store)
    original = DeviceSession(
        device=Device(node_id="device-index", platform="mac", group_id="group-a", tags=["role:primary"]),
        websocket=FakeWebSocket(),
        lease_id="lease-original",
    )
    replacement = DeviceSession(
        device=Device(node_id="device-index", platform="ios", group_id="group-b", tags=["role:peer"]),
        websocket=FakeWebSocket(),
        lease_id="lease-replacement",
    )

    assert await registry.upsert(original) is None
    assert await registry.upsert(replacement) == original
    assert [session.device.node_id for session in await registry.list(None)] == ["device-index"]
    assert await registry.list(DeviceSelector(platform="mac")) == []
    assert await registry.list(DeviceSelector(group_id="group-a")) == []
    assert await registry.list(DeviceSelector(tags=["role:primary"])) == []
    assert [session.device.node_id for session in await registry.list(DeviceSelector(platform="ios", tags=["role:peer"]))] == [
        "device-index"
    ]

    await registry.remove("device-index")
    assert await registry.list(None) == []
    await registry.load_from_store()
    assert await store.load_devices() == []


@pytest.mark.anyio
async def test_IT_SRV_DEVICE_RUNTIME_05_session_context_store_handles_removes_and_bad_records(tmp_path) -> None:
    store = JsonlDeviceSessionStore(tmp_path / "contexts.jsonl")
    await store.remove_context("context-missing")
    await store.upsert_context(
        SessionContext(
            node_id="context-valid",
            device=Device(node_id="context-valid", platform="mac"),
            callbacks={"callback-1": {"target": "event"}},
            version=2,
        )
    )
    await store.remove_context("context-valid")
    store_path = tmp_path / "contexts.jsonl"
    store_path.write_text(
        store_path.read_text(encoding="utf-8")
        + json.dumps({"kind": "device", "op": "upsert", "node_id": "bad-device"}, sort_keys=True)
        + "\n"
        + json.dumps(
            {"kind": "context", "op": "upsert", "node_id": "bad-version", "callbacks": {}, "version": "bad"},
            sort_keys=True,
        )
        + "\n"
        + json.dumps(["not", "a", "record"])
        + "\n{bad-json\n",
        encoding="utf-8",
    )

    assert await store.load_contexts() == []
    assert await store.load_devices() == []
    corrupt = store_path.with_suffix(".jsonl.corrupt").read_text(encoding="utf-8")
    assert '"bad-device"' in corrupt
    assert '"bad-version"' in corrupt
    assert '["not", "a", "record"]' in corrupt
    assert "{bad-json" in corrupt


@pytest.mark.anyio
async def test_IT_SRV_DEVICE_RUNTIME_06_session_manager_reconnect_unregister_and_clear_contexts(tmp_path) -> None:
    registry = DeviceRegistry()
    diagnostics = ConnectionEventStore()
    collector = ResultCollector(connection_diagnostics=diagnostics)
    manager = SessionManager(registry, ServerRunRuntime(collector), store=JsonlDeviceSessionStore(tmp_path / "sessions.jsonl"))

    missing_reconnect = await manager.handle_reconnect(
        FakeWebSocket(),
        {"common": {"action": "reconnectRequest", "op_id": "op-reconnect"}, "data": {"node_id": "device-missing"}},
    )
    assert missing_reconnect["data"]["state"] == 0
    assert await diagnostics.query(node_id="device-missing", event_type="reconnect_requires_register")

    websocket = FakeWebSocket()
    registered = await manager.handle_register(websocket, _register_packet("device-managed"))
    assert registered["data"]["state"] == 1
    stale_socket = FakeWebSocket()
    await manager.handle_register(stale_socket, _register_packet("device-managed"))
    stale_unregister = await manager.handle_unregister(websocket, {"common": {"action": "unregisterRequest"}, "data": {}})
    assert stale_unregister["data"]["code"] == 0
    assert await diagnostics.query(node_id="device-managed", event_type="stale_unregister_ignored")

    await manager.clear_context("device-managed")
    assert await manager.context("device-managed") is None

    no_store_manager = SessionManager(DeviceRegistry(), ServerRunRuntime(ResultCollector()))
    await no_store_manager.load_contexts_from_store()
