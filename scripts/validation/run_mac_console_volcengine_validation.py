#!/usr/bin/env python3
"""火山引擎 RTC 真实链路的 Mac Test Console autorun gate。

与 `make test-mac-console-agora` 同构但按火山自己的能力面收窄：Console 只负责选 case 与
发起 run，执行链上仍是「原生 Mac Agent（`mac_volcengine_agent_bridge`，链接火山真实后端）
直连 Server WebSocket」，Python harness 不持有 Agent WebSocket、不 relay 协议 packet。

B-020 起本 gate 覆盖 1V1 画面场景：同时起 primary/peer 两个 Agent（同 group，peer 带
`role:peer` tag），由 Server 端 role resolver 把 `devices=['primary','peer']` 的用例展开到
同组设备。画面证据按用例声明判定四个必需视图
（两侧各自 local/remote），任一视图缺失即失败。开发者证据边界见 `docs/development.md`。

token 总是现场签发：从用例导出的 join 参数里取 `{room_id}#{user_id}`，用 Server 端同一套
vendored builder 逐对签发，避免复用环境里可能过期的静态 token。

缺 SDK 或缺凭证时写 skipped 产物并 exit 0；环境齐备但构建、注册、autorun 或断言失败返回非 0。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports/latest"
AUTORUN_REPORT = REPORT_DIR / "mac_console_volcengine_autorun.json"
REPORT_JSON = REPORT_DIR / "mac_console_volcengine.json"
REPORT_JUNIT = REPORT_DIR / "mac_console_volcengine.junit.xml"
FAILED_CASE_EVIDENCE_JSON = REPORT_DIR / "mac_console_volcengine_failed_case_evidence.json"

CASE_PREFIX = "TC-PY-VOLCENGINE-L1-"
CASE_IDS_ENV = "BEACON_MAC_CONSOLE_VOLCENGINE_CASE_IDS"
ROUNDS_ENV = "BEACON_MAC_CONSOLE_VOLCENGINE_ROUNDS"
REQUIRED_ROUNDS = 3
DEFAULT_ROUNDS = REQUIRED_ROUNDS
REQUIRED_ENV = (
    "VOLCENGINE_MAC_SDK_ROOT",
    "VOLCENGINE_RTC_ID",
    "VOLCENGINE_RTC_APPKEY",
    "BEACON_AUTH_TOKEN",
)
NODE_ID = "mac-volcengine-real-001"
PEER_NODE_ID = "mac-volcengine-real-peer-001"
REAL_E2E_GROUP_ID = "volcengine-real-e2e"
AGENT_BINARY = ROOT / ".build" / "default" / "agents" / "mac" / "mac_volcengine_agent_bridge"
AGENT_TAGS = "volcengine,l1,role:primary"
PEER_AGENT_TAGS = "volcengine,l1,role:peer"
AGENT_CAPABILITIES = "rtc.real,volcengine"
CONSOLE_EXECUTABLE = ROOT / "apps/mac_test_console/.build/debug/BeaconMacTestConsole"
CLEANUP_CASE_ID = "TC-PY-VOLCENGINE-L1-RUNTIME-CLEANUP-BASELINE"
SYNTH_1V1_CASE_ID = "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH"
RENDERED_1V1_CASE_ID = "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED"

PRIMARY_LOCAL_VIEW_ID = "primary_local_preview"
PRIMARY_REMOTE_VIEW_ID = "primary_remote_view"
PEER_LOCAL_VIEW_ID = "peer_local_preview"
PEER_REMOTE_VIEW_ID = "peer_remote_view"
VISUAL_ARTIFACT_KEYS = (
    PRIMARY_LOCAL_VIEW_ID,
    PRIMARY_REMOTE_VIEW_ID,
    PEER_LOCAL_VIEW_ID,
    PEER_REMOTE_VIEW_ID,
)
ONE_TO_ONE_VISUAL_CASES = (SYNTH_1V1_CASE_ID, RENDERED_1V1_CASE_ID)
# 两个 peer 合成源参数变体共享同一份 1V1 场景证据，因此这两个回调在两个变体里都必须到达。
ONE_TO_ONE_REQUIRED_EVIDENCE: tuple[dict[str, Any], ...] = (
    {
        "function": "onRoomStateChanged",
        "interface": "byte_rtc_room",
        "class_name": "ByteRTCRoomDelegate",
        "payload": {"state": 0},
        "payload_room_id": True,
    },
    {
        "function": "onFirstRemoteVideoFrame",
        "interface": "byte_rtc_engine",
        "class_name": "ByteRTCEngineDelegate",
        "payload": {},
    },
    {
        "function": "onSnapshotTaken",
        "interface": "byte_rtc_engine",
        "class_name": "ByteRTCEngineDelegate",
        "payload": {"err_code": 0},
    },
)

# 每条用例必须观察到的真实回调证据：函数名、声明里的 interface/class_name 与 payload 子集。
# 只对真实链路上确定会到达的回调做硬断言，避免把「没观察到」写成「已证明」。
REQUIRED_EVIDENCE_BY_CASE: dict[str, tuple[dict[str, Any], ...]] = {
    "TC-PY-VOLCENGINE-L1-CONNECTION-STATE": (
        {
            "function": "onConnectionStateChanged",
            "interface": "byte_rtc_engine",
            "class_name": "ByteRTCEngineDelegate",
            "payload": {"state": 3},
        },
    ),
    "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK": (
        {
            "function": "onRoomStateChanged",
            "interface": "byte_rtc_room",
            "class_name": "ByteRTCRoomDelegate",
            "payload": {"state": 0},
            "payload_room_id": True,
        },
    ),
    "TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP": (
        {
            "function": "onLeaveRoom",
            "interface": "byte_rtc_room",
            "class_name": "ByteRTCRoomDelegate",
            "payload": {},
            "payload_room_id": True,
        },
    ),
    SYNTH_1V1_CASE_ID: ONE_TO_ONE_REQUIRED_EVIDENCE,
    RENDERED_1V1_CASE_ID: ONE_TO_ONE_REQUIRED_EVIDENCE,
}

sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "python_sdk"))
sys.path.insert(0, str(ROOT))

from scripts.validation.run_mac_agora_e2e_tests import (  # noqa: E402
    agent_ws_url,
    free_port,
    run,
    stop_native_websocket_agent,
    wait_for_registered_device,
    wait_http,
)
from scripts.support.visual_evidence import (  # noqa: E402
    SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
    SCENARIO_SMALL_ROOM,
    assert_scenario_has_no_picture_evidence,
    build_not_exercised_scenario,
    build_scenario_visual_evidence,
    summarize_visual_evidence,
)
from scripts.support.console_gate_support import (  # noqa: E402
    run_autorun_round as run_shared_autorun_round,
    stop_console_process,
    wait_for_autorun_report,
    write_gate_report,
)


def missing_real_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def sdk_root() -> Path | None:
    value = os.environ.get("VOLCENGINE_MAC_SDK_ROOT")
    return Path(value) if value else None


def framework_exists(root: Path | None) -> bool:
    return root is not None and (root / "VolcEngineRTC.framework").exists()


def write_report(status: str, message: str, extra: dict[str, Any] | None = None) -> None:
    write_gate_report(
        report_path=REPORT_JSON,
        junit_path=REPORT_JUNIT,
        junit_name="mac-console-volcengine",
        junit_classname="mac-console-volcengine",
        junit_case_name="app-driven-volcengine",
        run_id="run-mac-console-volcengine-local",
        expected_cases=EXPECTED_CASES,
        status=status,
        message=message,
        base_extra={"node_id": NODE_ID, "required_rounds": REQUIRED_ROUNDS, "case_results": []},
        extra=extra,
    )


def load_volcengine_cases() -> list[dict[str, Any]]:
    from scripts.support.native_case_catalog import load_cases

    return load_cases(CASE_PREFIX)


def expected_autorun_cases(cases: list[dict[str, Any]]) -> set[str]:
    runnable_cases = {
        case["case_id"]
        for case in cases
        if case["case_id"].startswith(CASE_PREFIX) and case.get("implementation_status") == "runnable"
    }
    configured = {
        item.strip() for item in os.environ.get(CASE_IDS_ENV, "").split(",") if item.strip()
    }
    if not configured:
        return runnable_cases
    unknown_cases = configured - {case["case_id"] for case in cases}
    if unknown_cases:
        raise ValueError(f"{CASE_IDS_ENV} contains unknown case ids: {sorted(unknown_cases)}")
    non_runnable_cases = configured - runnable_cases
    if non_runnable_cases:
        raise ValueError(f"{CASE_IDS_ENV} contains non-runnable case ids: {sorted(non_runnable_cases)}")
    return configured


CASES = load_volcengine_cases()
EXPECTED_CASES = expected_autorun_cases(CASES)


def autorun_round_count() -> int:
    """轮次下限是硬性的：验收标准是「连续 ≥3 轮全绿」，只允许调高、不允许跑更少。"""
    raw = os.environ.get(ROUNDS_ENV)
    if raw is None:
        return DEFAULT_ROUNDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{ROUNDS_ENV} must be an integer >= {REQUIRED_ROUNDS}") from exc
    if value < REQUIRED_ROUNDS:
        raise ValueError(f"{ROUNDS_ENV} must be >= {REQUIRED_ROUNDS}, got {value}")
    return value


def _case_call_params(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"room_id": room_id, "user_id": user_id, "token": "{{VOLCENGINE_RTC_TOKEN}}"}
        for room_id, user_id in case.get("token_bindings", [])
    ]


def join_rooms_by_case(cases: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """从导出的 join 调用里取 `(room_id, user_id)`：断言与签发都用同一份事实。"""
    return {case_id: pairs[-1] for case_id, pairs in join_pairs_by_case(cases).items()}


def join_pairs_by_case(cases: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    """按步骤顺序收集每条用例的 join `(room_id, user_id)`。

    1V1 用例有两个 join（primary 先、peer 后），顺序即角色顺序，画面证据声明的 uid 从这里取。
    """
    from app.sdk.sdk_extensions import VOLCENGINE_RTC_TOKEN_PLACEHOLDER

    pairs_by_case: dict[str, list[tuple[str, str]]] = {}
    for case in cases:
        if case["case_id"] not in EXPECTED_CASES:
            continue
        for payload in _case_call_params(case):
            room_id = payload.get("room_id")
            user_id = payload.get("user_id")
            if (
                payload.get("token") == VOLCENGINE_RTC_TOKEN_PLACEHOLDER
                and isinstance(room_id, str)
                and isinstance(user_id, str)
                and room_id
                and user_id
            ):
                pairs_by_case.setdefault(case["case_id"], []).append((room_id, user_id))
    return pairs_by_case


def visual_call_identities(pairs_by_case: dict[str, list[tuple[str, str]]]) -> tuple[str, str]:
    """从 1V1 画面用例的 join 顺序取 `(primary_user, peer_user)`；不一致即 fail closed。

    入参只包含本次选中且已导出 join 参数的用例，因此「不在表里」= 未选择，跳过即可。
    """
    identities: list[tuple[str, str]] = []
    for case_id in ONE_TO_ONE_VISUAL_CASES:
        if case_id not in pairs_by_case:
            continue
        pairs = pairs_by_case[case_id]
        if len(pairs) != 2 or pairs[0][0] != pairs[1][0] or pairs[0][1] == pairs[1][1]:
            raise AssertionError(f"{case_id} must join one room with two distinct users, got {pairs}")
        identities.append((pairs[0][1], pairs[1][1]))
    if not identities:
        raise AssertionError("no selected 1V1 visual case to declare picture evidence")
    if len(set(identities)) != 1:
        raise AssertionError(f"1V1 visual cases disagree on primary/peer users: {identities}")
    return identities[0]


def visual_call_views(primary_user: str, peer_user: str) -> tuple[dict[str, Any], ...]:
    """1V1 四个必需视图：两侧各自的 local/remote；uid 是火山侧的字符串 userId。"""
    return (
        {
            "view_role": PRIMARY_LOCAL_VIEW_ID,
            "node_id": NODE_ID,
            "node_role": "primary",
            "uid": primary_user,
            "kind": "local",
            "sdk": "volcengine_rtc",
            "expected_source_type": 0,
        },
        {
            "view_role": PRIMARY_REMOTE_VIEW_ID,
            "node_id": NODE_ID,
            "node_role": "primary",
            "uid": peer_user,
            "kind": "remote",
            "sdk": "volcengine_rtc",
            "expected_source_type": 4,
        },
        {
            "view_role": PEER_LOCAL_VIEW_ID,
            "node_id": PEER_NODE_ID,
            "node_role": "peer",
            "uid": peer_user,
            "kind": "local",
            "sdk": "volcengine_rtc",
            "expected_source_type": 4,
        },
        {
            "view_role": PEER_REMOTE_VIEW_ID,
            "node_id": PEER_NODE_ID,
            "node_role": "peer",
            "uid": primary_user,
            "kind": "remote",
            "sdk": "volcengine_rtc",
            "expected_source_type": 0,
        },
    )


def mint_token(room_id: str, user_id: str) -> str:
    """用 Server 端同一套 vendored builder 现场签发，不复用环境里的静态 token。"""
    from app.sdk.volcengine_token import token_signer

    ttl_seconds = int(os.environ.get("VOLCENGINE_TOKEN_TTL_SECONDS", "3600"))
    return token_signer.build_rtc_token(
        os.environ["VOLCENGINE_RTC_ID"],
        os.environ["VOLCENGINE_RTC_APPKEY"],
        room_id,
        user_id,
        ttl_seconds,
    )


def configure_case_token_map(pairs_by_case: dict[str, list[tuple[str, str]]]) -> dict[str, str]:
    """按用例的全部 join `(room_id, user_id)` 逐对签发；1V1 用例的两个用户缺一不可。"""
    from app.sdk.sdk_extensions import VOLCENGINE_TOKEN_MAP_ENV, volcengine_token_map_key

    token_map = {
        volcengine_token_map_key(room_id, user_id): mint_token(room_id, user_id)
        for room_id, user_id in sorted({pair for pairs in pairs_by_case.values() for pair in pairs})
    }
    if token_map:
        os.environ[VOLCENGINE_TOKEN_MAP_ENV] = json.dumps(token_map, separators=(",", ":"), sort_keys=True)
    else:
        os.environ.pop(VOLCENGINE_TOKEN_MAP_ENV, None)
    return token_map


async def start_real_agent(
    base_url: str,
    ws_url: str,
    *,
    node_id: str = NODE_ID,
    tags: str = AGENT_TAGS,
) -> asyncio.subprocess.Process:
    env = os.environ.copy()
    env["BEACON_AGENT_WS_URL"] = agent_ws_url(ws_url, env["BEACON_AUTH_TOKEN"])
    env["BEACON_NODE_ID"] = node_id
    env["BEACON_AGENT_GROUP_ID"] = REAL_E2E_GROUP_ID
    env["BEACON_AGENT_TAGS"] = tags
    env["BEACON_AGENT_CAPABILITIES"] = AGENT_CAPABILITIES
    process = await asyncio.create_subprocess_exec(
        str(AGENT_BINARY),
        cwd=str(ROOT),
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await wait_for_registered_device(base_url, process, node_id)
    except Exception:
        await stop_native_websocket_agent(process)
        raise
    return process


def launch_console_app(base_url: str) -> subprocess.Popen:
    AUTORUN_REPORT.unlink(missing_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "BEACON_CONSOLE_SERVER_URL": base_url,
            "BEACON_AUTH_TOKEN": os.environ["BEACON_AUTH_TOKEN"],
            "BEACON_NODE_ID": NODE_ID,
            "BEACON_CONSOLE_AUTORUN_PREFIX": CASE_PREFIX,
            "BEACON_CONSOLE_AUTORUN_CASE_IDS": ",".join(sorted(EXPECTED_CASES)),
            "BEACON_CONSOLE_AUTORUN_OUTPUT": str(AUTORUN_REPORT),
        }
    )
    return subprocess.Popen(
        [str(CONSOLE_EXECUTABLE)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


async def wait_autorun_report(process: subprocess.Popen, timeout_seconds: int = 300) -> dict[str, Any]:
    return await wait_for_autorun_report(process, AUTORUN_REPORT, timeout_seconds)


async def stop_console_app(process: subprocess.Popen) -> None:
    await stop_console_process(process)


def _evidence_matches(item: dict[str, Any], expected: dict[str, Any], room_id: str | None) -> bool:
    target = item.get("target", {})
    if target.get("function") != expected["function"]:
        return False
    if item.get("kind") != "event":
        return False
    if target.get("interface") != expected["interface"] or target.get("class") != expected["class_name"]:
        return False
    payload = item.get("payload", {})
    if any(payload.get(key) != value for key, value in expected.get("payload", {}).items()):
        return False
    if expected.get("payload_room_id") and payload.get("room_id") != room_id:
        return False
    return True


def case_evidence_gaps(case_id: str, report: dict[str, Any], rooms_by_case: dict[str, tuple[str, str]]) -> list[str]:
    required = REQUIRED_EVIDENCE_BY_CASE.get(case_id)
    if not required:
        return []
    room_id = rooms_by_case.get(case_id, (None, None))[0]
    evidence = [
        item for entry in report.get("case_results", []) for item in entry.get("observations", [])
    ]
    return [
        f"{item['function']}@{item['interface']}"
        for item in required
        if not any(_evidence_matches(entry, item, room_id) for entry in evidence)
    ]


def write_failed_case_evidence(case: dict[str, Any], report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_id": case.get("case_id"),
        "run_id": case.get("run_id"),
        "status": case.get("status"),
        "case_results": report.get("case_results", []),
    }
    FAILED_CASE_EVIDENCE_JSON.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


async def verify_server_reports(
    base_url: str, autorun: dict[str, Any], rooms_by_case: dict[str, tuple[str, str]]
) -> tuple[list[dict[str, Any]], list[str]]:
    import httpx

    if autorun.get("status") == "failed" and autorun.get("error"):
        raise AssertionError(str(autorun["error"]))
    cases = autorun.get("cases", [])
    case_ids = {case["case_id"] for case in cases}
    if case_ids != EXPECTED_CASES:
        raise AssertionError(f"unexpected autorun cases: {sorted(case_ids)}")

    reports: list[dict[str, Any]] = []
    failed_cases: list[str] = []
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        for case in cases:
            response = await client.get(
                f"{base_url}/api/v1/test-runs/{case['run_id']}/report",
                headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
            )
            response.raise_for_status()
            body = response.json()
            reports.append(body)
            # 跑完全部 case 再汇总失败：单个失败不应掩盖其他 case 的证据差异。
            if case["status"] != "passed":
                write_failed_case_evidence(case, body)
                failed_cases.append(case["case_id"])
                continue
            gaps = case_evidence_gaps(case["case_id"], body, rooms_by_case)
            if gaps:
                write_failed_case_evidence(case, body)
                failed_cases.append(f"{case['case_id']}(missing {','.join(gaps)})")
    return reports, failed_cases


def autorun_cleanup_case() -> dict[str, Any]:
    return {"case_id": CLEANUP_CASE_ID, "platform": "mac"}


async def run_cleanup_round(base_url: str, round_index: int) -> dict[str, Any]:
    import httpx
    from scripts.support.native_run_client import wait_run

    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        response = await client.post(
            f"{base_url}/api/v1/test-runs",
            headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
            json={"selector": {"node_id": NODE_ID}, "case_ids": [autorun_cleanup_case()["case_id"]]},
        )
        response.raise_for_status()
        body = await wait_run(client, base_url, response.json()["run_id"], {"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"})
    # 即时运行时只从 case 终态判断清理，不能用已删除的 StepResult 作为证据。
    results = body.get("case_results") if isinstance(body.get("case_results"), list) else []
    summary = {
        "round": round_index,
        "status": body.get("status"),
        "run_id": body.get("run_id"),
        "case_count": len({item.get("case_id") for item in results if item.get("case_id")}),
        "failed_case_ids": sorted(
            {str(item.get("case_id")) for item in results
             if item.get("status") != "passed" or item.get("cleanup_failed")}
        ),
    }
    if (summary["status"] != "passed" or summary["failed_case_ids"]
            or len(results) != 1 or results[0].get("case_id") != CLEANUP_CASE_ID):
        raise AssertionError(f"round {round_index} cleanup run failed: {body}")
    return summary


async def run_round(
    base_url: str, round_index: int, rooms_by_case: dict[str, tuple[str, str]]
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    autorun, reports, cleanup = await run_shared_autorun_round(
        base_url=base_url,
        round_index=round_index,
        run_cleanup=run_cleanup_round,
        launch_console=launch_console_app,
        wait_autorun=wait_autorun_report,
        verify_reports=lambda url, report: verify_server_reports(url, report, rooms_by_case),
        stop_console=stop_console_app,
    )
    reports, failed_cases = reports
    return autorun, reports, {**cleanup, "failed_cases": failed_cases}


def build_repeated_round_resilience(
    round_results: list[dict[str, Any]], cleanup_runs: list[dict[str, Any]]
) -> dict[str, Any]:
    cleanup_by_round = {item["round"]: item for item in cleanup_runs}
    per_round_results = []
    failed_rounds = []
    for item in round_results:
        cleanup = cleanup_by_round.get(item["round"], {})
        failed_cases = item.get("failed_cases") or []
        missing_run_id = not item.get("reports_verified") or not cleanup.get("run_id")
        round_status = "passed" if item.get("status") == "passed" and not failed_cases and not missing_run_id else "failed"
        if round_status == "failed":
            failed_rounds.append(item["round"])
        per_round_results.append(
            {
                "round": item["round"],
                "status": round_status,
                "autorun_status": item.get("status"),
                "reports_verified": int(item.get("reports_verified", 0)),
                "failed_cases": failed_cases,
                "cleanup_run_id": cleanup.get("run_id"),
                "cleanup_status": cleanup.get("status"),
                "cleanup_case_count": cleanup.get("case_count", 0),
                "cleanup_failed_case_ids": cleanup.get("failed_case_ids", []),
            }
        )
    cleanup_passed = len(cleanup_runs) == len(round_results) and all(
        item.get("status") == "passed"
        and item.get("case_count", 0) > 0
        and not item.get("failed_case_ids")
        for item in cleanup_runs
    )
    return {
        "status": "passed" if round_results and cleanup_passed and not failed_rounds else "failed",
        "rounds": len(round_results),
        "required_rounds": REQUIRED_ROUNDS,
        "reports_verified": sum(int(item.get("reports_verified", 0)) for item in round_results),
        "cleanup_runs": cleanup_runs,
        "round_results": per_round_results,
        "failed_rounds": failed_rounds,
    }


def build_visual_evidence_scenarios(
    reports: list[dict[str, Any]],
    selected_case_ids: set[str],
    pairs_by_case: dict[str, list[tuple[str, str]]],
) -> dict[str, Any]:
    """按标准汇总本 run 的场景画面证据：未选择的场景显式登记 not_exercised，不伪称已覆盖。"""
    one_to_one_cases = tuple(sorted(selected_case_ids & set(ONE_TO_ONE_VISUAL_CASES)))
    if one_to_one_cases:
        selected_pairs = {
            case_id: pairs for case_id, pairs in pairs_by_case.items() if case_id in one_to_one_cases
        }
        primary_user, peer_user = visual_call_identities(selected_pairs)
        one_to_one = build_scenario_visual_evidence(
            scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
            case_ids=one_to_one_cases,
            views=visual_call_views(primary_user, peer_user),
            reports=reports,
        )
    else:
        one_to_one = build_not_exercised_scenario(
            scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
            owner_layer="sdk_adapter_volcengine_rtc",
            reason="本次运行未选择 1V1 画面用例（BEACON_MAC_CONSOLE_VOLCENGINE_CASE_IDS 子集运行）。",
            follow_up="按子集 gate 运行 1V1 画面用例后转为硬门判定。",
        )
    # 火山目前没有 small room 用例与画面能力面：保持显式未覆盖，且一旦产出画面证据即失败。
    assert_scenario_has_no_picture_evidence(
        scenario_id=SCENARIO_SMALL_ROOM, reports=reports, case_ids=()
    )
    small_room = build_not_exercised_scenario(
        scenario_id=SCENARIO_SMALL_ROOM,
        owner_layer="sdk_adapter_volcengine_rtc",
        reason="火山链路当前没有 small room 场景用例，也没有对应的画面能力面声明。",
        follow_up="B-020 之外另立 small room 用例与能力面，声明必需视图后按同一标准判定。",
    )
    return summarize_visual_evidence(
        {item["scenario_id"]: item for item in (one_to_one, small_room)}
    )


def assert_visual_evidence_passed(visual_evidence: dict[str, Any]) -> None:
    """画面场景任一必需视图缺失即失败；把具名原因带进错误信息，便于事后定位。"""
    if visual_evidence.get("status") == "passed":
        return
    failing = {
        scenario_id: {
            "missing_views": visual_evidence.get("scenarios", {})
            .get(scenario_id, {})
            .get("missing_views", []),
            "fail_reasons": visual_evidence.get("scenarios", {}).get(scenario_id, {}).get("fail_reasons", {}),
        }
        for scenario_id in visual_evidence.get("missing_scenarios", [])
    }
    raise AssertionError(f"visual evidence failed: {json.dumps(failing, ensure_ascii=False, sort_keys=True)}")


async def run_real_validation(rounds: int) -> dict[str, Any]:
    import uvicorn

    from app.main import app

    rooms_by_case = join_rooms_by_case(CASES)
    pairs_by_case = join_pairs_by_case(CASES)
    configure_case_token_map(pairs_by_case)
    run(["cmake", "-S", ".", "-B", ".build/default"])
    run(["cmake", "--build", ".build/default", "--target", "mac_real_volcengine_adapter_test", "mac_volcengine_agent_bridge"])
    run(["ctest", "--test-dir", ".build/default", "-R", "VOLCENGINE-REAL", "--output-on-failure"])
    run(["swift", "build", "--package-path", "apps/mac_test_console"])

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    import app.main as server_main
    server_main.runner_supervisor._process._base_url = base_url
    ws_url = f"ws://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    primary_agent = peer_agent = None
    try:
        await wait_http(base_url)
        primary_agent = await start_real_agent(base_url, ws_url)
        peer_agent = await start_real_agent(
            base_url, ws_url, node_id=PEER_NODE_ID, tags=PEER_AGENT_TAGS
        )
        round_results = []
        cleanup_runs = []
        all_reports: list[dict[str, Any]] = []
        for round_index in range(1, rounds + 1):
            autorun, reports, cleanup = await run_round(base_url, round_index, rooms_by_case)
            all_reports.extend(reports)
            cleanup_runs.append(cleanup)
            round_results.append(
                {
                    "round": round_index,
                    "status": autorun.get("status"),
                    "autorun": autorun,
                    "reports_verified": len(reports),
                    "failed_cases": cleanup.get("failed_cases", []),
                }
            )
        resilience = build_repeated_round_resilience(round_results, cleanup_runs)
        if resilience["status"] != "passed":
            raise AssertionError(f"console volcengine rounds failed: {resilience['failed_rounds']}")
        visual_evidence = build_visual_evidence_scenarios(all_reports, EXPECTED_CASES, pairs_by_case)
        assert_visual_evidence_passed(visual_evidence)
        return {
            "server_url": base_url,
            "token_pairs": sorted(
                f"{room}#{user}" for pairs in pairs_by_case.values() for room, user in pairs
            ),
            "repeated_round_resilience": resilience,
            "autorun": round_results[-1]["autorun"],
            "case_results": [
                {
                    "case_id": case["case_id"],
                    "run_id": case["run_id"],
                    "status": case["status"],
                }
                for case in round_results[-1]["autorun"].get("cases", [])
            ],
            "round_results": resilience["round_results"],
            "visual_call": {
                "primary_node_id": NODE_ID,
                "peer_node_id": PEER_NODE_ID,
                "group_id": REAL_E2E_GROUP_ID,
                "user_ids": sorted(
                    {user for pairs in pairs_by_case.values() for _, user in pairs},
                ),
                "views": sorted(VISUAL_ARTIFACT_KEYS),
            },
            "visual_evidence": visual_evidence,
            "evidence_coverage": {
                case_id: sorted(item["function"] for item in required)
                for case_id, required in sorted(REQUIRED_EVIDENCE_BY_CASE.items())
                if case_id in EXPECTED_CASES
            },
        }
    finally:
        for process in (primary_agent, peer_agent):
            if process is not None:
                await stop_native_websocket_agent(process)
        server.should_exit = True
        thread.join(timeout=5)


def main() -> int:
    missing = missing_real_env()
    if missing or not framework_exists(sdk_root()):
        reason = (
            "missing real mac sdk environment: " + ",".join(missing)
            if missing
            else "missing VolcEngineRTC.framework under VOLCENGINE_MAC_SDK_ROOT"
        )
        write_report("skipped", reason)
        print(f"mac console volcengine: SKIPPED - {reason}")
        return 0
    try:
        # 先在起服务/起 Agent/编译之前校验轮次，避免参数写错时白跑一轮构建。
        rounds = autorun_round_count()
        result = asyncio.run(run_real_validation(rounds))
    except Exception as exc:  # noqa: BLE001
        message = f"mac console volcengine validation failed: {exc}"
        write_report("failed", message)
        print(message, file=sys.stderr)
        return 1
    write_report("passed", "mac console app-driven volcengine validation passed", result)
    print(f"mac console app-driven volcengine validation passed ({result['repeated_round_resilience']['rounds']} rounds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
