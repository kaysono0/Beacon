#!/usr/bin/env python3
"""运行 Direct Mac Agent WebSocket mock smoke。

该 gate 启动真实 macOS Agent 进程，由 Agent 自行连接 Server WebSocket。
Python harness 只负责启动 Server/Agent、触发测试、等待报告和清理进程。
"""

from __future__ import annotations

import asyncio
import contextlib
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
AUTH_TOKEN = os.environ.setdefault("BEACON_AUTH_TOKEN", "local-test-token")
AUTH = {"Authorization": f"Bearer {AUTH_TOKEN}"}

sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "python_sdk"))
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from scripts.validation.run_mac_agora_e2e_tests import agent_ws_url  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_report(status: str, message: str) -> None:
    now = utc_now()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "run_id": "run-mac-direct-agent-mock",
        "status": status,
        "started_at": now,
        "finished_at": now,
        "summary": {
            "total": 1,
            "passed": 1 if status == "passed" else 0,
            "failed": 1 if status == "failed" else 0,
            "skipped": 1 if status == "skipped" else 0,
        },
        "case_results": [
            {
                "case_id": "E2E-MAC-DIRECT-AGENT-MOCK",
                "status": status,
                "steps": [
                    {
                        "step_id": "direct-websocket-mock",
                        "status": status,
                        "error": 0 if status in {"passed", "skipped"} else 1,
                        "message": message,
                        "artifacts": [],
                    }
                ],
            }
        ],
        "artifacts": [],
    }
    (REPORT_DIR / "mac_direct_agent_mock.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (REPORT_DIR / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def write_junit(status: str, message: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suite = ET.Element(
        "testsuite",
        name="mac-direct-agent-mock",
        tests="1",
        failures="1" if status == "failed" else "0",
        skipped="1" if status == "skipped" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname="mac-direct-agent-mock", name="direct-websocket-mock")
    if status == "failed":
        ET.SubElement(case, "failure", message=message).text = message
    if status == "skipped":
        ET.SubElement(case, "skipped", message=message).text = message
    tree = ET.ElementTree(suite)
    tree.write(REPORT_DIR / "mac_direct_agent_mock.junit.xml", encoding="utf-8", xml_declaration=True)
    tree.write(REPORT_DIR / "report.junit.xml", encoding="utf-8", xml_declaration=True)


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


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


async def list_devices(base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        response = await client.get(f"{base_url}/api/v1/devices", headers=AUTH)
        return response.json() if response.status_code == 200 else {"status_code": response.status_code, "body": response.text}


async def wait_agent_registered(base_url: str, process: asyncio.subprocess.Process, node_id: str) -> None:
    deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < deadline:
        if process.returncode is not None:
            stderr = await process.stderr.read() if process.stderr is not None else b""
            raise RuntimeError(
                f"direct agent exited before registration: returncode={process.returncode} "
                f"stderr={stderr.decode('utf-8', errors='replace')[-4000:]}"
            )
        devices = await list_devices(base_url)
        for device in devices.get("devices", []):
            if device.get("node_id") == node_id:
                return
        await asyncio.sleep(0.1)
    raise RuntimeError(f"direct agent did not register: node_id={node_id}")


async def stop_agent(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


async def emit_mock_join_success(run_id: str) -> None:
    """在正式 Runner 完成 join 调用后注入模拟回调，不伪装为真实 SDK 事件。"""
    from app.observations.observation_models import ObservationQuery

    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        observations = await main_module.observation_service.query(
            ObservationQuery(run_id=run_id, kinds=frozenset({"operation"})),
        )
        joined = next((item for item in observations if item.target.function == "joinChannel"), None)
        if joined is not None:
            packet = {
                "common": {"action": "callbackEventRequest", "op_id": f"op-{run_id}-join", "timestamp_ms": 1},
                "data": {
                    "node_id": joined.node_id, "lease_id": joined.lease_id, "device_role": joined.device_role,
                    "run_id": run_id, "case_id": joined.case_id, "event_id": f"event-{run_id}-join",
                    "event_target": {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onJoinChannelSuccess"},
                    "payload": {"channel": "room", "uid": 1001, "elapsed_ms": 0},
                },
            }
            response = await main_module.agent_gateway.handle_packet(None, packet)
            assert response is not None and response.get("data", {}).get("code") == 0, response
            return
        await asyncio.sleep(0.05)
    raise RuntimeError("Runner did not complete mock join")


async def create_server_run(base_url: str) -> tuple[dict, dict]:
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        response = await client.post(
            f"{base_url}/api/v1/test-runs",
            headers=AUTH,
            json={
                "selector": {"platform": "mac", "tags": ["direct-mock"]},
                "case_ids": ["TC-PY-AGORA-JOIN-CALLBACK"],
            },
        )
        assert response.status_code == 200, response.text
        from scripts.support.native_run_client import wait_run
        run_id = response.json()["run_id"]
        await emit_mock_join_success(run_id)
        run_payload = await wait_run(client, base_url, run_id, AUTH)
        assert run_payload["status"] == "passed", run_payload
        report_response = await client.get(f"{base_url}/api/v1/test-runs/{run_payload['run_id']}/report", headers=AUTH)
        assert report_response.status_code == 200, report_response.text
        report = report_response.json()
        facts = report["case_results"][0]["observations"]
        join_events = [item for item in facts if item["kind"] == "event" and item["target"].get("function") == "onJoinChannelSuccess"]
        assert len(join_events) == 1 and join_events[0]["payload"]["channel"] == "room", report
        assert join_events[0]["operation_id"] is None, join_events
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "mac_direct_agent_mock_run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return run_payload, report


async def run_direct_smoke(base_url: str, ws_url: str) -> None:
    node_id = "mac-direct-agent-mock-001"
    env = os.environ.copy()
    env["BEACON_AGENT_WS_URL"] = agent_ws_url(ws_url, AUTH_TOKEN)
    env["BEACON_NODE_ID"] = node_id
    env["BEACON_AGENT_TAGS"] = "direct-mock"
    process = await asyncio.create_subprocess_exec(
        str(ROOT / ".build" / "default" / "agents" / "mac" / "mac_real_agent_bridge"),
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        try:
            await wait_agent_registered(base_url, process, node_id)
        except Exception as exc:
            devices = await list_devices(base_url)
            await stop_agent(process)
            raise RuntimeError(f"{exc}; devices={devices!r}") from exc
        first_run, _ = await create_server_run(base_url)
        second_run, _ = await create_server_run(base_url)
        assert first_run["run_id"] != second_run["run_id"]
    finally:
        await stop_agent(process)


def main() -> int:
    try:
        run(["cmake", "-S", ".", "-B", ".build/default"])
        run(["cmake", "--build", ".build/default", "--target", "mac_real_agent_bridge", "mac_mock_adapter_test"])
        run(["ctest", "--test-dir", ".build/default", "-R", "BRIDGE-MAC-EVENT", "--output-on-failure"])
        port = free_port()
        base_url = f"http://127.0.0.1:{port}"
        main_module.runner_supervisor._process._base_url = base_url
        ws_url = f"ws://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        server_loop = asyncio.new_event_loop()
        thread = threading.Thread(target=server_loop.run_until_complete, args=(server.serve(),), daemon=True)
        thread.start()
        try:
            asyncio.run(wait_http(base_url))
            asyncio.run_coroutine_threadsafe(run_direct_smoke(base_url, ws_url), server_loop).result()
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if not thread.is_alive():
                server_loop.close()
    except Exception as exc:  # noqa: BLE001
        detail = traceback.format_exc()
        message = f"mac direct agent mock failed: {exc}\n{detail}"
        write_report("failed", message)
        write_junit("failed", message)
        print(message, file=sys.stderr)
        return 1

    write_report("passed", "mac direct agent mock passed")
    write_junit("passed", "mac direct agent mock passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
