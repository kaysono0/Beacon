"""Mac Test Console API 测试。"""

import asyncio
import inspect
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.console_api as console_api
import app.main as main_module
import app.runs.python_native_registry as native_registry
from app.reporting.evidence_runtime import ResultCollector
from app.devices.device_models import Device, DeviceSelector, DeviceSession
from app.main import app
from app.observations.observation_models import ObservationInput
from app.observations.observation_service import ObservationService
from app.runs.run_runtime import ServerRunRuntime
from app.runs.test_models import TestCase
from app.reporting.reporting import ReportGenerator
from app.runs.test_models import TestRun


AUTH = {"Authorization": "Bearer local-test-token"}
ROOT = Path(__file__).resolve().parents[2]


def test_IT_CONSOLE_00_unified_mac_launcher_keeps_auth_and_routes_on_selected_port():
    manual = (ROOT / "scripts/dev/run_manual_env.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    zego_gate = (ROOT / "scripts/validation/run_mac_zego_real.py").read_text(encoding="utf-8")

    assert "make run-mac-console-real-server" in manual
    assert "BEACON_CONSOLE_SERVER_PORT=\"$PORT\"" in manual
    assert "BEACON_CONSOLE_SERVER_URL=\"http://127.0.0.1:${PORT}\"" in manual
    assert "test-mac-console-real:" in makefile
    assert "test-mac-console-dual-real:" not in makefile
    assert "run-mac-console-agora-server:" not in makefile
    assert "scripts/validation/run_mac_console_real_validation.py" in makefile
    assert "agora_rtc=$(BEACON_CONSOLE_SERVER_URL)#mac-real-e2e-001" in makefile
    assert "zego_express=$(BEACON_CONSOLE_SERVER_URL)#mac-zego-real-001" in makefile
    assert 'os.environ.setdefault("BEACON_AUTH_TOKEN"' not in zego_gate


def test_IT_CONSOLE_01_lists_sdk_capabilities(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/console/sdk-capabilities", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["sdks"][0]["sdk"] == "agora_rtc"
    assert any(item["interface"] == "rtc_engine" for item in body["sdks"][0]["interfaces"])
    assert any(method["function"] == "joinChannel" for method in body["sdks"][0]["interfaces"][0]["methods"])


def test_IT_CONSOLE_02_lists_python_native_test_cases_without_reading_compiled_json(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    sources = []
    load_module = native_registry._load_module

    def load_source(path):
        assert path.suffix == ".py"
        assert path.is_relative_to(ROOT / "test_cases/python")
        sources.append(path)
        return load_module(path)

    monkeypatch.setattr(native_registry, "_load_module", load_source)
    client = TestClient(app)

    response = client.get("/api/v1/console/test-cases", headers=AUTH)

    assert response.status_code == 200
    cases = response.json()["cases"]
    assert len(cases) == 59
    assert sources
    assert ROOT / "test_cases/python/zego/zego_video_cases.py" in sources
    assert any(case["case_id"] == "TC-MAC-SMOKE" for case in cases)
    assert any(
        case["case_id"] == "TC-PY-ZEGO-L1-1V1-VIDEO-RENDER-SNAPSHOT"
        and case["source"] == "test_cases/python/zego/zego_video_cases.py"
        for case in cases
    )
    assert any(
        case["case_id"] == "TC-PY-ZEGO-L1-1V1-VIDEO-SYNTH-RENDER-SNAPSHOT"
        and case["covered_capabilities"] == [
            "stream_publish",
            "stream_play",
            "local_video_preview",
            "synthetic_video_source",
            "visual_snapshot_observability",
        ]
        for case in cases
    )
    assert any(
        case["case_id"] == "TC-PY-MOCK-COMPLEX-REFERENCE-TRACER"
        and case["source"] == "test_cases/python/common/mock_complex_reference_cases.py"
        and case["covered_capabilities"] == ["apply_value", "value_applied", "last_applied_value"]
        for case in cases
    )
    assert any(
        case["case_id"] == "TC-PY-MOCK-COMPLEX-DIRECT-MATRIX"
        and case["source"] == "test_cases/python/common/mock_complex_reference_cases.py"
        and case["covered_capabilities"]
        == ["configure_value", "apply_value", "value_applied", "last_applied_value"]
        and "protocol_operation_tracer" in case["tags"]
        for case in cases
    )
    assert any(
        case["case_id"] == "TC-PY-PROTOCOL-OPERATION-JOIN-TRACER"
        and case["source"] == "test_cases/python/common/legacy_smoke_tracers.py"
        and case["tags"] == ["python_source", "protocol_operation_tracer"]
        for case in cases
    )
    assert all(case["source"].startswith("test_cases/python/") for case in cases)
    assert all("suite" in case for case in cases)
    python_join_case = next(case for case in cases if case["case_id"] == "TC-PY-AGORA-JOIN-CALLBACK")
    assert python_join_case["source"] == "test_cases/python/agora/agora_phase_a_cases.py"
    assert python_join_case["steps"] == []
    assert python_join_case["sdk_names"] == ["agora_rtc"]
    agora_real_cases = [case for case in cases if case["case_id"].startswith("TC-MAC-AGORA-REAL")]
    assert any(case["case_id"] == "TC-MAC-AGORA-REAL-JOIN-CALLBACK" for case in agora_real_cases)
    assert all(case["scenario_family"] == "direct_call" for case in agora_real_cases)
    assert all(case["implementation_status"] == "runnable" for case in agora_real_cases)
    assert all(case["suite"] == "agora_direct_call_core" for case in agora_real_cases)
    assert any(
        case["case_id"] == "TC-MAC-AGORA-REAL-JOIN-CALLBACK"
        and case["covered_capabilities"] == ["join_success_fact", "leave_cleanup", "clock_wait"]
        for case in agora_real_cases
    )
    invalid_token_case = next(case for case in cases if case["case_id"] == "TC-MAC-AGORA-INVALID-TOKEN-FAILURE")
    assert invalid_token_case["scenario_family"] == "failure_recovery"
    assert invalid_token_case["implementation_status"] == "runnable"
    assert invalid_token_case["covered_capabilities"] == ["invalid_token_failure"]
    assert invalid_token_case["suite"] == "agora_failure_recovery_resilience"
    invalid_token_recovery_case = next(
        case for case in cases if case["case_id"] == "TC-MAC-AGORA-INVALID-TOKEN-THEN-RECOVER"
    )
    assert invalid_token_recovery_case["scenario_family"] == "failure_recovery"
    assert invalid_token_recovery_case["implementation_status"] == "runnable"
    assert invalid_token_recovery_case["covered_capabilities"] == [
        "invalid_token_failure",
        "recovery_after_failure",
        "join_success_fact",
        "leave_cleanup",
    ]
    assert invalid_token_recovery_case["suite"] == "agora_failure_recovery_resilience"
    token_renewal_case = next(
        case for case in cases if case["case_id"] == "TC-MAC-AGORA-TOKEN-RENEWAL-RECOVERY"
    )
    assert token_renewal_case["scenario_family"] == "failure_recovery"
    assert token_renewal_case["implementation_status"] == "runnable"
    assert token_renewal_case["covered_capabilities"] == [
        "invalid_token_failure",
        "token_renewal_recovery",
        "join_success_fact",
        "leave_cleanup",
    ]
    assert token_renewal_case["suite"] == "agora_failure_recovery_resilience"
    permission_denied_case = next(
        case for case in cases if case["case_id"] == "TC-MAC-AGORA-PERMISSION-DENIED-JOIN-FAILURE"
    )
    assert permission_denied_case["scenario_family"] == "failure_recovery"
    assert permission_denied_case["implementation_status"] == "runnable"
    assert permission_denied_case["covered_capabilities"] == ["permission_denied_failure"]
    assert permission_denied_case["suite"] == "agora_failure_recovery_resilience"
    permission_denied_preview_case = next(
        case for case in cases if case["case_id"] == "TC-MAC-AGORA-PERMISSION-DENIED-PREVIEW-FAILURE"
    )
    assert permission_denied_preview_case["scenario_family"] == "failure_recovery"
    assert permission_denied_preview_case["implementation_status"] == "runnable"
    assert permission_denied_preview_case["covered_capabilities"] == ["permission_denied_failure"]
    assert permission_denied_preview_case["suite"] == "agora_failure_recovery_resilience"
    l1_join_case = next(case for case in cases if case["case_id"] == "TC-MAC-AGORA-JOIN-CALLBACK-SUCCESS")
    assert l1_join_case["scenario_family"] == "direct_call"
    assert l1_join_case["implementation_status"] == "runnable"
    assert l1_join_case["covered_capabilities"] == ["join_success_fact"]
    assert l1_join_case["suite"] == "agora_direct_call_l1"
    l1_state_case = next(case for case in cases if case["case_id"] == "TC-MAC-AGORA-CONNECTION-STATE-TRANSITION")
    assert l1_state_case["scenario_family"] == "direct_call"
    assert l1_state_case["implementation_status"] == "runnable"
    assert l1_state_case["covered_capabilities"] == ["connection_state_transition"]
    assert l1_state_case["suite"] == "agora_direct_call_l1"
    common_smoke = next(case for case in cases if case["case_id"] == "TC-COMMON-SMOKE")
    assert common_smoke["suite"] == "legacy_protocol_smoke"
    assert common_smoke["scenario_family"] == "legacy_protocol"
    assert common_smoke["implementation_status"] == "runnable"
    assert common_smoke["tags"] == ["legacy_protocol_reference"]
    mac_smoke = next(case for case in cases if case["case_id"] == "TC-MAC-SMOKE")
    assert mac_smoke["suite"] == "legacy_protocol_smoke"
    assert mac_smoke["scenario_family"] == "legacy_protocol"
    assert mac_smoke["implementation_status"] == "runnable"
    assert mac_smoke["tags"] == ["legacy_protocol_reference"]
    assert "TC-MAC-AGORA-WEAK-NETWORK-RECOVERY" not in {case["case_id"] for case in cases}
    assert all("requires_runtime_isolation" in case for case in cases)
    assert all(case["requires_runtime_isolation"] for case in agora_real_cases)
    cleanup_baseline = next(case for case in cases if case["case_id"] == "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE")
    assert "runtime-reset-baseline" in cleanup_baseline["tags"]
    # 火山变体的 runtime-isolation 清理用例：Console autorun 按「同 platform + 同 SDK + 唯一
    # runtime-reset-baseline」选它，缺了它整个 `make test-mac-console-volcengine` 会直接拒绝开跑。
    volcengine_baseline = next(
        case for case in cases if case["case_id"] == "TC-PY-VOLCENGINE-L1-RUNTIME-CLEANUP-BASELINE"
    )
    assert "runtime-reset-baseline" in volcengine_baseline["tags"]
    assert volcengine_baseline["platform"] == "mac"
    assert volcengine_baseline["implementation_status"] == "runnable"
    assert volcengine_baseline["requires_runtime_isolation"] is True
    # autorun-order 值是 autorun 顺序合同的一部分：真实的加载/加入顺序由这三条 case 的 tag 钉住，
    # 防止 tag 被改坏后 autorun 静默回退到 caseID 字典序。
    real_case_order_tags = {
        "TC-MAC-AGORA-REAL-LIFECYCLE": ["autorun-order:0"],
        "TC-MAC-AGORA-REAL-JOIN-CALLBACK": ["autorun-order:1"],
        "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE": ["autorun-order:2"],
    }
    for case_id, expected_tags in real_case_order_tags.items():
        assert next(case for case in cases if case["case_id"] == case_id)["tags"] == expected_tags
    mock_tracer = next(case for case in cases if case["case_id"] == "TC-PY-MOCK-COMPLEX-REFERENCE-TRACER")
    assert mock_tracer["requires_runtime_isolation"] is False




def test_IT_CONSOLE_03A_report_generator_accepts_get_run_only_reader():
    run = TestRun(run_id="run-reader-report", status="passed", selector=DeviceSelector(), cases=[])

    class RunReader:
        async def get_run(self, run_id: str) -> TestRun | None:
            return run if run_id == run.run_id else None

    run_reader = RunReader()
    generator = ReportGenerator(run_reader)
    report = asyncio.run(generator.generate(run.run_id, "json"))

    assert list(inspect.signature(ReportGenerator).parameters)[0] == "run_reader"
    assert generator._run_reader is run_reader
    assert not hasattr(generator, "_orchestrator")
    assert report.run_id == run.run_id
    assert report.summary["status"] == "passed"


def test_IT_CONSOLE_03B_run_detail_accepts_get_run_only_reader():
    run = TestRun(run_id="run-reader-console", status="passed", selector=DeviceSelector(), cases=[])

    class RunReader:
        async def get_run(self, run_id: str) -> TestRun | None:
            return run if run_id == run.run_id else None

    class LogReader:
        async def query_by_trace(self, run_id: str) -> list[dict]:
            return [{"run_id": run_id}]

    run_reader = RunReader()
    payload = asyncio.run(
        console_api.run_detail_payload(
            run.run_id,
            run_reader,
            ReportGenerator(run_reader),
            LogReader(),
        )
    )

    assert list(inspect.signature(console_api.run_detail_payload).parameters)[1] == "run_reader"
    assert payload["run"]["run_id"] == run.run_id
    assert payload["report"]["run_id"] == run.run_id
    assert payload["logs"] == [{"run_id": run.run_id}]
    assert payload["observation_cursor_enabled"] is False


def test_IR09_target_detail_reads_live_logs_from_observations_not_legacy_log_reader():
    observations = ObservationService()
    run = TestRun(
        run_id="target-console", status="running", execution_mode="target",
        selector=DeviceSelector(), cases=[TestCase(case_id="case-1", name="target", steps=[])],
    )

    class RunReader:
        async def get_run(self, run_id: str) -> TestRun | None:
            return run if run_id == run.run_id else None

    class LogReader:
        async def query_by_trace(self, run_id: str) -> list[dict]:
            raise AssertionError("target detail must not read legacy logs")

    async def exercise() -> dict:
        await observations.ingest(ObservationInput.model_validate({
            "observation_id": "log-1", "kind": "log", "run_id": run.run_id, "case_id": "case-1",
            "device_role": "primary", "node_id": "node-1", "lease_id": "lease-1",
            "source": "agent_log", "target": {"sdk": "beacon", "interface": "diagnostics", "name": "log"},
            "payload": {"level": "info", "message": "started", "node_id": "node-1"}, "timestamp_ms": 1,
        }))
        reader = RunReader()
        return await console_api.run_detail_payload(
            run.run_id, reader, ReportGenerator(reader, observation_service=observations),
            LogReader(), observations,
        )

    payload = asyncio.run(exercise())
    assert payload["run"]["results"] == []
    assert payload["logs"] == [{"level": "info", "message": "started", "node_id": "node-1"}]
    assert payload["observation_cursor_enabled"] is True


def test_IR09_http_run_detail_preserves_observation_cursor_mode(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    observations = ObservationService()
    runtime = ServerRunRuntime(ResultCollector())
    monkeypatch.setattr(main_module, "run_runtime", runtime)
    monkeypatch.setattr(main_module, "observation_service", observations)
    monkeypatch.setattr(main_module, "report_generator", ReportGenerator(runtime, observation_service=observations))
    client = TestClient(app)

    for mode in ("target", "legacy"):
        run = TestRun(
            run_id=f"cursor-mode-{mode}", status="queued", execution_mode=mode,
            selector=DeviceSelector(), cases=[],
        )
        asyncio.run(runtime.create_run(run))

        response = client.get(f"/api/v1/console/test-runs/{run.run_id}", headers=AUTH)

        assert response.status_code == 200
        assert response.json()["observation_cursor_enabled"] is (mode == "target")


def test_IT_CONSOLE_06_lists_run_history_newest_first(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    runtime = ServerRunRuntime(ResultCollector())
    monkeypatch.setattr(main_module, "run_runtime", runtime)
    for run_id, created_at_ms, finished_at_ms in [
        ("run-old", 100, 150),
        ("run-new", 300, None),
        ("run-mid", 200, 260),
    ]:
        asyncio.run(
            runtime.create_run(
                TestRun(
                    run_id=run_id,
                    status="queued",
                    selector=DeviceSelector(),
                    cases=[TestCase(case_id=f"case-{run_id}", name=run_id, steps=[])],
                    created_at_ms=created_at_ms,
                )
            )
        )
        if finished_at_ms is not None:
            asyncio.run(runtime.start_run(run_id, []))
            asyncio.run(runtime.finish_run(run_id, "passed", finished_at_ms))
    client = TestClient(app)

    response = client.get("/api/v1/console/test-runs", headers=AUTH)

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [item["run_id"] for item in runs] == ["run-new", "run-mid", "run-old"]
    assert runs[0]["status"] == "queued"
    assert runs[0]["finished_at_ms"] is None
    assert runs[0]["duration_ms"] is None
    assert runs[1]["status"] == "passed"
    assert runs[1]["finished_at_ms"] == 260
    assert runs[1]["duration_ms"] == 60
    assert runs[2]["case_ids"] == ["case-run-old"]

    limited = client.get("/api/v1/console/test-runs?limit=2", headers=AUTH)
    assert [item["run_id"] for item in limited.json()["runs"]] == ["run-new", "run-mid"]

    assert client.get("/api/v1/console/test-runs").status_code == 401


def test_IT_CONSOLE_06B_rejects_out_of_range_history_limit(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    assert client.get("/api/v1/console/test-runs?limit=0", headers=AUTH).status_code == 422
    assert client.get("/api/v1/console/test-runs?limit=201", headers=AUTH).status_code == 422


def test_IT_CONSOLE_07_cancels_active_run_and_is_idempotent_for_terminal_run(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    runtime = ServerRunRuntime(ResultCollector())
    monkeypatch.setattr(main_module, "run_runtime", runtime)

    async def seed() -> None:
        for run_id in ("run-active", "run-finished"):
            await runtime.create_run(
                TestRun(
                    run_id=run_id,
                    status="queued",
                    selector=DeviceSelector(),
                    cases=[TestCase(case_id=f"case-{run_id}", name=run_id, steps=[])],
                    created_at_ms=100,
                )
            )
            await runtime.start_run(run_id, [])
        await runtime.finish_run("run-finished", "passed", 200)

    asyncio.run(seed())
    client = TestClient(app)

    active = client.post("/api/v1/test-runs/run-active/cancel", headers=AUTH)
    assert active.status_code == 200
    # 协作式取消只登记请求：进行中的 run 仍由执行器在边界收敛到 cancelled。
    assert active.json()["status"] == "running"
    assert asyncio.run(runtime.is_cancellation_requested("run-active"))

    repeated = client.post("/api/v1/test-runs/run-active/cancel", headers=AUTH)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "running"

    finished = client.post("/api/v1/test-runs/run-finished/cancel", headers=AUTH)
    assert finished.status_code == 200
    assert finished.json()["status"] == "passed"
    assert finished.json()["finished_at_ms"] == 200
    assert not asyncio.run(runtime.is_cancellation_requested("run-finished"))

    assert client.post("/api/v1/test-runs/run-missing/cancel", headers=AUTH).status_code == 404
    assert client.post("/api/v1/test-runs/run-active/cancel").status_code == 401




def test_IT_CONSOLE_OPENAPI_01_exposes_console_response_contracts(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]

    assert schemas["ConsoleSDKCapabilitiesResponse"]["properties"]["sdks"]["items"]["$ref"].endswith(
        "ConsoleSDKCapability"
    )
    assert schemas["ConsoleTestCasesResponse"]["properties"]["cases"]["items"]["$ref"].endswith(
        "ConsoleTestCaseSummary"
    )
    assert schemas["ConsoleTestCaseSummary"]["properties"]["steps"]["items"]["type"] == "object"
    assert schemas["ConsoleTestCaseSummary"]["properties"]["blocked_category"]["type"] == "string"
    assert schemas["ConsoleTestCaseSummary"]["properties"]["runnable_prerequisites"]["items"]["type"] == "string"
    assert schemas["ConsoleTestCaseSummary"]["properties"]["requires_runtime_isolation"]["type"] == "boolean"
    assert schemas["ConsoleRunDetailResponse"]["required"] == ["run", "report", "observation_cursor_enabled"]
    assert schemas["ConsoleRunDetailResponse"]["properties"]["observation_cursor_enabled"]["type"] == "boolean"
    assert schemas["ConsoleRunHistoryResponse"]["properties"]["runs"]["items"]["$ref"].endswith(
        "ConsoleRunHistoryEntry"
    )
    assert schemas["ConsoleRunHistoryEntry"]["required"] == ["run_id", "status", "created_at_ms"]

    cancel_operation = document["paths"]["/api/v1/test-runs/{run_id}/cancel"]["post"]
    assert cancel_operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("TestRun")


def test_IT_CONSOLE_04_rejects_python_native_case_id_with_compiled_steps(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    dispatcher = _NativeRunRecordingDispatcher()
    monkeypatch.setattr(main_module, "dispatcher", dispatcher)
    asyncio.run(
        main_module.registry.upsert(
            DeviceSession(
                Device(node_id="node-console-native", platform="mac"),
                websocket=object(),
                lease_id="lease-console-native",
            )
        )
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/test-runs",
            headers=AUTH,
            json={
                "selector": {"node_id": "node-console-native"},
                "case_ids": ["TC-PY-COMMON-SMOKE"],
                "cases": [
                    {
                        "case_id": "TC-PY-COMMON-SMOKE",
                        "name": "payload should be rejected",
                        "platform": "mac",
                        "steps": [
                            {
                                "step_id": "compiled-payload-should-be-rejected",
                                "target": {"sdk": "test_sdk", "class_name": "Wrong", "function": "wrong"},
                                "params": {"force_code": 500},
                            }
                        ],
                    }
                ],
            },
        )

        assert response.status_code == 422
        assert dispatcher.calls == []
    finally:
        asyncio.run(main_module.registry.remove("node-console-native"))


def test_IT_CONSOLE_05_multi_python_case_run_rejects_compiled_steps(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    dispatcher = _NativeRunRecordingDispatcher()
    monkeypatch.setattr(main_module, "dispatcher", dispatcher)
    asyncio.run(
        main_module.registry.upsert(
            DeviceSession(
                Device(node_id="node-console-native-b7", platform="mac"),
                websocket=object(),
                lease_id="lease-console-native-b7",
            )
        )
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/test-runs",
            headers=AUTH,
            json={
                "selector": {"node_id": "node-console-native-b7"},
                "case_ids": ["TC-PY-COMMON-SMOKE", "TC-PY-AGORA-BLOCKED-PERMISSION"],
                "cases": [
                    {
                        "case_id": "TC-PY-COMMON-SMOKE",
                        "name": "payload should be rejected",
                        "platform": "mac",
                        "steps": [{"step_id": "wrong-runnable-step", "target": {"function": "wrong"}, "params": {}}],
                    },
                    {
                        "case_id": "TC-PY-AGORA-BLOCKED-PERMISSION",
                        "name": "blocked payload should be rejected",
                        "platform": "mac",
                        "steps": [{"step_id": "wrong-blocked-step", "target": {"function": "wrong"}, "params": {}}],
                    },
                ],
            },
        )

        assert response.status_code == 422
        assert dispatcher.calls == []
    finally:
        asyncio.run(main_module.registry.remove("node-console-native-b7"))


class _NativeRunRecordingDispatcher:
    def __init__(self) -> None:
        self.calls = []

    async def send_invoke(self, node_id, calls, timeout_ms=None):
        self.calls.append((node_id, calls))
        return {
            "common": {"action": "invokeResponse", "op_id": "op-console-native"},
            "data": {"code": 0, "message": "ok", "result": "{}"},
        }
