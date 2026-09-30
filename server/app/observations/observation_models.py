"""不可变 Observation 合同与查询模型。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator, model_validator


ObservationKind = Literal["event", "state", "metric", "log", "artifact", "connection", "operation"]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ObservationTarget(BaseModel):
    """Observation 使用的 canonical Native target。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    sdk: NonEmptyText
    interface: NonEmptyText
    class_name: str | None = Field(default=None, alias="class")
    function: str | None = None
    name: str | None = None
    overload: str | None = None

    @field_validator("sdk", "interface", "class_name", "function", "name", "overload")
    @classmethod
    def _strip_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("target fields must be non-empty strings")
        return normalized

    @model_validator(mode="after")
    def _require_capability_name(self) -> ObservationTarget:
        if (self.function is None) == (self.name is None):
            raise ValueError("target requires exactly one of function or name")
        return self


class ObservationInput(BaseModel):
    """Server 分配 cursor 前经过可信 ingress 构造的 Observation。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: NonEmptyText
    kind: ObservationKind
    run_id: NonEmptyText
    case_id: NonEmptyText
    step_id: NonEmptyText | None = None
    operation_id: NonEmptyText | None = None
    device_role: NonEmptyText
    node_id: NonEmptyText
    lease_id: NonEmptyText
    source: NonEmptyText
    target: ObservationTarget
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    callback_execution: dict[str, JsonValue] | None = None
    timestamp_ms: int = Field(ge=0)


class ObservationRecord(ObservationInput):
    """带 Server run-local cursor 的不可变原始事实。"""

    cursor: int = Field(ge=1)
    ingested_at_ms: int = Field(ge=0)


class ObservationQuery(BaseModel):
    """Observation 原始事实的精确匹配查询。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: NonEmptyText
    case_id: NonEmptyText | None = None
    device_role: NonEmptyText | None = None
    node_id: NonEmptyText | None = None
    lease_id: NonEmptyText | None = None
    kinds: frozenset[ObservationKind] | None = None
    target: ObservationTarget | None = None
    match: dict[str, JsonValue] = Field(default_factory=dict)
    after_cursor: int = Field(default=0, ge=0)


class ObservationPage(BaseModel):
    """后续 Console cursor endpoint 使用的稳定分页形状。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    items: list[ObservationRecord] = Field(default_factory=list)
    next_cursor: int = Field(ge=0)
    has_more: bool
