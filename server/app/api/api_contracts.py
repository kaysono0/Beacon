"""HTTP API request/response contracts for externally consumed Beacon routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.observations.observation_models import (
    ObservationInput as ObservationInput,
    ObservationPage as ObservationPage,
    ObservationQuery as ObservationQuery,
    ObservationRecord as ObservationRecord,
)


class RunnerSourceLocation(BaseModel):
    """Source location supplied by the isolated target-runtime Runner."""

    model_config = ConfigDict(extra="forbid")

    path: str
    line: int = Field(ge=1)
    function: str


class RunnerTarget(BaseModel):
    """Registry target for a single immediate remote-control capability."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    sdk: str
    interface: str
    class_name: str | None = Field(default=None, alias="class")
    function: str | None = None
    name: str | None = None


class ResourceReference(BaseModel):
    """Server-issued resource reference scoped to one run, case and role."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str
    run_id: str
    case_id: str
    device_role: str
    resource_type: str


class RunnerStartedRequest(BaseModel):
    """Handshake emitted once by an isolated case Runner process."""

    model_config = ConfigDict(extra="forbid")

    runner_protocol_version: Literal[1]
    python_version: str
    pid: int = Field(gt=0)


class RunnerCallRequest(BaseModel):
    """Target-only request DTO for one Runner-originated Native capability call."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    device_role: str
    target: RunnerTarget
    params: dict[str, Any] = Field(default_factory=dict)
    resource_ref: ResourceReference | None = None
    create_resource: bool = False
    timeout_ms: int = Field(default=5000, ge=1)
    source: RunnerSourceLocation


class RunnerCallResponse(BaseModel):
    """Direct Native result for one idempotent target-runtime call."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    device_role: str
    node_id: str
    code: int
    message: str
    result: Any
    resource_ref: ResourceReference | None = None
    failure_classification: str | None = None
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)


class RunnerCallbackCall(BaseModel):
    """Native operation to execute when a registered callback arrives."""

    model_config = ConfigDict(extra="forbid")

    target: RunnerTarget
    params: dict[str, Any] = Field(default_factory=dict)


class RunnerCallbackRegistrationRequest(BaseModel):
    """为一个 run 注册回调触发的 Native 操作。"""

    model_config = ConfigDict(extra="forbid")

    registration_id: str
    device_role: str
    event_target: RunnerTarget
    calls: list[RunnerCallbackCall] = Field(min_length=1)
    repeat: int = 1
    timeout_ms: int = Field(default=5000, ge=1)
    source: RunnerSourceLocation

    @field_validator("repeat")
    @classmethod
    def valid_repeat(cls, value: int) -> int:
        if value == -1 or value >= 1:
            return value
        raise ValueError("repeat must be -1 or >= 1")


class RunnerCallbackRegistrationResponse(BaseModel):
    registration_id: str
    device_role: str
    node_id: str
    code: int
    message: str
    started_at_ms: int = Field(ge=0)
    finished_at_ms: int = Field(ge=0)


class RunnerWaitRequest(BaseModel):
    """Target-only DTO for an Observation wait; it cannot select a device directly."""

    model_config = ConfigDict(extra="forbid")

    wait_id: str
    device_role: str
    kind: Literal["event", "state", "metric", "log", "artifact", "connection"]
    target: RunnerTarget
    match: dict[str, Any] = Field(default_factory=dict)
    after_cursor: int | None = Field(default=None, ge=0)
    timeout_ms: int = Field(ge=1)
    source: RunnerSourceLocation


class RunnerCaseResultRequest(BaseModel):
    """Runner candidate result; Server remains the case and run terminal owner."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed", "unsupported", "cancelled", "timed_out"]
    failure_classification: Literal[
        "python_assertion",
        "import_error",
        "python_exception",
        "process_crash",
    ] | None = None
    message: str = ""
    source: RunnerSourceLocation | None = None
    diagnostic_traceback: str | None = None
    timestamp_ms: int | None = Field(default=None, ge=0)


class ConsoleSDKCallbackCapability(BaseModel):
    model_config = ConfigDict(extra="allow")

    target: dict[str, Any]
    filterable_fields: list[str] = Field(default_factory=list)
    evidence_summary_fields: list[str] = Field(default_factory=list)
    payload_schema: dict[str, Any] = Field(default_factory=dict)


class ConsoleSDKInterfaceCapability(BaseModel):
    model_config = ConfigDict(extra="allow")

    interface: str
    methods: list[dict[str, Any]] = Field(default_factory=list)
    callbacks: list[ConsoleSDKCallbackCapability] = Field(default_factory=list)
    metrics: list[dict[str, Any]] = Field(default_factory=list)
    states: list[dict[str, Any]] = Field(default_factory=list)


class ConsoleSDKCapability(BaseModel):
    sdk: str
    interfaces: list[ConsoleSDKInterfaceCapability] = Field(default_factory=list)


class ConsoleSDKCapabilitiesResponse(BaseModel):
    sdks: list[ConsoleSDKCapability] = Field(default_factory=list)


class ConsoleTestCaseSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    case_id: str
    name: str
    platform: str
    suite: str
    tags: list[str] = Field(default_factory=list)
    covered_capabilities: list[str] = Field(default_factory=list)
    scenario_family: str = ""
    implementation_status: str = ""
    blocked_category: str = ""
    blocked_reason: str = ""
    runnable_prerequisites: list[str] = Field(default_factory=list)
    owner_layer: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)
    requires_runtime_isolation: bool = False
    source: str


class ConsoleTestCasesResponse(BaseModel):
    cases: list[ConsoleTestCaseSummary] = Field(default_factory=list)


class ConsoleRunHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    status: str
    case_ids: list[str] = Field(default_factory=list)
    created_at_ms: int
    finished_at_ms: int | None = None
    duration_ms: int | None = None


class ConsoleRunHistoryResponse(BaseModel):
    runs: list[ConsoleRunHistoryEntry] = Field(default_factory=list)


class ConsoleRunDetailResponse(BaseModel):
    run: dict[str, Any]
    report: dict[str, Any]
    logs: list[dict[str, Any]] = Field(default_factory=list)
    observation_cursor_enabled: bool


class TestRunCreateRequest(BaseModel):
    """正式入口只接受 catalog ID，不接受客户端提供源码或步骤。"""

    model_config = ConfigDict(extra="forbid")

    selector: dict[str, Any] = Field(default_factory=dict)
    case_ids: list[str] = Field(min_length=1)
