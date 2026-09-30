"""Beacon 测试用例 compiler library。

本模块只处理 YAML policy、normalization、schema validation 和 protocol validation。
CLI 负责文件遍历、报告生成和退出码。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import warnings
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

warnings.filterwarnings("ignore", category=DeprecationWarning)
from jsonschema import Draft202012Validator, RefResolver

ACTIONS = {
    "registerRequest",
    "registerResponse",
    "invokeRequest",
    "invokeResponse",
    "callbackRequest",
    "callbackResponse",
    "callbackEventRequest",
    "callbackEventResponse",
    "reconnectRequest",
    "reconnectResponse",
    "unregisterRequest",
    "unregisterResponse",
    "logReportRequest",
    "logReportResponse",
    "artifactUploadReq",
    "artifactUploadResp",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
SCHEMA_DIR = REPO_ROOT / "test_cases/schemas"

sys.path.insert(0, str(REPO_ROOT / "python_sdk"))

from beacon_test.wire_json import canonical_json  # noqa: E402


def fail(message: str) -> None:
    raise ValueError(message)


def load_schemas() -> dict[str, dict[str, Any]]:
    schemas = {}
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        schemas[path.name] = schema
        if "$id" in schema:
            schemas[schema["$id"]] = schema
    return schemas


def validate_with_schema(instance: Any, schema_name: str, schemas: dict[str, dict[str, Any]], source: str) -> None:
    schema = schemas[schema_name]
    resolver = RefResolver.from_schema(schema, store=schemas)
    validator = Draft202012Validator(schema, resolver=resolver)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "$"
        fail(f"{source}: schema {schema_name} failed at {location}: {error.message}")


def reject_yaml_features(path: Path, text: str) -> None:
    """拒绝会降低 review 可读性或改变语义的 YAML 特性。"""
    if re.search(r"(^|[\s\[{,])&[A-Za-z0-9_-]+", text):
        fail(f"{path}: YAML anchors are not allowed")
    if re.search(r"(^|[\s\[{,])\*[A-Za-z0-9_-]+", text):
        fail(f"{path}: YAML aliases are not allowed")
    if re.search(r"^\s*<<\s*:", text, flags=re.MULTILINE):
        fail(f"{path}: YAML merge keys are not allowed")
    if re.search(r"(^|\s)![A-Za-z]", text):
        fail(f"{path}: custom YAML tags are not allowed")


def reject_implicit_dates(value: Any, path: str = "$") -> None:
    if isinstance(value, (date, datetime)):
        fail(f"{path}: implicit YAML dates are not allowed")
    if isinstance(value, dict):
        for key, item in value.items():
            reject_implicit_dates(item, f"{path}.{key}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            reject_implicit_dates(item, f"{path}[{index}]")


def validate_json_string(value: Any, source: str, field: str) -> None:
    if not isinstance(value, str):
        fail(f"{source}: {field} must be a JSON string on the wire")
    json.loads(value)


def validate_call_item(item: dict[str, Any], source: str) -> None:
    if not isinstance(item, dict):
        fail(f"{source}: call item must be an object")
    target = item.get("target")
    if not isinstance(target, dict):
        fail(f"{source}: call target must be an object")
    for field in ("sdk", "class_name", "function"):
        if not isinstance(target.get(field), str) or not target[field]:
            fail(f"{source}: target.{field} must be a non-empty string")
    for field in ("params", "extra"):
        if field in item:
            validate_json_string(item[field], source, field)


def validate_target(target: Any, source: str) -> None:
    if not isinstance(target, dict):
        fail(f"{source}: target must be an object")
    for field in ("sdk", "class_name", "function"):
        if not isinstance(target.get(field), str) or not target[field]:
            fail(f"{source}: target.{field} must be a non-empty string")


def validate_assertions(assertions: Any, source: str) -> None:
    if assertions is None:
        return
    if not isinstance(assertions, list):
        fail(f"{source}: assertions must be an array")
    for index, assertion in enumerate(assertions):
        if not isinstance(assertion, dict):
            fail(f"{source}: assertions[{index}] must be an object")
        assertion_type = assertion.get("type")
        if assertion_type not in {
            "event_exists",
            "metric_gt",
            "state_equals",
            "error_code",
            "failure_classification",
            "log_event_exists",
            "log_event_absent",
            "log_error_code_equals",
            "log_extra_matches",
        }:
            fail(
                f"{source}: assertions[{index}].type must be event_exists, metric_gt, state_equals, error_code, failure_classification, or log_*"
            )
        if assertion_type in {"event_exists", "metric_gt", "state_equals"}:
            validate_target(assertion.get("target"), f"{source}:assertions[{index}]")
        if assertion_type == "metric_gt" and not isinstance(assertion.get("value"), (int, float)):
            fail(f"{source}: assertions[{index}].value must be numeric for metric_gt")
        if assertion_type == "state_equals" and "value" not in assertion:
            fail(f"{source}: assertions[{index}].value is required for state_equals")
        if assertion_type == "error_code" and not isinstance(assertion.get("value"), int):
            fail(f"{source}: assertions[{index}].value must be an integer for error_code")
        if assertion_type == "failure_classification" and not isinstance(assertion.get("value"), dict):
            fail(f"{source}: assertions[{index}].value must be an object for failure_classification")
        if assertion_type in {"log_event_exists", "log_event_absent", "log_error_code_equals", "log_extra_matches"}:
            if not isinstance(assertion.get("module"), str) or not assertion["module"]:
                fail(f"{source}: assertions[{index}].module must be a non-empty string for log assertion")
            if not isinstance(assertion.get("event"), str) or not assertion["event"]:
                fail(f"{source}: assertions[{index}].event must be a non-empty string for log assertion")
            if "level" in assertion and not isinstance(assertion["level"], str):
                fail(f"{source}: assertions[{index}].level must be a string for log assertion")
            if "where" in assertion and not isinstance(assertion["where"], dict):
                fail(f"{source}: assertions[{index}].where must be an object for log assertion")
        if assertion_type == "log_error_code_equals" and not isinstance(assertion.get("value"), int):
            fail(f"{source}: assertions[{index}].value must be an integer for log_error_code_equals")
        if "payload_filters" in assertion and not isinstance(assertion["payload_filters"], dict):
            fail(f"{source}: assertions[{index}].payload_filters must be an object")
        if "timeout_ms" in assertion and (not isinstance(assertion["timeout_ms"], int) or assertion["timeout_ms"] < 1):
            fail(f"{source}: assertions[{index}].timeout_ms must be a positive integer")


def validate_packet(packet: dict[str, Any], source: str) -> None:
    """校验 common + data 协议包的最小合同。"""
    if not isinstance(packet, dict):
        fail(f"{source}: packet must be an object")
    common = packet.get("common")
    data = packet.get("data")
    if not isinstance(common, dict):
        fail(f"{source}: common must be an object")
    if not isinstance(data, dict):
        fail(f"{source}: data must be an object")
    action = common.get("action")
    if action not in ACTIONS:
        fail(f"{source}: invalid or missing common.action")
    if not isinstance(common.get("op_id"), str) or not common["op_id"]:
        fail(f"{source}: common.op_id must be a non-empty string")
    if not isinstance(common.get("timestamp_ms"), int) or common["timestamp_ms"] < 0:
        fail(f"{source}: common.timestamp_ms must be a non-negative integer")
    for field in ("params", "extra", "result"):
        if field in data:
            validate_json_string(data[field], source, f"data.{field}")
    if "list" in data:
        if not isinstance(data["list"], list) or not data["list"]:
            fail(f"{source}: data.list must be a non-empty array")
        for index, item in enumerate(data["list"]):
            if not isinstance(item, dict):
                fail(f"{source}: data.list[{index}] must be an object")
            if action == "invokeRequest":
                validate_call_item(item, f"{source}:data.list[{index}]")
            if action == "callbackRequest":
                event_target = item.get("event_target")
                if not isinstance(event_target, dict):
                    fail(f"{source}: callback descriptor event_target must be an object")
                for field in ("sdk", "class_name", "function"):
                    if not isinstance(event_target.get(field), str) or not event_target[field]:
                        fail(f"{source}: callback descriptor event_target.{field} must be a non-empty string")
                repeat = item.get("repeat", 1)
                if repeat == 0 or repeat < -1:
                    fail(f"{source}: callbackRequest repeat must be -1 or >= 1")
                elements = item.get("call_elements")
                if not isinstance(elements, list) or not elements:
                    fail(f"{source}: callback descriptor call_elements must be a non-empty array")
                for call_index, call in enumerate(elements):
                    validate_call_item(call, f"{source}:data.list[{index}].call_elements[{call_index}]")
    if "call_results" in data:
        if not isinstance(data["call_results"], list):
            fail(f"{source}: data.call_results must be an array")
        for index, item in enumerate(data["call_results"]):
            if not isinstance(item, dict):
                fail(f"{source}: data.call_results[{index}] must be an object")
            target = item.get("target")
            if not isinstance(target, dict):
                fail(f"{source}: data.call_results[{index}].target must be an object")
            for field in ("sdk", "class_name", "function"):
                if not isinstance(target.get(field), str) or not target[field]:
                    fail(f"{source}: data.call_results[{index}].target.{field} must be a non-empty string")
            if not isinstance(item.get("error"), int):
                fail(f"{source}: data.call_results[{index}].error must be an integer")
            if not isinstance(item.get("message"), str):
                fail(f"{source}: data.call_results[{index}].message must be a string")
            validate_json_string(item.get("return_value"), source, f"data.call_results[{index}].return_value")
    if action == "callbackRequest":
        repeat = data.get("repeat", 1)
        if repeat == 0 or repeat < -1:
            fail(f"{source}: callbackRequest repeat must be -1 or >= 1")
    if action in {"invokeRequest", "callbackRequest"} and "list" not in data:
        fail(f"{source}: {action} requires data.list")
    if action in {"invokeRequest", "callbackRequest"} and data.get("sync") is False:
        fail(f"{source}: {action} sync=false is not allowed in Phase 0")
    if action == "callbackEventRequest":
        event_target = data.get("event_target")
        if not isinstance(event_target, dict):
            fail(f"{source}: callbackEventRequest requires data.event_target")
        for field in ("sdk", "class_name", "function"):
            if not isinstance(event_target.get(field), str) or not event_target[field]:
                fail(f"{source}: callbackEventRequest event_target.{field} must be a non-empty string")
        if not isinstance(data.get("payload"), dict):
            fail(f"{source}: callbackEventRequest data.payload must be an object")


def normalize_packet(packet: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(packet))
    data = normalized["data"]
    for field in ("params", "extra", "result"):
        if field in data:
            data[field] = canonical_json(data[field])
    for item in data.get("list", []):
        for field in ("params", "extra", "result"):
            if field in item:
                item[field] = canonical_json(item[field])
        for call in item.get("call_elements", []):
            for field in ("params", "extra"):
                if field in call:
                    call[field] = canonical_json(call[field])
    for item in data.get("call_results", []):
        if "return_value" in item:
            item["return_value"] = canonical_json(item["return_value"])
    return normalized


def validate_test_case(case: dict[str, Any], source: str) -> None:
    required = {"case_id", "name", "platform", "steps"}
    optional = {
        "suite",
        "devices",
        "tags",
        "covered_capabilities",
        "scenario_family",
        "implementation_status",
        "blocked_category",
        "blocked_reason",
        "runnable_prerequisites",
        "owner_layer",
    }
    if set(case) - (required | optional):
        fail(f"{source}: unexpected test case fields")
    for field in required:
        if field not in case:
            fail(f"{source}: missing {field}")
    if case["platform"] not in {"common", "mac", "ios", "android"}:
        fail(f"{source}: invalid platform")
    if "covered_capabilities" in case:
        capabilities = case["covered_capabilities"]
        if not isinstance(capabilities, list) or not capabilities or any(
            not isinstance(item, str) or not item for item in capabilities
        ):
            fail(f"{source}: covered_capabilities must be a non-empty string list")
    for field in ("devices", "tags"):
        if field in case:
            values = case[field]
            if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item for item in values):
                fail(f"{source}: {field} must be a non-empty string list")
    if "scenario_family" in case and (not isinstance(case["scenario_family"], str) or not case["scenario_family"]):
        fail(f"{source}: scenario_family must be a non-empty string")
    if "suite" in case and (not isinstance(case["suite"], str) or not case["suite"]):
        fail(f"{source}: suite must be a non-empty string")
    if "implementation_status" in case and case["implementation_status"] not in {
        "runnable",
        "runnable_or_partial",
        "designed_but_blocked",
    }:
        fail(f"{source}: invalid implementation_status")
    for field in ("blocked_category", "blocked_reason", "owner_layer"):
        if field in case and (not isinstance(case[field], str) or not case[field]):
            fail(f"{source}: {field} must be a non-empty string")
    if "runnable_prerequisites" in case:
        prerequisites = case["runnable_prerequisites"]
        if not isinstance(prerequisites, list) or not prerequisites or any(
            not isinstance(item, str) or not item for item in prerequisites
        ):
            fail(f"{source}: runnable_prerequisites must be a non-empty string list")
    if case.get("implementation_status") == "designed_but_blocked":
        for field in ("blocked_category", "blocked_reason", "runnable_prerequisites", "owner_layer"):
            if field not in case:
                fail(f"{source}: designed_but_blocked case missing {field}")
    if not isinstance(case["steps"], list) or not case["steps"]:
        fail(f"{source}: steps must be a non-empty list")
    for step in case["steps"]:
        if set(step) - {"step_id", "packet", "assertions"}:
            fail(f"{source}: unexpected step fields")
        if "step_id" not in step or "packet" not in step:
            fail(f"{source}: each step must contain step_id and packet")
        validate_assertions(step.get("assertions"), f"{source}:{step['step_id']}")
        validate_packet(step["packet"], f"{source}:{step['step_id']}")


def compile_case(path: Path, schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    reject_yaml_features(path, text)
    loaded = yaml.safe_load(text)
    reject_implicit_dates(loaded)
    if not isinstance(loaded, dict):
        fail(f"{path}: top-level YAML must be an object")
    for step in loaded.get("steps", []):
        step["packet"] = normalize_packet(step["packet"])
    validate_test_case(loaded, str(path))
    validate_with_schema(loaded, "test_case.schema.json", schemas, str(path))
    return loaded


def validate_examples(schemas: dict[str, dict[str, Any]]) -> None:
    expected = {
        "register_req.json",
        "register_resp.json",
        "invoke_req.json",
        "invoke_resp.json",
        "callback_req.json",
        "callback_resp.json",
        "callback_event_req.json",
        "callback_event_resp.json",
        "reconnect_req.json",
        "reconnect_resp.json",
    }
    files = {p.name for p in (REPO_ROOT / "test_cases/protocol_examples").glob("*.json")}
    missing = expected - files
    if missing:
        fail(f"missing protocol examples: {sorted(missing)}")
    for path in (REPO_ROOT / "test_cases/protocol_examples").glob("*.json"):
        packet = json.loads(path.read_text(encoding="utf-8"))
        validate_packet(packet, str(path))
        validate_with_schema(packet, "packet.schema.json", schemas, str(path))


def validate_negative_cases(schemas: dict[str, dict[str, Any]]) -> None:
    """确认负例会失败，避免校验器只验证正向路径。"""
    base = {
        "common": {"action": "invokeRequest", "op_id": "op-neg", "timestamp_ms": 1},
        "data": {
            "node_id": "n1",
            "sync": True,
            "list": [{"target": {"sdk": "mock", "class_name": "Mock", "function": "m"}, "params": "{}"}],
        },
    }
    invalid_packets = [
        ({**base, "data": {"params": {}}}, "object params"),
        ({"common": {"op_id": "op-neg", "timestamp_ms": 1}, "data": {}}, "missing action"),
        (
            {
                "common": {"action": "callbackRequest", "op_id": "op-neg", "timestamp_ms": 1},
                "data": {
                    "node_id": "n1",
                    "sync": True,
                    "list": [
                        {
                            "event_target": {"sdk": "mock", "class_name": "MockDelegate", "function": "e"},
                            "repeat": 0,
                            "call_elements": [{"target": {"sdk": "mock", "class_name": "Mock", "function": "m"}, "params": "{}"}],
                        }
                    ],
                },
            },
            "repeat zero",
        ),
        (
            {
                "common": {"action": "invokeRequest", "op_id": "op-neg", "timestamp_ms": 1},
                "data": {"node_id": "n1", "sync": False, "list": [{"target": {"sdk": "mock", "class_name": "Mock", "function": "m"}, "params": "{}"}]},
            },
            "sync false",
        ),
        (
            {
                "common": {"action": "invokeRequest", "op_id": "op-neg", "timestamp_ms": 1},
                "data": {"node_id": "n1", "sync": True, "list": [{"method": "m", "params": "{}"}]},
            },
            "legacy method",
        ),
    ]
    for packet, name in invalid_packets:
        try:
            validate_with_schema(packet, "packet.schema.json", schemas, name)
            validate_packet(packet, name)
        except ValueError:
            continue
        fail(f"negative packet accepted: {name}")

    invalid_yaml = {
        "anchor": "x: &a 1\ny: *a\n",
        "merge": "base: &b {x: 1}\nitem:\n  <<: *b\n",
        "tag": "value: !custom test\n",
        "date": "value: 2026-05-24\n",
    }
    for name, text in invalid_yaml.items():
        path = Path(f"<negative:{name}>")
        try:
            reject_yaml_features(path, text)
            loaded = yaml.safe_load(text)
            reject_implicit_dates(loaded)
        except ValueError:
            continue
        fail(f"negative YAML accepted: {name}")


def write_outputs(compiled: list[dict[str, Any]]) -> None:
    output_root = REPO_ROOT / "reports/latest/compiled-test-cases"
    if output_root.exists():
        shutil.rmtree(output_root)
    for case in compiled:
        output = output_root / case["platform"] / f"{case['case_id']}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(case, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = REPO_ROOT / "reports/latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "protocol.json").write_text(
        json.dumps(
            {
                "status": "passed",
                "compiled_export_artifact": str(output_root.relative_to(REPO_ROOT)),
                "compiled": [case["case_id"] for case in compiled],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def compile_python_cases(path: Path, schemas: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:

    from scripts.support.native_case_catalog import load_cases

    source = path.relative_to(REPO_ROOT).as_posix()
    return [case for case in load_cases() if case["source_path"] == source]


def compile_all(case_roots: tuple[str, ...] = ("python",)) -> list[dict[str, Any]]:
    schemas = load_schemas()
    validate_examples(schemas)
    validate_negative_cases(schemas)
    cases = []
    from scripts.support.native_case_catalog import load_cases

    python_cases = load_cases()
    platform_roots = {"common", "mac", "ios", "android"}
    if "python" in case_roots:
        cases.extend(python_cases)
    for platform in sorted(platform_roots & set(case_roots)):
        cases.extend(case for case in python_cases if case["platform"] == platform)
    if not cases:
        fail("no test cases found")
    duplicate_ids = sorted(case_id for case_id, count in Counter(case["case_id"] for case in cases).items() if count > 1)
    if duplicate_ids:
        fail(f"duplicate test case ids: {duplicate_ids}")
    return cases
