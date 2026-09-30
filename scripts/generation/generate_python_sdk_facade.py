#!/usr/bin/env python3
"""Generate typed Python authoring facades from SDK Registry artifacts."""

from __future__ import annotations

import argparse
import json
import keyword
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python_sdk"))

from beacon_test.registry_paths import registry_dir  # noqa: E402


DEFAULT_OUTPUT_DIR = REPO_ROOT / "python_sdk" / "beacon_test" / "generated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    # 默认值调用期求值，保证 BEACON_SDK_REGISTRY_DIR 在 import 后仍能生效。
    registry_root = args.registry_dir if args.registry_dir is not None else registry_dir()
    outputs = generate_target_outputs(registry_root)
    output_dir = args.output_dir
    if args.check:
        stale = []
        for relative_path, content in outputs.items():
            path = output_dir / relative_path
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(_display_path(path))
        orphans = [_display_path(path) for path in _orphan_paths(output_dir, outputs)]
        if stale:
            print("generated facade files are out of date:", file=sys.stderr)
            for item in stale:
                print(f"  {item}", file=sys.stderr)
        if orphans:
            print("orphan generated files not produced by the registry:", file=sys.stderr)
            for item in orphans:
                print(f"  {item}", file=sys.stderr)
        return 1 if stale or orphans else 0

    output_dir.mkdir(parents=True, exist_ok=True)
    for relative_path, content in outputs.items():
        path = output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return 0


def generate_target_outputs(registry_root: Path) -> dict[str, str]:
    artifacts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(registry_root.glob("*.json"))]
    outputs = {"__init__.py": _target_init_module(artifacts)}
    for artifact in artifacts:
        outputs[f"{artifact['sdk']}.py"] = _target_sdk_module(artifact)
    return outputs


def _target_init_module(artifacts: list[dict[str, Any]]) -> str:
    lines = ['"""Generated synchronous Runner SDK facades."""', "", "from __future__ import annotations", "", "from typing import TYPE_CHECKING, Callable", "", "if TYPE_CHECKING:", "    from beacon_test.target_session import BeaconSession", ""]
    entries = []
    names = []
    for artifact in artifacts:
        sdk = artifact["sdk"]
        class_name = _sdk_class_name(sdk)
        lines.append(f"from .{sdk} import {class_name}")
        entries.append(f"    {sdk!r}: {class_name},")
        names.append(class_name)
    lines.extend(["", f"__all__ = {names!r}", "", "FACADES: dict[str, Callable[[BeaconSession, str], object]] = {"])
    lines.extend(entries)
    lines.extend(["}", ""])
    return "\n".join(lines)


def _target_sdk_module(artifact: dict[str, Any]) -> str:
    sdk = artifact["sdk"]
    sdk_class = _sdk_class_name(sdk)
    interfaces = _group_by_interface(artifact.get("interfaces", []))
    lines = [
        '"""Generated from sdk_registry/compiled; do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any, Literal",
        "from beacon_test.target_session import BeaconSession, CallResult, ObservationHandle, ResourceRef",
        "",
        f"class {sdk_class}:",
        "    def __init__(self, session: BeaconSession, role: str) -> None:",
        "        self._session = session",
        "        self._role = role",
        "",
    ]
    for interface in sorted(interfaces):
        interface_class = _interface_class_name(sdk, interface)
        lines.extend([
            "    @property",
            f"    def {_safe_identifier(interface)}(self) -> {interface_class}:",
            f"        return {interface_class}(self._session, self._role)",
            "",
        ])
    for interface, items in sorted(interfaces.items()):
        interface_class = _interface_class_name(sdk, interface)
        lines.extend([
            "",
            f"class {interface_class}:",
            "    def __init__(self, session: BeaconSession, role: str) -> None:",
            "        self._session = session",
            "        self._role = role",
            "",
        ])
        used_names: set[str] = set()
        for item in sorted(items, key=lambda value: (value.get("kind", ""), value.get("target", {}).get("function", ""))):
            function = item["target"].get("function") or item["target"].get("name")
            name = _target_identifier(_snake_case(function))
            if name in used_names:
                raise ValueError(f"duplicate Python facade name: {sdk}.{interface}.{name}")
            used_names.add(name)
            if item["kind"] in {"call", "state"}:
                lines.extend(_target_call_method(name, item))
                if item["kind"] == "state":
                    observation_name = f"{name}_observations"
                    if observation_name in used_names:
                        raise ValueError(f"duplicate Python facade name: {sdk}.{interface}.{observation_name}")
                    used_names.add(observation_name)
                    lines.extend([
                        "    @property",
                        f"    def {observation_name}(self) -> ObservationHandle:",
                        f"        return ObservationHandle(self._session, self._role, 'state', {item['target']!r})",
                        "",
                    ])
            elif item["kind"] in {"callback", "metric", "artifact", "log"}:
                lines.extend([
                    "    @property",
                    f"    def {name}(self) -> ObservationHandle:",
                    f"        return ObservationHandle(self._session, self._role, {item['kind']!r}, {item['target']!r})",
                    "",
                ])
    return "\n".join(lines)


def _target_call_method(name: str, item: dict[str, Any]) -> list[str]:
    schema = item.get("params_schema") or {}
    properties = schema.get("properties", {})
    required = list(schema.get("required", []))
    ordered = [field for field in required if field in properties]
    ordered.extend(sorted((field for field in properties if field not in ordered), key=_param_order_key))
    params = []
    body = ["        params: dict[str, Any] = {}"]
    used = {"self", "params", "check", "timeout_s", "resource", "create_resource"}
    for field in ordered:
        python_field = _target_identifier(field)
        if field in used or python_field in used:
            raise ValueError(f"Native parameter conflicts with facade control: {item['target']}.{field}")
        used.add(python_field)
        annotation = _schema_type(properties[field])
        if field in required:
            params.append(f"{python_field}: {annotation}")
            body.append(f"        params[{field!r}] = {python_field}")
        elif "default" in properties[field]:
            params.append(f"{python_field}: {annotation} = {properties[field]['default']!r}")
            body.append(f"        params[{field!r}] = {python_field}")
        else:
            params.append(f"{python_field}: {annotation} | None = None")
            body.extend([f"        if {python_field} is not None:", f"            params[{field!r}] = {python_field}"])
    params.extend(["check: bool = True", "timeout_s: float = 5.0", "resource: ResourceRef | None = None", "create_resource: bool = False"])
    return [
        f"    def {name}(self, *, {', '.join(params)}) -> CallResult[Any]:",
        *body,
        f"        return self._session.call(self._role, {item['target']!r}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)",
        "",
    ]


def _target_identifier(value: str) -> str:
    identifier = re.sub(r"\W", "_", value)
    if not identifier or identifier[0].isdigit():
        identifier = f"_{identifier}"
    if keyword.iskeyword(identifier):
        identifier += "_"
    return identifier


def _orphan_paths(output_dir: Path, expected: dict[str, str]) -> list[Path]:
    if not output_dir.is_dir():
        return []
    orphans = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output_dir)
        if relative.as_posix() in expected:
            continue
        if any(part == "__pycache__" or part.startswith(".") for part in relative.parts):
            continue
        if path.suffix == ".pyc":
            continue
        orphans.append(path)
    return orphans


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _param_order_key(name: str) -> tuple[int, str]:
    preferred = {
        "token": 10,
        "uid": 20,
        "view_id": 30,
        "view": 31,
        "auto_subscribe_audio": 40,
        "auto_subscribe_video": 41,
        "publish_camera": 42,
        "publish_microphone": 43,
        "_extra": 1000,
    }
    return preferred.get(name, 500), name


def _group_by_interface(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        interface = item.get("target", {}).get("interface")
        if interface:
            grouped.setdefault(interface, []).append(item)
    return grouped


def _schema_type(schema: dict[str, Any]) -> str:
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return f"Literal[{', '.join(repr(value) for value in enum)}]"
    kind = schema.get("type")
    if isinstance(kind, list):
        types = [_schema_type({**schema, "type": value}) for value in kind]
        return " | ".join(dict.fromkeys(types))
    if kind == "null":
        return "None"
    if kind == "string":
        return "str"
    if kind == "integer":
        return "int"
    if kind == "number":
        return "float"
    if kind == "boolean":
        return "bool"
    if kind == "array":
        return f"list[{_schema_type(schema.get('items', {}))}]"
    if kind == "object":
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return f"dict[str, {_schema_type(additional)}]"
        return "dict[str, Any]"
    return "Any"


def _sdk_class_name(sdk: str) -> str:
    return "".join(part.capitalize() for part in sdk.split("_")) + "Facade"


def _interface_class_name(sdk: str, interface: str) -> str:
    return "".join(part.capitalize() for part in f"{sdk}_{interface}".split("_")) + "Interface"


def _snake_case(value: str) -> str:
    value = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub("([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def _safe_identifier(value: str) -> str:
    value = re.sub(r"\W", "_", value)
    if not value or value[0].isdigit():
        value = f"_{value}"
    if value in {"class", "def", "from", "global", "import", "pass", "return"}:
        value = f"{value}_"
    return value


if __name__ == "__main__":
    raise SystemExit(main())
