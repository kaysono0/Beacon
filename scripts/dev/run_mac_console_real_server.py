#!/usr/bin/env python3
"""启动一个 Beacon Server，并注册三家 SDK 的真实 Mac Agent。"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_TOKEN = os.environ["BEACON_AUTH_TOKEN"]
PORT = int(os.environ.get("BEACON_CONSOLE_SERVER_PORT", "8000"))
ZEGO_PRIMARY_NODE_ID = "mac-zego-real-001"
ZEGO_PEER_NODE_ID = "mac-zego-real-peer-001"
ZEGO_AGENT_BINARY = ROOT / ".build" / "default" / "agents" / "mac" / "mac_zego_agent_bridge"

sys.path[:0] = [str(ROOT / "server"), str(ROOT / "python_sdk"), str(ROOT)]

import uvicorn  # noqa: E402

import scripts.validation.run_mac_console_agora_validation as agora  # noqa: E402
import scripts.validation.run_mac_console_volcengine_validation as volcengine  # noqa: E402
from app.main import app  # noqa: E402
from scripts.validation.run_mac_agora_e2e_tests import agent_ws_url, run, stop_native_websocket_agent, wait_for_registered_device, wait_http  # noqa: E402
from scripts.validation.run_mac_zego_real import REQUIRED_ENV as ZEGO_REQUIRED_ENV, framework_slice  # noqa: E402


def ensure_port_available() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError as exc:
            raise RuntimeError(f"Beacon unified Console server port {PORT} is already in use") from exc


def missing_real_environment() -> list[str]:
    missing = agora.missing_real_env() + volcengine.missing_real_env()
    missing.extend(name for name in ZEGO_REQUIRED_ENV if not os.environ.get(name))
    if not agora.agora_framework_exists():
        missing.append("AGORA_MAC_SDK_ROOT/AgoraRtcKit.xcframework")
    if not volcengine.framework_exists(volcengine.sdk_root()):
        missing.append("VOLCENGINE_MAC_SDK_ROOT/VolcEngineRTC.framework")
    if framework_slice() is None:
        missing.append("ZEGO_MAC_SDK_ROOT/ZegoExpressEngine.xcframework")
    return sorted(set(missing))


async def start_zego_agents(base_url: str, ws_url: str, slice_dir: Path) -> list[asyncio.subprocess.Process]:
    base_env = os.environ.copy()
    base_env.update(
        {
            "BEACON_AGENT_WS_URL": agent_ws_url(ws_url, AUTH_TOKEN),
            "BEACON_AGENT_GROUP_ID": "zego-real-e2e",
            "BEACON_AGENT_CAPABILITIES": "rtc.real,zego",
            "DYLD_FRAMEWORK_PATH": str(slice_dir),
        }
    )
    agents: list[asyncio.subprocess.Process] = []
    try:
        for node_id, tags in (
            (ZEGO_PRIMARY_NODE_ID, "zego,l1,role:primary"),
            (ZEGO_PEER_NODE_ID, "zego,l1,role:peer"),
        ):
            env = base_env | {"BEACON_NODE_ID": node_id, "BEACON_AGENT_TAGS": tags}
            process = await asyncio.create_subprocess_exec(str(ZEGO_AGENT_BINARY), cwd=str(ROOT), env=env)
            agents.append(process)
            await wait_for_registered_device(base_url, process, node_id)
        return agents
    except Exception:
        for process in agents:
            await stop_native_websocket_agent(process)
        raise


def agora_roles_for_unified_server() -> list[str]:
    cases = agora.load_agora_cases()
    return sorted({
        str(role)
        for case in cases
        if case["case_id"].startswith(agora.CASE_PREFIX) and case.get("implementation_status") == "runnable"
        for role in case.get("devices", [])
    })


async def start_agora_agents(base_url: str, ws_url: str) -> list[asyncio.subprocess.Process]:
    agents: list[asyncio.subprocess.Process] = []
    try:
        for role in agora_roles_for_unified_server():
            agents.append(await agora.start_real_agent(
                base_url,
                ws_url,
                node_id=agora.agent_node_id_for_role(role),
                tags=agora.agent_tags_for_role(role),
            ))
        return agents
    except Exception:
        for process in reversed(agents):
            await stop_native_websocket_agent(process)
        raise


async def start_all_agents(base_url: str, ws_url: str, slice_dir: Path) -> list[asyncio.subprocess.Process]:
    agora.configure_rtc_token()
    agora.configure_case_token_map()
    volcengine.configure_case_token_map(volcengine.join_pairs_by_case(volcengine.CASES))
    run(["cmake", "-S", ".", "-B", ".build/default", "-DBEACON_ENABLE_ZEGO_REAL=ON"])
    run([
        "cmake", "--build", ".build/default", "--target",
        "mac_real_agent_bridge", "mac_volcengine_agent_bridge", "mac_zego_agent_bridge",
    ])
    agents: list[asyncio.subprocess.Process] = []
    try:
        agents.extend(await start_agora_agents(base_url, ws_url))
        agents.append(await volcengine.start_real_agent(base_url, ws_url))
        agents.append(await volcengine.start_real_agent(
            base_url, ws_url, node_id=volcengine.PEER_NODE_ID, tags=volcengine.PEER_AGENT_TAGS,
        ))
        agents.extend(await start_zego_agents(base_url, ws_url, slice_dir))
        return agents
    except Exception:
        for process in agents:
            await stop_native_websocket_agent(process)
        raise


async def serve() -> None:
    missing = missing_real_environment()
    if missing:
        raise RuntimeError("unified real Console requires: " + ", ".join(missing))
    slice_dir = framework_slice()
    assert slice_dir is not None
    base_url = f"http://127.0.0.1:{PORT}"
    import app.main as server_main
    server_main.runner_supervisor._process._base_url = base_url
    ws_url = f"ws://127.0.0.1:{PORT}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    agents: list[asyncio.subprocess.Process] = []
    try:
        await wait_http(base_url)
        agents = await start_all_agents(base_url, ws_url, slice_dir)
        print(
            f"Beacon unified Mac Console ready: {base_url} "
            f"agora={agora.PRIMARY_NODE_ID} volcengine={volcengine.NODE_ID} zego={ZEGO_PRIMARY_NODE_ID}",
            flush=True,
        )
        while not server.should_exit:
            await asyncio.sleep(0.2)
    finally:
        for process in agents:
            await stop_native_websocket_agent(process)
        server.should_exit = True
        thread.join(timeout=5)


def main() -> int:
    ensure_port_available()
    signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
