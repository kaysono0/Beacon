"""IR-07 Server 管理的单 case Runner 子进程边界。

本模块负责启动、握手时限、取消/超时终止和进程回收；候选结果来自
RunnerCaseRegistry，run 终态与 Agent reset 仍由上层 orchestrator 决定。
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Literal

from app.api.api_contracts import RunnerCaseResultRequest
from app.runs.runner_case_registry import RunnerCaseContext, RunnerCaseRegistry, RunnerCredential
from app.reporting.server_log_events import record_server_log


RUNNER_TOKEN_ENV = "BEACON_RUNNER_TOKEN"
RUNNER_BASE_URL_ENV = "BEACON_RUNNER_BASE_URL"
RUNNER_RUN_ID_ENV = "BEACON_RUNNER_RUN_ID"
RUNNER_CASE_ID_ENV = "BEACON_RUNNER_CASE_ID"
STARTUP_TIMEOUT_MS = 5_000
TERMINATE_GRACE_MS = 2_000
MONITOR_INTERVAL_MS = 20
ProcessReason = Literal["completed", "runner_startup_failure", "process_crash", "case_timeout", "cancelled"]


@dataclass(frozen=True)
class RunnerProcessOutcome:
    """进程结束事实；不能单独决定 case/run 终态。"""

    reason: ProcessReason
    exit_code: int
    candidate: RunnerCaseResultRequest | None


class RunnerProcessManager:
    """独占一个 Runner 子进程从创建到 reap 的生命周期。"""

    def __init__(
        self,
        registry: RunnerCaseRegistry,
        *,
        repo_root: Path,
        base_url: str,
        log_collector: object | None = None,
        case_environment: dict[str, str] | None = None,
        startup_timeout_ms: int = STARTUP_TIMEOUT_MS,
        terminate_grace_ms: int = TERMINATE_GRACE_MS,
    ) -> None:
        self._registry = registry
        self._repo_root = repo_root
        self._base_url = base_url
        self._log_collector = log_collector
        self._case_environment = dict(case_environment or {})
        self._startup_timeout_ms = startup_timeout_ms
        self._terminate_grace_ms = terminate_grace_ms

    async def run(
        self,
        context: RunnerCaseContext,
        credential: RunnerCredential,
        *,
        cancel_requested: Callable[[], Awaitable[bool]],
    ) -> RunnerProcessOutcome:
        """只传最小进程环境，循环监督握手、候选结果和进程终止。"""

        process = await self._spawn(context, credential)
        try:
            await self._log(
                context, "runner.process.started", "Runner process started", pid=process.pid,
                case_environment_keys=sorted(self._case_environment),
            )
            reason, candidate = await self._monitor(process, context, cancel_requested)
        finally:
            await self._reap(process)
        exit_code = process.returncode
        assert exit_code is not None
        outcome = RunnerProcessOutcome(reason=reason, exit_code=exit_code, candidate=candidate)
        await self._log(
            context, "runner.process.finished", "Runner process reaped",
            pid=process.pid, reason=reason, exit_code=exit_code,
        )
        return outcome

    async def _spawn(self, context: RunnerCaseContext, credential: RunnerCredential) -> asyncio.subprocess.Process:
        """构造不含 token 的命令行，并限制子进程继承的环境。"""

        source = context.metadata
        args = [
            sys.executable, "-m", "beacon_test.runner",
            "--repo-root", str(self._repo_root),
            "--source-path", source.source_path,
            "--function-name", source.function_name,
        ]
        for role in source.device_roles:
            args.extend(("--role", role))
        env = {
            **self._case_environment,
            RUNNER_TOKEN_ENV: credential.token,
            RUNNER_BASE_URL_ENV: self._base_url,
            RUNNER_RUN_ID_ENV: context.run_id,
            RUNNER_CASE_ID_ENV: context.case_id,
            "PYTHONPATH": os.pathsep.join((str(self._repo_root / "python_sdk"), str(self._repo_root))),
            "PATH": os.environ.get("PATH", ""),
        }
        return await asyncio.create_subprocess_exec(
            *args, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

    async def _monitor(
        self,
        process: asyncio.subprocess.Process,
        context: RunnerCaseContext,
        cancel_requested: Callable[[], Awaitable[bool]],
    ) -> tuple[ProcessReason, RunnerCaseResultRequest | None]:
        """轮询 process 与 Server 协议快照；不在这里写 run 终态。"""

        loop = asyncio.get_running_loop()
        started_deadline = loop.time() + self._startup_timeout_ms / 1000
        case_deadline = loop.time() + context.case_timeout_ms / 1000
        while True:
            if await cancel_requested():
                return "cancelled", None
            started, candidate = await self._registry.protocol_snapshot(context)
            if started is not None and started.pid != process.pid:
                return "runner_startup_failure", None
            if process.returncode is not None:
                if started is None:
                    return "runner_startup_failure", None
                if candidate is None or process.returncode != (0 if candidate.status == "passed" else 1):
                    return "process_crash", candidate
                return "completed", candidate
            now = loop.time()
            if started is None and now >= started_deadline:
                return "runner_startup_failure", None
            if now >= case_deadline:
                return "case_timeout", candidate
            await asyncio.sleep(MONITOR_INTERVAL_MS / 1000)

    async def _reap(self, process: asyncio.subprocess.Process) -> None:
        """退出或升级 kill 后必须 wait，避免遗留孤儿进程。"""

        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            self._signal_group(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), self._terminate_grace_ms / 1000)
            except asyncio.TimeoutError:
                self._signal_group(process.pid, signal.SIGKILL)
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        else:
            await process.wait()
        self._signal_group(process.pid, signal.SIGKILL)

    @staticmethod
    def _signal_group(pid: int, sig: signal.Signals) -> None:
        """独立 session 的进程组包含 case 派生进程；直接父进程退出也要清理。"""

        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass

    async def _log(self, context: RunnerCaseContext, event: str, message: str, **extra: object) -> None:
        await record_server_log(
            self._log_collector, event=event, message=message,
            run_id=context.run_id, case_id=context.case_id, extra=extra,
        )
