#!/usr/bin/env python3
"""启动 Mac Console 本地手动验证服务。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
AUTH_TOKEN = os.environ.setdefault("BEACON_AUTH_TOKEN", "local-test-token")
PORT = int(os.environ.get("BEACON_CONSOLE_SERVER_PORT", "8000"))
PRIMARY_REAL_NODE_ID = "mac-real-e2e-001"
PEER_REAL_NODE_ID = "mac-real-peer-e2e-001"
PEER_B_REAL_NODE_ID = "mac-real-peer-b-e2e-001"

sys.path.insert(0, str(ROOT / "server"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import HTTPException, Request  # noqa: E402

from app.main import app  # noqa: E402
from app.sdk.sdk_extensions import AGORA_RTC_TOKEN_PLACEHOLDER, TOKEN_MAP_ENV, token_map_key  # noqa: E402


from scripts.support.native_case_catalog import load_cases  # noqa: E402

from scripts.validation.run_mac_agora_e2e_tests import (  # noqa: E402
    agora_framework_exists,
    configure_rtc_token,
    missing_real_env,
    run,
    start_native_websocket_agent,
    stop_native_websocket_agent,
    wait_for_registered_device,
)


async def wait_http(base_url: str) -> None:
    async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
        for _ in range(100):
            try:
                if (await client.get(f"{base_url}/api/v1/status")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    raise RuntimeError("server did not start")


def ensure_port_available(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise RuntimeError(f"Beacon console server port {port} is already in use") from exc


async def wait_for_owned_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    for _ in range(100):
        if server.started:
            return
        if not thread.is_alive():
            raise RuntimeError("Beacon console server process stopped before startup completed")
        await asyncio.sleep(0.05)
    raise RuntimeError("Beacon console server did not finish startup")


class ConsoleMockAgent:
    def __init__(self, node_id: str, websocket) -> None:
        self.node_id = node_id
        self.websocket = websocket
        self.lease_id = ""
        self._pending: dict[str, asyncio.Queue[dict]] = {
            "registerResponse": asyncio.Queue(),
            "reconnectResponse": asyncio.Queue(),
        }

    async def register(self) -> None:
        response = await self.send_and_wait(
            {
                "common": {"action": "registerRequest", "op_id": f"op-register-{self.node_id}", "timestamp_ms": 1},
                "data": {
                    "node_id": self.node_id,
                    "platform": "mac",
                    "tags": ["local-console"],
                    "capabilities": ["rtc.mock"],
                },
            },
            "registerResponse",
        )
        code = response.get("data", {}).get("code", 1)
        if code != 0:
            raise RuntimeError(f"mock agent register failed: {self.node_id} {response}")
        if not self.lease_id:
            raise RuntimeError(f"mock agent register missing lease: {self.node_id} {response}")

    async def send_and_wait(self, packet: dict, response_action: str) -> dict:
        await self.websocket.send(json.dumps(packet))
        response = await self._pending[response_action].get()
        data = response.get("data", {})
        if response_action in {"registerResponse", "reconnectResponse"} and isinstance(data, dict):
            self.lease_id = data.get("lease_id") or self.lease_id
        return response

    async def pump(self) -> None:
        import websockets

        try:
            while True:
                packet = json.loads(await self.websocket.recv())
                action = packet.get("common", {}).get("action", "")
                if action in self._pending:
                    await self._pending[action].put(packet)
                elif action == "invokeRequest":
                    await self._handle_invoke(packet)
                elif action == "callbackEventResponse":
                    continue
        except websockets.ConnectionClosed:
            return

    async def _handle_invoke(self, packet: dict) -> None:
        data = packet.get("data", {})
        call = (data.get("list") or [{}])[0]
        extra = _json_object(call.get("extra", {}))
        params = _json_object(call.get("params", {}))
        target = call.get("target", {})
        await self.websocket.send(
            json.dumps(
                {
                    "common": {
                        "action": "invokeResponse",
                        "op_id": packet.get("common", {}).get("op_id", ""),
                        "timestamp_ms": 1,
                    },
                    "data": {
                        "node_id": data.get("node_id", self.node_id),
                        "lease_id": self.lease_id,
                        "code": 0,
                        "message": "ok",
                        "result": _result_for(target),
                    },
                }
            )
        )
        if target.get("function") == "joinChannel":
            await self._send_join_event(extra, params)

    async def _send_join_event(self, extra: dict, params: dict) -> None:
        event_id = f"evt-{self.node_id}-{uuid.uuid4().hex}"
        await self.websocket.send(
            json.dumps(
                {
                    "common": {
                        "action": "callbackEventRequest",
                        "op_id": event_id,
                        "timestamp_ms": 2,
                    },
                    "data": {
                        "event_id": event_id,
                        "node_id": self.node_id,
                        "lease_id": self.lease_id,
                        "run_id": extra.get("run_id"),
                        "case_id": extra.get("case_id"),
                        "step_id": extra.get("step_id"),
                        "event_target": {
                            "sdk": "agora_rtc",
                            "interface": "rtc_engine",
                            "class_name": "AgoraRtcEngineDelegate",
                            "function": "onJoinChannelSuccess",
                        },
                        "payload": {
                            "channel": params.get("channel", "smoke"),
                            "uid": params.get("uid", 1001),
                            "elapsed_ms": 1,
                        },
                    },
                }
            )
        )


def _json_object(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _result_for(target: dict) -> str:
    if target.get("function") == "getConnectionState":
        return json.dumps({"state": "connected"}, separators=(",", ":"))
    return "{}"


async def start_agent(ws_url: str, node_id: str) -> ConsoleMockAgent:
    import websockets

    query = urlencode({"token": AUTH_TOKEN})
    websocket = await websockets.connect(f"{ws_url}/api/v1/agent/ws?{query}", proxy=None)
    agent = ConsoleMockAgent(node_id, websocket)
    pump_task = asyncio.create_task(agent.pump())
    await agent.register()
    agent.pump_task = pump_task
    return agent


def _agent_mode() -> str:
    mode = os.environ.get("BEACON_CONSOLE_AGENT_MODE", "auto").strip().lower()
    if mode not in {"auto", "mock", "real"}:
        raise RuntimeError(f"unsupported BEACON_CONSOLE_AGENT_MODE: {mode}")
    return mode


def _real_agent_available() -> bool:
    return not missing_real_env() and agora_framework_exists()


def _case_token_requests(cases: list[dict]) -> set[tuple[str, int]]:
    requests: set[tuple[str, int]] = set()
    for case in cases:
        if case.get("implementation_status") != "runnable":
            continue
        for channel, uid in case.get("token_bindings", []):
            if isinstance(channel, str) and isinstance(uid, int):
                requests.add((channel, uid))
    return requests


def _build_rtc_token(channel: str, uid: int) -> str:
    expire_at = int(time.time()) + 3600
    return subprocess.check_output(
        [
            "uv",
            "run",
            "--python",
            "3.11",
            "--extra",
            "agora",
            "python",
            "-c",
            (
                "from agora_token_builder import RtcTokenBuilder;"
                "import os,sys;"
                "sys.stdout.write(RtcTokenBuilder.buildTokenWithUid("
                f"os.environ['AGORA_APP_ID'], os.environ['AGORA_APP_CERT'], {channel!r}, {uid}, 1, {expire_at}))"
            ),
        ],
        cwd=ROOT / "server",
        text=True,
    )


def configure_console_case_token_map() -> None:
    token_requests = sorted(_case_token_requests([case for case in load_cases() if case["platform"] == "mac"]))
    token_map = {token_map_key(channel, uid): _build_rtc_token(channel, uid) for channel, uid in token_requests}
    if token_map:
        os.environ[TOKEN_MAP_ENV] = json.dumps(token_map, separators=(",", ":"), sort_keys=True)
    else:
        os.environ.pop(TOKEN_MAP_ENV, None)


async def start_mock_agents(ws_url: str) -> list[ConsoleMockAgent]:
    agents: list[ConsoleMockAgent] = []
    try:
        for node_id in ("mac-local-001", PRIMARY_REAL_NODE_ID):
            agents.append(await start_agent(ws_url, node_id))
    except Exception:
        await stop_mock_agents(agents)
        raise
    return agents


async def stop_mock_agents(agents: list[ConsoleMockAgent]) -> None:
    for agent in agents:
        await agent.websocket.close()
        agent.pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await agent.pump_task


async def start_real_agents(base_url: str, ws_url: str) -> list[asyncio.subprocess.Process]:
    configure_rtc_token()
    configure_console_case_token_map()
    run(["cmake", "-S", ".", "-B", ".build/default"])
    run(["cmake", "--build", ".build/default", "--target", "mac_real_agent_bridge"])
    agents: list[asyncio.subprocess.Process] = []
    try:
        for node_id, tags in (
            (PRIMARY_REAL_NODE_ID, ["real-e2e", "real-primary", "role:primary"]),
            (PEER_REAL_NODE_ID, ["real-e2e", "real-peer", "role:peer"]),
            (PEER_B_REAL_NODE_ID, ["real-e2e", "real-peer-b", "role:peer_b"]),
        ):
            agents.append(await start_native_websocket_agent(ws_url, node_id=node_id, tags=tags))
        for node_id, process in zip(
            (PRIMARY_REAL_NODE_ID, PEER_REAL_NODE_ID, PEER_B_REAL_NODE_ID),
            agents,
            strict=True,
        ):
            await wait_for_registered_device(base_url, process, node_id)
    except Exception:
        for process in agents:
            await stop_native_websocket_agent(process)
        raise
    return agents


async def start_console_agents(base_url: str, ws_url: str) -> tuple[str, list[object]]:
    mode = _agent_mode()
    if mode == "real" or (mode == "auto" and _real_agent_available()):
        if not _real_agent_available():
            raise RuntimeError("real console agent mode requires AGORA_MAC_SDK_ROOT, AGORA_APP_ID, AGORA_APP_CERT, and BEACON_AUTH_TOKEN")
        return "real", await start_real_agents(base_url, ws_url)
    return "mock", await start_mock_agents(ws_url)


async def stop_console_agents(mode: str, agents: list[object]) -> None:
    if mode == "real":
        for process in agents:
            await stop_native_websocket_agent(process)
    else:
        await stop_mock_agents([agent for agent in agents if isinstance(agent, ConsoleMockAgent)])


async def serve_until_stopped(
    base_url: str,
    ws_url: str,
    stop_event: threading.Event,
    server: uvicorn.Server,
    server_thread: threading.Thread,
) -> None:
    await wait_for_owned_server(server, server_thread)
    await wait_http(base_url)
    mode, agents = await start_console_agents(base_url, ws_url)
    print(f"Beacon Mac Console local server ready: {base_url} agent_mode={mode}")
    if mode == "real":
        print(f"BEACON_NODE_ID={PRIMARY_REAL_NODE_ID}")
    try:
        while not stop_event.is_set():
            await asyncio.sleep(0.2)
    finally:
        await stop_console_agents(mode, agents)


def main() -> int:
    os.environ.setdefault("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    ensure_port_available("127.0.0.1", PORT)
    base_url = f"http://127.0.0.1:{PORT}"
    import app.main as server_main
    server_main.runner_supervisor._process._base_url = base_url
    ws_url = f"ws://127.0.0.1:{PORT}"
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    stop_event = threading.Event()

    async def request_console_shutdown(request: Request) -> dict[str, str]:
        if request.headers.get("authorization") != f"Bearer {AUTH_TOKEN}":
            raise HTTPException(status_code=401, detail="invalid auth token")
        stop_event.set()
        server.should_exit = True
        return {"status": "shutting_down"}

    app.add_api_route("/api/v1/console/shutdown", request_console_shutdown, methods=["POST"])

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()
        server.should_exit = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        asyncio.run(serve_until_stopped(base_url, ws_url, stop_event, server, thread))
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
