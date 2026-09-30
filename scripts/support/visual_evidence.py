#!/usr/bin/env python3
"""画面证据标准（B-009）：一场景一份画面证据的统一判定入口。

本模块是画面证据判定的唯一实现。输入是任意 run report 的 evidence 流与 artifact 文件路径，
模块本身不感知 Agora 或火山命名；「场景 → 必需视图」与「视图 → 节点归属、uid」由调用方以
声明形式传入，因此第二家 SDK 接入时只做声明，不复制判定逻辑。

开发者证据边界见 `docs/development.md`。
本模块判定层级固定为 L1：快照存在 / 落盘契约 /
尺寸 / 内容区非空 + 绑定证据 + 端到端收发活性统计；不做画面内容归属断言。
"""

from __future__ import annotations

import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any, Callable

VERDICT_PASSED = "passed"
VERDICT_MISSING = "missing"
VERDICT_NOT_EXERCISED = "not_exercised"

SCENARIO_ONE_TO_ONE_MEDIA_QUALITY = "one_to_one_media_quality"
SCENARIO_SMALL_ROOM = "small_room"

# 标准的画面场景清单：每个 gate 都按同一份清单声明自己的已覆盖 / not_exercised 状态。
STANDARD_SCENARIOS = (SCENARIO_ONE_TO_ONE_MEDIA_QUALITY, SCENARIO_SMALL_ROOM)

# 判定内容区时忽略的四周边缘比例：真实视频窗口边缘常为边框与黑边，不参与「有画面」判定。
PIXEL_EDGE_EXCLUDE_RATIO = 0.25

REMOTE_VIDEO_BIND_FUNCTIONS = frozenset({"bindRemoteVideo"})

# 一旦某个 SDK/场景的用例开始产出这些证据，说明画面能力面已经落地，不能继续登记为未覆盖。
PICTURE_EVIDENCE_FUNCTIONS = frozenset(
    {
        "onSnapshotRequested",
        "onSnapshotTaken",
        "onFirstRemoteVideoFrame",
        "onRemoteVideoStats",
        "onLocalVideoStats",
        "bindRemoteVideo",
    }
)

# 具名失败原因码：报告只给一个布尔值时读者无法判断是哪一层没通过，原因码是标准的一部分。
REASON_SNAPSHOT_REQUEST_MISSING = "snapshot_request_missing"
REASON_SNAPSHOT_REQUEST_FAILED = "snapshot_request_failed"
REASON_SNAPSHOT_CALLBACK_MISSING = "snapshot_callback_missing"
REASON_SNAPSHOT_ERROR = "snapshot_error"
REASON_SNAPSHOT_PATH_MISMATCH = "snapshot_path_mismatch"
REASON_ARTIFACT_FILE_MISSING = "artifact_file_missing"
REASON_ARTIFACT_UNDECODABLE = "artifact_undecodable"
REASON_ARTIFACT_ZERO_DIMENSION = "artifact_zero_dimension"
REASON_ARTIFACT_EMPTY_CONTENT = "artifact_empty_content"
REASON_REMOTE_VIEW_NOT_BOUND = "remote_view_not_bound"
REASON_FIRST_REMOTE_VIDEO_FRAME_MISSING = "first_remote_video_frame_missing"
REASON_LOCAL_VIDEO_SEND_MISSING = "local_video_send_missing"
REASON_REMOTE_VIDEO_RECEIVE_MISSING = "remote_video_receive_missing"
REASON_RTC_VIDEO_RECEIVE_MISSING = "rtc_video_receive_missing"
REASON_FOREIGN_NODE_EVIDENCE = "foreign_node_evidence"
REASON_SOURCE_TYPE_MISSING = "source_type_missing"
REASON_SOURCE_TYPE_MISMATCH = "source_type_mismatch"

SOURCE_TYPE_CAMERA = 0
SOURCE_TYPE_SYNTHETIC = 4


def _function(item: dict[str, Any]) -> str:
    return str(item.get("target", {}).get("function") or "")


def _payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload")
    return payload if isinstance(payload, dict) else {}


def _view_key(payload: dict[str, Any]) -> str:
    return str(payload.get("view_role") or payload.get("artifact_key") or "")


def _missing_pixel_facts(path: str, error: str | None = None) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "path": path,
        "exists": False,
        "bytes": 0,
        "width": 0,
        "height": 0,
        "total_pixels": 0,
        "non_empty_pixels": 0,
        "non_empty": False,
    }
    if error:
        facts["error"] = error
    return facts


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a png file")
    chunks = []
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        chunks.append((kind, data[start:end]))
        offset = end + 4
        if kind == b"IEND":
            break
    return chunks


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    distances = (abs(p - a), abs(p - b), abs(p - c))
    if distances[0] <= distances[1] and distances[0] <= distances[2]:
        return a
    if distances[1] <= distances[2]:
        return b
    return c


def _decode_png_rgba(data: bytes) -> tuple[int, int, bytes]:
    chunks = _png_chunks(data)
    ihdr = next(payload for kind, payload in chunks if kind == b"IHDR")
    width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    if bit_depth != 8 or compression != 0 or filter_method != 0 or interlace != 0 or color_type not in {2, 6}:
        raise ValueError("unsupported png format")
    channels = 4 if color_type == 6 else 3
    stride = width * channels
    raw = zlib.decompress(b"".join(payload for kind, payload in chunks if kind == b"IDAT"))
    rows = []
    previous = bytearray(stride)
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + stride])
        offset += stride
        for index, value in enumerate(row):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (value + up) & 0xFF
            elif filter_type == 3:
                row[index] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[index] = (value + _paeth(left, up, upper_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError("unsupported png filter")
        rows.append(bytes(row))
        previous = row
    return width, height, b"".join(rows)


def _read_artifact_as_png(path: Path) -> bytes:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as converted:
        converted_path = Path(converted.name)
    try:
        subprocess.run(
            ["/usr/bin/sips", "-s", "format", "png", str(path), "--out", str(converted_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return converted_path.read_bytes()
    finally:
        converted_path.unlink(missing_ok=True)


def png_pixel_diagnostics(path: str | Path | None) -> dict[str, Any]:
    """读取快照 artifact 并给出内容区像素事实；桥内快照实际落盘为 jpg，按需归一化为 png。"""
    if path is None:
        return _missing_pixel_facts("")
    path_text = str(path)
    if not path_text:
        return _missing_pixel_facts("")
    artifact_path = Path(path_text)
    if not artifact_path.exists():
        return _missing_pixel_facts(path_text)
    try:
        size = artifact_path.stat().st_size
        width, height, pixels = _decode_png_rgba(_read_artifact_as_png(artifact_path))
    except (
        StopIteration,
        ValueError,
        IndexError,
        KeyError,
        zlib.error,
        struct.error,
        subprocess.CalledProcessError,
        OSError,
    ) as exc:
        # 截断或半写入的快照会在这里被判定为不可解码，而不是让 gate 崩在 traceback 上。
        facts = _missing_pixel_facts(path_text, str(exc))
        facts["exists"] = True
        return facts
    channels = len(pixels) // (width * height) if width > 0 and height > 0 else 0
    edge_x = int(width * PIXEL_EDGE_EXCLUDE_RATIO)
    edge_y = int(height * PIXEL_EDGE_EXCLUDE_RATIO)
    content_left = edge_x if width > edge_x * 2 else 0
    content_top = edge_y if height > edge_y * 2 else 0
    content_right = width - content_left
    content_bottom = height - content_top
    non_empty_pixels = 0
    content_pixels = 0
    for y in range(content_top, content_bottom):
        row_start = y * width * channels
        for x in range(content_left, content_right):
            offset = row_start + x * channels
            content_pixels += 1
            red, green, blue = pixels[offset], pixels[offset + 1], pixels[offset + 2]
            alpha = pixels[offset + 3] if channels == 4 else 255
            if alpha > 0 and (red > 0 or green > 0 or blue > 0):
                non_empty_pixels += 1
    return {
        "path": path_text,
        "exists": True,
        "bytes": size,
        "width": width,
        "height": height,
        "total_pixels": width * height,
        "content_pixels": content_pixels,
        "content_bounds": {
            "left": content_left,
            "top": content_top,
            "right": content_right,
            "bottom": content_bottom,
        },
        "non_empty_pixels": non_empty_pixels,
        "non_empty": non_empty_pixels > 0,
    }


def _source_facts(
    view_uid: Any, node_items: list[dict[str, Any]], all_evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    """画面来源：本地视图取本节点的发布统计；远端视图取该 uid 发布方的统计（画面由对端发布）。

    同一场景可能有多个 case（例如真相机与合成源变体）提供同一份场景证据，此时必须把观测到的
    来源都记下来，不能只留其中一个——否则「这份画面由谁产出」会被静默折叠成一个值。
    """
    ordered = node_items + [item for item in all_evidence if item not in node_items]
    observed: list[dict[str, Any]] = []
    for item in ordered:
        if _function(item) != "onLocalVideoStats":
            continue
        payload = _payload(item)
        if payload.get("uid") != view_uid:
            continue
        source_type = payload.get("source_type")
        entry = {
            "source_type": source_type,
            "origin": {SOURCE_TYPE_CAMERA: "camera", SOURCE_TYPE_SYNTHETIC: "synthetic"}.get(
                source_type, "unknown"
            ),
            "publisher_node_id": item.get("node_id"),
        }
        if entry not in observed:
            observed.append(entry)
    if not observed:
        return {
            "source_type": None,
            "origin": "unknown",
            "publisher_node_id": None,
            "observed": [],
        }
    if len(observed) == 1:
        return {**observed[0], "observed": observed}
    return {"source_type": None, "origin": "mixed", "publisher_node_id": None, "observed": observed}


def _snapshot_facts(
    view_role: str,
    node_items: list[dict[str, Any]],
    reasons: list[str],
    pixel_probe: Callable[[str], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    requests = [
        item
        for item in node_items
        if _function(item) == "onSnapshotRequested" and _view_key(_payload(item)) == view_role
    ]
    callbacks = [
        item
        for item in node_items
        if _function(item) == "onSnapshotTaken" and _view_key(_payload(item)) == view_role
    ]

    request_ok = next(
        (
            _payload(item)
            for item in requests
            if _payload(item).get("return_code") == 0 and str(_payload(item).get("file_path") or "")
        ),
        None,
    )
    if not requests:
        reasons.append(REASON_SNAPSHOT_REQUEST_MISSING)
    elif request_ok is None:
        reasons.append(REASON_SNAPSHOT_REQUEST_FAILED)

    callback_ok = next(
        (
            _payload(item)
            for item in callbacks
            if _payload(item).get("err_code") == 0 and str(_payload(item).get("file_path") or "")
        ),
        None,
    )
    if not callbacks:
        reasons.append(REASON_SNAPSHOT_CALLBACK_MISSING)
    elif callback_ok is None:
        reasons.append(REASON_SNAPSHOT_ERROR)

    request_path = str((request_ok or {}).get("file_path") or "")
    callback_path = str((callback_ok or {}).get("file_path") or "")
    if request_ok and callback_ok and request_path != callback_path:
        reasons.append(REASON_SNAPSHOT_PATH_MISMATCH)
    artifact_path = callback_path or request_path

    snapshot = {
        "request": {
            "observed": bool(requests),
            "return_code": (_payload(requests[-1]).get("return_code") if requests else None),
            "path": request_path,
        },
        "callback": {
            "observed": bool(callbacks),
            "err_code": (_payload(callbacks[-1]).get("err_code") if callbacks else None),
            "path": callback_path,
        },
        "path_consistent": bool(request_ok and callback_ok and request_path == callback_path),
        "artifact_path": artifact_path,
    }

    if not artifact_path:
        return snapshot, _missing_pixel_facts("")
    artifact = pixel_probe(artifact_path)
    if not artifact.get("exists"):
        reasons.append(REASON_ARTIFACT_FILE_MISSING)
    elif artifact.get("error"):
        reasons.append(REASON_ARTIFACT_UNDECODABLE)
    elif not artifact.get("width") or not artifact.get("height"):
        reasons.append(REASON_ARTIFACT_ZERO_DIMENSION)
    elif not artifact.get("non_empty"):
        reasons.append(REASON_ARTIFACT_EMPTY_CONTENT)
    return snapshot, artifact


def _local_liveness_facts(view_uid: Any, node_items: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "sent_bitrate": None,
        "sent_frame_rate": None,
        "tx_video_kbitrate": None,
        "local_send": False,
    }
    for item in node_items:
        payload = _payload(item)
        function = _function(item)
        if function == "onLocalVideoStats" and payload.get("uid") == view_uid:
            facts["sent_bitrate"] = payload.get("sent_bitrate")
            facts["sent_frame_rate"] = payload.get("sent_frame_rate")
            if (payload.get("sent_bitrate") or 0) > 0 and (payload.get("sent_frame_rate") or 0) > 0:
                facts["local_send"] = True
        if function == "onRtcStats":
            if (payload.get("tx_video_kbitrate") or 0) > 0:
                facts["tx_video_kbitrate"] = payload.get("tx_video_kbitrate")
                facts["local_send"] = True
    return facts


def _remote_liveness_facts(view_uid: Any, node_items: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "received_bitrate": None,
        "decoder_output_frame_rate": None,
        "renderer_output_frame_rate": None,
        "rx_video_kbitrate": None,
        "first_remote_video_frame": False,
        "remote_receive": False,
        "rtc_video_receive": False,
    }
    for item in node_items:
        payload = _payload(item)
        function = _function(item)
        if function == "onFirstRemoteVideoFrame" and payload.get("uid") == view_uid:
            facts["first_remote_video_frame"] = True
        if function == "onRemoteVideoStats" and payload.get("uid") == view_uid:
            facts["received_bitrate"] = payload.get("received_bitrate")
            facts["decoder_output_frame_rate"] = payload.get("decoder_output_frame_rate")
            facts["renderer_output_frame_rate"] = payload.get("renderer_output_frame_rate")
            if (payload.get("received_bitrate") or 0) > 0 and (
                (payload.get("decoder_output_frame_rate") or 0) > 0
                or (payload.get("renderer_output_frame_rate") or 0) > 0
            ):
                facts["remote_receive"] = True
        if function == "onRtcStats" and (payload.get("rx_video_kbitrate") or 0) > 0:
            facts["rx_video_kbitrate"] = payload.get("rx_video_kbitrate")
            facts["rtc_video_receive"] = True
    if facts["remote_receive"] is False and facts["first_remote_video_frame"] and facts["rtc_video_receive"]:
        facts["remote_receive"] = True
    return facts


def _remote_binding_facts(
    view_role: str, view_uid: Any, node_items: list[dict[str, Any]]
) -> dict[str, Any]:
    """远端视图绑定证据。

    真实链路的 report evidence 只承载回调事件，SDK 调用结果（`bindRemoteVideo` 的
    `configured/view_id/uid`）不进入 evidence 流；因此绑定以「该视图在声明节点上有与其
    `view_role`、`uid` 一致的快照证据」为主证据，调用结果存在时作为更强的直接证据。
    """
    bind_call = any(
        _payload(item).get("configured") is True
        and _payload(item).get("view_id") == view_role
        and _payload(item).get("uid") == view_uid
        for item in node_items
        if _function(item) in REMOTE_VIDEO_BIND_FUNCTIONS
    )
    snapshot_bound = any(
        _view_key(_payload(item)) == view_role and _payload(item).get("uid") == view_uid
        for item in node_items
        if _function(item) in {"onSnapshotRequested", "onSnapshotTaken"}
    )
    if bind_call:
        source = "bind_call_result"
    elif snapshot_bound:
        source = "snapshot_evidence"
    else:
        source = "none"
    return {
        "configured": bind_call or snapshot_bound,
        "view_id": view_role,
        "uid": view_uid,
        "source": source,
    }


def build_view_visual_evidence(
    view: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    pixel_probe: Callable[[str], dict[str, Any]] = png_pixel_diagnostics,
) -> dict[str, Any]:
    """按标准判定单个必需视图；view 声明 node_id / view_role / uid / kind（local|remote）。"""
    node_id = str(view["node_id"])
    view_role = str(view["view_role"])
    view_uid = view.get("uid")
    kind = str(view.get("kind", "remote"))
    reasons: list[str] = []

    node_items = [item for item in evidence if item.get("node_id") == node_id]
    foreign_nodes = sorted(
        {
            str(item.get("node_id"))
            for item in evidence
            if _view_key(_payload(item)) == view_role and item.get("node_id") != node_id
        }
    )
    if foreign_nodes:
        reasons.append(REASON_FOREIGN_NODE_EVIDENCE)

    snapshot, artifact = _snapshot_facts(view_role, node_items, reasons, pixel_probe)

    if kind == "local":
        liveness = _local_liveness_facts(view_uid, node_items)
        binding: dict[str, Any] = {}
        if not liveness["local_send"]:
            reasons.append(REASON_LOCAL_VIDEO_SEND_MISSING)
    else:
        binding = _remote_binding_facts(view_role, view_uid, node_items)
        liveness = _remote_liveness_facts(view_uid, node_items)
        if not binding["configured"]:
            reasons.append(REASON_REMOTE_VIEW_NOT_BOUND)
        if not liveness["first_remote_video_frame"]:
            reasons.append(REASON_FIRST_REMOTE_VIDEO_FRAME_MISSING)
        if not liveness["remote_receive"]:
            reasons.append(REASON_REMOTE_VIDEO_RECEIVE_MISSING)
        if not liveness["rtc_video_receive"]:
            reasons.append(REASON_RTC_VIDEO_RECEIVE_MISSING)

    source = _source_facts(view_uid, node_items, evidence)
    expected_source_type = view.get("expected_source_type")
    if expected_source_type is not None:
        observed_source_types = {item.get("source_type") for item in source["observed"]}
        if not observed_source_types or observed_source_types == {None}:
            reasons.append(REASON_SOURCE_TYPE_MISSING)
        elif source["source_type"] != expected_source_type:
            reasons.append(REASON_SOURCE_TYPE_MISMATCH)

    return {
        "view_role": view_role,
        "node_id": node_id,
        "node_role": str(view.get("node_role", "")),
        "uid": view_uid,
        "kind": kind,
        "sdk": str(view.get("sdk", "")),
        "source": source,
        "expected_source_type": expected_source_type,
        "binding": binding,
        "snapshot": snapshot,
        "artifact": artifact,
        "liveness": liveness,
        "foreign_node_evidence": foreign_nodes,
        "view_verdict": VERDICT_PASSED if not reasons else VERDICT_MISSING,
        "fail_reasons": sorted(set(reasons)),
    }


def build_scenario_visual_evidence(
    *,
    scenario_id: str,
    case_ids: tuple[str, ...],
    views: tuple[dict[str, Any], ...],
    reports: list[dict[str, Any]],
    pixel_probe: Callable[[str], dict[str, Any]] = png_pixel_diagnostics,
) -> dict[str, Any]:
    """判定一个画面场景：场景 verdict 是全部必需视图 verdict 的 AND。"""
    case_id_set = {str(case_id) for case_id in case_ids}
    evidence = [
        item
        for report in reports
        for result in report.get("case_results", [])
        if str(result.get("case_id")) in case_id_set
        for item in result.get("observations", [])
        if isinstance(item, dict)
    ]
    built = [build_view_visual_evidence(view, evidence, pixel_probe=pixel_probe) for view in views]
    missing_views = sorted(
        item["view_role"] for item in built if item["view_verdict"] != VERDICT_PASSED
    )
    return {
        "scenario_id": scenario_id,
        "status": VERDICT_PASSED if not missing_views else VERDICT_MISSING,
        "case_ids": sorted(case_id_set),
        "required_views": sorted(item["view_role"] for item in built),
        "missing_views": missing_views,
        "fail_reasons": {
            item["view_role"]: item["fail_reasons"] for item in built if item["fail_reasons"]
        },
        "views": {item["view_role"]: item for item in built},
    }


def build_not_exercised_scenario(
    *,
    scenario_id: str,
    owner_layer: str,
    reason: str,
    follow_up: str,
    case_ids: tuple[str, ...] = (),
    views: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """登记「该场景没有声明画面能力面」：有声明就必须有证据，没有能力面必须显式登记。

    传入 `views` 说明该场景已经有必需视图，此时只能按标准判定，不允许再登记为未覆盖。
    """
    if views:
        raise AssertionError(
            f"scenario {scenario_id} declares required views {sorted(v['view_role'] for v in views)}; "
            "it must be judged by build_scenario_visual_evidence, not registered as not_exercised"
        )
    return {
        "scenario_id": scenario_id,
        "status": VERDICT_NOT_EXERCISED,
        "case_ids": sorted(str(case_id) for case_id in case_ids),
        "required_views": [],
        "missing_views": [],
        "fail_reasons": {},
        "views": {},
        "owner_layer": owner_layer,
        "reason": reason,
        "follow_up": follow_up,
    }


def assert_scenario_has_no_picture_evidence(
    *,
    scenario_id: str,
    reports: list[dict[str, Any]],
    case_ids: tuple[str, ...],
) -> None:
    """声明 not_exercised 的场景不得已经产出画面证据。

    这是给「能力面还没做」的缺口登记加的护栏：一旦该场景的用例开始产出快照/远端视频证据，
    说明能力面已经落地，必须改为按标准声明必需视图并判定，不能继续挂在 not_exercised 上。
    """
    case_id_set = {str(case_id) for case_id in case_ids}
    offenders = sorted(
        {
            _function(item)
            for report in reports
            for result in report.get("case_results", [])
            if str(result.get("case_id")) in case_id_set
            for item in result.get("observations", [])
            if isinstance(item, dict) and _function(item) in PICTURE_EVIDENCE_FUNCTIONS
        }
    )
    if offenders:
        raise AssertionError(
            f"scenario {scenario_id} is registered as not_exercised but its cases already produced "
            f"picture evidence {offenders}; declare its required views and judge it by the standard"
        )


def summarize_visual_evidence(scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """汇总场景 verdict：只有 passed 与 not_exercised 不算失败；其余一律按 fail closed 计入未通过。"""
    by_status: dict[str, list[str]] = {}
    for scenario_id, scenario in sorted(scenarios.items()):
        by_status.setdefault(str(scenario.get("status")), []).append(scenario_id)
    # 未知 status（漏字段、拼写错、上游新增取值）不得被静默忽略：只有明确的通过态才算通过。
    failing = sorted(
        scenario_id
        for scenario_id, scenario in scenarios.items()
        if scenario.get("status") not in (VERDICT_PASSED, VERDICT_NOT_EXERCISED)
    )
    return {
        "status": VERDICT_MISSING if failing else VERDICT_PASSED,
        "scenario_count": len(scenarios),
        "passed_scenarios": by_status.get(VERDICT_PASSED, []),
        "missing_scenarios": failing,
        "not_exercised_scenarios": by_status.get(VERDICT_NOT_EXERCISED, []),
        "scenarios": {key: scenarios[key] for key in sorted(scenarios)},
    }
