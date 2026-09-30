"""Server test run data models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.api.api_contracts import RunnerSourceLocation
from app.devices.device_models import Device, DeviceSelector
from app.reporting.evidence_runtime import now_ms

RunStatus = Literal["queued", "running", "passed", "failed", "cancelled"]
RunTerminalStatus = Literal["passed", "failed", "cancelled"]


class TestStep(BaseModel):
    """编译后测试用例中的单个执行步骤。"""

    __test__ = False

    step_id: str
    target: dict | None = None
    params: dict = Field(default_factory=dict)
    assertions: list[dict] = Field(default_factory=list)
    packet: dict | None = None


class TestCase(BaseModel):
    """运行元数据与历史报告使用的 canonical test case。"""

    __test__ = False

    case_id: str
    name: str
    platform: str = "common"
    suite: str = ""
    covered_capabilities: list[str] = Field(default_factory=list)
    scenario_family: str = ""
    implementation_status: str = ""
    blocked_category: str = ""
    blocked_reason: str = ""
    runnable_prerequisites: list[str] = Field(default_factory=list)
    owner_layer: str = ""
    steps: list[TestStep]


class StepResult(BaseModel):
    """单个测试步骤的执行证据。"""

    case_id: str
    step_id: str
    status: str
    node_id: str | None = None
    lease_id: str | None = None
    error: dict | None = None
    failure_classification: dict | None = None
    artifacts: list[str] = Field(default_factory=list)
    started_at_ms: int | None = None
    finished_at_ms: int | None = None
    duration_ms: int = 0
    source_locations: list[dict[str, Any]] = Field(default_factory=list)


class CaseExecutionResult(BaseModel):
    """目标 Runner case 的终态；不把每次操作伪装成 step。"""

    case_id: str
    status: Literal["passed", "failed", "unsupported", "cancelled", "timed_out"]
    failure_classification: str | None = None
    message: str = ""
    started_at_ms: int
    finished_at_ms: int
    cleanup_failed: bool = False
    source: RunnerSourceLocation | None = None


class TestRun(BaseModel):
    """一次服务端测试运行。"""

    __test__ = False

    run_id: str
    status: str
    execution_mode: Literal["legacy", "target"] = "legacy"
    selector: DeviceSelector
    cases: list[TestCase]
    selected_devices: list[Device] = Field(default_factory=list)
    results: list[StepResult] = Field(default_factory=list)
    case_results: list[CaseExecutionResult] = Field(default_factory=list)
    created_at_ms: int = Field(default_factory=now_ms)
    finished_at_ms: int | None = None


class TestReport(BaseModel):
    """run 级报告模型。"""

    __test__ = False

    run_id: str
    format: str
    summary: dict
    case_results: list[dict]
    capability_coverage: dict = Field(default_factory=dict)
    scenario_coverage: dict = Field(default_factory=dict)
    blocked_scenarios: list[dict] = Field(default_factory=list)
    artifact_urls: list[str] = Field(default_factory=list)
