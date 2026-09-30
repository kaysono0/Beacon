"""IR-07 独立 Python case 进程入口。

只执行 Server 指定的源码函数并上报候选结果；run 终态、进程回收和 reset
均由 Server Supervisor 负责。token 只通过进程环境传入，不写入命令行。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from .target_session import BeaconSession, UnsupportedCallError


RUNNER_TOKEN_ENV = "BEACON_RUNNER_TOKEN"
RUNNER_BASE_URL_ENV = "BEACON_RUNNER_BASE_URL"
RUNNER_RUN_ID_ENV = "BEACON_RUNNER_RUN_ID"
RUNNER_CASE_ID_ENV = "BEACON_RUNNER_CASE_ID"
RUNNER_PROTOCOL_VERSION = 1
RUNNER_CONTROL_TIMEOUT_S = 5.0
MAX_DIAGNOSTIC_CHARS = 16_384
USER_PATH = re.compile(r"/(?:Users|home)/[^/\s\"']+/[^\s\"']+")


def _exception_line(exc: Exception, source: Path) -> int:
    """只从受信任 case 源文件的 traceback frame 提取行号。"""

    frames = traceback.extract_tb(exc.__traceback__)
    return next((frame.lineno for frame in reversed(frames) if Path(frame.filename).resolve() == source), 1)


def _diagnostic(exc: Exception, token: str) -> str:
    """发送前遮蔽 Runner credential 与本机路径；Server 再做统一文本脱敏。"""

    rendered = "".join(traceback.format_exception(exc)).replace(token, "<redacted>")
    return USER_PATH.sub("<redacted>", rendered)[:MAX_DIAGNOSTIC_CHARS]


def _load_case(repo_root: Path, source_path: str, function_name: str) -> Any:
    """仅加载 Server catalog 指定且位于仓库内的 Python 源码函数。"""

    source = (repo_root / source_path).resolve()
    if not source.is_relative_to(repo_root.resolve()) or source.suffix != ".py":
        raise ImportError("Runner source is outside trusted repository")
    spec = importlib.util.spec_from_file_location(f"_beacon_runner_{os.getpid()}", source)
    if spec is None or spec.loader is None:
        raise ImportError("Runner source cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    candidate = getattr(module, function_name)
    if not callable(candidate):
        raise ImportError("Runner source function is not callable")
    return candidate


def _execute_python_case(
    session: BeaconSession, repo_root: Path, source_path: str, function_name: str, token: str,
) -> tuple[str, str | None, str, int, str | None]:
    """执行一次作者函数，并将异常分类、源码行与诊断一起返回。"""

    source = (repo_root / source_path).resolve()
    try:
        case = _load_case(repo_root, source_path, function_name)
    except Exception as exc:
        return "failed", "import_error", type(exc).__name__, _exception_line(exc, source), _diagnostic(exc, token)
    try:
        case(session)
    except UnsupportedCallError as exc:
        return "unsupported", None, "UnsupportedCallError", _exception_line(exc, source), None
    except AssertionError as exc:
        return "failed", "python_assertion", type(exc).__name__, _exception_line(exc, source), _diagnostic(exc, token)
    except Exception as exc:
        return "failed", "python_exception", type(exc).__name__, _exception_line(exc, source), _diagnostic(exc, token)
    return "passed", None, "", max(1, getattr(getattr(case, "__code__", None), "co_firstlineno", 1)), None


def run_case(
    *,
    base_url: str,
    repo_root: Path,
    source_path: str,
    function_name: str,
    run_id: str,
    case_id: str,
    roles: frozenset[str],
    token: str,
) -> int:
    """向 Server 握手、执行一次 case、上报候选结果并返回进程退出码。"""

    with BeaconSession(
        base_url=base_url,
        run_id=run_id,
        case_id=case_id,
        run_token=token,
        device_roles=roles,
        source_path=source_path,
        source_function=function_name,
    ) as session:
        session._request(
            "POST", "/started", timeout_s=RUNNER_CONTROL_TIMEOUT_S,
            json={
                "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
                "python_version": sys.version.split()[0],
                "pid": os.getpid(),
            },
        )
        status, classification, message, line, diagnostic = _execute_python_case(
            session, repo_root, source_path, function_name, token,
        )
        session._request(
            "POST", "/result", timeout_s=RUNNER_CONTROL_TIMEOUT_S,
            json={
                "status": status, "failure_classification": classification, "message": message,
                "source": {"path": source_path, "function": function_name, "line": line},
                "diagnostic_traceback": diagnostic,
                "timestamp_ms": int(time.time() * 1000),
            },
        )
        return 0 if status == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    """解析 Supervisor 提供的非秘密参数；缺 token 时拒绝执行。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--role", action="append", required=True)
    args = parser.parse_args(argv)
    token = os.environ.get(RUNNER_TOKEN_ENV)
    base_url = os.environ.get(RUNNER_BASE_URL_ENV)
    run_id = os.environ.get(RUNNER_RUN_ID_ENV)
    case_id = os.environ.get(RUNNER_CASE_ID_ENV)
    if not token or not base_url or not run_id or not case_id:
        parser.error("Runner environment is incomplete")
    return run_case(
        base_url=base_url,
        repo_root=args.repo_root,
        source_path=args.source_path,
        function_name=args.function_name,
        run_id=run_id,
        case_id=case_id,
        roles=frozenset(args.role),
        token=token,
    )


if __name__ == "__main__":
    raise SystemExit(main())
