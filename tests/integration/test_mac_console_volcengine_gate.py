"""Mac Test Console 火山真实链路 gate 的合同测试。

覆盖新 gate 脚本里最容易静默退化成「橡皮图章」的四类逻辑：期望 case 集合、必备回调证据的
fail-closed 判定、轮次下限，以及轮次/cleanup 汇总。真实 SDK 链路本身由 `make
test-mac-console-volcengine` 验证，这里只钉住纯逻辑与目录契约。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sdk.sdk_extensions import VOLCENGINE_TOKEN_MAP_ENV

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import scripts.validation.run_mac_console_volcengine_validation as volcengine_gate  # noqa: E402
from scripts.validation.run_mac_console_volcengine_validation import (  # noqa: E402
    CASE_IDS_ENV,
    CASE_PREFIX,
    CLEANUP_CASE_ID,
    REQUIRED_ROUNDS,
    ROUNDS_ENV,
    autorun_round_count,
    build_repeated_round_resilience,
    case_evidence_gaps,
    configure_case_token_map,
    expected_autorun_cases,
    framework_exists,
    join_pairs_by_case,
    join_rooms_by_case,
    missing_real_env,
    verify_server_reports,
)

AUTH = {"Authorization": "Bearer local-test-token"}
VOLCENGINE_CASE_IDS = {
    "TC-PY-VOLCENGINE-L1-LIFECYCLE",
    "TC-PY-VOLCENGINE-L1-CONNECTION-STATE",
    "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK",
    "TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP",
    "TC-PY-VOLCENGINE-L1-INVALID-TOKEN",
    "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH",
    "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED",
    CLEANUP_CASE_ID,
}
JOIN_CASE_IDS = {
    "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK",
    "TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP",
    "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH",
    "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED",
}


def _console_cases(monkeypatch) -> dict[str, dict]:
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)
    response = client.get("/api/v1/console/test-cases", headers=AUTH)
    assert response.status_code == 200
    return {item["case_id"]: item for item in response.json()["cases"]}


def _evidence_report(function: str, interface: str, class_name: str, payload: dict) -> dict:
    return {
        "case_results": [
            {
                "observations": [
                    {
                        "kind": "event",
                        "target": {"function": function, "interface": interface, "class": class_name},
                        "payload": payload,
                    }
                ]
            }
        ]
    }


def test_IT_MAC_CONSOLE_VOLCENGINE_01_cases_are_visible_and_runnable(monkeypatch):
    cases = _console_cases(monkeypatch)

    assert VOLCENGINE_CASE_IDS.issubset(cases)
    for case_id in VOLCENGINE_CASE_IDS:
        assert cases[case_id]["platform"] == "mac", case_id
        assert cases[case_id]["implementation_status"] == "runnable", case_id
    join_case = next(case for case in volcengine_gate.CASES if case["case_id"] == "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK")
    assert join_case["token_bindings"]
    assert "runtime-reset-baseline" in cases[CLEANUP_CASE_ID]["tags"]


def test_IT_MAC_CONSOLE_VOLCENGINE_02_baseline_satisfies_runtime_isolation_contract(monkeypatch):
    cases = _console_cases(monkeypatch)

    # Console autorun 只在 requires_runtime_isolation 为真时插入 cleanup run：
    # 这五个 L1 用例必须被判定为需要隔离，否则本 gate 覆盖不到清理路径。
    for case_id in sorted(VOLCENGINE_CASE_IDS - {CLEANUP_CASE_ID}):
        assert cases[case_id]["requires_runtime_isolation"] is True, case_id

    # `autorunCleanupCase` 要求「同 platform + runnable + runtime-reset-baseline tag +
    # 覆盖同一 SDK」且候选唯一；唯一候选必须落在本 gate 的 cleanup 常量上。
    candidates = [
        case
        for case in cases.values()
        if case["platform"] == "mac"
        and case["implementation_status"] == "runnable"
        and "runtime-reset-baseline" in case["tags"]
        and "volcengine_rtc" in case["sdk_names"]
    ]
    assert [case["case_id"] for case in candidates] == [CLEANUP_CASE_ID]




def test_IT_MAC_CONSOLE_VOLCENGINE_03_expected_cases_cover_the_runnable_catalog(monkeypatch):
    monkeypatch.delenv(CASE_IDS_ENV, raising=False)
    cases = volcengine_gate.CASES

    assert expected_autorun_cases(cases) == VOLCENGINE_CASE_IDS

    monkeypatch.setenv(CASE_IDS_ENV, "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK")
    assert expected_autorun_cases(cases) == {"TC-PY-VOLCENGINE-L1-JOIN-CALLBACK"}

    monkeypatch.setenv(CASE_IDS_ENV, "TC-PY-VOLCENGINE-L1-NOT-A-CASE")
    with pytest.raises(ValueError, match=CASE_IDS_ENV):
        expected_autorun_cases(cases)


def test_IT_MAC_CONSOLE_VOLCENGINE_04_round_count_requires_the_documented_minimum(monkeypatch):
    monkeypatch.delenv(ROUNDS_ENV, raising=False)
    assert autorun_round_count() == REQUIRED_ROUNDS

    monkeypatch.setenv(ROUNDS_ENV, str(REQUIRED_ROUNDS + 1))
    assert autorun_round_count() == REQUIRED_ROUNDS + 1

    # 少于验收要求的轮次不能写成 passed 产物，因此必须直接拒绝。
    for value in ("1", "0", "-3", "two"):
        monkeypatch.setenv(ROUNDS_ENV, value)
        with pytest.raises(ValueError, match=ROUNDS_ENV):
            autorun_round_count()


def test_IT_MAC_CONSOLE_VOLCENGINE_05_evidence_gaps_fail_closed():
    rooms = {"TC-PY-VOLCENGINE-L1-JOIN-CALLBACK": ("room-a", "user-a")}
    good = _evidence_report(
        "onRoomStateChanged", "byte_rtc_room", "ByteRTCRoomDelegate", {"room_id": "room-a", "state": 0}
    )

    assert case_evidence_gaps("TC-PY-VOLCENGINE-L1-JOIN-CALLBACK", good, rooms) == []

    wrong_interface = _evidence_report(
        "onRoomStateChanged", "byte_rtc_engine", "ByteRTCEngineDelegate", {"room_id": "room-a", "state": 0}
    )
    wrong_state = _evidence_report(
        "onRoomStateChanged", "byte_rtc_room", "ByteRTCRoomDelegate", {"room_id": "room-a", "state": 2}
    )
    wrong_room = _evidence_report(
        "onRoomStateChanged", "byte_rtc_room", "ByteRTCRoomDelegate", {"room_id": "room-b", "state": 0}
    )
    for report in (wrong_interface, wrong_state, wrong_room):
        assert case_evidence_gaps("TC-PY-VOLCENGINE-L1-JOIN-CALLBACK", report, rooms) == [
            "onRoomStateChanged@byte_rtc_room"
        ]

    # 未声明证据要求的 case 不应被这条检查误判。
    assert case_evidence_gaps("TC-PY-VOLCENGINE-L1-LIFECYCLE", wrong_room, rooms) == []


def test_IT_MAC_CONSOLE_VOLCENGINE_06_verify_reports_fails_closed_on_missing_evidence(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    rooms = {
        "TC-PY-VOLCENGINE-L1-JOIN-CALLBACK": ("room-a", "user-a"),
        "TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP": ("room-a", "user-a"),
        "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH": ("room-a", "user-b"),
        "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED": ("room-a", "user-b"),
    }
    autorun = {
        "status": "passed",
        "cases": [
            {"case_id": case_id, "run_id": case_id, "status": "passed"}
            for case_id in sorted(VOLCENGINE_CASE_IDS)
        ],
    }
    reports = {
        case_id: {"case_results": []} for case_id in sorted(VOLCENGINE_CASE_IDS)
    }
    reports["TC-PY-VOLCENGINE-L1-CONNECTION-STATE"] = _evidence_report(
        "onConnectionStateChanged", "byte_rtc_engine", "ByteRTCEngineDelegate", {"state": 3}
    )
    reports["TC-PY-VOLCENGINE-L1-JOIN-CALLBACK"] = _evidence_report(
        "onRoomStateChanged", "byte_rtc_room", "ByteRTCRoomDelegate", {"room_id": "room-a", "state": 0}
    )
    reports["TC-PY-VOLCENGINE-L1-LEAVE-CLEANUP"] = _evidence_report(
        "onLeaveRoom", "byte_rtc_room", "ByteRTCRoomDelegate", {"room_id": "room-a"}
    )
    # 1V1 画面用例的必备证据：join 成功 + 远端首帧 + 快照回调（任一缺失即失败）。
    for case_id in ("TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH", "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED"):
        reports[case_id] = {
            "case_results": [
                {
                    "observations": [
                        {
                            "kind": "event",
                            "target": {
                                "function": "onRoomStateChanged",
                                "interface": "byte_rtc_room",
                                "class": "ByteRTCRoomDelegate",
                            },
                            "payload": {"room_id": "room-a", "state": 0},
                        },
                        {
                            "kind": "event",
                            "target": {
                                "function": "onFirstRemoteVideoFrame",
                                "interface": "byte_rtc_engine",
                                "class": "ByteRTCEngineDelegate",
                            },
                            "payload": {"uid": "user-a"},
                        },
                        {
                            "kind": "event",
                            "target": {
                                "function": "onSnapshotTaken",
                                "interface": "byte_rtc_engine",
                                "class": "ByteRTCEngineDelegate",
                            },
                            "payload": {"view_role": "primary_local_preview", "err_code": 0},
                        },
                    ]
                }
            ]
        }

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class FakeClient:
        def __init__(self, payloads: dict) -> None:
            self._payloads = payloads

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def get(self, url: str, headers: dict | None = None) -> FakeResponse:
            run_id = url.split("/test-runs/")[1].split("/")[0]
            return FakeResponse(self._payloads[run_id])

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient(reports))
    _, failed = asyncio.run(verify_server_reports("http://127.0.0.1:1", autorun, rooms))
    assert failed == []

    # 少一条 join 证据（其他 case 的证据不能顶替）：必须报成失败而不是通过。
    reports["TC-PY-VOLCENGINE-L1-JOIN-CALLBACK"] = {"case_results": []}
    _, failed = asyncio.run(verify_server_reports("http://127.0.0.1:1", autorun, rooms))
    assert failed == ["TC-PY-VOLCENGINE-L1-JOIN-CALLBACK(missing onRoomStateChanged@byte_rtc_room)"]


def test_IT_MAC_CONSOLE_VOLCENGINE_07_round_summary_fails_closed():
    round_results = [
        {"round": 1, "status": "passed", "reports_verified": 6, "failed_cases": []},
        {"round": 2, "status": "passed", "reports_verified": 6, "failed_cases": ["TC-X"]},
        {"round": 3, "status": "failed", "reports_verified": 6, "failed_cases": []},
    ]
    cleanup_runs = [
        {"round": 1, "status": "passed", "run_id": "run-cleanup-1", "case_count": 1, "failed_case_ids": []},
        {"round": 2, "status": "passed", "run_id": "run-cleanup-2", "case_count": 1, "failed_case_ids": []},
        {"round": 3, "status": "passed", "run_id": "run-cleanup-3", "case_count": 1, "failed_case_ids": []},
    ]

    summary = build_repeated_round_resilience(round_results, cleanup_runs)

    assert summary["status"] == "failed"
    assert summary["failed_rounds"] == [2, 3]
    assert summary["round_results"][0]["status"] == "passed"
    assert summary["round_results"][1]["failed_cases"] == ["TC-X"]

    # cleanup run 没跑起来（没有 run_id / 没有 case 终态）不能算通过。
    summary = build_repeated_round_resilience(round_results[:1], [{"round": 1, "status": "passed"}])
    assert summary["status"] == "failed"
    assert summary["cleanup_runs"][0].get("run_id") is None

    # 单轮汇总只反映它实际跑过的轮次；「至少 3 轮」由 autorun_round_count() 在解析期强制。
    summary = build_repeated_round_resilience(round_results[:1], cleanup_runs[:1])
    assert summary["status"] == "passed"
    assert (summary["rounds"], summary["required_rounds"]) == (1, REQUIRED_ROUNDS)


@pytest.mark.parametrize("case_results", [
    [{"case_id": CLEANUP_CASE_ID, "status": "passed", "cleanup_failed": False}],
    [],
    [{"case_id": CLEANUP_CASE_ID, "status": "failed", "cleanup_failed": False}],
    [{"case_id": CLEANUP_CASE_ID, "status": "passed", "cleanup_failed": True}],
    [{"case_id": "wrong-case", "status": "passed", "cleanup_failed": False}],
])
def test_IT_MAC_CONSOLE_VOLCENGINE_cleanup_uses_current_case_terminal_results(monkeypatch, case_results):
    from scripts.support import native_run_client

    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    body = {"run_id": "cleanup-current", "status": "passed", "case_results": case_results,
            "results": [{"case_id": CLEANUP_CASE_ID, "status": "passed"}]}
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"run_id": body["run_id"]}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport, **kwargs))

    async def wait_run(*args, **kwargs):
        return body

    monkeypatch.setattr(native_run_client, "wait_run", wait_run)
    if case_results and case_results[0] == {"case_id": CLEANUP_CASE_ID, "status": "passed", "cleanup_failed": False}:
        summary = asyncio.run(volcengine_gate.run_cleanup_round("http://server", 1))
        assert summary["case_count"] == 1
        assert summary["failed_case_ids"] == []
    else:
        with pytest.raises(AssertionError, match="cleanup run failed"):
            asyncio.run(volcengine_gate.run_cleanup_round("http://server", 1))


def test_IT_MAC_CONSOLE_VOLCENGINE_08_token_map_is_minted_per_room_and_user(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv(CASE_IDS_ENV, raising=False)
    monkeypatch.setenv("VOLCENGINE_RTC_ID", "app-id")
    monkeypatch.setenv("VOLCENGINE_RTC_APPKEY", "app-key")
    # 先登记该环境变量，保证测试结束后 monkeypatch 会把 gate 写入的值还原。
    monkeypatch.setenv(VOLCENGINE_TOKEN_MAP_ENV, "")
    monkeypatch.setattr(
        volcengine_gate, "mint_token", lambda room_id, user_id: f"token:{room_id}:{user_id}"
    )

    pairs_by_case = join_pairs_by_case(volcengine_gate.CASES)
    assert set(pairs_by_case) == JOIN_CASE_IDS
    # 1V1 用例必须导出两个 join，否则 primary 的 token 不会被签发。
    for case_id in ("TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-SYNTH", "TC-PY-VOLCENGINE-L1-1V1-REMOTE-VIDEO-RENDERED"):
        assert len(pairs_by_case[case_id]) == 2, case_id

    token_map = configure_case_token_map(pairs_by_case)

    assert token_map
    for pairs in pairs_by_case.values():
        for room_id, user_id in pairs:
            assert token_map[f"{room_id}#{user_id}"] == f"token:{room_id}:{user_id}"
    assert json.loads(os.environ[VOLCENGINE_TOKEN_MAP_ENV]) == token_map
    # 单 join 用例的 rooms 投影与全量 pairs 保持一致。
    rooms = join_rooms_by_case(volcengine_gate.CASES)
    assert set(rooms) == JOIN_CASE_IDS
    assert {pair for pairs in pairs_by_case.values() for pair in pairs}.issuperset(rooms.values())


def test_IT_MAC_CONSOLE_VOLCENGINE_09_gate_launches_a_native_direct_agent():
    source = (ROOT / "scripts/validation/run_mac_console_volcengine_validation.py").read_text(encoding="utf-8")

    # harness 只能启动原生 Agent 进程，不得自己持有 Agent WebSocket 或 relay 协议 packet。
    assert "mac_volcengine_agent_bridge" in source
    assert "RealAgentBridge" not in source
    assert "websockets.connect" not in source
    assert "async def stop_console_app(" in source


def test_IT_MAC_CONSOLE_VOLCENGINE_10_missing_environment_skips_the_gate(monkeypatch, tmp_path):
    for name in ("VOLCENGINE_MAC_SDK_ROOT", "VOLCENGINE_RTC_ID", "VOLCENGINE_RTC_APPKEY", "BEACON_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    missing = missing_real_env()
    assert {"VOLCENGINE_RTC_ID", "VOLCENGINE_RTC_APPKEY"}.issubset(set(missing))
    assert framework_exists(None) is False
    assert framework_exists(tmp_path) is False


def test_IT_MAC_CONSOLE_VOLCENGINE_11_prefix_matches_every_gate_case():
    assert all(case_id.startswith(CASE_PREFIX) for case_id in VOLCENGINE_CASE_IDS)


@pytest.mark.parametrize("state", [0, -1000])
def test_IT_MAC_CONSOLE_VOLCENGINE_native_gate_consumes_current_callback_target(state):
    from scripts.validation.run_mac_volcengine_real import assert_join_evidence

    report = _evidence_report("onRoomStateChanged", "byte_rtc_room", "ByteRTCRoomDelegate", {"state": state})
    if state == 0:
        assert_join_evidence(report)
    else:
        with pytest.raises(AssertionError):
            assert_join_evidence(report)
