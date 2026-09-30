"""真实 Runner 进程的 facade 错误到 Server/report 终态合同。"""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app import main
from app.devices.device_models import Device, DeviceSelector, DeviceSession
from app.devices.device_runtime import DeviceRegistry
from app.observations.observation_service import ObservationService
from app.reporting.evidence_runtime import ResultCollector, now_ms
from app.reporting.reporting import ReportGenerator
from app.runs.python_native_models import NativeTestCase
from app.runs.python_native_runtime import RuntimeParamResolver
from app.runs.run_call_service import RunCallService
from app.runs.run_runtime import ServerRunRuntime
from app.runs.runner_case_registry import RunnerCaseRegistry
from app.runs.runner_process import RunnerProcessManager
from app.runs.runner_supervisor import RunnerSupervisor
from app.sdk.sdk_registry import SDKRegistry
from beacon_test.registry_paths import registry_dir


ROOT = Path(__file__).resolve().parents[2]


class NativeResultDispatcher:
    def __init__(self, code, fail_final):
        self.code = code
        self.fail_final = fail_final
        self.phases = []
        self.native_calls = []

    async def send_protocol_invoke(self, node_id, calls, op_id, timeout_ms, *, expected_lease_id=None):
        assert (node_id, expected_lease_id) == ("node-1", "lease-1")
        phase = calls[0]["extra"].get("runtime_phase")
        if phase:
            self.phases.append(phase)
            code = 500 if self.fail_final and phase == "final" else 0
        else:
            self.native_calls.extend(calls)
            code = self.code
        return {"common": {"op_id": op_id}, "data": {"code": code, "message": "native result", "result": "{}"}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("native_code", "check", "expected_assertion", "fail_final", "case_status", "run_status"),
    [(488, True, None, False, "unsupported", "passed"),
     (500, True, None, False, "failed", "failed"),
     (488, False, 488, False, "passed", "passed"),
     (488, False, 0, False, "failed", "failed"),
     (488, True, None, True, "failed", "failed")],
)
async def test_generated_facade_native_result_survives_runner_supervisor_and_report(
    monkeypatch, tmp_path, native_code, check, expected_assertion, fail_final, case_status, run_status,
):
    (tmp_path / "python_sdk").symlink_to(ROOT / "python_sdk", target_is_directory=True)
    source = tmp_path / "case.py"
    source.write_text(
        "def test_case(session):\n"
        f"    result = session.device('primary').mock_echo.echo.echo(message='hello', check={check})\n"
        + (f"    assert result.code == {expected_assertion}\n" if expected_assertion is not None else ""),
        encoding="utf-8",
    )
    case = NativeTestCase(
        case_id="TC-UNSUPPORTED-CONTRACT", name="unsupported contract", platform="macos", devices=["primary"],
        suite="contract", scenario_family="native-result", implementation_status="runnable",
        covered_capabilities=[], tags=[], source_path="case.py", function_name="test_case", function=lambda _: None,
    )
    devices = DeviceRegistry()
    await devices.upsert(DeviceSession(Device(node_id="node-1", platform="macos"), object(), "lease-1"))
    observations = ObservationService()
    runtime = ServerRunRuntime(ResultCollector(), observation_service=observations)
    registry = RunnerCaseRegistry([case], now_ms=now_ms)
    dispatcher = NativeResultDispatcher(native_code, fail_final)
    calls = RunCallService(dispatcher, SDKRegistry.load_from(registry_dir()), RuntimeParamResolver(), runtime, observations)
    monkeypatch.setattr(main, "runner_case_registry", registry)
    monkeypatch.setattr(main, "run_call_service", calls)
    monkeypatch.setattr(main, "observation_service", observations)
    app = FastAPI()
    app.include_router(main.runner_router)
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                response = asyncio.run_coroutine_threadsafe(
                    client.post(self.path, headers=dict(self.headers), content=body), loop,
                ).result(timeout=10)
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response.content)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            process = RunnerProcessManager(registry, repo_root=tmp_path, base_url=f"http://127.0.0.1:{server.server_port}")
            supervisor = RunnerSupervisor(
                cases=[case], device_registry=devices, run_runtime=runtime, case_registry=registry,
                call_service=calls, process_manager=process, dispatcher=dispatcher, observation_service=observations,
                case_timeout_ms=10_000,
            )
            run = await supervisor.create_run([case.case_id], DeviceSelector())
            await asyncio.wait_for(asyncio.gather(*supervisor._tasks), timeout=15)
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join()
    finished = await runtime.get_run(run.run_id)
    assert finished.status == run_status
    assert finished.case_results[0].status == case_status
    assert finished.case_results[0].cleanup_failed == fail_final
    assert dispatcher.phases == ["pre", "final"]
    assert len(dispatcher.native_calls) == 1
    assert dispatcher.native_calls[0]["params"] == {"message": "hello"}
    generator = ReportGenerator(runtime, observation_service=observations)
    report = await generator.generate(run.run_id, "json")
    assert report.summary["status"] == run_status
    assert report.case_results[0]["status"] == case_status
    assert report.case_results[0]["operations"][0]["payload"]["code"] == native_code
    junit = await generator.generate_junit(run.run_id)
    assert ('<failure ' in junit) == (case_status == "failed")
    if fail_final:
        assert report.case_results[0]["failure_classification"] == "final_reset_failure"
    elif native_code == 488 and check:
        assert report.case_results[0]["failure_classification"] is None
    elif native_code == 500:
        assert report.case_results[0]["failure_classification"] == "python_exception"
    elif case_status == "failed":
        assert report.case_results[0]["failure_classification"] == "python_assertion"
