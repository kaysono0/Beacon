import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
_UNSUPPORTED_CONCURRENCY_MODULES = frozenset({"asyncio", "concurrent", "multiprocessing", "threading"})


def _implicit_concurrency_offenders(paths: list[Path], *, root: Path) -> list[str]:
    findings: list[tuple[str, int, str]] = []
    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                findings.append(
                    (
                        relative_path,
                        node.lineno,
                        "async test source is unsupported; use sequential ctx.step() calls",
                    )
                )
                continue
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".", maxsplit=1)[0] in _UNSUPPORTED_CONCURRENCY_MODULES:
                    findings.append((relative_path, node.lineno, f"unsupported concurrency import: {module}"))
    return [f"{path}:{line}: {message}" for path, line, message in sorted(findings)]


def test_PY_SOURCE_STYLE_01_no_unannotated_dynamic_sdk_in_python_native_cases():
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "test_cases" / "python").rglob("*.py")):
        if path.name == "__init__.py":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if ".sdk(" in line and "beacon-allow-dynamic-sdk" not in line:
                relative_path = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert offenders == []


def test_PY_SOURCE_STYLE_CONCURRENCY_CONTRACT_02_python_native_cases_do_not_use_implicit_concurrency():
    offenders = _implicit_concurrency_offenders(
        sorted((REPO_ROOT / "test_cases" / "python").rglob("*.py")),
        root=REPO_ROOT,
    )

    assert offenders == []


def test_PY_SOURCE_STYLE_CONCURRENCY_CONTRACT_02A_guard_reports_unsupported_patterns(tmp_path: Path):
    source_path = tmp_path / "implicit_concurrency_case.py"
    source_path.write_text(
        """\
import asyncio
import threading as threads
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool

async def case(ctx):
    pass
""",
        encoding="utf-8",
    )

    assert _implicit_concurrency_offenders([source_path], root=tmp_path) == [
        "implicit_concurrency_case.py:1: unsupported concurrency import: asyncio",
        "implicit_concurrency_case.py:2: unsupported concurrency import: threading",
        "implicit_concurrency_case.py:3: unsupported concurrency import: concurrent.futures",
        "implicit_concurrency_case.py:4: unsupported concurrency import: multiprocessing",
        "implicit_concurrency_case.py:6: async test source is unsupported; use sequential ctx.step() calls",
    ]
