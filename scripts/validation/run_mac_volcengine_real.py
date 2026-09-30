#!/usr/bin/env python3
"""火山引擎 RTC 真实链路 gate。

启动原生 Mac Agent（火山真实变体 `mac_volcengine_agent_bridge`）直连 Server WebSocket，
由 Server 执行 `test_cases/python/volcengine/volcengine_l1_cases.py` 的 L1 用例，打真实火山 SDK。

缺 SDK 或缺凭证时写 skipped 产物并 exit 0；环境齐备但构建、注册、join 或断言失败时返回非 0。
"""

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
from time import time as unix_time
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports" / "latest"
AUTH_TOKEN = os.environ.setdefault("BEACON_AUTH_TOKEN", "local-test-token")
AUTH = {"Authorization": f"Bearer {AUTH_TOKEN}"}

NODE_ID = "mac-volcengine-real-001"
AGENT_BINARY = ROOT / ".build" / "default" / "agents" / "mac" / "mac_volcengine_agent_bridge"
AGENT_TAGS = "volcengine,l1"
REPORT_PATH = REPORT_DIR / "mac_volcengine_real.json"
JUNIT_PATH = REPORT_DIR / "mac_volcengine_real.junit.xml"
CASE_IDS = (
    "TC-PY-VOLCENGINE-L1-LIFECYCLE",
    "TC-PY-VOLCENGINE-L1-CONNECTION-STATE",
    "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK",
    "TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP",
    "TC-PY-VOLCENGINE-L1-INVALID-TOKEN",
    # Console autorun 用的清理用例；同时纳入本 gate，保证真实链路上它也能跑通。
    "TC-PY-VOLCENGINE-L1-RUNTIME-CLEANUP-BASELINE",
)
REQUIRED_ENV = ("VOLCENGINE_MAC_SDK_ROOT", "VOLCENGINE_RTC_ID", "VOLCENGINE_RTC_APPKEY")

sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "python_sdk"))
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from scripts.validation.run_mac_agora_e2e_tests import agent_ws_url  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def missing_real_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def sdk_root() -> Path | None:
    value = os.environ.get("VOLCENGINE_MAC_SDK_ROOT")
    return Path(value) if value else None


def framework_exists(root: Path | None) -> bool:
    return root is not None and (root / "VolcEngineRTC.framework").exists()


def write_report(status: str, message: str, case_results: list[dict] | None = None) -> None:
    now = utc_now()
    results = case_results or []
    report = {
        "run_id": "run-mac-volcengine-real",
        "status": status,
        "started_at": now,
        "finished_at": now,
        "summary": {
            "total": len(results) or 1,
            "passed": sum(1 for item in results if item["status"] == "passed"),
            "failed": sum(1 for item in results if item["status"] not in {"passed", "skipped"}),
            "skipped": sum(1 for item in results if item["status"] == "skipped") or (1 if not results and status == "skipped" else 0),
        },
        "case_results": results
        or [
            {
                "case_id": "E2E-MAC-VOLCENGINE-REAL",
                "status": status,
                "steps": [
                    {
                        "step_id": "volcengine-real-chain",
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
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def write_junit(status: str, message: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suite = ET.Element(
        "testsuite",
        name="mac-volcengine-real",
        tests="1",
        failures="1" if status == "failed" else "0",
        skipped="1" if status == "skipped" else "0",
    )
    case = ET.SubElement(suite, "testcase", classname="mac-volcengine-real", name="volcengine-real-chain")
    if status == "failed":
        ET.SubElement(case, "failure", message=message).text = message
    if status == "skipped":
        ET.SubElement(case, "skipped", message=message).text = message
    ET.ElementTree(suite).write(JUNIT_PATH, encoding="utf-8", xml_declaration=True)


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def configure_rtc_token() -> None:
    """用 vendored 官方 builder 为本轮 gate 签发 room token（不落盘、不打印）。

    正式 gate 总是现场签发：环境里预设的 token 可能是过期的旧值，静默复用会让门禁
    拿到与凭证不一致的 token（Agora 侧已因静态 token 过期复现过一次）。
    """
    app_id = os.environ["VOLCENGINE_RTC_ID"]
    app_key = os.environ["VOLCENGINE_RTC_APPKEY"]
    room_id = os.environ.get("VOLCENGINE_RTC_ROOM_ID") or "beacon-volcengine-l1-room"
    user_id = os.environ.get("VOLCENGINE_RTC_USER_ID") or "beacon-user-001"
    script = (
        "import sys, time; sys.path.insert(0, 'server');"
        "from vendor.volcengine_rtc_token import AccessToken;"
        "expire = int(time.time()) + 3600;"
        f"t = AccessToken.AccessToken({app_id!r}, {app_key!r}, {room_id!r}, {user_id!r});"
        "t.add_privilege(AccessToken.PrivSubscribeStream, expire);"
        "t.add_privilege(AccessToken.PrivPublishStream, expire);"
        "t.expire_time(expire); print(t.serialize())"
    )
    token = subprocess.check_output([sys.executable, "-c", script], cwd=ROOT, text=True).strip()
    if not token:
        raise RuntimeError("failed to mint a Volcengine room token")
    os.environ["VOLCENGINE_RTC_TOKEN"] = token


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


async def wait_agent_registered(base_url: str, process: asyncio.subprocess.Process, node_id: str) -> None:
    async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
        for _ in range(200):
            if process.returncode is not None:
                stderr = b""
                if process.stderr is not None:
                    stderr = await process.stderr.read()
                raise RuntimeError(f"agent exited early rc={process.returncode}: {stderr.decode(errors='replace')}")
            try:
                response = await client.get(f"{base_url}/api/v1/devices", headers=AUTH)
                if response.status_code == 200:
                    devices = response.json().get("devices", [])
                    if any(device.get("node_id") == node_id for device in devices):
                        return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    raise RuntimeError("agent did not register")


async def stop_agent(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.terminate()
    await process.wait()


async def run_case(base_url: str, case_id: str) -> tuple[dict, dict]:
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        response = await client.post(
            f"{base_url}/api/v1/test-runs",
            headers=AUTH,
            json={"selector": {"platform": "mac", "tags": ["volcengine", "l1"]}, "case_ids": [case_id]},
        )
        assert response.status_code == 200, response.text
        from scripts.support.native_run_client import wait_run
        run_payload = await wait_run(client, base_url, response.json()["run_id"], AUTH)
        report_response = await client.get(f"{base_url}/api/v1/test-runs/{run_payload['run_id']}/report", headers=AUTH)
        assert report_response.status_code == 200, report_response.text
        return run_payload, report_response.json()


def assert_join_evidence(report: dict) -> None:
    """真实链路下 join 成功必须有房间态事件证据，且目标落在房间级 delegate 上。"""
    evidence = [
        item
        for entry in report["case_results"]
        for item in entry["observations"]
        if item["kind"] == "event" and item["target"].get("function") == "onRoomStateChanged"
    ]
    assert evidence, "missing onRoomStateChanged evidence on the real chain"
    assert evidence[0]["target"]["interface"] == "byte_rtc_room"
    assert evidence[0]["target"]["class"] == "ByteRTCRoomDelegate"
    assert evidence[0]["payload"]["state"] == 0, evidence[0]["payload"]


async def run_real_chain(base_url: str, ws_url: str) -> list[dict]:
    env = os.environ.copy()
    env["BEACON_AGENT_WS_URL"] = agent_ws_url(ws_url, AUTH_TOKEN)
    env["BEACON_NODE_ID"] = NODE_ID
    env["BEACON_AGENT_TAGS"] = AGENT_TAGS
    env["BEACON_AGENT_CAPABILITIES"] = "rtc.real,volcengine"
    process = await asyncio.create_subprocess_exec(
        str(AGENT_BINARY),
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await wait_agent_registered(base_url, process, NODE_ID)
        results = []
        failures: list[str] = []
        for case_id in CASE_IDS:
            run_payload, report = await run_case(base_url, case_id)
            results.append(
                {
                    "case_id": case_id,
                    "status": run_payload["status"],
                    "run_id": run_payload["run_id"],
                    "cases": [
                        {"case_id": item["case_id"], "status": item["status"], "message": item.get("message", "")}
                        for item in run_payload.get("case_results", [])
                    ],
                }
            )
            if run_payload["status"] != "passed":
                # 跑完全部用例再汇总失败；只输出诊断摘要，不回显完整事实正文。
                failures.append(case_id)
                print(
                    f"{case_id} failed: " + json.dumps({
                        "cases": [(item["status"], item.get("failure_classification"), item.get("message")) for item in run_payload.get("case_results", [])],
                        "observations": [(item["kind"], item["target"].get("function"), item["payload"].get("outcome"), item["payload"].get("state") if item["kind"] == "event" else item["payload"].get("code")) for entry in report["case_results"] for item in entry.get("observations", [])],
                    }, ensure_ascii=False),
                    file=sys.stderr,
                )
                continue
            if case_id == "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK":
                assert_join_evidence(report)
        if failures:
            raise RuntimeError("volcengine real cases failed: " + ", ".join(failures))
        return results
    finally:
        await stop_agent(process)


def main() -> int:
    missing = missing_real_env()
    if missing or not framework_exists(sdk_root()):
        reason = (
            "missing real mac sdk environment: " + ",".join(missing)
            if missing
            else "missing VolcEngineRTC.framework under VOLCENGINE_MAC_SDK_ROOT"
        )
        write_report("skipped", reason)
        write_junit("skipped", reason)
        print(f"mac volcengine real: SKIPPED - {reason}")
        return 0

    try:
        configure_rtc_token()
        run(["cmake", "-S", ".", "-B", ".build/default"])
        run(["cmake", "--build", ".build/default", "--target", "mac_volcengine_agent_bridge"])
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
            results = asyncio.run(run_real_chain(base_url, ws_url))
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    except Exception as exc:  # noqa: BLE001
        detail = traceback.format_exc()
        message = f"mac volcengine real failed: {type(exc).__name__}"
        write_report("failed", message)
        write_junit("failed", message)
        print(f"{message}: {exc}\n{detail}", file=sys.stderr)
        return 1

    write_report("passed", "mac volcengine real passed", results)
    write_junit("passed", "mac volcengine real passed")
    print(f"mac volcengine real passed: {len(results)} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
