"""IR-07 Runner 子进程启动、握手和回收合同。"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.api.api_contracts import RunnerCaseResultRequest, RunnerStartedRequest
from app.runs.python_native_models import NativeTestCase
from app.runs.runner_case_registry import RunnerCaseContext, RunnerCaseMetadata, RunnerCaseRegistry, RunnerRoleBinding
from app.runs.runner_process import (
    RUNNER_BASE_URL_ENV,
    RUNNER_CASE_ID_ENV,
    RUNNER_RUN_ID_ENV,
    RUNNER_TOKEN_ENV,
    RunnerProcessManager,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _protect_fake_process_group(monkeypatch):
    real_killpg = os.killpg

    def killpg(pgid, sig):
        if pgid != 1234:
            real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", killpg)


def _unused_case(_):
    raise AssertionError("case source must not execute in Server")


async def _case_scope(*, case_timeout_ms=1_000):
    case = NativeTestCase(
        case_id="TC-RUNNER-PROCESS", name="runner process", platform="macos", devices=["primary"],
        suite="target-runtime", scenario_family="runner", implementation_status="runnable",
        covered_capabilities=[], tags=[], source_path="test_cases/target_runtime/runner_case.py",
        function_name="test_runner_case", function=_unused_case,
    )
    registry = RunnerCaseRegistry([case], now_ms=lambda: 1_000, token_factory=lambda: b"t" * 32)
    context = RunnerCaseContext(
        run_id="run-process", metadata=RunnerCaseMetadata.from_native_case(case),
        bindings={"primary": RunnerRoleBinding("primary", "node-1", "lease-1")},
        case_timeout_ms=case_timeout_ms, token_expires_at_ms=2_000,
    )
    credential = await registry.register(context)
    return registry, context, credential


class FakeProcess:
    def __init__(self, *, exit_code=None, ignores_terminate=False):
        self.pid = 1234
        self.returncode = exit_code
        self.ignores_terminate = ignores_terminate
        self.terminated = False
        self.killed = False
        self.done = asyncio.Event()
        if exit_code is not None:
            self.done.set()

    async def wait(self):
        await self.done.wait()
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.ignores_terminate:
            self.returncode = -15
            self.done.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.done.set()


@pytest.mark.anyio
async def test_IR07_process_launch_keeps_token_out_of_argv_and_accepts_candidate(monkeypatch):
    registry, context, credential = await _case_scope()
    process = FakeProcess(exit_code=0)
    await registry.record_started(context, RunnerStartedRequest(runner_protocol_version=1, python_version="3.11", pid=process.pid))
    await registry.record_result(context, RunnerCaseResultRequest(status="passed"))
    launch = {}

    async def fake_spawn(*args, **kwargs):
        launch["args"] = args
        launch["env"] = kwargs["env"]
        launch["start_new_session"] = kwargs["start_new_session"]
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(registry, repo_root=ROOT, base_url="http://server")
    outcome = await manager.run(context, credential, cancel_requested=lambda: _false())

    assert outcome.reason == "completed" and outcome.exit_code == 0
    assert outcome.candidate is not None and outcome.candidate.status == "passed"
    assert credential.token not in launch["args"]
    assert launch["env"][RUNNER_TOKEN_ENV] == credential.token
    assert launch["env"][RUNNER_BASE_URL_ENV] == "http://server"
    assert launch["env"][RUNNER_RUN_ID_ENV] == context.run_id
    assert launch["env"][RUNNER_CASE_ID_ENV] == context.case_id
    assert context.run_id not in launch["args"] and context.case_id not in launch["args"]
    assert "--source-path" in launch["args"] and "--role" in launch["args"]
    assert "HOME" not in launch["env"]
    assert launch["start_new_session"] is True


async def _false():
    return False


@pytest.mark.anyio
async def test_IR07_runner_preserves_public_case_configuration_without_parent_secrets(monkeypatch):
    from app.sdk.sdk_extensions import SDK_RUNNER_ENVIRONMENT_NAMES

    registry, context, credential = await _case_scope()
    configuration = {"VOLCENGINE_RTC_ROOM_ID": "configured-room", "VOLCENGINE_RTC_USER_ID": "configured-user"}
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "server-secret")
    monkeypatch.setenv("VOLCENGINE_RTC_APPKEY", "sdk-secret")
    assert set(configuration) == set(SDK_RUNNER_ENVIRONMENT_NAMES)
    launch = {}

    async def fake_spawn(*args, **kwargs):
        launch.update(kwargs)
        return FakeProcess(exit_code=0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(
        registry, repo_root=ROOT, base_url="http://server", case_environment=configuration,
    )
    configuration["VOLCENGINE_RTC_USER_ID"] = "mutated-user"
    await manager._spawn(context, credential)
    probe = (
        "import json,runpy; "
        "case=runpy.run_path('test_cases/python/volcengine/volcengine_l1_cases.py'); "
        "print(json.dumps([case['PRIMARY_ROOM'],case['PRIMARY_USER']]))"
    )
    actual = subprocess.check_output([sys.executable, "-c", probe], cwd=ROOT, env=launch["env"], text=True)
    assert json.loads(actual) == ["configured-room", "configured-user"]
    assert "BEACON_AUTH_TOKEN" not in launch["env"]
    assert "VOLCENGINE_RTC_APPKEY" not in launch["env"]
    assert "VOLCENGINE_RTC_TOKEN" not in launch["env"]


@pytest.mark.anyio
async def test_IR07_startup_timeout_terminates_and_reaps_child(monkeypatch):
    registry, context, credential = await _case_scope()
    process = FakeProcess()
    async def fake_spawn(*_, **__):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(
        registry, repo_root=ROOT, base_url="http://server", startup_timeout_ms=1,
    )
    outcome = await asyncio.wait_for(manager.run(context, credential, cancel_requested=_false), 1)
    assert outcome.reason == "runner_startup_failure"
    assert process.terminated and process.returncode == -15


@pytest.mark.anyio
async def test_IR07_cancel_escalates_to_kill_when_terminate_does_not_reap(monkeypatch):
    registry, context, credential = await _case_scope()
    process = FakeProcess(ignores_terminate=True)
    async def fake_spawn(*_, **__):
        return process
    async def cancelled():
        return True
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(
        registry, repo_root=ROOT, base_url="http://server", terminate_grace_ms=1,
    )
    outcome = await asyncio.wait_for(manager.run(context, credential, cancel_requested=cancelled), 1)
    assert outcome.reason == "cancelled"
    assert process.terminated and process.killed and process.returncode == -9


@pytest.mark.anyio
async def test_IR07_nonzero_exit_without_result_is_process_crash(monkeypatch):
    registry, context, credential = await _case_scope()
    process = FakeProcess(exit_code=2)
    await registry.record_started(context, RunnerStartedRequest(runner_protocol_version=1, python_version="3.11", pid=process.pid))
    async def fake_spawn(*_, **__):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(registry, repo_root=ROOT, base_url="http://server")
    outcome = await manager.run(context, credential, cancel_requested=_false)
    assert outcome.reason == "process_crash" and outcome.candidate is None


@pytest.mark.anyio
async def test_IR07_failed_candidate_requires_expected_process_exit(monkeypatch):
    registry, context, credential = await _case_scope()
    process = FakeProcess(exit_code=-9)
    await registry.record_started(context, RunnerStartedRequest(runner_protocol_version=1, python_version="3.11", pid=process.pid))
    await registry.record_result(context, RunnerCaseResultRequest(status="failed", failure_classification="python_assertion"))
    async def fake_spawn(*_, **__):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(registry, repo_root=ROOT, base_url="http://server")
    outcome = await manager.run(context, credential, cancel_requested=_false)
    assert outcome.reason == "process_crash"


@pytest.mark.anyio
async def test_IR07_case_timeout_reaps_started_child(monkeypatch):
    registry, context, credential = await _case_scope(case_timeout_ms=1)
    process = FakeProcess()
    await registry.record_started(context, RunnerStartedRequest(runner_protocol_version=1, python_version="3.11", pid=process.pid))
    async def fake_spawn(*_, **__):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(registry, repo_root=ROOT, base_url="http://server")
    outcome = await asyncio.wait_for(manager.run(context, credential, cancel_requested=_false), 1)
    assert outcome.reason == "case_timeout"
    assert process.terminated and process.returncode == -15


@pytest.mark.anyio
async def test_IR07_handshake_pid_mismatch_is_startup_failure(monkeypatch):
    registry, context, credential = await _case_scope()
    process = FakeProcess()
    await registry.record_started(context, RunnerStartedRequest(runner_protocol_version=1, python_version="3.11", pid=9999))
    async def fake_spawn(*_, **__):
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    manager = RunnerProcessManager(registry, repo_root=ROOT, base_url="http://server")
    outcome = await manager.run(context, credential, cancel_requested=_false)
    assert outcome.reason == "runner_startup_failure"
    assert process.terminated and process.returncode == -15


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["passed", "timed_out", "cancelled"])
async def test_IR07_real_runner_subprocess_handshakes_and_exits(tmp_path, mode):
    times_out = mode == "timed_out"
    registry, context, credential = await _case_scope(case_timeout_ms=800 if times_out else 5_000)
    source = tmp_path / context.metadata.source_path
    waiting_marker = tmp_path / "playback-wait-entered"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import time\nfrom pathlib import Path\ndef test_runner_case(session):\n"
        "    assert session.run_id == 'run-process'\n"
        + (f"    Path({str(waiting_marker)!r}).write_text('waiting')\n" if mode == "cancelled" else "")
        + ("    time.sleep(5)\n" if mode != "passed" else ""), encoding="utf-8",
    )
    (tmp_path / "python_sdk").symlink_to(ROOT / "python_sdk", target_is_directory=True)
    loop = asyncio.get_running_loop()
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            assert self.headers["Authorization"] == f"Bearer {credential.token}"
            if self.path.endswith("/started"):
                request = RunnerStartedRequest.model_validate(body)
                operation = registry.record_started(context, request)
                seen.append(("started", request.pid))
            else:
                request = RunnerCaseResultRequest.model_validate(body)
                operation = registry.record_result(context, request)
                seen.append(("result", request.status))
            asyncio.run_coroutine_threadsafe(operation, loop).result(timeout=3)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"accepted"}')

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cancellation_started_at = None

    async def cancel_during_playback_wait():
        nonlocal cancellation_started_at
        if mode != "cancelled" or not waiting_marker.exists():
            return False
        cancellation_started_at = loop.time()
        return True

    try:
        manager = RunnerProcessManager(
            registry, repo_root=tmp_path, base_url=f"http://127.0.0.1:{server.server_port}",
        )
        outcome = await asyncio.wait_for(
            manager.run(context, credential, cancel_requested=cancel_during_playback_wait),
            10,
        )
        if mode == "cancelled":
            assert cancellation_started_at is not None
            assert loop.time() - cancellation_started_at < 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert outcome.reason == {"timed_out": "case_timeout", "passed": "completed", "cancelled": "cancelled"}[mode]
    assert [entry[0] for entry in seen] == (["started", "result"] if mode == "passed" else ["started"])
    assert isinstance(seen[0][1], int) and seen[0][1] > 0
    if mode == "passed":
        assert outcome.exit_code == 0 and seen[1][1] == "passed"
    with pytest.raises(ProcessLookupError):
        os.kill(seen[0][1], 0)


@pytest.mark.anyio
async def test_IR07_reap_kills_runner_descendant_that_ignores_terminate(tmp_path):
    registry, _, _ = await _case_scope()
    pid_file = tmp_path / "child.pid"
    ready_file = tmp_path / "child.ready"
    child_code = (
        "import pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(30)"
    )
    parent_code = (
        "import pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c',sys.argv[3],sys.argv[2]]); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", parent_code, str(pid_file), str(ready_file), child_code,
        start_new_session=True, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    manager = RunnerProcessManager(registry, repo_root=ROOT, base_url="http://server", terminate_grace_ms=100)
    try:
        for _ in range(200):
            if pid_file.exists() and ready_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists() and ready_file.exists()
        child_pid = int(pid_file.read_text())
        await manager._reap(process)
        for _ in range(100):
            status = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)], capture_output=True, text=True)
            if status.returncode != 0 or status.stdout.strip().startswith("Z"):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("Runner descendant is still running after reap")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.returncode is None:
            process.kill()
            await process.wait()
