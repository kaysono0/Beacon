"""Python-native case 发现器。

扫描 `test_cases/python/**/*.py`，加载带 `__beacon_test__` 元数据的函数，
并把它们转换成 `NativeTestCase`。这里负责 source discovery 和 metadata 校验，
不执行 case 函数。
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from importlib import util
from pathlib import Path
from types import ModuleType

from app.runs.python_native_models import NativeTestCase


_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PythonNativeRegistry:
    """已发现 Python-native case 的只读目录。"""

    cases: list[NativeTestCase]

    @classmethod
    def discover(cls, source_root: Path, *, repo_root: Path | None = None) -> "PythonNativeRegistry":
        """从源码目录发现 case，并按 case_id 稳定排序。"""
        repo_root = repo_root or _REPO_ROOT
        cases: list[NativeTestCase] = []
        seen: dict[str, NativeTestCase] = {}

        for path in sorted(source_root.glob("**/*.py")):
            if path.name.startswith("__"):
                continue
            module = _load_module(path)
            for _, candidate in inspect.getmembers(module, inspect.isfunction):
                definition = getattr(candidate, "__beacon_test__", None)
                if definition is None:
                    continue
                source_path = path.relative_to(repo_root).as_posix()
                case = NativeTestCase(
                    case_id=definition.case_id,
                    name=definition.name,
                    platform=definition.platform,
                    devices=list(definition.devices),
                    suite=definition.suite or "",
                    scenario_family=definition.scenario_family or "",
                    implementation_status=definition.implementation_status or "",
                    covered_capabilities=list(definition.covered_capabilities),
                    tags=list(definition.tags),
                    source_path=source_path,
                    function_name=candidate.__name__,
                    function=candidate,
                    blocked_category=getattr(definition, "blocked_category", None) or "",
                    blocked_reason=getattr(definition, "blocked_reason", None) or "",
                    runnable_prerequisites=list(getattr(definition, "runnable_prerequisites", [])),
                    owner_layer=getattr(definition, "owner_layer", None) or "",
                    token_bindings=list(getattr(definition, "token_bindings", [])),
                    sdk_names=list(getattr(definition, "sdk_names", [])),
                )
                if case.implementation_status == "designed_but_blocked":
                    _validate_blocked_metadata(case)
                if case.case_id in seen:
                    raise ValueError(f"duplicate case_id: {case.case_id}")
                seen[case.case_id] = case
                cases.append(case)

        return cls(cases=sorted(cases, key=lambda case: case.case_id))


def _load_module(path: Path) -> ModuleType:
    """按文件路径隔离加载 case 模块，避免模块名冲突。"""
    module_name = f"_beacon_native_{abs(hash(path.resolve()))}_{path.stem}"
    spec = util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load python test source: {path}")
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _validate_blocked_metadata(case: NativeTestCase) -> None:
    """阻止 designed_but_blocked case 缺少责任边界信息。"""
    missing = []
    if not case.blocked_category:
        missing.append("blocked_category")
    if not case.blocked_reason:
        missing.append("blocked_reason")
    if not case.runnable_prerequisites:
        missing.append("runnable_prerequisites")
    if not case.owner_layer:
        missing.append("owner_layer")
    if missing:
        fields = ", ".join(missing)
        raise ValueError(f"designed_but_blocked case {case.case_id} missing {fields}")
