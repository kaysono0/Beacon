"""SDK Registry compiler library。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml
from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SCHEMA_DIR = REPO_ROOT / "sdk_registry" / "schemas" / "adapter_source"
sys.path.insert(0, str(REPO_ROOT / "server"))
sys.path.insert(0, str(REPO_ROOT / "python_sdk"))

from app.common.target_contract import TargetContractError, normalize_target, target_key  # noqa: E402
from beacon_test.registry_paths import default_registry_dir  # noqa: E402


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def load_yaml(path: Path, schema_name: str | None = None) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        fail(f"{path}: top-level YAML must be an object")
    if schema_name is not None:
        validate_source_document(loaded, path, schema_name)
    return loaded


def validate_source_document(document: dict[str, Any], path: Path, schema_name: str) -> None:
    schema_path = SOURCE_SCHEMA_DIR / f"{schema_name}.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "$"
        fail(f"{path}: source schema {schema_name} failed at {location}: {error.message}")


def canonical_target(target: dict[str, Any], source: str) -> dict[str, Any]:
    target_fields = {
        field: target[field]
        for field in ("sdk", "interface", "class_name", "function", "overload")
        if field in target
    }
    try:
        return normalize_target(target_fields, "registry")
    except TargetContractError as exc:
        fail(f"{source}: {exc}")


def canonical_adapter_target(target: dict[str, Any], source: str, sdk: str) -> dict[str, Any]:
    normalized = canonical_target(target, source)
    if normalized["sdk"] != sdk:
        fail(f"{source}: target.sdk must match adapter sdk {sdk}")
    return normalized


def compile_registry_source(source_dir: Path) -> dict[str, Any]:
    capabilities_source = load_yaml(source_dir / "capabilities.yaml", "capabilities")
    mappings_source = load_yaml(source_dir / "mappings.yaml", "mappings")
    evidence_source = load_yaml(source_dir / "evidence.yaml", "evidence")
    sdk = capabilities_source["sdk"]
    if mappings_source["sdk"] != sdk or evidence_source["sdk"] != sdk:
        fail(f"{source_dir}: sdk must match across registry source files")
    providers_declaration = load_providers_declaration(source_dir, sdk)

    capabilities = capabilities_source["capabilities"]
    capability_ids = set()
    normalized_capabilities = []
    for item in capabilities:
        capability_id = item["id"]
        name = item["name"]
        if capability_id in capability_ids:
            fail(f"{source_dir}: duplicate capability {capability_id}")
        capability_ids.add(capability_id)
        normalized_capabilities.append({"id": capability_id, "name": name})

    interfaces = []
    for mapping_index, mapping in enumerate(mappings_source["mappings"]):
        capability = mapping["capability"]
        if capability not in capability_ids:
            fail(f"{source_dir}: unknown capability {capability}")
        for call in mapping.get("calls", []):
            item = {
                "kind": "call",
                "capability": capability,
                "target": canonical_adapter_target(call, f"{source_dir}:mappings[{mapping_index}].calls", sdk),
            }
            if "params_schema" in call:
                item["params_schema"] = call["params_schema"]
            if "result_schema" in call:
                item["result_schema"] = call["result_schema"]
            interfaces.append(item)
        for group, kind in (
            ("callbacks", "callback"),
            ("metrics", "metric"),
            ("artifacts", "artifact"),
            ("logs", "log"),
        ):
            for observed in mapping.get(group, []):
                item = {
                    "kind": kind,
                    "capability": capability,
                    "target": canonical_adapter_target(observed, f"{source_dir}:mappings[{mapping_index}].{group}", sdk),
                }
                for field in ("payload_schema", "filterable_fields", "evidence_summary_fields"):
                    if field in observed:
                        item[field] = observed[field]
                interfaces.append(item)
        for state in mapping.get("states", []):
            item = {
                "kind": "state",
                "capability": capability,
                "target": canonical_adapter_target(state, f"{source_dir}:mappings[{mapping_index}].states", sdk),
            }
            if "payload_schema" in state:
                item["payload_schema"] = state["payload_schema"]
            interfaces.append(item)
    if not interfaces:
        fail(f"{source_dir}: mappings must define at least one interface")
    if providers_declaration is not None:
        validate_declaration_targets(providers_declaration, interfaces, source_dir)

    evidence = []
    for evidence_index, item in enumerate(evidence_source["evidence"]):
        capability = item["capability"]
        if capability not in capability_ids:
            fail(f"{source_dir}: unknown capability {capability}")
        expects = []
        for expect in item["expects"]:
            expects.append(
                {
                    "type": "event",
                    "event_target": canonical_adapter_target(
                        expect["event_target"], f"{source_dir}:evidence[{evidence_index}].expects", sdk
                    ),
                }
            )
        evidence.append({"capability": capability, "expects": expects})

    artifact = {
        "sdk": sdk,
        "version": 1,
        "capabilities": sorted(normalized_capabilities, key=lambda item: item["id"]),
        "interfaces": sorted(interfaces, key=lambda item: (item["kind"], item["capability"], json.dumps(item["target"], sort_keys=True))),
        "evidence": sorted(evidence, key=lambda item: item["capability"]),
        "contract_matrix": _contract_matrix(sdk, interfaces, evidence, providers_declaration),
    }
    validate_registry_artifact(artifact, str(source_dir))
    return artifact


def _contract_matrix(
    sdk: str,
    interfaces: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    providers_declaration: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    evidence_by_target = {
        target_key(expect["event_target"]): item["capability"]
        for item in evidence
        for expect in item.get("expects", [])
        if expect.get("type") == "event"
    }
    rows = []
    for item in interfaces:
        target = item["target"]
        row = {
            "capability": item["capability"],
            "kind": item["kind"],
            "target": target,
            "authoring": {
                "dynamic": f'ctx.device(role).sdk("{sdk}").{target.get("interface", "")}.{target["function"]}',
                "typed_facade": _typed_facade_path(sdk, target),
            },
            "server_validation": {
                "target_contract": "sdk_interface_class_function",
                "params_schema": item.get("params_schema", {}),
                "result_schema": item.get("result_schema", {}),
                "payload_schema": item.get("payload_schema", {}),
            },
            "provider_mappings": _provider_mappings(target, providers_declaration),
            "evidence_projection": _evidence_projection(sdk, item, evidence_by_target),
            "object_lifecycle": _object_lifecycle(item),
            "callback_lifecycle": _callback_lifecycle(item),
            "scheduling": _scheduling(item),
        }
        rows.append(row)
    return sorted(rows, key=lambda row: (row["kind"], row["capability"], json.dumps(row["target"], sort_keys=True)))


def _typed_facade_path(sdk: str, target: dict[str, Any]) -> str:
    interface = target.get("interface")
    function = _snake_case(target["function"])
    if interface:
        return f"ctx.device(role).{sdk}.{interface}.{function}"
    return f"ctx.device(role).{sdk}.{function}"


def validate_declaration_targets(declaration: dict[str, Any], interfaces: list[dict[str, Any]], source_dir: Path) -> None:
    """校验声明里的 interface / function 名确实存在于本 SDK 的编译产物。

    不做这层校验时，拼错的声明不会报错，只会静默把 target 降级成 `mac/unsupported`
    或落到后面更宽的规则，因此这里让拼写错误在编译期失败。
    """
    functions_by_interface: dict[str, set[str]] = {}
    for item in interfaces:
        target = item["target"]
        functions_by_interface.setdefault(target.get("interface", ""), set()).add(target["function"])
    path = source_dir / "providers.yaml"
    for index, rule in enumerate(declaration["rules"]):
        unknown_interfaces = sorted(interface for interface in rule["interfaces"] if interface not in functions_by_interface)
        if unknown_interfaces:
            fail(f"{path}: rules[{index}].interfaces declares unknown interface(s) {unknown_interfaces}")
        functions = rule["functions"]
        if functions is None:
            continue
        declared = set().union(*(functions_by_interface[interface] for interface in rule["interfaces"]))
        unknown_functions = sorted(function for function in functions if function not in declared)
        if unknown_functions:
            fail(f"{path}: rules[{index}].functions declares unknown function(s) {unknown_functions}")


def _provider_mappings(target: dict[str, Any], declaration: dict[str, Any] | None) -> list[dict[str, Any]]:
    """按 Adapter Source 的 providers.yaml 声明解析 provider 支持关系。

    编译器不认识任何具体 SDK：未命中任何声明规则（含未提供声明）的 target
    统一落到 SDK 中立的兜底行 `mac/unsupported`。
    """
    rules = declaration.get("rules", []) if declaration else []
    interface = target.get("interface", "")
    function = target.get("function")
    for rule in rules:
        if interface not in rule["interfaces"]:
            continue
        functions = rule.get("functions")
        if functions is not None and function not in functions:
            continue
        return [dict(mapping) for mapping in rule["mappings"]]
    return [{"platform": "mac", "status": "unsupported", "provider": None, "bridge_boundary": "agents/mac"}]


def load_providers_declaration(source_dir: Path, sdk: str) -> dict[str, Any] | None:
    """读取并校验 `sdk_adapters/<sdk>/providers.yaml`；文件缺失时返回 None。"""
    path = source_dir / "providers.yaml"
    if not path.exists():
        return None
    source = load_yaml(path, "providers")
    if source["sdk"] != sdk:
        fail(f"{path}: sdk must match capabilities.yaml")
    rules = source.get("rules")
    if not isinstance(rules, list) or not rules:
        fail(f"{path}: rules must be a non-empty array (省略整个文件即表示未声明)")
    normalized_rules = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            fail(f"{path}: rules[{index}] must be an object")
        interfaces = rule.get("interfaces")
        if not isinstance(interfaces, list) or not interfaces or not all(isinstance(item, str) and item for item in interfaces):
            fail(f"{path}: rules[{index}].interfaces must be a non-empty string array")
        functions = rule.get("functions")
        if functions is not None and (
            not isinstance(functions, list) or not functions or not all(isinstance(item, str) and item for item in functions)
        ):
            fail(f"{path}: rules[{index}].functions must be a non-empty string array when declared")
        mappings = rule.get("mappings")
        if not isinstance(mappings, list) or not mappings:
            fail(f"{path}: rules[{index}].mappings must be a non-empty array")
        normalized_mappings = []
        for mapping_index, mapping in enumerate(mappings):
            if not isinstance(mapping, dict) or set(mapping) != {"platform", "status", "provider", "bridge_boundary"}:
                fail(
                    f"{path}: rules[{index}].mappings[{mapping_index}] must declare exactly "
                    "platform, status, provider, bridge_boundary"
                )
            if not isinstance(mapping["platform"], str) or not mapping["platform"]:
                fail(f"{path}: rules[{index}].mappings[{mapping_index}].platform must be a non-empty string")
            if mapping["status"] not in {"supported", "unsupported", "partial", "designed_but_blocked"}:
                fail(f"{path}: rules[{index}].mappings[{mapping_index}].status is not a supported status")
            if mapping["provider"] is not None and not isinstance(mapping["provider"], str):
                fail(f"{path}: rules[{index}].mappings[{mapping_index}].provider must be a string or null")
            if not isinstance(mapping["bridge_boundary"], str) or not mapping["bridge_boundary"]:
                fail(f"{path}: rules[{index}].mappings[{mapping_index}].bridge_boundary must be a non-empty string")
            status = mapping["status"]
            provider = mapping["provider"]
            # supported 必须有真实 provider，否则该行会声称支持平台却不受 handler 注册一致性约束。
            if status == "supported" and not (isinstance(provider, str) and provider):
                fail(f"{path}: rules[{index}].mappings[{mapping_index}] status supported requires a non-empty provider")
            if status in {"unsupported", "designed_but_blocked"} and provider is not None:
                fail(f"{path}: rules[{index}].mappings[{mapping_index}] status {status} requires provider null")
            normalized_mappings.append(
                {
                    "platform": mapping["platform"],
                    "status": status,
                    "provider": provider,
                    "bridge_boundary": mapping["bridge_boundary"],
                }
            )
        normalized_rules.append(
            {"interfaces": set(interfaces), "functions": set(functions) if functions is not None else None, "mappings": normalized_mappings}
        )
    return {"rules": normalized_rules}


def _evidence_projection(sdk: str, item: dict[str, Any], evidence_by_target: dict[str, str]) -> dict[str, Any]:
    target = item["target"]
    if item["kind"] == "callback":
        key = target_key(target)
        capability = evidence_by_target.get(key)
        if capability is None:
            fail(f"{sdk}: callback target has no event evidence binding: {key}")
        return {
            "evidence_type": "event",
            "report_projection": "step.evidence",
            "summary_fields": item.get("evidence_summary_fields", []),
            "evidence_capability": capability,
        }
    if item["kind"] == "state":
        return {
            "evidence_type": "state",
            "report_projection": "step.evidence",
            "summary_fields": [],
            "evidence_capability": None,
        }
    if item["kind"] in {"metric", "artifact", "log"}:
        return {
            "evidence_type": item["kind"],
            "report_projection": "step.evidence",
            "summary_fields": item.get("evidence_summary_fields", []),
            "evidence_capability": item["capability"],
        }
    return {
        "evidence_type": "sdk_call",
        "report_projection": "step.facts",
        "summary_fields": [],
        "evidence_capability": None,
    }


def _object_lifecycle(item: dict[str, Any]) -> dict[str, Any]:
    if item["kind"] in {"call", "state"}:
        return {"handle_kind": "sdk_instance", "owner": "provider_bridge", "author_visible": False}
    return {"handle_kind": "none", "owner": "not_applicable", "author_visible": False}


def _callback_lifecycle(item: dict[str, Any]) -> dict[str, Any]:
    if item["kind"] != "callback":
        return {"handle_kind": "none", "subscribe": False, "observe": False, "unsubscribe": False}
    return {
        "handle_kind": "callback_subscription",
        "subscribe": True,
        "observe": True,
        "unsubscribe": True,
        "filterable_fields": item.get("filterable_fields", []),
    }


def _scheduling(item: dict[str, Any]) -> dict[str, Any]:
    if item["kind"] == "callback":
        return {"mode": "async_callback", "thread": "provider_default"}
    if item["kind"] in {"metric", "artifact", "log"}:
        return {"mode": "custom", "thread": "evidence_store"}
    return {"mode": "sync", "thread": "provider_default"}


def _snake_case(value: str) -> str:
    value = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub("([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.lower()


def validate_registry_artifact(artifact: dict[str, Any], source: str) -> None:
    schema_path = REPO_ROOT / "sdk_registry/schemas/sdk_registry.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(artifact), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "$"
        fail(f"{source}: schema sdk_registry.schema.json failed at {location}: {error.message}")


def compile_all_registries(adapter_root: Path = REPO_ROOT / "sdk_adapters") -> list[dict[str, Any]]:
    artifacts = []
    for source_dir in sorted(path for path in adapter_root.iterdir() if path.is_dir() and (path / "capabilities.yaml").exists()):
        artifacts.append(compile_registry_source(source_dir))
    if not artifacts:
        fail("no SDK registry sources found")
    return artifacts


def write_registry_outputs(artifacts: list[dict[str, Any]]) -> None:
    # 写入目标不受 BEACON_SDK_REGISTRY_DIR 影响：该变量只是读取覆盖，
    # 否则 make test-protocol 会把产物写到别处，提交版本悄悄失去刷新。
    output_dir = default_registry_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        (output_dir / f"{artifact['sdk']}.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
