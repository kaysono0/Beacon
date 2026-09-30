"""SDK Registry 只读查询模块。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.common.target_contract import target_key


class SDKRegistry:
    def __init__(self, artifacts: list[dict[str, Any]]) -> None:
        self._artifacts: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            sdk_name = artifact.get("sdk", "")
            if sdk_name:
                self._artifacts[sdk_name] = artifact
        self._call_targets = {
            target_key(item.get("target", {}))
            for artifact in artifacts
            for item in artifact.get("interfaces", [])
            if item.get("kind") == "call"
        }
        self._state_targets = {
            target_key(item.get("target", {}))
            for artifact in artifacts
            for item in artifact.get("interfaces", [])
            if item.get("kind") == "state"
        }
        # provider_mappings 只出现在 contract_matrix 行上（interfaces 不带该字段）。
        self._provider_mappings = {
            target_key(item.get("target", {})): list(item.get("provider_mappings", []))
            for artifact in artifacts
            for item in artifact.get("contract_matrix", [])
            if item.get("kind") in {"call", "state"}
        }
        self._resource_types = {
            target_key(item.get("target", {})): item.get("object_lifecycle", {}).get("handle_kind")
            for artifact in artifacts
            for item in artifact.get("contract_matrix", [])
            if item.get("kind") in {"call", "state"}
        }
        self._invoke_schemas = {
            target_key(item.get("target", {})): item.get("params_schema", {})
            for artifact in artifacts
            for item in artifact.get("interfaces", [])
            if item.get("kind") in {"call", "state"}
        }
        self._observation_items = {
            (item.get("kind"), target_key(item.get("target", {}))): item
            for artifact in artifacts
            for item in artifact.get("interfaces", [])
            if item.get("kind") in {"callback", "state", "metric", "log", "artifact"}
        }

    @property
    def artifacts(self) -> dict[str, dict[str, Any]]:
        return self._artifacts

    @classmethod
    def load_from(cls, directory: Path) -> "SDKRegistry":
        artifacts = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                artifacts.append(json.loads(path.read_text(encoding="utf-8")))
        return cls(artifacts)

    def supports_call(self, target: dict[str, Any]) -> bool:
        return target_key(target) in self._call_targets

    def supports_state(self, target: dict[str, Any]) -> bool:
        return target_key(target) in self._state_targets

    def supports_invoke(self, target: dict[str, Any]) -> bool:
        key = target_key(target)
        return key in self._call_targets or key in self._state_targets

    def resource_type_for_target(self, target: dict[str, Any]) -> str | None:
        """只从 Registry 生命周期声明取得可发行的资源类型。"""

        value = self._resource_types.get(target_key(target))
        return value if isinstance(value, str) and value not in {"", "none"} else None

    def observation_match_error(
        self,
        kind: str,
        target: dict[str, Any],
        match: dict[str, Any],
    ) -> str | None:
        """按 Registry 声明验证 Runner Observation 的精确匹配字段。"""

        registry_kind = "callback" if kind == "event" else kind
        item = self._observation_items.get((registry_kind, target_key(target)))
        if item is None:
            return "unsupported observation target"
        allowed = set(item.get("filterable_fields", []))
        unknown = sorted(set(match) - allowed)
        if unknown:
            return f"unsupported observation match fields: {', '.join(unknown)}"
        return None

    def unsupported_platform_error(self, target: dict[str, Any]) -> dict[str, Any] | None:
        """target 已声明、但没有任何平台标注 supported 时返回 488。

        `provider_mappings` 是 Adapter Source 声明的平台支持关系；没有它，
        「声明了但本平台不支持」在运行期就没有落点，只能靠设备端返回 unknown invocation。
        """
        key = target_key(target)
        if key not in self._invoke_schemas:
            return None
        mappings = self._provider_mappings.get(key, [])
        if any(mapping.get("status") == "supported" for mapping in mappings):
            return None
        return {
            "code": 488,
            "message": "unsupported sdk target",
            "failure_classification": {
                "category": "unsupported",
                "source": "sdk_registry",
                "reason": "unsupported_target",
            },
        }

    def validate_invoke(self, target: dict[str, Any], params: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
        schema = self._invoke_schemas.get(target_key(target))
        if schema is None:
            return {
                "code": 488,
                "message": "unsupported sdk target",
                "failure_classification": {
                    "category": "unsupported",
                    "source": "sdk_registry",
                    "reason": "unsupported_target",
                },
            }
        unsupported = self.unsupported_platform_error(target)
        if unsupported is not None:
            return unsupported
        instance = dict(params)
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        if "_extra" in properties:
            instance["_extra"] = dict(extra or {})
        errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda error: list(error.absolute_path))
        if not errors:
            return None
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        return {
            "code": 422,
            "message": f"invalid sdk parameters at {path}: {error.validator}",
            "failure_classification": {
                "category": "validation",
                "source": "sdk_registry",
                "reason": "invalid_parameters",
                "path": path,
                "validator": error.validator,
            },
        }
