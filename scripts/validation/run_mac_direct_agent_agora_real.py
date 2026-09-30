#!/usr/bin/env python3
"""运行 Direct Mac Agent WebSocket real Agora smoke。"""

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
AUTH_TOKEN = os.environ.get("BEACON_AUTH_TOKEN", "")
AUTH = {"Authorization": f"Bearer {AUTH_TOKEN}"}

sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "python_sdk"))
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

import app.main as main_module  # noqa: E402
from app.main import app  # noqa: E402
from scripts.validation.run_mac_agora_e2e_tests import (  # noqa: E402
    agent_ws_url,
    agora_dyld_framework_path,
    agora_framework_exists,
    configure_rtc_token,
    missing_real_env,
)


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
        "run_id": "run-mac-direct-agent-real",
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
                "case_id": "E2E-MAC-DIRECT-AGENT-REAL",
                "status": status,
                "steps": [
                    {
                        "step_id": "direct-websocket-real",
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
    (REPORT_DIR / "mac_direct_agent_real.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (REPORT_DIR / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def write_junit(status: str, message: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suite = ET.Element(
        "testsuite",
        name="mac-direct-agent-real",
        tests="1",
        failures="1" if status == "failed" else "0",
        skipped="1" if status == "skipped" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname="mac-direct-agent-real", name="direct-websocket-real")
    if status == "failed":
        ET.SubElement(case, "failure", message=message).text = message
    if status == "skipped":
        ET.SubElement(case, "skipped", message=message).text = message
    tree = ET.ElementTree(suite)
    tree.write(REPORT_DIR / "mac_direct_agent_real.junit.xml", encoding="utf-8", xml_declaration=True)
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
    deadline = asyncio.get_running_loop().time() + 30
    while asyncio.get_running_loop().time() < deadline:
        if process.returncode is not None:
            stderr = await process.stderr.read() if process.stderr is not None else b""
            raise RuntimeError(
                f"direct real agent exited before registration: returncode={process.returncode} "
                f"stderr={stderr.decode('utf-8', errors='replace')[-4000:]}"
            )
        devices = await list_devices(base_url)
        for device in devices.get("devices", []):
            if device.get("node_id") == node_id:
                return
        await asyncio.sleep(0.1)
    raise RuntimeError(f"direct real agent did not register: node_id={node_id}")


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


async def create_server_run(base_url: str) -> tuple[dict, dict]:
    async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
        response = await client.post(
            f"{base_url}/api/v1/test-runs",
            headers=AUTH,
            json={
                "selector": {"platform": "mac", "tags": ["real-e2e", "direct-real"]},
                "case_ids": ["TC-MAC-AGORA-REAL-JOIN-CALLBACK"],
            },
        )
        assert response.status_code == 200, response.text
        from scripts.support.native_run_client import wait_run
        run_payload = await wait_run(client, base_url, response.json()["run_id"], AUTH)
        assert run_payload["status"] == "passed", run_payload
        report_response = await client.get(f"{base_url}/api/v1/test-runs/{run_payload['run_id']}/report", headers=AUTH)
        assert report_response.status_code == 200, report_response.text
        report = report_response.json()
        join_evidence = [
            item
            for item in report["case_results"][0]["observations"]
            if item["kind"] == "event" and item["target"].get("function") == "onJoinChannelSuccess"
        ]
        assert len(join_evidence) == 1, report
        assert join_evidence[0]["payload"]["channel"] == "real-smoke"
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "mac_direct_agent_real_run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return run_payload, report


async def run_direct_real_smoke(base_url: str, ws_url: str) -> None:
    node_id = "mac-direct-agent-real-001"
    env = os.environ.copy()
    env["BEACON_AGENT_WS_URL"] = agent_ws_url(ws_url, AUTH_TOKEN)
    env["BEACON_NODE_ID"] = node_id
    env["BEACON_AGENT_TAGS"] = "real-e2e,direct-real"
    env["BEACON_AGENT_CAPABILITIES"] = "rtc.real"
    dyld_framework_path = agora_dyld_framework_path()
    if dyld_framework_path:
        existing = env.get("DYLD_FRAMEWORK_PATH", "")
        env["DYLD_FRAMEWORK_PATH"] = f"{dyld_framework_path}:{existing}" if existing else dyld_framework_path

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

        await create_server_run(base_url)
    finally:
        await stop_agent(process)


def main() -> int:
    missing = missing_real_env()
    if missing:
        message = "missing real mac sdk environment: " + ",".join(missing)
        write_report("skipped", message)
        write_junit("skipped", message)
        print(message)
        return 0
    if not agora_framework_exists():
        message = "missing AgoraRtcKit.framework under AGORA_MAC_SDK_ROOT"
        write_report("skipped", message)
        write_junit("skipped", message)
        print(message)
        return 0

    os.environ.setdefault("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    configure_rtc_token()

    try:
        run(["cmake", "-S", ".", "-B", ".build/default"])
        run(["cmake", "--build", ".build/default", "--target", "mac_real_adapter_test", "mac_real_agent_bridge"])
        run(["ctest", "--test-dir", ".build/default", "-R", "BRIDGE-MAC-REAL|IT-AGORA|FI-RTC", "--output-on-failure"])
        port = free_port()
        base_url = f"http://127.0.0.1:{port}"
        import app.main as server_main
        server_main.runner_supervisor._process._base_url = base_url
        ws_url = f"ws://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            asyncio.run(wait_http(base_url))
            asyncio.run(run_direct_real_smoke(base_url, ws_url))
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    except Exception as exc:  # noqa: BLE001
        detail = traceback.format_exc()
        message = f"mac direct agent real failed: {exc}\n{detail}"
        write_report("failed", message)
        write_junit("failed", message)
        print(message, file=sys.stderr)
        return 1

    write_report("passed", "mac direct agent real passed")
    write_junit("passed", "mac direct agent real passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
