#!/usr/bin/env python3
"""Run Phase 4B macOS real SDK tests and E2E."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from time import time as unix_time
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORT_DIR = ROOT / "reports/latest"
REQUIRED_ENV = ("AGORA_MAC_SDK_ROOT", "AGORA_APP_ID", "AGORA_APP_CERT", "BEACON_AUTH_TOKEN")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def missing_real_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def agora_framework_exists() -> bool:
    root = agora_sdk_root()
    if root is None:
        return False
    if (root / "AgoraRtcKit.framework").exists():
        return True
    return any((root / "AgoraRtcKit.xcframework").glob("*/AgoraRtcKit.framework"))


def agora_sdk_root() -> Path | None:
    sdk_root = os.environ.get("AGORA_MAC_SDK_ROOT")
    if not sdk_root:
        return None
    root = Path(sdk_root)
    full_sdk_libs = root / "Shengwang_Native_SDK_for_Mac_FULL" / "libs"
    return full_sdk_libs if (full_sdk_libs / "AgoraRtcKit.xcframework").exists() else root


def agora_dyld_framework_path() -> str:
    root = agora_sdk_root()
    if root is None:
        return ""
    if (root / "AgoraRtcKit.framework").exists():
        return str(root)
    slice_dirs = sorted(
        {
            str(path)
            for pattern in ("*.xcframework/macos-*", "*.xcframework/*-macos*")
            for path in root.glob(pattern)
            if path.is_dir()
        }
    )
    return ":".join(slice_dirs)


def write_report(status: str, case_id: str, step_id: str, message: str) -> None:
    now = utc_now()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "run_id": "run-mac-real-local",
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
                "case_id": case_id,
                "status": status,
                "steps": [
                    {
                        "step_id": step_id,
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
    (REPORT_DIR / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def write_junit(status: str, case_id: str, message: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suite = ET.Element(
        "testsuite",
        name=case_id,
        tests="1",
        failures="1" if status == "failed" else "0",
        skipped="1" if status == "skipped" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname=case_id, name=case_id)
    if status == "failed":
        ET.SubElement(case, "failure", message=message).text = message
    if status == "skipped":
        ET.SubElement(case, "skipped", message=message).text = message
    ET.ElementTree(suite).write(REPORT_DIR / "mac_real.junit.xml", encoding="utf-8", xml_declaration=True)


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def configure_rtc_token() -> None:
    if os.environ.get("AGORA_RTC_TOKEN") and not (os.environ.get("AGORA_APP_ID") and os.environ.get("AGORA_APP_CERT")):
        return
    expire_at = int(unix_time()) + 3600
    token = subprocess.check_output(
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
                "os.environ['AGORA_APP_ID'], os.environ['AGORA_APP_CERT'], 'real-smoke', 1001, 1, "
                f"{expire_at}))"
            ),
        ],
        cwd=ROOT / "server",
        text=True,
    )
    os.environ["AGORA_RTC_TOKEN"] = token


def agent_ws_url(ws_url: str, token: str) -> str:
    return f"{ws_url}/api/v1/agent/ws?{urlencode({'token': token})}"


async def wait_http(base_url: str) -> None:
    import httpx

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
    import httpx

    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        response = await client.get(
            f"{base_url}/api/v1/devices",
            headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
        )
        return response.json() if response.status_code == 200 else {
            "status_code": response.status_code,
            "body": response.text,
        }


async def start_native_websocket_agent(
    ws_url: str,
    *,
    node_id: str,
    tags: list[str],
    group_id: str = "real-e2e",
) -> asyncio.subprocess.Process:
    env = os.environ.copy()
    env["BEACON_AGENT_WS_URL"] = agent_ws_url(ws_url, env["BEACON_AUTH_TOKEN"])
    env["BEACON_NODE_ID"] = node_id
    env["BEACON_AGENT_TAGS"] = ",".join(tags)
    env["BEACON_AGENT_CAPABILITIES"] = "rtc.real"
    env["BEACON_AGENT_GROUP_ID"] = group_id
    dyld_framework_path = agora_dyld_framework_path()
    if dyld_framework_path:
        existing = env.get("DYLD_FRAMEWORK_PATH", "")
        env["DYLD_FRAMEWORK_PATH"] = f"{dyld_framework_path}:{existing}" if existing else dyld_framework_path
    return await asyncio.create_subprocess_exec(
        str(ROOT / ".build" / "default" / "agents" / "mac" / "mac_real_agent_bridge"),
        cwd=str(ROOT),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )


async def wait_for_registered_device(
    base_url: str,
    process: asyncio.subprocess.Process,
    node_id: str,
    *,
    timeout_seconds: float = 30,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if process.returncode is not None:
            stderr = await process.stderr.read() if process.stderr is not None else b""
            raise RuntimeError(
                f"native agent exited before registration: node_id={node_id} "
                f"returncode={process.returncode} stderr={stderr.decode('utf-8', errors='replace')[-4000:]}"
            )
        devices = await list_devices(base_url)
        if any(device.get("node_id") == node_id for device in devices.get("devices", [])):
            return
        await asyncio.sleep(0.1)
    raise RuntimeError(f"native agent did not register: node_id={node_id}; devices={await list_devices(base_url)!r}")


async def stop_native_websocket_agent(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


async def run_real_e2e(base_url: str, ws_url: str) -> None:
    import httpx

    from scripts.support.native_run_client import wait_run

    sys.path.insert(0, str(ROOT / "server"))
    sys.path.insert(0, str(ROOT / "python_sdk"))
    from app.main import app

    async def create_server_run(
        client: httpx.AsyncClient,
        *,
        case_id: str,
    ) -> tuple[dict, dict]:
        response = await client.post(
            f"{base_url}/api/v1/test-runs",
            headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
            json={
                "selector": {"platform": "mac", "tags": ["real-e2e"]},
                "case_ids": [case_id],
            },
        )
        assert response.status_code == 200, response.text
        run = await wait_run(client, base_url, response.json()["run_id"], {"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"})
        report_response = await client.get(
            f"{base_url}/api/v1/test-runs/{run['run_id']}/report",
            headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
        )
        assert report_response.status_code == 200
        report = report_response.json()
        assert run["status"] == "passed", {
            "cases": [
                (item["case_id"], item["status"], item.get("failure_classification"), item.get("message"))
                for item in run.get("case_results", [])
            ],
            "observations": [
                (item.get("kind"), item.get("target", {}).get("function"), item.get("payload", {}).get("outcome"))
                for item in report["case_results"][0].get("observations", [])
            ],
        }
        join_evidence = [
            item
            for item in report["case_results"][0]["observations"]
            if item["kind"] == "event" and item["target"].get("function") == "onJoinChannelSuccess"
        ]
        assert len(join_evidence) == 1
        assert join_evidence[0]["target"]["interface"] == "rtc_engine"
        assert join_evidence[0]["payload"]["channel"] == "real-smoke"
        if case_id == "TC-MAC-AGORA-REAL-JOIN-CALLBACK":
            execution = join_evidence[0]["callback_execution"]
            assert execution["defer_matched"] is True
            assert execution["defer_executed"] is True
            assert len(execution["call_results"]) == 1
            assert execution["call_results"][0]["target"]["sdk"] == "beacon_system"
            assert execution["call_results"][0]["target"]["function"] == "waitInMs"
            assert execution["call_results"][0]["error"] == 0
            assert json.loads(execution["call_results"][0]["return_value"]) == {"waited": True}
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / f"mac_real_{case_id}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return run, report

    node_id = "mac-real-e2e-001"
    process = await start_native_websocket_agent(
        ws_url,
        node_id=node_id,
        tags=["real-e2e"],
    )
    try:
        await wait_for_registered_device(base_url, process, node_id)
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            first_run, _ = await create_server_run(client, case_id="TC-MAC-AGORA-REAL-JOIN-CALLBACK")
            second_run, _ = await create_server_run(client, case_id="TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE")
            assert first_run["run_id"] != second_run["run_id"]
    finally:
        await stop_native_websocket_agent(process)


def main() -> int:
    missing = missing_real_env()
    if missing:
        message = "missing real mac sdk environment: " + ",".join(missing)
        write_report("skipped", "E2E-AGORA-MAC-REAL", "real-env", message)
        write_junit("skipped", "E2E-AGORA-MAC-REAL", message)
        print(message)
        return 0
    if not agora_framework_exists():
        message = "missing AgoraRtcKit.framework under AGORA_MAC_SDK_ROOT"
        write_report("skipped", "E2E-AGORA-MAC-REAL", "real-sdk", message)
        write_junit("skipped", "E2E-AGORA-MAC-REAL", message)
        print(message)
        return 0

    os.environ.setdefault("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    configure_rtc_token()

    try:
        run(["cmake", "-S", ".", "-B", ".build/default"])
        run(["cmake", "--build", ".build/default", "--target", "mac_real_adapter_test", "mac_real_agent_bridge"])
        run(["ctest", "--test-dir", ".build/default", "-R", "BRIDGE-MAC-REAL|IT-AGORA|FI-RTC", "--output-on-failure"])

        sys.path.insert(0, str(ROOT / "server"))
        import uvicorn
        from app.main import app

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
            asyncio.run(run_real_e2e(base_url, ws_url))
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            time.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        message = f"mac real e2e failed: {exc}"
        write_report("failed", "E2E-AGORA-MAC-REAL", "real-e2e", message)
        write_junit("failed", "E2E-AGORA-MAC-REAL", message)
        print(message, file=sys.stderr)
        return 1

    write_report("passed", "E2E-AGORA-MAC-REAL", "real-e2e", "mac real sdk e2e passed")
    write_junit("passed", "E2E-AGORA-MAC-REAL", "mac real sdk e2e passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
