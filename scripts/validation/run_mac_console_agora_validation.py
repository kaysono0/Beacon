#!/usr/bin/env python3
"""Run Agora real macOS cases through Beacon Mac Test Console autorun mode."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports/latest"
AUTORUN_REPORT = REPORT_DIR / "mac_console_agora_autorun.json"
REPORT_JSON = REPORT_DIR / "mac_console_agora.json"
REPORT_JUNIT = REPORT_DIR / "mac_console_agora.junit.xml"
FAILED_CASE_REPORT_JSON = REPORT_DIR / "mac_console_agora_failed_case_report.json"
FAILED_CASE_EVIDENCE_JSON = REPORT_DIR / "mac_console_agora_failed_case_evidence.json"
CASE_PREFIX = "TC-MAC-AGORA-"
CASE_IDS_ENV = "BEACON_MAC_CONSOLE_AGORA_CASE_IDS"
REQUIRED_ENV = ("AGORA_MAC_SDK_ROOT", "AGORA_APP_ID", "AGORA_APP_CERT", "BEACON_AUTH_TOKEN")
PRIMARY_NODE_ID = "mac-real-e2e-001"
PEER_NODE_ID = "mac-real-peer-e2e-001"
PEER_B_NODE_ID = "mac-real-peer-b-e2e-001"
REAL_E2E_GROUP_ID = "real-e2e"
AUTORUN_ROUNDS = 2
AUTORUN_ROUNDS_ENV = "BEACON_MAC_CONSOLE_AGORA_ROUNDS"
AUTORUN_TIMEOUT_SECONDS = 600
VISUAL_CALL_CASE_ID = "TC-MAC-AGORA-1V1-REMOTE-VIDEO-RENDERED"
SYNTH_PEER_CASE_ID = "TC-MAC-AGORA-1V1-REMOTE-VIDEO-SYNTH-PEER"
SMALL_ROOM_CASE_ID = "TC-MAC-AGORA-SMALL-ROOM-BASELINE"
AUDIO_MUTE_RECOVER_CASE_ID = "TC-MAC-AGORA-1V1-AUDIO-MUTE-RECOVER"
AUDIO_PLAYBACK_MUTE_RECOVER_CASE_ID = "TC-MAC-AGORA-1V1-AUDIO-PLAYBACK-MUTE-RECOVER"
MEDIA_PLAYER_PAUSE_RESUME_CASE_ID = "TC-MAC-AGORA-1V1-MEDIA-PLAYER-PAUSE-RESUME"
SIMULCAST_LAYER_TOGGLE_CASE_ID = "TC-MAC-AGORA-1V1-SIMULCAST-LAYER-TOGGLE"
REMOTE_VIDEO_BIND_FUNCTIONS = {"bindRemoteVideo"}
REMOTE_VIDEO_RENDER_CASE_IDS = {
    VISUAL_CALL_CASE_ID,
    AUDIO_PLAYBACK_MUTE_RECOVER_CASE_ID,
}
AUTORUN_CLEANUP_CASE_ID = "TC-MAC-AGORA-RUNTIME-CLEANUP-BASELINE"
PRIMARY_LOCAL_VIEW_ID = "primary_local_preview"
PRIMARY_REMOTE_VIEW_ID = "primary_remote_view"
PEER_LOCAL_VIEW_ID = "peer_local_preview"
PEER_REMOTE_VIEW_ID = "peer_remote_view"
VISUAL_CALL_PRIMARY_UID = 1001
VISUAL_CALL_PEER_UID = 1002
SMALL_ROOM_PRIMARY_UID = 1101
SMALL_ROOM_PEER_UIDS = (1102, 1103)
VISUAL_ARTIFACT_KEYS = (
    "primary_local_preview",
    "primary_remote_view",
    "peer_local_preview",
    "peer_remote_view",
)
VISUAL_ARTIFACT_EXPECTED_NODE = {
    "primary_local_preview": PRIMARY_NODE_ID,
    "primary_remote_view": PRIMARY_NODE_ID,
    "peer_local_preview": PEER_NODE_ID,
    "peer_remote_view": PEER_NODE_ID,
}
REQUIRED_EVIDENCE_FUNCTIONS_BY_CASE = {
    "TC-MAC-AGORA-REAL-JOIN-CALLBACK": {"onJoinChannelSuccess"},
    "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE": {"onJoinChannelSuccess"},
    "TC-MAC-AGORA-JOIN-CALLBACK-SUCCESS": {"onJoinChannelSuccess"},
    "TC-MAC-AGORA-REMOTE-AUDIO-STATS-OBSERVABLE": {"onRemoteAudioStats"},
    AUDIO_MUTE_RECOVER_CASE_ID: {"onRemoteAudioStats"},
    AUDIO_PLAYBACK_MUTE_RECOVER_CASE_ID: {
        "remote_video_binding",
        "onFirstRemoteVideoFrame",
        "onRemoteVideoStats",
        "onRemoteAudioStats",
        "onRtcStats",
    },
    MEDIA_PLAYER_PAUSE_RESUME_CASE_ID: {
        "onMediaPlayerStateChanged",
        "onFirstRemoteVideoFrame",
        "onRemoteVideoStats",
        "onRemoteAudioStats",
    },
    "TC-MAC-AGORA-REMOTE-VIDEO-STATS-OBSERVABLE": {"onRemoteVideoStats"},
    SMALL_ROOM_CASE_ID: {"onRemoteAudioStats", "onRtcStats"},
    VISUAL_CALL_CASE_ID: {
        "remote_video_binding",
        "onFirstRemoteVideoFrame",
        "onRtcStats",
    },
    SYNTH_PEER_CASE_ID: {
        "onJoinChannelSuccess",
        "onLocalVideoStats",
    },
    SIMULCAST_LAYER_TOGGLE_CASE_ID: {"onRemoteVideoStats"},
}
REFERENCE_CAPABILITY_CASES = {
    "call": (
        "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
        "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE",
    ),
    "callback": (
        "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
        "TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT",
    ),
    "state": (
        "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE",
        "TC-MAC-AGORA-SUCCESS-THEN-LEAVE-CLEANUP",
    ),
    "metric": (
        "TC-MAC-AGORA-RTC-STATS-OBSERVABLE",
        "TC-MAC-AGORA-REMOTE-AUDIO-STATS-OBSERVABLE",
        SMALL_ROOM_CASE_ID,
    ),
    "artifact": (VISUAL_CALL_CASE_ID,),
    "log": (
        "TC-MAC-AGORA-INVALID-TOKEN-FAILURE",
        "TC-MAC-AGORA-PERMISSION-DENIED-JOIN-FAILURE",
        "TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT",
    ),
    "device": (VISUAL_CALL_CASE_ID, SMALL_ROOM_CASE_ID),
    "report": (
        "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE",
        "TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT",
        "TC-MAC-AGORA-PERMISSION-DENIED-JOIN-FAILURE",
    ),
}

sys.path.insert(0, str(ROOT))
from scripts.validation.run_mac_agora_e2e_tests import (  # noqa: E402
    agora_framework_exists,
    configure_rtc_token,
    free_port,
    missing_real_env,
    run,
    start_native_websocket_agent,
    stop_native_websocket_agent,
    wait_http,
    wait_for_registered_device,
)
from scripts.support.visual_evidence import (  # noqa: E402
    SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
    SCENARIO_SMALL_ROOM,
    VERDICT_NOT_EXERCISED,
    VERDICT_PASSED,
    assert_scenario_has_no_picture_evidence,
    build_not_exercised_scenario,
    build_scenario_visual_evidence,
    png_pixel_diagnostics as build_png_pixel_diagnostics,
    summarize_visual_evidence,
)
from scripts.support.console_gate_support import (  # noqa: E402
    run_autorun_round as run_shared_autorun_round,
    stop_console_process,
    wait_for_autorun_report,
    write_gate_report,
)


def write_report(status: str, message: str, extra: dict[str, Any] | None = None) -> None:
    write_gate_report(
        report_path=REPORT_JSON,
        junit_path=REPORT_JUNIT,
        junit_name="mac-console-agora",
        junit_classname="mac-console-agora",
        junit_case_name="app-driven-agora",
        run_id="run-mac-console-agora-local",
        expected_cases=EXPECTED_CASES,
        status=status,
        message=message,
        extra=extra,
    )


def gate_level_for_case(case: dict[str, Any]) -> str:
    suite = str(case.get("suite", ""))
    scenario_family = str(case.get("scenario_family", ""))
    if suite.endswith("_core") or suite.endswith("_l1"):
        return "core"
    if suite.endswith("_resilience") or scenario_family == "failure_recovery":
        return "resilience"
    return "enhanced"


def build_gate_report(cases: list[dict[str, Any]], reports: list[dict[str, Any]]) -> dict[str, Any]:
    executed_status_by_case: dict[str, str] = {}
    for report in reports:
        for result in report.get("case_results", []):
            executed_status_by_case[result["case_id"]] = result["status"]

    gate_report: dict[str, Any] = {}
    for gate_level in ("core", "enhanced", "resilience"):
        gate_cases = [case for case in cases if gate_level_for_case(case) == gate_level]
        runnable_cases = sorted(
            case["case_id"] for case in gate_cases if case.get("implementation_status") == "runnable"
        )
        partial_cases = sorted(
            case["case_id"] for case in gate_cases if case.get("implementation_status") == "runnable_or_partial"
        )
        blocked_cases = sorted(
            case["case_id"] for case in gate_cases if case.get("implementation_status") == "designed_but_blocked"
        )
        executed_cases = sorted(case_id for case_id in runnable_cases if case_id in executed_status_by_case)
        if any(executed_status_by_case.get(case_id) == "failed" for case_id in executed_cases):
            status = "failed"
        elif executed_cases:
            status = "passed"
        elif runnable_cases:
            status = "not_run"
        elif blocked_cases:
            status = "blocked"
        else:
            status = "not_applicable"
        gate_report[f"{gate_level}_gate"] = {
            "status": status,
            "executed_cases": executed_cases,
            "catalog_runnable_cases": runnable_cases,
            "catalog_partial_cases": partial_cases,
            "catalog_blocked_cases": blocked_cases,
        }
    return gate_report


def build_peer_isolation_diagnostics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    remote_audio_stats_on_primary = False
    remote_video_stats_on_primary = False
    unexpected_peer_owned_primary_evidence: list[dict[str, Any]] = []
    for report in reports:
        for result in report.get("case_results", []):
            for item in result.get("observations", []):
                function = item.get("target", {}).get("function")
                node_id = item.get("node_id")
                if function == "onRemoteAudioStats" and node_id == PRIMARY_NODE_ID:
                    remote_audio_stats_on_primary = True
                if function == "onRemoteVideoStats" and node_id == PRIMARY_NODE_ID:
                    remote_video_stats_on_primary = True
                if function in {"onRemoteAudioStats", "onRemoteVideoStats"} and node_id == PEER_NODE_ID:
                    unexpected_peer_owned_primary_evidence.append(
                        {
                            "case_id": result.get("case_id"),
                            "function": function,
                            "node_id": node_id,
                        }
                    )
    return {
        "primary_node_id": PRIMARY_NODE_ID,
        "peer_node_id": PEER_NODE_ID,
        "remote_audio_stats_on_primary": remote_audio_stats_on_primary,
        "remote_video_stats_on_primary": remote_video_stats_on_primary,
        "unexpected_peer_owned_primary_evidence": unexpected_peer_owned_primary_evidence,
    }


def build_small_room_diagnostics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    remote_audio_stats_on_primary_uids: set[int] = set()
    peer_audio_transmit_observed_uids: set[int] = set()
    primary_rtc_audio_receive_observed = False
    peer_uid_by_node = {PEER_NODE_ID: 1102, PEER_B_NODE_ID: 1103}
    for report in reports:
        for result in report.get("case_results", []):
            if result.get("case_id") != SMALL_ROOM_CASE_ID:
                continue
            for item in result.get("observations", []):
                function = item.get("target", {}).get("function")
                payload = item.get("payload", {})
                node_id = item.get("node_id")
                if function == "onRemoteAudioStats" and node_id == PRIMARY_NODE_ID:
                    uid = payload.get("uid")
                    if isinstance(uid, int) and uid in SMALL_ROOM_PEER_UIDS:
                        remote_audio_stats_on_primary_uids.add(uid)
                if function == "onRtcStats" and node_id == PRIMARY_NODE_ID:
                    primary_rtc_audio_receive_observed = (
                        primary_rtc_audio_receive_observed or payload.get("rx_audio_kbitrate", 0) > 0
                    )
                if (
                    function == "onRtcStats"
                    and node_id in peer_uid_by_node
                    and payload.get("tx_audio_kbitrate", 0) > 0
                ):
                    peer_audio_transmit_observed_uids.add(peer_uid_by_node[node_id])
    observed_uids = sorted(remote_audio_stats_on_primary_uids)
    transmitting_uids = sorted(peer_audio_transmit_observed_uids)
    return {
        "primary_node_id": PRIMARY_NODE_ID,
        "peer_node_ids": [PEER_NODE_ID, PEER_B_NODE_ID],
        "primary_uid": SMALL_ROOM_PRIMARY_UID,
        "peer_uids": list(SMALL_ROOM_PEER_UIDS),
        "remote_audio_stats_on_primary_uids": observed_uids,
        "peer_audio_transmit_observed_uids": transmitting_uids,
        "primary_rtc_audio_receive_observed": primary_rtc_audio_receive_observed,
        "small_room_proof_passed": primary_rtc_audio_receive_observed
        and transmitting_uids == list(SMALL_ROOM_PEER_UIDS)
        and bool(observed_uids),
    }


def build_simulcast_layer_diagnostics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """各 run 独立核对低高层，再汇总；顶层样本展示最后一轮。"""

    runs = [
        _build_simulcast_run_diagnostics(report)
        for report in reports
        if any(result.get("case_id") == SIMULCAST_LAYER_TOGGLE_CASE_ID for result in report.get("case_results", []))
    ]
    latest = runs[-1] if runs else _build_simulcast_run_diagnostics({})
    return {
        **latest,
        "run_diagnostics": runs,
        "simulcast_layer_proof_passed": bool(runs) and all(run["simulcast_layer_proof_passed"] for run in runs),
    }


def _build_simulcast_run_diagnostics(report: dict[str, Any]) -> dict[str, Any]:
    """从实际 SDK 统计按 cursor 验证低层后出现高层，不依赖旧 step 归属。"""

    low_samples: list[tuple[int, dict[str, int]]] = []
    high_samples: list[tuple[int, dict[str, int]]] = []
    for result in report.get("case_results", []):
        if result.get("case_id") != SIMULCAST_LAYER_TOGGLE_CASE_ID:
            continue
        for item in result.get("observations", []):
            payload = item.get("payload", {})
            if (
                item.get("kind") != "event"
                or item.get("node_id") != PRIMARY_NODE_ID
                or item.get("target", {}).get("function") != "onRemoteVideoStats"
                or payload.get("uid") != VISUAL_CALL_PEER_UID
            ):
                continue
            values = {name: payload.get(name) for name in ("width", "height", "received_bitrate")}
            if all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in values.values()):
                sample = (item["cursor"], values)
                if payload.get("rx_stream_type") == 1:
                    low_samples.append(sample)
                elif payload.get("rx_stream_type") == 0:
                    high_samples.append(sample)

    low = low_samples[-1] if low_samples else None
    high = next((sample for sample in high_samples if low and sample[0] > low[0]), None)
    low_sample = low[1] if low else None
    high_sample = high[1] if high else None
    dimensions_increased = bool(
        low_sample
        and high_sample
        and high_sample["width"] > low_sample["width"]
        and high_sample["height"] > low_sample["height"]
    )
    bitrate_changed = bool(
        low_sample and high_sample and high_sample["received_bitrate"] != low_sample["received_bitrate"]
    )
    return {
        "run_id": report.get("run_id"),
        "primary_node_id": PRIMARY_NODE_ID,
        "peer_uid": VISUAL_CALL_PEER_UID,
        "low_layer_samples": [sample[1] for sample in low_samples],
        "high_layer_samples": [sample[1] for sample in high_samples],
        "low_layer_sample": low_sample,
        "high_layer_sample": high_sample,
        "dimensions_increased": dimensions_increased,
        "bitrate_changed": bitrate_changed,
        "bitrate_delta_kbps": (
            high_sample["received_bitrate"] - low_sample["received_bitrate"] if low_sample and high_sample else None
        ),
        "simulcast_layer_proof_passed": bool(low_sample and high_sample and dimensions_increased and bitrate_changed),
    }


def build_audible_audio_diagnostics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    observer_received_bitrates: list[int] = []
    observer_audio_receive_bitrates: list[int] = []
    source_audio_transmit_bitrates: list[int] = []
    for report in reports:
        for result in report.get("case_results", []):
            if result.get("case_id") != AUDIO_PLAYBACK_MUTE_RECOVER_CASE_ID:
                continue
            for item in result.get("observations", []):
                payload = item.get("payload", {})
                function = item.get("target", {}).get("function")
                node_id = item.get("node_id")
                if function == "onRemoteAudioStats" and node_id == PRIMARY_NODE_ID and payload.get("uid") == 1312:
                    bitrate = payload.get("received_bitrate")
                    if isinstance(bitrate, int):
                        observer_received_bitrates.append(bitrate)
                if function == "onRtcStats" and node_id == PRIMARY_NODE_ID:
                    bitrate = payload.get("rx_audio_kbitrate")
                    if isinstance(bitrate, int):
                        observer_audio_receive_bitrates.append(bitrate)
                if function == "onRtcStats" and node_id == PEER_NODE_ID:
                    bitrate = payload.get("tx_audio_kbitrate")
                    if isinstance(bitrate, int):
                        source_audio_transmit_bitrates.append(bitrate)
    return {
        "source_node_id": PEER_NODE_ID,
        "observer_node_id": PRIMARY_NODE_ID,
        "source_audio_transmit_bitrates": source_audio_transmit_bitrates,
        "observer_audio_receive_bitrates": observer_audio_receive_bitrates,
        "observer_remote_audio_received_bitrates": observer_received_bitrates,
        "audible_stream_proof_passed": (
            any(value > 0 for value in source_audio_transmit_bitrates)
            and any(value > 0 for value in observer_audio_receive_bitrates)
            and any(value > 0 for value in observer_received_bitrates)
        ),
    }


def _executed_passed_case_ids(reports: list[dict[str, Any]]) -> set[str]:
    passed: set[str] = set()
    for report in reports:
        for result in report.get("case_results", []):
            if result.get("status") == "passed" and isinstance(result.get("case_id"), str):
                passed.add(result["case_id"])
    return passed


def _blocked_scenario_group_summary(blocked_scenarios: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for item in blocked_scenarios:
        key = str(item.get(field) or "unknown")
        case_id = item.get("case_id")
        if isinstance(case_id, str):
            grouped.setdefault(key, []).append(case_id)
    return {
        key: {"count": len(case_ids), "case_ids": sorted(case_ids)}
        for key, case_ids in sorted(grouped.items())
    }


def build_catalog_coverage(cases: list[dict[str, Any]], reports: list[dict[str, Any]]) -> dict[str, Any]:
    family_counts: dict[str, dict[str, int]] = {}
    blocked_scenarios: list[dict[str, Any]] = []
    all_capabilities: set[str] = set()
    covered_capabilities: set[str] = set()
    passed_case_ids = _executed_passed_case_ids(reports)

    for case in cases:
        family = str(case.get("scenario_family") or "uncategorized")
        status = str(case.get("implementation_status") or "unknown")
        counts = family_counts.setdefault(
            family,
            {
                "total": 0,
                "runnable": 0,
                "runnable_or_partial": 0,
                "designed_but_blocked": 0,
            },
        )
        counts["total"] += 1
        if status in counts:
            counts[status] += 1

        capabilities = [str(item) for item in case.get("covered_capabilities", [])]
        all_capabilities.update(capabilities)
        if case.get("case_id") in passed_case_ids:
            covered_capabilities.update(capabilities)
        if status == "designed_but_blocked":
            blocked_scenarios.append(
                {
                    "case_id": case.get("case_id"),
                    "name": case.get("name"),
                    "suite": case.get("suite"),
                    "scenario_family": family,
                    "covered_capabilities": capabilities,
                    "blocked_category": case.get("blocked_category", ""),
                    "blocked_reason": case.get("blocked_reason", ""),
                    "runnable_prerequisites": case.get("runnable_prerequisites", []),
                    "owner_layer": case.get("owner_layer", ""),
                }
            )

    total = len(all_capabilities)
    covered = len(covered_capabilities)
    percent = round((covered / total) * 100, 2) if total else 100
    sorted_blocked_scenarios = sorted(blocked_scenarios, key=lambda item: str(item["case_id"]))
    return {
        "scenario_coverage": {"families": dict(sorted(family_counts.items()))},
        "blocked_scenarios": sorted_blocked_scenarios,
        "blocked_scenario_summary": {
            "total": len(sorted_blocked_scenarios),
            "by_owner_layer": _blocked_scenario_group_summary(sorted_blocked_scenarios, "owner_layer"),
            "by_blocked_category": _blocked_scenario_group_summary(sorted_blocked_scenarios, "blocked_category"),
        },
        "capability_coverage": {
            "total": total,
            "covered": covered,
            "percent": percent,
            "covered_capabilities": sorted(covered_capabilities),
            "missing_capabilities": sorted(all_capabilities - covered_capabilities),
        },
    }


def build_evidence_coverage(reports: list[dict[str, Any]]) -> dict[str, Any]:
    observed_by_case: dict[str, set[str]] = {}
    total_required = 0
    total_observed = 0
    for report in reports:
        for result in report.get("case_results", []):
            case_id = result.get("case_id")
            required = REQUIRED_EVIDENCE_FUNCTIONS_BY_CASE.get(str(case_id))
            if not required:
                continue
            functions = {
                item.get("target", {}).get("function")
                for item in result.get("observations", [])
                if item.get("target", {}).get("function")
            }
            if str(case_id) in REMOTE_VIDEO_RENDER_CASE_IDS and functions & REMOTE_VIDEO_BIND_FUNCTIONS:
                functions.add("remote_video_binding")
            if str(case_id) in REMOTE_VIDEO_RENDER_CASE_IDS:
                remote_snapshot_roles = {
                    item.get("payload", {}).get("view_role") or item.get("payload", {}).get("artifact_key")
                    for item in result.get("observations", [])
                    if item.get("target", {}).get("function") in {"onSnapshotRequested", "onSnapshotTaken"}
                }
                if {PRIMARY_REMOTE_VIEW_ID, PEER_REMOTE_VIEW_ID} & remote_snapshot_roles:
                    functions.add("remote_video_binding")
            observed_by_case.setdefault(str(case_id), set()).update(
                functions
            )

    by_case: dict[str, dict[str, Any]] = {}
    for case_id, observed in observed_by_case.items():
        required = REQUIRED_EVIDENCE_FUNCTIONS_BY_CASE[case_id]
        missing = sorted(required - observed)
        observed_required = sorted(required & observed)
        total_required += len(required)
        total_observed += len(observed_required)
        by_case[case_id] = {
            "required_functions": sorted(required),
            "observed_functions": observed_required,
            "missing_functions": missing,
        }

    missing_cases = {
        case_id: data["missing_functions"]
        for case_id, data in by_case.items()
        if data["missing_functions"]
    }
    return {
        "status": "failed" if missing_cases else "passed",
        "total_required_functions": total_required,
        "observed_required_functions": total_observed,
        "missing": missing_cases,
        "by_case": dict(sorted(by_case.items())),
    }


def build_failure_log_contract_coverage(reports: list[dict[str, Any]]) -> dict[str, Any]:
    required_fields = ("related_logs", "log_artifacts", "log_query")
    reference_case_ids = set(REFERENCE_CAPABILITY_CASES["log"])
    failed_results = [
        result
        for report in reports
        for result in report.get("case_results", [])
        if result.get("case_id") in reference_case_ids and result.get("status") == "failed"
    ]
    missing_fields = {
        result["case_id"]: [field for field in required_fields if field not in result]
        for result in failed_results
        if any(field not in result for field in required_fields)
    }
    return {
        "evidence_status": "not_exercised" if not failed_results else "passed" if not missing_fields else "missing",
        "required_fields": list(required_fields),
        "validated_case_ids": sorted(result["case_id"] for result in failed_results),
        "missing_fields": dict(sorted(missing_fields.items())),
    }


def build_reference_validation_matrix(
    cases: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    *,
    evidence_coverage: dict[str, Any],
    visual_diagnostics: dict[str, Any],
    visual_evidence_scenarios: dict[str, Any],
    small_room_diagnostics: dict[str, Any],
    resilience_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    """将 Agora adapter 的真实验证映射为通用能力与场景证据。"""

    case_statuses = {
        result["case_id"]: result.get("status")
        for report in reports
        for result in report.get("case_results", [])
        if isinstance(result.get("case_id"), str)
    }
    catalog = {case["case_id"]: case for case in cases}

    def case_coverage(case_ids: tuple[str, ...]) -> dict[str, Any]:
        missing = sorted(case_id for case_id in case_ids if case_statuses.get(case_id) != "passed")
        return {
            "status": "passed" if not missing else "missing",
            "case_ids": list(case_ids),
            "missing_case_ids": missing,
        }

    capabilities = {
        name: case_coverage(case_ids)
        for name, case_ids in REFERENCE_CAPABILITY_CASES.items()
        if name != "log"
    }
    if evidence_coverage.get("status") != "passed":
        for name in ("callback", "metric"):
            capabilities[name]["status"] = "missing"
            capabilities[name]["evidence_gaps"] = evidence_coverage.get("missing", {})
    if not (small_room_diagnostics.get("small_room_proof_passed") and resilience_diagnostics.get("status") == "passed"):
        capabilities["device"]["status"] = "missing"
    expected_case_ids = sorted(case["case_id"] for case in expected_catalog_cases(cases))
    expected_case_id_set = set(expected_case_ids)
    report_case_ids = sorted(
        case_id for case_id in case_statuses if case_id in expected_case_id_set
    )
    ignored_report_case_ids = sorted(set(case_statuses) - expected_case_id_set)
    if report_case_ids != expected_case_ids:
        capabilities["report"]["status"] = "missing"
        capabilities["report"]["expected_case_ids"] = expected_case_ids
        capabilities["report"]["reported_case_ids"] = report_case_ids
    if ignored_report_case_ids:
        capabilities["report"]["ignored_report_case_ids"] = ignored_report_case_ids
    log_contract_coverage = build_failure_log_contract_coverage(reports)
    capabilities["log"] = {
        "status": "failure_report_contract",
        "case_ids": list(REFERENCE_CAPABILITY_CASES["log"]),
        **log_contract_coverage,
        "scope": "failed real SDK steps only",
    }

    permission = case_coverage(
        (
            "TC-MAC-AGORA-PERMISSION-DENIED-JOIN-FAILURE",
            "TC-MAC-AGORA-PERMISSION-DENIED-PREVIEW-FAILURE",
        )
    )
    callback_heavy = case_coverage(
        (
            "TC-MAC-AGORA-REAL-JOIN-CALLBACK",
            "TC-MAC-AGORA-JOIN-CALLBACK-TIMEOUT",
        )
    )
    if evidence_coverage.get("status") != "passed":
        callback_heavy["status"] = "missing"
        callback_heavy["evidence_gaps"] = evidence_coverage.get("missing", {})
    weak_network = catalog.get("TC-MAC-AGORA-WEAK-NETWORK-RECOVERY", {})
    # 画面场景的 status 直接取画面证据标准的场景 verdict，避免同一份报告里
    # 「场景段说 not_exercised、矩阵说 missing/failed」自相矛盾。
    one_to_one_scene = visual_evidence_scenarios.get("scenarios", {}).get(
        SCENARIO_ONE_TO_ONE_MEDIA_QUALITY, {}
    )
    one_to_one_status = str(one_to_one_scene.get("status", "missing"))
    small_room_scene = visual_evidence_scenarios.get("scenarios", {}).get(SCENARIO_SMALL_ROOM, {})
    scenarios = {
        "one_to_one_media_quality": {
            "status": one_to_one_status,
            "diagnostic_owner": "adapter_reference_validation",
            "case_ids": list(one_to_one_scene.get("case_ids", [])) or [VISUAL_CALL_CASE_ID],
            "missing_views": one_to_one_scene.get("missing_views", []),
            "fail_reasons": one_to_one_scene.get("fail_reasons", {}),
        },
        "small_room": {
            "status": "passed" if small_room_diagnostics.get("small_room_proof_passed") else "missing",
            "diagnostic_owner": "adapter_reference_validation",
            "case_ids": [SMALL_ROOM_CASE_ID],
            "picture_evidence_status": small_room_scene.get("status", "missing"),
            "picture_evidence_owner_layer": small_room_scene.get("owner_layer", ""),
        },
        "weak_network_recovery": {
            "status": weak_network.get("implementation_status", "missing"),
            "case_ids": ["TC-MAC-AGORA-WEAK-NETWORK-RECOVERY"],
            "blocked_category": weak_network.get("blocked_category", ""),
            "owner_layer": weak_network.get("owner_layer", ""),
        },
        "permission": permission,
        "callback_heavy": callback_heavy,
    }
    if one_to_one_status == VERDICT_NOT_EXERCISED:
        capabilities["artifact"]["status"] = VERDICT_NOT_EXERCISED
        capabilities["artifact"]["reason"] = one_to_one_scene.get("reason", "")
        capabilities["artifact"]["follow_up"] = one_to_one_scene.get("follow_up", "")
    elif one_to_one_status != VERDICT_PASSED:
        capabilities["artifact"]["status"] = "missing"
        capabilities["artifact"]["fail_reasons"] = one_to_one_scene.get("fail_reasons", {})
    required_statuses = [item.get("status") for name, item in capabilities.items() if name != "log"]
    required_statuses.extend(item.get("status") for name, item in scenarios.items() if name != "weak_network_recovery")
    return {
        "status": (
            "passed"
            if all(status in (VERDICT_PASSED, VERDICT_NOT_EXERCISED) for status in required_statuses)
            else "failed"
        ),
        "boundary": "adapter_reference_validation",
        "capabilities": capabilities,
        "scenarios": scenarios,
    }


def assert_required_evidence_coverage(reports: list[dict[str, Any]]) -> dict[str, Any]:
    coverage = build_evidence_coverage(reports)
    if coverage["missing"]:
        raise AssertionError(f"missing required evidence coverage: {coverage['missing']}")
    return coverage


def _failed_case_ids(items: list[dict[str, Any]]) -> list[str]:
    case_ids = {
        str(item["case_id"])
        for item in items
        if item.get("case_id") and item.get("status") is not None and item.get("status") != "passed"
    }
    return sorted(case_ids)


def _round_autorun_status(round_result: dict[str, Any]) -> str:
    autorun = round_result.get("autorun")
    if isinstance(autorun, dict) and autorun.get("status"):
        return str(autorun["status"])
    return str(round_result.get("status") or "passed")


def _round_failed_case_ids(round_result: dict[str, Any]) -> list[str]:
    failed_case_ids = round_result.get("failed_case_ids")
    if isinstance(failed_case_ids, list):
        return sorted(str(case_id) for case_id in failed_case_ids)
    autorun = round_result.get("autorun")
    if isinstance(autorun, dict):
        cases = autorun.get("cases", [])
        if isinstance(cases, list):
            return _failed_case_ids(cases)
    return []


def build_repeated_join_leave_resilience(
    round_results: list[dict[str, Any]], cleanup_runs: list[dict[str, Any]]
) -> dict[str, Any]:
    reports_verified = sum(int(item.get("reports_verified", 0)) for item in round_results)
    cleanup_by_round = {item.get("round"): item for item in cleanup_runs}
    per_round_results = []
    failed_rounds = []
    evidence_gaps = {}
    for item in round_results:
        round_index = item.get("round")
        cleanup = cleanup_by_round.get(round_index, {})
        autorun_status = _round_autorun_status(item)
        failed_case_ids = _round_failed_case_ids(item)
        cleanup_failed_case_ids = cleanup.get("failed_case_ids") or []
        round_evidence_gaps = item.get("evidence_gaps") or {}
        round_status = "passed"
        if (
            autorun_status != "passed"
            or failed_case_ids
            or cleanup.get("status") != "passed"
            or int(cleanup.get("case_count", 0)) <= 0
            or cleanup_failed_case_ids
            or round_evidence_gaps
        ):
            round_status = "failed"
            failed_rounds.append(round_index)
        if round_evidence_gaps:
            evidence_gaps[str(round_index)] = round_evidence_gaps
        per_round_results.append(
            {
                "round": round_index,
                "status": round_status,
                "autorun_status": autorun_status,
                "reports_verified": int(item.get("reports_verified", 0)),
                "failed_case_ids": failed_case_ids,
                "cleanup_run_id": cleanup.get("run_id"),
                "cleanup_status": cleanup.get("status"),
                "cleanup_failed_case_ids": sorted(str(case_id) for case_id in cleanup_failed_case_ids),
                "evidence_gaps": round_evidence_gaps,
            }
        )
    cleanup_passed = len(cleanup_runs) == len(round_results) and all(
        item.get("status") == "passed"
        and item.get("case_count", 0) > 0
        and not item.get("failed_case_ids")
        for item in cleanup_runs
    )
    return {
        "status": "passed" if round_results and cleanup_passed and not failed_rounds and not evidence_gaps else "failed",
        "rounds": len(round_results),
        "reports_verified": reports_verified,
        "cleanup_runs": cleanup_runs,
        "round_results": per_round_results,
        "failed_rounds": failed_rounds,
        "evidence_gaps": evidence_gaps,
    }


VISUAL_CALL_VIEWS = (
    {
        "view_role": PRIMARY_LOCAL_VIEW_ID,
        "node_id": PRIMARY_NODE_ID,
        "node_role": "primary",
        "uid": VISUAL_CALL_PRIMARY_UID,
        "kind": "local",
        "sdk": "agora_rtc",
    },
    {
        "view_role": PRIMARY_REMOTE_VIEW_ID,
        "node_id": PRIMARY_NODE_ID,
        "node_role": "primary",
        "uid": VISUAL_CALL_PEER_UID,
        "kind": "remote",
        "sdk": "agora_rtc",
    },
    {
        "view_role": PEER_LOCAL_VIEW_ID,
        "node_id": PEER_NODE_ID,
        "node_role": "peer",
        "uid": VISUAL_CALL_PEER_UID,
        "kind": "local",
        "sdk": "agora_rtc",
    },
    {
        "view_role": PEER_REMOTE_VIEW_ID,
        "node_id": PEER_NODE_ID,
        "node_role": "peer",
        "uid": VISUAL_CALL_PRIMARY_UID,
        "kind": "remote",
        "sdk": "agora_rtc",
    },
)
ONE_TO_ONE_VISUAL_CASES = (VISUAL_CALL_CASE_ID, SYNTH_PEER_CASE_ID)


def build_one_to_one_visual_evidence(
    reports: list[dict[str, Any]], *, case_ids: tuple[str, ...] = ONE_TO_ONE_VISUAL_CASES
) -> dict[str, Any]:
    """1V1 画面场景声明：四个必需视图；真相机与合成源变体共享同一份场景证据。"""
    return build_scenario_visual_evidence(
        scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
        case_ids=case_ids,
        views=VISUAL_CALL_VIEWS,
        reports=reports,
    )


def build_visual_evidence_scenarios(
    reports: list[dict[str, Any]], selected_case_ids: set[str]
) -> dict[str, Any]:
    """按标准汇总本 run 的场景画面证据：未选择的场景显式登记 not_exercised，不伪称已覆盖。"""
    one_to_one_cases = tuple(
        sorted(selected_case_ids & set(ONE_TO_ONE_VISUAL_CASES))
    )
    if one_to_one_cases:
        one_to_one = build_one_to_one_visual_evidence(reports, case_ids=one_to_one_cases)
    else:
        one_to_one = build_not_exercised_scenario(
            scenario_id=SCENARIO_ONE_TO_ONE_MEDIA_QUALITY,
            owner_layer="adapter_reference_validation",
            reason="本次运行未选择 1V1 画面用例（BEACON_MAC_CONSOLE_AGORA_CASE_IDS 子集运行）。",
            follow_up="按子集 gate 运行 1V1 画面用例后转为硬门判定。",
        )
    small_room_cases = tuple(sorted(selected_case_ids & {SMALL_ROOM_CASE_ID}))
    assert_scenario_has_no_picture_evidence(
        scenario_id=SCENARIO_SMALL_ROOM, reports=reports, case_ids=small_room_cases
    )
    small_room = build_not_exercised_scenario(
        scenario_id=SCENARIO_SMALL_ROOM,
        case_ids=small_room_cases,
        owner_layer="adapter_reference_validation",
        reason="Small Room 场景当前只有音频 proof（small_room_proof_passed 判 tx/rx_audio_kbitrate），没有画面能力面与画面用例。",
        follow_up="B-003 选定 Small Room 高阶 runnable case 后声明必需视图并转为硬门。",
    )
    return summarize_visual_evidence(
        {item["scenario_id"]: item for item in (one_to_one, small_room)}
    )


def build_visual_call_diagnostics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    primary_remote_view_bound = False
    peer_remote_view_bound = False
    primary_first_remote_video_frame_observed = False
    peer_first_remote_video_frame_observed = False
    primary_local_video_send_observed = False
    peer_local_video_send_observed = False
    primary_to_peer_remote_video_receive_observed = False
    peer_to_primary_remote_video_receive_observed = False
    primary_remote_video_stats_observed = False
    peer_remote_video_stats_observed = False
    primary_rtc_video_receive_observed = False
    peer_rtc_video_receive_observed = False
    view_capture_artifacts: dict[str, str] = {}
    sdk_snapshot_artifacts: dict[str, str] = {}
    snapshot_callbacks: dict[str, dict[str, Any]] = {}
    snapshot_request_artifacts: dict[str, str] = {}
    snapshot_requests: list[dict[str, Any]] = []
    for report in reports:
        for result in report.get("case_results", []):
            if result.get("case_id") != VISUAL_CALL_CASE_ID:
                continue
            for item in result.get("observations", []):
                function = item.get("target", {}).get("function")
                payload = item.get("payload", {})
                node_id = item.get("node_id")
                if function in REMOTE_VIDEO_BIND_FUNCTIONS and node_id == PRIMARY_NODE_ID:
                    primary_remote_view_bound = (
                        payload.get("configured") is True
                        and payload.get("view_id") == PRIMARY_REMOTE_VIEW_ID
                        and payload.get("uid") == VISUAL_CALL_PEER_UID
                    )
                if function in REMOTE_VIDEO_BIND_FUNCTIONS and node_id == PEER_NODE_ID:
                    peer_remote_view_bound = (
                        payload.get("configured") is True
                        and payload.get("view_id") == PEER_REMOTE_VIEW_ID
                        and payload.get("uid") == VISUAL_CALL_PRIMARY_UID
                    )
                if function == "onFirstRemoteVideoFrame" and node_id == PRIMARY_NODE_ID:
                    primary_first_remote_video_frame_observed = payload.get("uid") == VISUAL_CALL_PEER_UID
                if function == "onFirstRemoteVideoFrame" and node_id == PEER_NODE_ID:
                    peer_first_remote_video_frame_observed = payload.get("uid") == VISUAL_CALL_PRIMARY_UID
                if function == "onRemoteVideoStats" and node_id == PRIMARY_NODE_ID:
                    primary_remote_video_stats_observed = payload.get("uid") == VISUAL_CALL_PEER_UID
                    if (
                        primary_remote_video_stats_observed
                        and payload.get("received_bitrate", 0) > 0
                        and (
                            payload.get("decoder_output_frame_rate", 0) > 0
                            or payload.get("renderer_output_frame_rate", 0) > 0
                        )
                    ):
                        peer_to_primary_remote_video_receive_observed = True
                if function == "onRemoteVideoStats" and node_id == PEER_NODE_ID:
                    peer_remote_video_stats_observed = payload.get("uid") == VISUAL_CALL_PRIMARY_UID
                    if (
                        peer_remote_video_stats_observed
                        and payload.get("received_bitrate", 0) > 0
                        and (
                            payload.get("decoder_output_frame_rate", 0) > 0
                            or payload.get("renderer_output_frame_rate", 0) > 0
                        )
                    ):
                        primary_to_peer_remote_video_receive_observed = True
                if function == "onLocalVideoStats" and node_id == PRIMARY_NODE_ID:
                    primary_local_video_send_observed = (
                        payload.get("uid") == VISUAL_CALL_PRIMARY_UID
                        and payload.get("sent_bitrate", 0) > 0
                        and payload.get("sent_frame_rate", 0) > 0
                    )
                if function == "onLocalVideoStats" and node_id == PEER_NODE_ID:
                    peer_local_video_send_observed = (
                        payload.get("uid") == VISUAL_CALL_PEER_UID
                        and payload.get("sent_bitrate", 0) > 0
                        and payload.get("sent_frame_rate", 0) > 0
                    )
                if function == "onRtcStats" and node_id == PRIMARY_NODE_ID:
                    if payload.get("tx_video_kbitrate", 0) > 0:
                        primary_local_video_send_observed = True
                    primary_rtc_video_receive_observed = (
                        primary_rtc_video_receive_observed or payload.get("rx_video_kbitrate", 0) > 0
                    )
                    if primary_first_remote_video_frame_observed and primary_rtc_video_receive_observed:
                        peer_to_primary_remote_video_receive_observed = True
                if function == "onRtcStats" and node_id == PEER_NODE_ID:
                    if payload.get("tx_video_kbitrate", 0) > 0:
                        peer_local_video_send_observed = True
                    peer_rtc_video_receive_observed = (
                        peer_rtc_video_receive_observed or payload.get("rx_video_kbitrate", 0) > 0
                    )
                    if peer_first_remote_video_frame_observed and peer_rtc_video_receive_observed:
                        primary_to_peer_remote_video_receive_observed = True
                if node_id == PRIMARY_NODE_ID and isinstance(payload.get("visual_artifacts"), dict):
                    for key in VISUAL_ARTIFACT_KEYS:
                        if payload["visual_artifacts"].get(key):
                            view_capture_artifacts[key] = str(payload["visual_artifacts"][key])
                if function == "onSnapshotRequested" and node_id in {PRIMARY_NODE_ID, PEER_NODE_ID}:
                    snapshot_requests.append(payload)
                    key = payload.get("view_role") or payload.get("artifact_key")
                    expected_node = VISUAL_ARTIFACT_EXPECTED_NODE.get(str(key))
                    if (
                        key in VISUAL_ARTIFACT_KEYS
                        and node_id == expected_node
                        and payload.get("return_code") == 0
                        and payload.get("file_path")
                        and Path(str(payload["file_path"])).exists()
                    ):
                        snapshot_request_artifacts[str(key)] = str(payload["file_path"])
                        sdk_snapshot_artifacts.setdefault(str(key), str(payload["file_path"]))
                if function == "onSnapshotTaken" and node_id in {PRIMARY_NODE_ID, PEER_NODE_ID}:
                    key = payload.get("view_role") or payload.get("artifact_key")
                    expected_node = VISUAL_ARTIFACT_EXPECTED_NODE.get(str(key))
                    if key in VISUAL_ARTIFACT_KEYS and node_id == expected_node:
                        snapshot_callbacks[str(key)] = payload
                        if payload.get("err_code") == 0 and payload.get("file_path"):
                            sdk_snapshot_artifacts[str(key)] = str(payload["file_path"])
    peer_to_primary_remote_video_receive_observed = (
        peer_to_primary_remote_video_receive_observed
        or (primary_first_remote_video_frame_observed and primary_rtc_video_receive_observed)
    )
    primary_to_peer_remote_video_receive_observed = (
        primary_to_peer_remote_video_receive_observed
        or (peer_first_remote_video_frame_observed and peer_rtc_video_receive_observed)
    )
    primary_remote_view_bound = primary_remote_view_bound or (
        bool(snapshot_request_artifacts.get(PRIMARY_REMOTE_VIEW_ID))
        or bool(snapshot_callbacks.get(PRIMARY_REMOTE_VIEW_ID))
    )
    peer_remote_view_bound = peer_remote_view_bound or (
        bool(snapshot_request_artifacts.get(PEER_REMOTE_VIEW_ID))
        or bool(snapshot_callbacks.get(PEER_REMOTE_VIEW_ID))
    )
    diagnostics = {
        "primary_node_id": PRIMARY_NODE_ID,
        "peer_node_id": PEER_NODE_ID,
        "primary_uid": VISUAL_CALL_PRIMARY_UID,
        "peer_uid": VISUAL_CALL_PEER_UID,
        "primary_remote_view_id": PRIMARY_REMOTE_VIEW_ID,
        "peer_remote_view_id": PEER_REMOTE_VIEW_ID,
        "view_capture_artifacts": view_capture_artifacts,
        "sdk_snapshot_artifacts": sdk_snapshot_artifacts,
        "snapshot_callbacks": snapshot_callbacks,
        "snapshot_request_artifacts": snapshot_request_artifacts,
        "snapshot_requests": snapshot_requests,
        "primary_local_video_send_observed": primary_local_video_send_observed,
        "peer_local_video_send_observed": peer_local_video_send_observed,
        "primary_to_peer_remote_video_receive_observed": primary_to_peer_remote_video_receive_observed,
        "peer_to_primary_remote_video_receive_observed": peer_to_primary_remote_video_receive_observed,
        "primary_remote_view_bound": primary_remote_view_bound,
        "peer_remote_view_bound": peer_remote_view_bound,
        "primary_first_remote_video_frame_observed": primary_first_remote_video_frame_observed,
        "peer_first_remote_video_frame_observed": peer_first_remote_video_frame_observed,
        "primary_remote_video_stats_observed": primary_remote_video_stats_observed,
        "peer_remote_video_stats_observed": peer_remote_video_stats_observed,
        "primary_rtc_video_receive_observed": primary_rtc_video_receive_observed,
        "peer_rtc_video_receive_observed": peer_rtc_video_receive_observed,
    }
    pixel_diagnostics = {
        key: build_png_pixel_diagnostics(str(diagnostics["sdk_snapshot_artifacts"].get(key, "")))
        for key in VISUAL_ARTIFACT_KEYS
    }
    scenario = build_one_to_one_visual_evidence(reports)
    return {
        **diagnostics,
        "pixel_diagnostics": pixel_diagnostics,
        # 通过与否由画面证据标准统一判定，本地布尔量只作为诊断细节。
        "artifact_proof_passed": scenario["status"] == VERDICT_PASSED,
        "missing_views": scenario["missing_views"],
        "fail_reasons": scenario["fail_reasons"],
    }


def build_failed_case_evidence_summary(case: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    case_id = case.get("case_id")
    failure: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = []
    bind_remote_video_observed = False
    first_remote_video_frame_observed = False
    remote_video_stats_observed = False
    rtc_video_receive_observed = False
    for result in report.get("case_results", []):
        if result.get("case_id") != case_id:
            continue
        if result.get("status") != "passed" and failure is None:
            failure = {
                "case_id": result.get("case_id"),
                "step_id": result.get("step_id"),
                "status": result.get("status"),
                "error": result.get("error"),
            }
        for item in result.get("observations", []):
            function = item.get("target", {}).get("function")
            payload = item.get("payload", {})
            evidence.append(
                {
                    "node_id": item.get("node_id"),
                    "function": function,
                    "payload": payload,
                }
            )
            if function in REMOTE_VIDEO_BIND_FUNCTIONS:
                bind_remote_video_observed = True
            if function == "onFirstRemoteVideoFrame":
                first_remote_video_frame_observed = True
            if function == "onRemoteVideoStats":
                remote_video_stats_observed = True
            if function == "onRtcStats" and payload.get("rx_video_kbitrate", 0) > 0:
                rtc_video_receive_observed = True
    summary = {
        "case_id": case_id,
        "run_id": case.get("run_id"),
        "failure": failure,
        "evidence": evidence,
        "bind_remote_video_observed": bind_remote_video_observed,
        "first_remote_video_frame_observed": first_remote_video_frame_observed,
        "remote_video_stats_observed": remote_video_stats_observed,
        "rtc_video_receive_observed": rtc_video_receive_observed,
    }
    # 画面类失败必须把具名原因一起落盘，事后定位不依赖重跑。
    if str(case_id) in ONE_TO_ONE_VISUAL_CASES:
        summary["visual_evidence"] = build_one_to_one_visual_evidence(
            [report], case_ids=(str(case_id),)
        )
    return summary


def write_failed_case_artifacts(case: dict[str, Any], report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_CASE_REPORT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = build_failed_case_evidence_summary(case, report)
    FAILED_CASE_EVIDENCE_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_cleanup_run_summary(round_index: int, cleanup: dict[str, Any]) -> dict[str, Any]:
    cases = cleanup.get("cases")
    if not isinstance(cases, list):
        cases = cleanup.get("case_results", [])
    return {
        "round": round_index,
        "status": cleanup.get("status"),
        "run_id": cleanup.get("run_id"),
        "case_count": len(cases),
        "failed_case_ids": _failed_case_ids(cases),
    }


def load_agora_cases() -> list[dict[str, Any]]:
    from scripts.support.native_case_catalog import load_cases

    return load_cases(CASE_PREFIX)


def expected_autorun_cases(cases: list[dict[str, Any]]) -> set[str]:
    runnable_cases = {
        case["case_id"]
        for case in cases
        if case["case_id"].startswith(CASE_PREFIX) and case.get("implementation_status") == "runnable"
    }
    configured = {
        item.strip()
        for item in os.environ.get(CASE_IDS_ENV, "").split(",")
        if item.strip()
    }
    if not configured:
        return runnable_cases
    unknown_cases = configured - {case["case_id"] for case in cases}
    if unknown_cases:
        raise ValueError(f"{CASE_IDS_ENV} contains unknown case ids: {sorted(unknown_cases)}")
    non_runnable_cases = configured - runnable_cases
    if non_runnable_cases:
        raise ValueError(f"{CASE_IDS_ENV} contains non-runnable case ids: {sorted(non_runnable_cases)}")
    return configured


EXPECTED_CASES = expected_autorun_cases(load_agora_cases())


def expected_catalog_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [case for case in cases if case["case_id"] in EXPECTED_CASES]


def agent_node_id_for_role(role: str) -> str:
    known_node_ids = {
        "primary": PRIMARY_NODE_ID,
        "peer": PEER_NODE_ID,
        "peer_b": PEER_B_NODE_ID,
    }
    if role in known_node_ids:
        return known_node_ids[role]
    return f"mac-real-{role.replace('_', '-')}-e2e-001"


def agent_tags_for_role(role: str) -> list[str]:
    return ["real-e2e", f"real-{role.replace('_', '-')}", f"role:{role}"]


def required_agent_roles(cases: list[dict[str, Any]]) -> list[str]:
    return sorted({str(role) for case in expected_catalog_cases(cases) for role in case.get("devices", [])})


def autorun_round_count() -> int:
    raw = os.environ.get(AUTORUN_ROUNDS_ENV)
    if raw is None:
        return AUTORUN_ROUNDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{AUTORUN_ROUNDS_ENV} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{AUTORUN_ROUNDS_ENV} must be a positive integer")
    return value


def case_token_requests(cases: list[dict[str, Any]]) -> set[tuple[str, int]]:
    server_path = str(ROOT / "server")
    if server_path not in sys.path:
        sys.path.insert(0, server_path)
    from app.sdk.sdk_extensions import AGORA_RTC_TOKEN_PLACEHOLDER

    requests: set[tuple[str, int]] = set()
    token_case_ids = EXPECTED_CASES | {AUTORUN_CLEANUP_CASE_ID}
    for case in cases:
        if case["case_id"] not in token_case_ids:
            continue
        for channel, uid in case.get("token_bindings", []):
            if isinstance(channel, str) and isinstance(uid, int):
                requests.add((channel, uid))
    return requests


def build_rtc_token(channel: str, uid: int = 1001) -> str:
    expire_at = int(time.time()) + 3600
    return subprocess.check_output(
        [
            "uv",
            "run",
            "--python",
            "3.11",
            "--extra",
            "agora",
            "python",
            "-c",
            (
                "from agora_token_builder import RtcTokenBuilder;"
                "import os,sys;"
                "sys.stdout.write(RtcTokenBuilder.buildTokenWithUid("
                f"os.environ['AGORA_APP_ID'], os.environ['AGORA_APP_CERT'], {channel!r}, {uid}, 1, {expire_at}))"
            ),
        ],
        cwd=ROOT / "server",
        text=True,
    )


def configure_case_token_map() -> dict[str, str]:
    server_path = str(ROOT / "server")
    if server_path not in sys.path:
        sys.path.insert(0, server_path)
    from app.sdk.sdk_extensions import TOKEN_MAP_ENV, token_map_key

    token_requests = sorted(case_token_requests(load_agora_cases()))
    token_map = {token_map_key(channel, uid): build_rtc_token(channel, uid) for channel, uid in token_requests}
    if token_map:
        os.environ[TOKEN_MAP_ENV] = json.dumps(token_map, separators=(",", ":"), sort_keys=True)
    else:
        os.environ.pop(TOKEN_MAP_ENV, None)
    return token_map


def agent_ws_url(ws_url: str, token: str) -> str:
    return f"{ws_url}/api/v1/agent/ws?{urlencode({'token': token})}"


async def start_real_agent(
    base_url: str,
    ws_url: str,
    *,
    node_id: str,
    tags: list[str],
    group_id: str = REAL_E2E_GROUP_ID,
):
    process = await start_native_websocket_agent(
        ws_url,
        node_id=node_id,
        tags=tags,
        group_id=group_id,
    )
    try:
        await wait_for_registered_device(base_url, process, node_id)
    except Exception:
        await stop_native_websocket_agent(process)
        raise
    return process


def launch_console_app(base_url: str) -> subprocess.Popen:
    server_path = str(ROOT / "server")
    if server_path not in sys.path:
        sys.path.insert(0, server_path)
    from app.sdk.sdk_extensions import TOKEN_MAP_ENV

    subprocess.check_call(["swift", "build", "--package-path", "apps/mac_test_console"], cwd=ROOT)
    executable = ROOT / "apps/mac_test_console/.build/debug/BeaconMacTestConsole"
    AUTORUN_REPORT.unlink(missing_ok=True)
    env = os.environ.copy()
    if TOKEN_MAP_ENV not in env:
        configure_case_token_map()
        env = os.environ.copy()
    env.update(
        {
            "BEACON_CONSOLE_SERVER_URL": base_url,
            "BEACON_AUTH_TOKEN": os.environ["BEACON_AUTH_TOKEN"],
            "BEACON_NODE_ID": PRIMARY_NODE_ID,
            "BEACON_PEER_NODE_ID": PEER_NODE_ID,
            "BEACON_CONSOLE_AUTORUN_PREFIX": CASE_PREFIX,
            "BEACON_CONSOLE_AUTORUN_CASE_IDS": ",".join(sorted(EXPECTED_CASES)),
            "BEACON_CONSOLE_AUTORUN_OUTPUT": str(AUTORUN_REPORT),
        }
    )
    return subprocess.Popen(
        [str(executable)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


async def wait_autorun_report(
    process: subprocess.Popen,
    timeout_seconds: int = AUTORUN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    return await wait_for_autorun_report(process, AUTORUN_REPORT, timeout_seconds)


async def stop_console_app(process: subprocess.Popen) -> None:
    await stop_console_process(process)


async def verify_server_reports(base_url: str, autorun: dict[str, Any]) -> list[dict[str, Any]]:
    import httpx

    if autorun.get("status") == "failed" and autorun.get("error"):
        raise AssertionError(str(autorun["error"]))
    cases = autorun.get("cases", [])
    case_ids = {case["case_id"] for case in cases}
    if case_ids != EXPECTED_CASES:
        raise AssertionError(f"unexpected autorun cases: {sorted(case_ids)}")

    reports = []
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        for case in cases:
            response = await client.get(
                f"{base_url}/api/v1/test-runs/{case['run_id']}/report",
                headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
            )
            response.raise_for_status()
            body = response.json()
            reports.append(body)
            if case["status"] != "passed":
                write_failed_case_artifacts(case, body)
                failures = [
                    {
                        "case_id": result["case_id"],
                        "step_id": result.get("step_id"),
                        "status": result["status"],
                        "failure_classification": result.get("failure_classification"),
                        "message": result.get("message"),
                    }
                    for result in body["case_results"]
                    if result["status"] != "passed"
                ]
                raise AssertionError(f"autorun case failed: {case['case_id']} {failures}")
            if case["case_id"] == "TC-MAC-AGORA-REMOTE-AUDIO-STATS-OBSERVABLE":
                functions = {
                    item["target"]["function"]
                    for result in body["case_results"]
                    for item in result.get("observations", [])
                }
                assert "onRemoteAudioStats" in functions
            if case["case_id"] == "TC-MAC-AGORA-REMOTE-VIDEO-STATS-OBSERVABLE":
                functions = {
                    item["target"]["function"]
                    for result in body["case_results"]
                    for item in result.get("observations", [])
                }
                assert "onRemoteVideoStats" in functions
            if case["case_id"] == SMALL_ROOM_CASE_ID:
                diagnostics = build_small_room_diagnostics([body])
                if not diagnostics["small_room_proof_passed"]:
                    write_failed_case_artifacts(case, body)
                    raise AssertionError(f"small room proof failed: {diagnostics}")
            if case["case_id"] == AUDIO_PLAYBACK_MUTE_RECOVER_CASE_ID:
                diagnostics = build_audible_audio_diagnostics([body])
                if not diagnostics["audible_stream_proof_passed"]:
                    write_failed_case_artifacts(case, body)
                    raise AssertionError(f"audible audio stream proof failed: {diagnostics}")
            if case["case_id"] == SIMULCAST_LAYER_TOGGLE_CASE_ID:
                diagnostics = build_simulcast_layer_diagnostics([body])
                if not diagnostics["simulcast_layer_proof_passed"]:
                    write_failed_case_artifacts(case, body)
                    raise AssertionError(f"simulcast layer proof failed: {diagnostics}")
            if case["case_id"] in {"TC-MAC-AGORA-REAL-JOIN-CALLBACK", "TC-MAC-AGORA-REAL-JOIN-LEAVE-STATE"}:
                evidence = [
                    item
                    for result in body["case_results"]
                    for item in result.get("observations", [])
                    if item["kind"] == "event" and item["target"]["function"] == "onJoinChannelSuccess"
                ]
                if not evidence:
                    raise AssertionError(f"missing join callback evidence for {case['case_id']}")
                channels = {item["payload"]["channel"] for item in evidence}
                if not channels & {"real-smoke", "real-smoke-state"}:
                    raise AssertionError(f"unexpected callback channels for {case['case_id']}: {channels}")
    # 画面场景按标准判定：同一场景的多个 case（真相机 / 合成源变体）共享一份场景证据，
    # 因此断言的是全部已执行 1V1 用例的并集，而不是逐个 case 各自成立一套通过条件。
    one_to_one_cases = tuple(sorted(EXPECTED_CASES & set(ONE_TO_ONE_VISUAL_CASES)))
    if one_to_one_cases:
        scenario = build_one_to_one_visual_evidence(reports, case_ids=one_to_one_cases)
        if scenario["status"] != VERDICT_PASSED:
            write_failed_case_artifacts(
                {"case_id": one_to_one_cases[0], "run_id": None},
                {
                    "case_results": [
                        result
                        for report in reports
                        for result in report.get("case_results", [])
                        if str(result.get("case_id")) in set(one_to_one_cases)
                    ]
                },
            )
            raise AssertionError(
                f"1v1 visual evidence standard failed: missing_views={scenario['missing_views']} "
                f"fail_reasons={scenario['fail_reasons']}"
            )
    assert_required_evidence_coverage(reports)
    return reports


def autorun_cleanup_case(platform: str = "mac") -> dict[str, Any]:
    return {
        "case_id": AUTORUN_CLEANUP_CASE_ID,
        "platform": platform,
    }


async def run_cleanup_round(base_url: str, *, round_index: int | None = None) -> dict[str, Any]:
    import httpx
    from scripts.support.native_run_client import wait_run

    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        response = await client.post(
            f"{base_url}/api/v1/test-runs",
            headers={"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"},
            json={
                "selector": {"node_id": PRIMARY_NODE_ID},
                "case_ids": [autorun_cleanup_case()["case_id"]],
            },
        )
        response.raise_for_status()
        body = await wait_run(client, base_url, response.json()["run_id"], {"Authorization": f"Bearer {os.environ['BEACON_AUTH_TOKEN']}"})
    if body.get("status") != "passed":
        phase = f"round {round_index} cleanup" if round_index is not None else "cleanup"
        raise AssertionError(f"{phase} run failed: {body}")
    return body


async def run_autorun_round(base_url: str, round_index: int) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    return await run_shared_autorun_round(
        base_url=base_url,
        round_index=round_index,
        run_cleanup=lambda url, index: run_cleanup_round(url, round_index=index),
        launch_console=launch_console_app,
        wait_autorun=wait_autorun_report,
        verify_reports=verify_server_reports,
        stop_console=stop_console_app,
    )


async def run_real_validation() -> dict[str, Any]:
    import uvicorn

    sys.path.insert(0, str(ROOT / "server"))
    from app.main import app

    os.environ.setdefault("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    configure_rtc_token()
    configure_case_token_map()
    run(["cmake", "-S", ".", "-B", ".build/default"])
    run(["cmake", "--build", ".build/default", "--target", "mac_real_adapter_test", "mac_real_agent_bridge"])
    run(["ctest", "--test-dir", ".build/default", "-R", "BRIDGE-MAC-REAL|IT-AGORA|FI-RTC", "--output-on-failure"])

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    import app.main as server_main
    server_main.runner_supervisor._process._base_url = base_url
    ws_url = f"ws://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    agents: list[Any] = []
    try:
        await wait_http(base_url)
        all_cases = load_agora_cases()
        for role in required_agent_roles(all_cases):
            agents.append(await start_real_agent(
                base_url,
                ws_url,
                node_id=agent_node_id_for_role(role),
                tags=agent_tags_for_role(role),
            ))
        all_reports = []
        round_results = []
        cleanup_runs = []
        autorun_rounds = autorun_round_count()
        for round_index in range(1, autorun_rounds + 1):
            autorun, reports, cleanup = await run_autorun_round(base_url, round_index)
            all_reports.extend(reports)
            evidence_coverage = build_evidence_coverage(reports)
            cleanup_runs.append(build_cleanup_run_summary(round_index, cleanup))
            round_results.append(
                {
                    "round": round_index,
                    "status": autorun.get("status"),
                    "autorun": autorun,
                    "reports_verified": len(reports),
                    "failed_case_ids": _failed_case_ids(autorun.get("cases", [])),
                    "evidence_gaps": evidence_coverage["missing"],
                }
            )
        cases = expected_catalog_cases(all_cases)
        catalog_coverage = build_catalog_coverage(cases, all_reports)
        evidence_coverage = build_evidence_coverage(all_reports)
        small_room_diagnostics = build_small_room_diagnostics(all_reports)
        audible_audio_diagnostics = build_audible_audio_diagnostics(all_reports)
        simulcast_layer_diagnostics = build_simulcast_layer_diagnostics(all_reports)
        visual_call_diagnostics = build_visual_call_diagnostics(all_reports)
        resilience_diagnostics = build_repeated_join_leave_resilience(round_results, cleanup_runs)
        visual_evidence_scenarios = build_visual_evidence_scenarios(all_reports, EXPECTED_CASES)
        reference_validation_matrix = build_reference_validation_matrix(
            all_cases,
            all_reports,
            evidence_coverage=evidence_coverage,
            visual_diagnostics=visual_call_diagnostics,
            visual_evidence_scenarios=visual_evidence_scenarios,
            small_room_diagnostics=small_room_diagnostics,
            resilience_diagnostics=resilience_diagnostics,
        )
        return {
            "server_url": base_url,
            "autorun_rounds": round_results,
            "autorun": round_results[-1]["autorun"],
            "reports_verified": sum(int(item["reports_verified"]) for item in round_results),
            "repeated_join_leave_resilience": resilience_diagnostics,
            "dual_node_diagnostics": {
                "primary_node_id": PRIMARY_NODE_ID,
                "peer_node_id": PEER_NODE_ID,
                "autorun_rounds": autorun_rounds,
                "cleanup_runs": cleanup_runs,
                "peer_isolation": build_peer_isolation_diagnostics(all_reports),
            },
            "small_room_diagnostics": small_room_diagnostics,
            "audible_audio_diagnostics": audible_audio_diagnostics,
            "simulcast_layer_diagnostics": simulcast_layer_diagnostics,
            "visual_call_diagnostics": visual_call_diagnostics,
            "visual_evidence": visual_evidence_scenarios,
            "evidence_coverage": evidence_coverage,
            "generic_reference_matrix": reference_validation_matrix,
            **catalog_coverage,
            **build_gate_report(cases, all_reports),
        }
    finally:
        for process in reversed(agents):
            if process:
                await stop_native_websocket_agent(process)
        server.should_exit = True
        thread.join(timeout=5)


def main() -> int:
    missing = missing_real_env()
    if missing:
        message = "missing real mac sdk environment: " + ",".join(missing)
        write_report("skipped", message)
        print(message)
        return 0
    if not agora_framework_exists():
        message = "missing AgoraRtcKit.framework under AGORA_MAC_SDK_ROOT"
        write_report("skipped", message)
        print(message)
        return 0
    try:
        result = asyncio.run(run_real_validation())
    except Exception as exc:  # noqa: BLE001
        message = f"mac console agora validation failed: {exc}"
        write_report("failed", message)
        print(message, file=sys.stderr)
        return 1
    write_report("passed", "mac console app-driven agora validation passed", result)
    print("mac console app-driven agora validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
