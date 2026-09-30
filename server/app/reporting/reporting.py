"""生成即时运行报告，并支持读取历史 run 报告；不执行测试或断言。"""

from __future__ import annotations

import html
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.reporting.evidence_runtime import Evidence, ResultCollector
from app.common.redaction import redact_local_paths
from app.common.interfaces import TestRunReaderProtocol
from app.observations.observation_models import ObservationQuery
from app.observations.observation_service import ObservationService
from app.runs.test_models import StepResult, TestCase, TestReport, TestRun


def _safe_artifact_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value)


class ReportGenerator:
    """生成 run 级报告。

    旧 run 消费 StepResult；目标 run 从 case 终态和 Observation 投影。
    """

    def __init__(
        self,
        run_reader: TestRunReaderProtocol,
        collector: ResultCollector | None = None,
        log_collector: Any | None = None,
        log_artifact_dir: Path | None = None,
        observation_service: ObservationService | None = None,
    ) -> None:
        self._run_reader = run_reader
        self._collector = collector
        self._log_collector = log_collector
        self._log_artifact_dir = log_artifact_dir
        self._observations = observation_service

    async def generate(self, run_id: str, format: str) -> TestReport:
        run = await self._run_reader.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run.execution_mode == "target":
            return await self._target_report(run, format)
        case_results = [await self._case_result(run.run_id, result) for result in run.results]
        return TestReport(
            run_id=run.run_id,
            format=format,
            summary=self._summary(run, case_results),
            case_results=case_results,
            capability_coverage=self._capability_coverage(run),
            scenario_coverage=self._scenario_coverage(run),
            blocked_scenarios=self._blocked_scenarios(run),
            artifact_urls=[artifact for result in run.results for artifact in result.artifacts],
        )

    async def _target_report(self, run: TestRun, format: str) -> TestReport:
        """目标报告只投影 case 终态和 Observation，不读取旧 StepResult。"""

        if self._observations is None:
            raise RuntimeError("target report requires ObservationService")
        records = await self._observations.query(ObservationQuery(run_id=run.run_id))
        by_case: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_case.setdefault(record.case_id, []).append(record.model_dump(mode="json", by_alias=True))
        case_results = []
        for result in run.case_results:
            facts = by_case.get(result.case_id, [])
            case_results.append({
                **result.model_dump(mode="json"),
                "operations": [fact for fact in facts if fact["kind"] == "operation"],
                "observations": facts,
            })
        return TestReport(
            run_id=run.run_id, format=format,
            summary={
                "status": run.status, "total_cases": len(run.cases),
                "passed": sum(item.status == "passed" for item in run.case_results),
                "failed": sum(item.status in ("failed", "timed_out") for item in run.case_results),
            },
            case_results=case_results,
            capability_coverage=self._capability_coverage(run),
            scenario_coverage=self._scenario_coverage(run),
            blocked_scenarios=self._blocked_scenarios(run),
            artifact_urls=[
                path for record in records
                if record.kind == "artifact"
                and isinstance(path := record.payload.get("path"), str)
                and path.startswith("artifact://")
            ],
        )

    async def generate_junit(self, run_id: str) -> str:
        """生成 CI 可解析的最小 JUnit XML。"""
        report = await self.generate(run_id, "junit")
        failures = sum(1 for result in report.case_results if result["status"] in ("failed", "timed_out"))
        cases = []
        for result in report.case_results:
            name = f"{result['case_id']}.{result['step_id']}" if "step_id" in result else result["case_id"]
            failure = ""
            if result["status"] in ("failed", "timed_out"):
                message = html.escape((result.get("error") or {}).get("message") or result.get("message") or "failed")
                failure = f'<failure message="{message}" />'
            cases.append(f'<testcase classname="BeaconPhase1" name="{html.escape(name)}">{failure}</testcase>')
        return f'<testsuite name="beacon-server" tests="{len(cases)}" failures="{failures}">{"".join(cases)}</testsuite>'

    def _summary(self, run: TestRun, case_results: list[dict] | None = None) -> dict:
        passed = sum(1 for result in run.results if result.status == "passed")
        failed = sum(1 for result in run.results if result.status == "failed")
        unsupported = sum(1 for result in run.results if result.status == "unsupported")
        summary = {
            "status": run.status,
            "total_steps": len(run.results),
            "passed": passed,
            "failed": failed,
            "unsupported": unsupported,
            "core_gate_status": self._gate_status(run, "core"),
            "enhanced_gate_status": self._gate_status(run, "enhanced"),
            "resilience_gate_status": self._gate_status(run, "resilience"),
        }
        failure_diagnostics = self._failure_diagnostics(run, case_results or [])
        if failure_diagnostics["total"]:
            summary["failure_diagnostics"] = failure_diagnostics
        return summary

    def _failure_diagnostics(self, run: TestRun, case_results: list[dict] | None = None) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {
            "total": 0,
            "by_category": {},
            "by_reason": {},
            "items": [],
        }
        case_result_by_step = {
            (item.get("case_id"), item.get("step_id")): item for item in (case_results or [])
        }
        for result in run.results:
            classification = result.failure_classification
            if classification is None:
                case_result = case_result_by_step.get((result.case_id, result.step_id), {})
                classification = self._log_failure_classification(case_result)
            if classification is None:
                continue
            diagnostics["total"] += 1
            category = classification.get("category")
            if isinstance(category, str):
                diagnostics["by_category"][category] = diagnostics["by_category"].get(category, 0) + 1
            reason = classification.get("reason")
            if isinstance(reason, str):
                diagnostics["by_reason"][reason] = diagnostics["by_reason"].get(reason, 0) + 1
            owner_layer = classification.get("owner_layer")
            if isinstance(owner_layer, str):
                by_owner_layer = diagnostics.setdefault("by_owner_layer", {})
                by_owner_layer[owner_layer] = by_owner_layer.get(owner_layer, 0) + 1
            diagnostics["items"].append(
                {
                    "case_id": result.case_id,
                    "step_id": result.step_id,
                    "status": result.status,
                    "error": result.error,
                    "classification": classification,
                }
            )
        return diagnostics

    def _log_failure_classification(self, case_result: dict) -> dict[str, Any] | None:
        for log in case_result.get("related_logs", {}).get("warnings_errors", []):
            extra = log.get("extra", {})
            if not isinstance(extra, dict):
                continue
            category = extra.get("failure_category")
            owner_layer = extra.get("owner_layer")
            if not isinstance(category, str) and not isinstance(owner_layer, str):
                continue
            classification: dict[str, Any] = {"source": "related_log"}
            if isinstance(category, str):
                classification["category"] = category
            reason = extra.get("failure_reason")
            if isinstance(reason, str):
                classification["reason"] = reason
            if isinstance(owner_layer, str):
                classification["owner_layer"] = owner_layer
            if isinstance(log.get("event"), str):
                classification["event"] = log["event"]
            artifact_uri = extra.get("artifact_uri")
            if isinstance(artifact_uri, str):
                classification["artifact_uri"] = artifact_uri
            for key in ("round_id", "attempt", "reset_id"):
                if key in extra:
                    classification[key] = extra[key]
            return classification
        return None

    def _gate_status(self, run: TestRun, gate_level: str) -> str:
        case_ids = {case.case_id for case in run.cases if self._gate_level(case) == gate_level}
        if not case_ids:
            return "not_applicable"
        results = [result for result in run.results if result.case_id in case_ids]
        if any(result.status == "failed" for result in results):
            return "failed"
        if any(result.status == "passed" for result in results):
            return "passed"
        if any(case.case_id in case_ids and case.implementation_status == "designed_but_blocked" for case in run.cases):
            return "blocked"
        return "not_run"

    def _gate_level(self, case: TestCase) -> str:
        suite = case.suite
        if suite.endswith("_core") or suite.endswith("_l1"):
            return "core"
        if suite.endswith("_resilience") or case.scenario_family == "failure_recovery":
            return "resilience"
        return "enhanced"

    def _capability_coverage(self, run: TestRun) -> dict[str, Any]:
        all_capabilities: set[str] = set()
        covered_capabilities: set[str] = set()
        case_count_by_capability: dict[str, int] = {}
        case_count_by_layer = {"core": 0, "enhanced": 0, "resilience": 0}
        for case in run.cases:
            case_count_by_layer[self._gate_level(case)] += 1
            for capability in case.covered_capabilities:
                all_capabilities.add(capability)
                case_count_by_capability[capability] = case_count_by_capability.get(capability, 0) + 1
                if case.implementation_status != "designed_but_blocked":
                    covered_capabilities.add(capability)
        total = len(all_capabilities)
        covered = len(covered_capabilities)
        percent = int((covered / total) * 100) if total else 0
        return {
            "total": total,
            "covered": covered,
            "percent": percent,
            "missing_capabilities": sorted(all_capabilities - covered_capabilities),
            "case_count_by_capability": dict(sorted(case_count_by_capability.items())),
            "case_count_by_layer": case_count_by_layer,
        }

    def _scenario_coverage(self, run: TestRun) -> dict[str, Any]:
        families: dict[str, dict[str, int]] = {}
        totals = {"total": 0, "runnable": 0, "runnable_or_partial": 0, "designed_but_blocked": 0}
        for case in run.cases:
            family = case.scenario_family or "unclassified"
            family_counts = families.setdefault(
                family,
                {"total": 0, "runnable": 0, "runnable_or_partial": 0, "designed_but_blocked": 0},
            )
            family_counts["total"] += 1
            totals["total"] += 1
            status = case.implementation_status or "runnable"
            if status in family_counts:
                family_counts[status] += 1
                totals[status] += 1
        return {"families": families, "totals": totals}

    def _blocked_scenarios(self, run: TestRun) -> list[dict[str, Any]]:
        blocked = []
        for case in run.cases:
            if case.implementation_status != "designed_but_blocked":
                continue
            blocked.append(
                {
                    "case_id": case.case_id,
                    "name": case.name,
                    "suite": case.suite,
                    "scenario_family": case.scenario_family,
                    "covered_capabilities": case.covered_capabilities,
                    "implementation_status": case.implementation_status,
                    "blocked_category": case.blocked_category,
                    "blocked_reason": case.blocked_reason,
                    "runnable_prerequisites": case.runnable_prerequisites,
                    "owner_layer": case.owner_layer,
                }
            )
        return blocked

    async def _case_result(self, run_id: str, result: StepResult) -> dict:
        data = result.model_dump()
        if not result.source_locations:
            data.pop("source_locations", None)
        data["evidence"] = []
        if self._collector is not None:
            evidence = await self._collector.evidence_for_step(run_id, result.case_id, result.step_id)
            data["evidence"] = [self._evidence_summary(item) for item in evidence]
            if result.status == "failed":
                diagnostics = await self._collector.connection_events(
                    node_id=result.node_id,
                    run_id=run_id,
                    case_id=result.case_id,
                    step_id=result.step_id,
                )
                if diagnostics:
                    data["connection_diagnostics"] = diagnostics
        if result.status == "failed" and self._log_collector is not None:
            logs = await self._log_collector.query_by_trace(
                run_id,
                result.case_id,
                result.step_id,
                node_id=result.node_id,
                lease_id=result.lease_id,
            )
            data.update(self._related_log_projection(run_id, result, logs))
        return data

    def _related_log_projection(self, run_id: str, result: StepResult, logs: list[dict]) -> dict:
        window_ms = 5000
        window_start = result.finished_at_ms - window_ms if result.finished_at_ms is not None else None
        window_end = result.finished_at_ms + window_ms if result.finished_at_ms is not None else None
        window_logs = [
            log
            for log in logs
            if window_start is None
            or window_end is None
            or window_start <= int(log.get("timestamp_ms", 0)) <= window_end
        ]
        warnings_errors = [
            self._log_summary(log) for log in logs if str(log.get("level", "")).lower() in {"warn", "error", "fatal"}
        ][:50]
        op_id = next((log.get("op_id") for log in logs if log.get("op_id")), "")
        op_logs = [self._log_summary(log) for log in logs if op_id and log.get("op_id") == op_id][:50]
        log_artifacts = list(result.artifacts)
        artifact_uri = self._write_log_artifact(run_id, result, logs)
        if artifact_uri is not None:
            log_artifacts.append(artifact_uri)
        projection: dict[str, Any] = {
            "related_logs": {
                "op_id": op_logs,
                "time_window": [self._log_summary(log) for log in window_logs][:50],
                "warnings_errors": warnings_errors,
            },
            "log_artifacts": log_artifacts,
            "log_query": {
                "run_id": run_id,
                "case_id": result.case_id,
                "step_id": result.step_id,
                "op_id": op_id,
                "window_ms": window_ms,
            },
        }
        if window_start is not None and window_end is not None:
            projection["log_query"]["start_ms"] = window_start
            projection["log_query"]["end_ms"] = window_end
        if result.node_id is not None:
            projection["log_query"]["node_id"] = result.node_id
        if result.lease_id is not None:
            projection["log_query"]["lease_id"] = result.lease_id
        return projection

    def _write_log_artifact(self, run_id: str, result: StepResult, logs: list[dict]) -> str | None:
        if self._log_artifact_dir is None or not logs:
            return None
        filename = f"{_safe_artifact_part(result.case_id)}.{_safe_artifact_part(result.step_id)}.jsonl"
        path = self._log_artifact_dir / run_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(log, sort_keys=True) + "\n" for log in logs), encoding="utf-8")
        return f"artifact://logs/{run_id}/{filename}"

    def _log_summary(self, log: dict) -> dict:
        return {
            key: log[key]
            for key in ("timestamp_ms", "level", "node_id", "lease_id", "module", "event", "message", "error", "extra")
            if key in log
        }

    def _evidence_summary(self, evidence: Evidence) -> dict:
        summary = {
            "type": evidence.type,
            "source": evidence.source,
            "node_id": evidence.node_id,
            "target": evidence.target,
            "payload": evidence.payload,
            "timestamp_ms": evidence.timestamp_ms,
        }
        if evidence.callback_context is not None:
            summary["callback_context"] = evidence.callback_context
        if evidence.callback_execution is not None:
            summary["callback_execution"] = evidence.callback_execution
        return summary
