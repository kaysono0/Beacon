#!/usr/bin/env python3
"""运行 IR-08 独立 Runner、Mock Agent、Observation 和报告纵向 tracer。"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "python_sdk"))
os.environ.setdefault("BEACON_AUTH_TOKEN", "local-target-test-token")

import httpx  # noqa: E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402


import scripts.validation.run_e2e_mock_tests as mock  # noqa: E402
from app import main as server_main  # noqa: E402


MIGRATION_CASES = (
    "TC-PY-COMMON-SMOKE",
    "TC-PY-MOCK-COMPLEX-REFERENCE-TRACER",
    "TC-PY-MOCK-COMPLEX-DIRECT-MATRIX",
    "TC-COMMON-ECHO-CALL",
    "TC-COMMON-ECHO-CALLBACK",
    "TC-COMMON-ECHO-STATE",
    "TC-PY-VOLCENGINE-L1-LIFECYCLE",
    "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK",
    "TC-PY-VOLCENGINE-L1-CONNECTION-STATE",
    "TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP",
    "TC-PY-VOLCENGINE-L1-INVALID-TOKEN",
    "TC-PY-VOLCENGINE-L1-RUNTIME-CLEANUP-BASELINE",
    "TC-PY-AGORA-SMOKE",
    "TC-PY-AGORA-JOIN-CALLBACK",
    "TC-PY-AGORA-LEAVE-STATE",
    "TC-PY-AGORA-INVALID-TOKEN",
    "TC-COMMON-SMOKE",
    "TC-PY-PROTOCOL-OPERATION-JOIN-TRACER",
    "TC-MAC-AGORA-JOIN-CALLBACK-SUCCESS",
    "TC-MAC-SMOKE",
    "TC-MAC-AGORA-CONNECTION-STATE-SEQUENCE",
    "TC-MAC-AGORA-CONNECTION-STATE-TRANSITION",
    "TC-MAC-AGORA-PREVIEW-CONTROL",
    "TC-MAC-AGORA-PREVIEW-LIFECYCLE-AROUND-JOIN",
    "TC-PY-ZEGO-L1-LIFECYCLE",
    "TC-PY-ZEGO-L1-LOGIN-CALLBACK",
    "TC-PY-ZEGO-L1-LOGOUT-CALLBACK",
    "TC-MAC-AGORA-PERMISSION-DENIED-JOIN-FAILURE",
    "TC-MAC-AGORA-PERMISSION-DENIED-PREVIEW-FAILURE",
    "TC-MAC-AGORA-SUCCESS-THEN-LEAVE-CLEANUP",
    "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE",
    "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
    "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE",
    "TC-MAC-AGORA-REAL-LIFECYCLE",
    "TC-MAC-AGORA-INVALID-TOKEN-FAILURE",
    "TC-MAC-AGORA-INVALID-TOKEN-ONERROR-DIAGNOSTIC",
    "TC-MAC-AGORA-INVALID-TOKEN-THEN-RECOVER",
    "TC-MAC-AGORA-TOKEN-RENEWAL-RECOVERY",
    "TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT",
    "TC-MAC-AGORA-RTC-STATS-OBSERVABLE",
    "TC-MAC-AGORA-AUDIO-ONLY-DIRECT-CALL",
    "TC-MAC-AGORA-LOCAL-VIDEO-STATS-OBSERVABLE",
)
MULTI_DEVICE_CASES = (
    "TC-PY-ZEGO-L1-1V1-ROOM-CONNECTED",
    "TC-PY-AGORA-1V1-REMOTE-VIDEO",
    "TC-MAC-AGORA-REMOTE-AUDIO-STATS-OBSERVABLE",
    "TC-MAC-AGORA-REMOTE-VIDEO-STATS-OBSERVABLE",
    "TC-MAC-AGORA-1V1-REMOTE-VIDEO-RENDERED",
    "TC-MAC-AGORA-1V1-REMOTE-VIDEO-SYNTH-PEER",
    "TC-MAC-AGORA-1V1-AUDIO-MUTE-RECOVER",
    "TC-MAC-AGORA-1V1-AUDIO-PLAYBACK-MUTE-RECOVER",
    "TC-MAC-AGORA-1V1-MEDIA-PLAYER-PAUSE-RESUME",
    "TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE",
    "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH",
    "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED",
    "TC-PY-ZEGO-L1-1V1-VIDEO-RENDER-SNAPSHOT",
    "TC-PY-ZEGO-L1-1V1-VIDEO-SYNTH-RENDER-SNAPSHOT",
)
SMALL_ROOM_CASES = ("TC-MAC-AGORA-SMALL-ROOM-BASELINE",)
GRID4_CASES = ("TC-MAC-AGORA-4-GRID-CAMERA-MEDIA-SEGMENTS",)
GRID9_CASES = ("TC-MAC-AGORA-9-GRID-CAMERA-MEDIA-SEGMENTS",)
GRID9_ROLES = ("primary", "segment_1", "segment_2", "segment_3", "segment_4", "segment_5", "segment_6", "segment_7", "segment_8")


async def _finished(client: httpx.AsyncClient, base_url: str, run_id: str) -> dict:
    """从正式读取端点等待 Server 终态，不直接改运行态。"""

    for _ in range(200):
        response = await client.get(f"{base_url}/api/v1/console/test-runs/{run_id}", headers=mock.AUTH)
        assert response.status_code == 200, response.text
        run = response.json()["run"]
        if run["status"] in ("passed", "failed", "cancelled"):
            return run
        await asyncio.sleep(0.05)
    raise AssertionError("target run did not finish")


async def _run(base_url: str, ws_url: str) -> None:
    """使用正式 run 入口、WebSocket Agent 和 Runner 子进程跑单角色用例。"""

    async with websockets.connect(f"{ws_url}/api/v1/agent/ws?token={mock.AUTH_TOKEN}", proxy=None) as websocket:
        agent = mock.MockAgentHarness(websocket, target_mode=True)
        pump = asyncio.create_task(agent.pump())
        try:
            registered = await agent.send_and_wait({
                "common": {"action": "registerRequest", "op_id": "target-register", "timestamp_ms": 1},
                "data": {"node_id": "mac-target-001", "platform": "mac", "tags": ["mock-e2e"], "capabilities": ["rtc.mock"]},
            }, "registerResponse")
            assert registered["data"]["code"] == 0
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                for case_id in MIGRATION_CASES:
                    response = await client.post(
                        f"{base_url}/api/v1/test-runs", headers=mock.AUTH,
                        json={"selector": {"platform": "mac", "tags": ["mock-e2e"]}, "case_ids": [case_id]},
                    )
                    assert response.status_code == 200, response.text
                    run = await _finished(client, base_url, response.json()["run_id"])
                    report_response = await client.get(
                        f"{base_url}/api/v1/test-runs/{run['run_id']}/report", headers=mock.AUTH,
                    )
                    assert report_response.status_code == 200, report_response.text
                    report = report_response.json()
                    assert run["status"] == "passed", (case_id, run["case_results"], report["case_results"])
                    assert report["case_results"][0]["case_id"] == case_id
                    assert report["case_results"][0]["operations"]
                    if case_id == "TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT":
                        assert any(
                            fact["payload"].get("operation_type") == "wait" and fact["payload"].get("outcome") == "timed_out"
                            for fact in report["case_results"][0]["operations"]
                        )
            assert agent.reset_phases == ["pre", "final"] * len(MIGRATION_CASES)
        finally:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump


async def _run_multi_device(base_url: str, ws_url: str, roles: tuple[str, ...], cases: tuple[str, ...]) -> None:
    """为每个 role 注册独立 Agent，检查绑定与 lease 没有串线。"""
    async with contextlib.AsyncExitStack() as stack:
        sockets = [
            await stack.enter_async_context(websockets.connect(f"{ws_url}/api/v1/agent/ws?token={mock.AUTH_TOKEN}", proxy=None))
            for _ in roles
        ]
        room_members: dict[str, set[int | str]] = {}
        agents = tuple(mock.MockAgentHarness(sock, target_mode=True, room_members=room_members) for sock in sockets)
        pumps = [asyncio.create_task(agent.pump()) for agent in agents]
        leases: dict[str, str] = {}
        try:
            for role, agent in zip(roles, agents, strict=True):
                response = await agent.send_and_wait({
                    "common": {"action": "registerRequest", "op_id": f"target-register-{role}", "timestamp_ms": 1},
                    "data": {
                        "node_id": f"mac-target-{role}", "platform": "mac", "group_id": "target-pair",
                        "tags": ["mock-e2e", f"role:{role}"], "capabilities": ["rtc.mock"],
                    },
                }, "registerResponse")
                assert response["data"]["code"] == 0
                leases[role] = response["data"]["lease_id"]
            assert len(set(leases.values())) == len(roles)
            async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                for case_id in cases:
                    response = await client.post(
                        f"{base_url}/api/v1/test-runs", headers=mock.AUTH,
                        json={"selector": {"platform": "mac", "group_id": "target-pair", "tags": ["mock-e2e"]}, "case_ids": [case_id]},
                    )
                    assert response.status_code == 200, response.text
                    run = await _finished(client, base_url, response.json()["run_id"])
                    assert run["status"] == "passed", (case_id, run["case_results"])
                    report_response = await client.get(f"{base_url}/api/v1/test-runs/{run['run_id']}/report", headers=mock.AUTH)
                    assert report_response.status_code == 200, report_response.text
                    facts = report_response.json()["case_results"][0]["observations"]
                    assert {fact["device_role"] for fact in facts if fact["kind"] == "operation"} == set(roles)
                    assert all(
                        (fact["node_id"], fact["lease_id"]) == (f"mac-target-{fact['device_role']}", leases[fact["device_role"]])
                        for fact in facts if fact["kind"] == "operation"
                    )
            assert all(agent.reset_phases == ["pre", "final"] * len(cases) for agent in agents)
        finally:
            for pump in pumps:
                pump.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)


def main() -> int:
    """启动同机 Server 并保证测试结束后停止监听线程。"""

    port = mock.free_port()
    base_url = f"http://127.0.0.1:{port}"
    server_main.runner_supervisor._process._base_url = base_url
    original_started = server_main.runner_case_registry.record_started
    runner_pids: list[int] = []

    async def observed_started(context, payload):
        runner_pids.append(payload.pid)
        return await original_started(context, payload)

    server_main.runner_case_registry.record_started = observed_started
    server = uvicorn.Server(uvicorn.Config(server_main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        asyncio.run(mock.wait_http(base_url))
        asyncio.run(_run(base_url, f"ws://127.0.0.1:{port}"))
        asyncio.run(_run_multi_device(base_url, f"ws://127.0.0.1:{port}", ("primary", "peer"), MULTI_DEVICE_CASES))
        asyncio.run(_run_multi_device(base_url, f"ws://127.0.0.1:{port}", ("primary", "peer", "peer_b"), SMALL_ROOM_CASES))
        asyncio.run(_run_multi_device(base_url, f"ws://127.0.0.1:{port}", ("primary", "segment_1", "segment_4", "segment_7"), GRID4_CASES))
        asyncio.run(_run_multi_device(base_url, f"ws://127.0.0.1:{port}", GRID9_ROLES, GRID9_CASES))
        migrated_count = len(MIGRATION_CASES) + len(MULTI_DEVICE_CASES) + len(SMALL_ROOM_CASES) + len(GRID4_CASES) + len(GRID9_CASES)
        assert len(runner_pids) == migrated_count
        assert len(set(runner_pids)) == len(runner_pids)
        assert all(pid != os.getpid() for pid in runner_pids)
        print(f"production mock tracer: PASS ({migrated_count} migrated cases)")
        return 0
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        server_main.runner_case_registry.record_started = original_started


if __name__ == "__main__":
    raise SystemExit(main())
