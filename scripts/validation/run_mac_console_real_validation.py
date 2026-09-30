#!/usr/bin/env python3
"""在同一 Beacon Server 上验证 Mac Console 三家真实 SDK 用例共存。

此 smoke 证明单个 Server 可以同时承载三家原生 Agent，并由 Console 分别执行三套
case；它不替代各自的多轮、画面和回调深度 gate。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports/latest"
REPORT_JSON = REPORT_DIR / "mac_console_real.json"
REPORT_JUNIT = REPORT_DIR / "mac_console_real.junit.xml"
ZEGO_AUTORUN_REPORT = REPORT_DIR / "mac_console_zego_autorun.json"

sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

import scripts.validation.run_mac_console_agora_validation as agora  # noqa: E402
import scripts.validation.run_mac_console_volcengine_validation as volcengine  # noqa: E402
import scripts.validation.run_mac_zego_real as zego  # noqa: E402
from scripts.support.console_gate_support import stop_console_process, wait_for_autorun_report, write_gate_report  # noqa: E402
from scripts.dev.run_mac_console_real_server import agora_roles_for_unified_server, start_agora_agents, start_zego_agents  # noqa: E402
from scripts.validation.run_mac_agora_e2e_tests import free_port, run, stop_native_websocket_agent, wait_http  # noqa: E402


class VendorGateFailure(AssertionError):
    def __init__(self, vendor: str, details: dict[str, Any]) -> None:
        super().__init__(f"{vendor} autorun did not satisfy the unified-real gate: {json.dumps(details, sort_keys=True)}")
        self.details = {"vendor": vendor, **details}


def missing_real_environment() -> list[str]:
    missing = agora.missing_real_env() + volcengine.missing_real_env()
    missing.extend(name for name in zego.REQUIRED_ENV if not os.environ.get(name))
    if not agora.agora_framework_exists():
        missing.append("AGORA_MAC_SDK_ROOT/AgoraRtcKit.xcframework")
    if not volcengine.framework_exists(volcengine.sdk_root()):
        missing.append("VOLCENGINE_MAC_SDK_ROOT/VolcEngineRTC.framework")
    if zego.framework_slice() is None:
        missing.append("ZEGO_MAC_SDK_ROOT/ZegoExpressEngine.xcframework")
    return sorted(set(missing))


def write_report(status: str, message: str, extra: dict[str, Any] | None = None) -> None:
    write_gate_report(
        report_path=REPORT_JSON,
        junit_path=REPORT_JUNIT,
        junit_name="mac-console-real",
        junit_classname="mac-console-real",
        junit_case_name="app-driven-unified-real",
        run_id="run-mac-console-real-local",
        expected_cases=agora.EXPECTED_CASES | volcengine.EXPECTED_CASES | set(zego.CASE_IDS),
        status=status,
        message=message,
        base_extra={"vendors": ["agora_rtc", "volcengine_rtc", "zego_express"]},
        extra=extra,
    )


def assert_vendor_result(
    vendor: str,
    autorun: dict[str, Any],
    reports: list[dict[str, Any]],
    cleanup: dict[str, Any],
    expected_cases: set[str],
) -> None:
    failed_cases = cleanup.get("failed_cases", cleanup.get("failed_case_ids", []))
    details = {
        "autorun_status": autorun.get("status"),
        "report_count": len(reports),
        "expected_report_count": len(expected_cases),
        "cleanup_run_id": cleanup.get("run_id"),
        "cleanup_status": cleanup.get("status"),
        "failed_cases": failed_cases,
    }
    if (
        details["autorun_status"] != "passed"
        or details["cleanup_status"] != "passed"
        or details["report_count"] != details["expected_report_count"]
        or failed_cases
    ):
        raise VendorGateFailure(vendor, details)


def launch_zego_console_app(base_url: str) -> subprocess.Popen[str]:
    ZEGO_AUTORUN_REPORT.unlink(missing_ok=True)
    executable = ROOT / "apps/mac_test_console/.build/debug/BeaconMacTestConsole"
    env = os.environ.copy()
    env.update(
        {
            "BEACON_CONSOLE_SERVER_URL": base_url,
            "BEACON_AUTH_TOKEN": os.environ["BEACON_AUTH_TOKEN"],
            "BEACON_NODE_ID": zego.NODE_ID,
            "BEACON_CONSOLE_AUTORUN_PREFIX": "TC-PY-ZEGO-L1-",
            "BEACON_CONSOLE_AUTORUN_CASE_IDS": ",".join(zego.CASE_IDS),
            "BEACON_CONSOLE_AUTORUN_OUTPUT": str(ZEGO_AUTORUN_REPORT),
        }
    )
    return subprocess.Popen(
        [str(executable)], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


async def run_zego_autorun(base_url: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    import httpx

    process = launch_zego_console_app(base_url)
    try:
        autorun = await wait_for_autorun_report(process, ZEGO_AUTORUN_REPORT, timeout_seconds=300)
        if autorun.get("status") == "failed" and autorun.get("error"):
            raise AssertionError(str(autorun["error"]))
        cases = autorun.get("cases", [])
        if {case.get("case_id") for case in cases} != set(zego.CASE_IDS):
            raise AssertionError(f"unexpected ZEGO autorun cases: {cases}")
        reports: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            for case in cases:
                response = await client.get(
                    f"{base_url}/api/v1/test-runs/{case['run_id']}/report",
                    headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
                )
                response.raise_for_status()
                report = response.json()
                reports.append(report)
                if case.get("status") != "passed":
                    raise AssertionError(f"ZEGO autorun case failed: {case['case_id']}")
        # ZEGO 每个 case 自己执行幂等 logout/destroy 与 view release，没有独立 cleanup case。
        return autorun, reports, {"status": "passed", "mode": "case_owned"}
    finally:
        await stop_console_process(process)


async def run_real_validation() -> dict[str, Any]:
    import httpx
    import uvicorn
    from app.main import app

    os.environ.setdefault("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    agora.configure_rtc_token()
    agora.configure_case_token_map()
    volcengine.configure_case_token_map(volcengine.join_pairs_by_case(volcengine.CASES))

    run(["cmake", "-S", ".", "-B", ".build/default", "-DBEACON_ENABLE_ZEGO_REAL=ON"])
    run([
        "cmake", "--build", ".build/default", "--target",
        "mac_real_agent_bridge", "mac_volcengine_agent_bridge", "mac_zego_agent_bridge",
    ])
    run(["swift", "build", "--package-path", "apps/mac_test_console"])

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    import app.main as server_main
    server_main.runner_supervisor._process._base_url = base_url
    ws_url = f"ws://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    agents: list[asyncio.subprocess.Process] = []
    try:
        await wait_http(base_url)
        agents.extend(await start_agora_agents(base_url, ws_url))
        agents.append(await volcengine.start_real_agent(base_url, ws_url))
        agents.append(await volcengine.start_real_agent(
            base_url, ws_url, node_id=volcengine.PEER_NODE_ID, tags=volcengine.PEER_AGENT_TAGS,
        ))
        zego_slice = zego.framework_slice()
        assert zego_slice is not None
        agents.extend(await start_zego_agents(base_url, ws_url, zego_slice))

        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            devices = (await client.get(
                f"{base_url}/api/v1/devices",
                headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
            )).json()["devices"]
        node_ids = {device["node_id"] for device in devices}
        expected_node_ids = {
            *(agora.agent_node_id_for_role(role) for role in agora_roles_for_unified_server()),
            volcengine.NODE_ID, volcengine.PEER_NODE_ID,
            zego.NODE_ID, zego.PEER_NODE_ID,
        }
        if not expected_node_ids <= node_ids:
            raise AssertionError(f"dual server missing registered agents: {sorted(expected_node_ids - node_ids)}")

        agora_autorun, agora_reports, agora_cleanup = await agora.run_autorun_round(base_url, 1)
        volcengine_autorun, volcengine_reports, volcengine_cleanup = await volcengine.run_round(
            base_url, 1, volcengine.join_rooms_by_case(volcengine.CASES),
        )
        zego_autorun, zego_reports, zego_cleanup = await run_zego_autorun(base_url)
        assert_vendor_result("agora_rtc", agora_autorun, agora_reports, agora_cleanup, agora.EXPECTED_CASES)
        assert_vendor_result(
            "volcengine_rtc", volcengine_autorun, volcengine_reports, volcengine_cleanup,
            volcengine.EXPECTED_CASES,
        )
        assert_vendor_result("zego_express", zego_autorun, zego_reports, zego_cleanup, set(zego.CASE_IDS))
        return {
            "server_url": base_url,
            "registered_node_ids": sorted(node_ids),
            "agora": {
                "status": agora_autorun["status"], "reports_verified": len(agora_reports),
                "cleanup_status": agora_cleanup["status"],
            },
            "volcengine": {
                "status": volcengine_autorun["status"], "reports_verified": len(volcengine_reports),
                "cleanup_status": volcengine_cleanup["status"],
            },
            "zego": {
                "status": zego_autorun["status"], "reports_verified": len(zego_reports),
                "cleanup_status": zego_cleanup["status"],
            },
        }
    finally:
        for process in agents:
            await stop_native_websocket_agent(process)
        server.should_exit = True
        thread.join(timeout=5)


def main() -> int:
    missing = missing_real_environment()
    if missing:
        write_report("skipped", "missing real mac sdk environment: " + ",".join(missing))
        return 0
    try:
        result = asyncio.run(run_real_validation())
    except Exception as exc:  # noqa: BLE001
        extra = {"failure": exc.details} if isinstance(exc, VendorGateFailure) else None
        write_report("failed", f"mac console unified real validation failed: {exc}", extra)
        print(f"mac console unified real validation failed: {exc}", file=sys.stderr)
        return 1
    write_report("passed", "mac console unified real validation passed", result)
    print("mac console unified real validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
