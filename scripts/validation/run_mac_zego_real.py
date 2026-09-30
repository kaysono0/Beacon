#!/usr/bin/env python3
"""ZEGO Express macOS 真实 L1 gate。"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "latest"
# 独立 real gate 可以使用本地默认 token，但 import 本模块不能改变调用方环境。
AUTH_TOKEN = os.environ.get("BEACON_AUTH_TOKEN", "local-test-token")
AUTH = {"Authorization": f"Bearer {AUTH_TOKEN}"}
NODE_ID = "mac-zego-real-001"
PEER_NODE_ID = "mac-zego-real-peer-001"
AGENT_BINARY = ROOT / ".build" / "default" / "agents" / "mac" / "mac_zego_agent_bridge"
CASE_IDS = (
    "TC-PY-ZEGO-L1-LIFECYCLE",
    "TC-PY-ZEGO-L1-LOGIN-CALLBACK",
    "TC-PY-ZEGO-L1-LOGOUT-CALLBACK",
    "TC-PY-ZEGO-L1-1V1-ROOM-CONNECTED",
    "TC-PY-ZEGO-L1-1V1-VIDEO-RENDER-SNAPSHOT",
    "TC-PY-ZEGO-L1-1V1-VIDEO-SYNTH-RENDER-SNAPSHOT",
)
REQUIRED_ENV = (
    "ZEGO_MAC_SDK_ROOT",
    "ZEGO_APP_ID",
    "ZEGO_APP_SIGN",
    "ZEGO_USER1_ID",
    "ZEGO_USER2_ID",
    "ZEGO_USER1_TOKEN",
    "ZEGO_USER2_TOKEN",
)

sys.path[:0] = [str(ROOT / "server"), str(ROOT / "python_sdk"), str(ROOT)]

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from scripts.validation.run_mac_agora_e2e_tests import agent_ws_url  # noqa: E402


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def framework_slice() -> Path | None:
    root = os.environ.get("ZEGO_MAC_SDK_ROOT")
    if not root:
        return None
    root_path = Path(root)
    direct = root_path / "ZegoExpressEngine.framework"
    if direct.exists():
        return root_path
    candidates = sorted(root_path.glob("ZegoExpressEngine.xcframework/macos-*/ZegoExpressEngine.framework"))
    return candidates[0].parent if candidates else None


def write_result(status: str, message: str, cases: list[dict] | None = None) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = cases or []
    report = {
        "run_id": "run-mac-zego-real",
        "status": status,
        "started_at": now(),
        "finished_at": now(),
        "summary": {
            "total": len(results) or 1,
            "passed": sum(item["status"] == "passed" for item in results),
            "failed": sum(item["status"] not in {"passed", "skipped"} for item in results),
            "skipped": sum(item["status"] == "skipped" for item in results) or (1 if not results and status == "skipped" else 0),
        },
        "case_results": results or [{"case_id": "E2E-MAC-ZEGO-REAL", "status": status, "message": message}],
        "artifacts": [],
    }
    (REPORT_DIR / "mac_zego_real.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    suite = ET.Element("testsuite", name="mac-zego-real", tests="1", failures="1" if status == "failed" else "0", skipped="1" if status == "skipped" else "0")
    case = ET.SubElement(suite, "testcase", classname="mac-zego-real", name="zego-real-chain")
    if status == "failed":
        ET.SubElement(case, "failure", message=message).text = message
    elif status == "skipped":
        ET.SubElement(case, "skipped", message=message).text = message
    ET.ElementTree(suite).write(REPORT_DIR / "mac_zego_real.junit.xml", encoding="utf-8", xml_declaration=True)


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def wait_http(base_url: str) -> None:
    async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
        for _ in range(80):
            try:
                if (await client.get(f"{base_url}/api/v1/status")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    raise RuntimeError("server did not start")


async def wait_agent(base_url: str, process: asyncio.subprocess.Process, node_id: str) -> None:
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        for _ in range(200):
            if process.returncode is not None:
                stderr = await process.stderr.read() if process.stderr else b""
                raise RuntimeError(f"agent exited early rc={process.returncode}: {stderr.decode(errors='replace')}")
            try:
                devices = (await client.get(f"{base_url}/api/v1/devices", headers=AUTH)).json().get("devices", [])
                if any(item.get("node_id") == node_id for item in devices):
                    return
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(0.05)
    raise RuntimeError("agent did not register")


async def run_chain(base_url: str, ws_url: str, slice_dir: Path) -> list[dict]:
    env = os.environ.copy()
    env.update({
        "BEACON_AGENT_WS_URL": agent_ws_url(ws_url, AUTH_TOKEN),
        "BEACON_NODE_ID": NODE_ID,
        "BEACON_AGENT_GROUP_ID": "zego-real-e2e",
        "BEACON_AGENT_TAGS": "zego,l1,role:primary",
        "BEACON_AGENT_CAPABILITIES": "rtc.real,zego",
        "DYLD_FRAMEWORK_PATH": str(slice_dir),
    })
    process = await asyncio.create_subprocess_exec(str(AGENT_BINARY), cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    peer_env = env.copy()
    peer_env["BEACON_NODE_ID"] = PEER_NODE_ID
    peer_env["BEACON_AGENT_TAGS"] = "zego,l1,role:peer"
    peer = await asyncio.create_subprocess_exec(str(AGENT_BINARY), cwd=str(ROOT), env=peer_env, stdout=subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        await wait_agent(base_url, process, NODE_ID)
        await wait_agent(base_url, peer, PEER_NODE_ID)
        results = []
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            for case_id in CASE_IDS:
                response = await client.post(f"{base_url}/api/v1/test-runs", headers=AUTH, json={"selector": {"platform": "mac", "tags": ["zego", "l1"]}, "case_ids": [case_id]})
                response.raise_for_status()
                from scripts.support.native_run_client import wait_run
                payload = await wait_run(client, base_url, response.json()["run_id"], AUTH)
                results.append({"case_id": case_id, "status": payload["status"], "run_id": payload["run_id"], "steps": payload.get("results", [])})
                if payload["status"] != "passed":
                    raise RuntimeError(f"ZEGO case failed: {case_id}: {json.dumps(payload, ensure_ascii=False)[:16000]}")
        return results
    finally:
        for agent in (process, peer):
            if agent.returncode is None:
                agent.terminate()
        await process.wait()
        await peer.wait()


def main() -> int:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    slice_dir = framework_slice()
    if missing or slice_dir is None:
        reason = "missing real mac sdk environment: " + ",".join(missing) if missing else "missing ZegoExpressEngine.framework under ZEGO_MAC_SDK_ROOT"
        write_result("skipped", reason)
        print(f"mac zego real: SKIPPED - {reason}")
        return 0
    try:
        run(["cmake", "-S", ".", "-B", ".build/default", "-DBEACON_ENABLE_ZEGO_REAL=ON"])
        run(["cmake", "--build", ".build/default", "--target", "mac_zego_agent_bridge"])
        port = free_port()
        base_url, ws_url = f"http://127.0.0.1:{port}", f"ws://127.0.0.1:{port}"
        import app.main as server_main
        server_main.runner_supervisor._process._base_url = base_url
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            asyncio.run(wait_http(base_url))
            cases = asyncio.run(run_chain(base_url, ws_url, slice_dir))
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    except Exception as exc:  # noqa: BLE001
        message = f"mac zego real failed: {exc}\n{traceback.format_exc()}"
        write_result("failed", message)
        print(message, file=sys.stderr)
        return 1
    write_result("passed", "mac zego real passed", cases)
    print(f"mac zego real passed: {len(cases)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
