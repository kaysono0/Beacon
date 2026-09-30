#!/usr/bin/env python3
"""运行 Phase 4A Mac mock E2E。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

os.environ.setdefault("BEACON_AUTH_TOKEN", "local-test-token")
AUTH_TOKEN = os.environ["BEACON_AUTH_TOKEN"]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "python_sdk"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
import websockets  # noqa: E402

from app.main import app  # noqa: E402
from app.common.target_contract import target_key  # noqa: E402


from scripts.support.generate_report import main as generate_report_main  # noqa: E402
from scripts.support.write_junit import main as write_junit_main  # noqa: E402


AUTH = {"Authorization": f"Bearer {AUTH_TOKEN}"}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def wait_http(base_url: str) -> None:
    async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
        for _ in range(50):
            try:
                if (await client.get(f"{base_url}/api/v1/status")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.05)
    raise RuntimeError("server did not start")


class MockAgentHarness:
    def __init__(
        self, websocket, *, target_mode: bool = False, callback_gate: threading.Event | None = None,
        room_members: dict[str, set[int | str]] | None = None,
    ) -> None:
        self._websocket = websocket
        self._lease_id = ""
        self._last_applied = {"value": "", "revision": 0}
        self._last_echo: str | None = None
        self._callback_rules: dict[str, dict[str, object]] = {}
        self._joined = False
        self._previewing = False
        self._zego_room_id: str | None = None
        self._zego_published_stream: str | None = None
        self._zego_views: set[str] = set()
        self._volc_room_id: str | None = None
        self._volc_user_id: str | None = None
        self._volc_local_views: set[str] = set()
        self._volc_remote_views: dict[str, str] = {}
        self._room_members = room_members if room_members is not None else {}
        self._own_channel: str | None = None
        self._own_uid: int | None = None
        self._local_views: set[str] = set()
        self._remote_views: dict[str, int] = {}
        self._handlers = {}
        self.registered_handler_keys: set[str] = set()
        self.handled_target_keys: list[str] = []
        self.callback_events: list[dict[str, object]] = []
        self.callback_receipts: list[dict[str, object]] = []
        self.target_mode = target_mode
        self.callback_gate = callback_gate
        self.reset_phases: list[str] = []
        self._register_handler(
            {"sdk": "mock_complex_sdk", "interface": "session", "class_name": "MockComplexSession", "function": "applyValue"},
            self._handle_mock_complex_apply_value,
        )
        self._register_handler(
            {"sdk": "mock_complex_sdk", "interface": "session", "class_name": "MockComplexSession", "function": "configureValue"},
            self._handle_mock_complex_configure_value,
        )
        self._register_handler(
            {"sdk": "mock_complex_sdk", "interface": "session", "class_name": "MockComplexSession", "function": "getLastAppliedValue"},
            self._handle_mock_complex_get_last_applied_value,
        )
        for function in ("echo", "echoWithCallback", "getLastEcho"):
            self._register_handler(
                {"sdk": "mock_echo", "interface": "echo", "class_name": "EchoService", "function": function},
                self._handle_mock_echo,
            )
        self._pending: dict[str, asyncio.Queue[dict[str, object]]] = {
            "registerResponse": asyncio.Queue(),
            "reconnectResponse": asyncio.Queue(),
        }

    async def pump(self) -> None:
        try:
            while True:
                packet = json.loads(await self._websocket.recv())
                action = packet["common"]["action"]
                if action in self._pending:
                    await self._pending[action].put(packet)
                    continue
                if action == "invokeRequest":
                    await self._handle_invoke(packet)
                elif action == "callbackRequest":
                    await self._handle_callback_request(packet)
                elif action == "callbackEventResponse":
                    self.callback_receipts.append(packet)
                    continue
        except websockets.ConnectionClosed:
            return

    async def send_and_wait(self, packet: dict[str, object], response_action: str) -> dict[str, object]:
        await self._websocket.send(json.dumps(packet))
        response = await self._pending[response_action].get()
        data = response.get("data", {})
        if response_action in {"registerResponse", "reconnectResponse"} and isinstance(data, dict):
            self._lease_id = str(data.get("lease_id") or self._lease_id)
        return response

    def _register_handler(self, target: dict[str, object], handler) -> None:
        key = target_key(target)
        self._handlers[key] = handler
        self.registered_handler_keys.add(key)

    def _handle_mock_echo(
        self,
        packet: dict[str, object],
        params: dict[str, object],
        extra: dict[str, object],
    ) -> tuple[int, str, str, dict[str, object] | None]:
        target = packet["data"]["list"][0]["target"]
        function = target["function"]
        if function == "getLastEcho":
            return 0, "ok", json.dumps({"message": self._last_echo}), None
        message = params.get("message")
        if not isinstance(message, str):
            return 400, "missing message", "{}", None
        self._last_echo = message
        callback = (
            self._callback_event(
                packet, extra,
                {"sdk": "mock_echo", "interface": "echo", "class_name": "EchoDelegate", "function": "onEchoReceived"},
                {"message": message},
            )
            if function == "echoWithCallback" else None
        )
        return 0, "ok", "{}", callback

    def _handle_mock_complex_configure_value(
        self,
        packet: dict[str, object],
        params: dict[str, object],
        extra: dict[str, object],
    ) -> tuple[int, str, str, dict[str, object] | None]:
        _ = (packet, extra)
        value = params.get("value")
        options = params.get("options")
        if not isinstance(value, str) or not isinstance(options, dict):
            return 400, "invalid configure value params", "{}", None
        self._last_applied = {
            "value": value,
            "revision": 0,
            "options": options,
        }
        return 0, "ok", json.dumps({"configured": True}, separators=(",", ":")), None

    def _handle_mock_complex_apply_value(
        self,
        packet: dict[str, object],
        params: dict[str, object],
        extra: dict[str, object],
    ) -> tuple[int, str, str, dict[str, object] | None]:
        value = params.get("value")
        if not isinstance(value, str):
            return 400, "missing value", "{}", None
        self._last_applied = {"value": value, "revision": int(self._last_applied["revision"]) + 1}
        return (
            0,
            "ok",
            "{}",
            self._callback_event(
                packet,
                extra,
                {
                    "sdk": "mock_complex_sdk",
                    "interface": "session",
                    "class_name": "MockComplexSessionObserver",
                    "function": "onValueApplied",
                },
                dict(self._last_applied),
            ),
        )

    def _handle_mock_complex_get_last_applied_value(
        self,
        packet: dict[str, object],
        params: dict[str, object],
        extra: dict[str, object],
    ) -> tuple[int, str, str, dict[str, object] | None]:
        _ = (packet, params, extra)
        return 0, "ok", json.dumps(self._last_applied, separators=(",", ":")), None

    def _callback_event(
        self,
        packet: dict[str, object],
        extra: dict[str, object],
        event_target: dict[str, object],
        payload: dict[str, object],
    ) -> dict[str, object]:
        invoke_op_id = str(packet["common"]["op_id"])
        event_nonce = uuid.uuid4().hex if self.target_mode else invoke_op_id
        event_function = str(event_target.get("function", "callback"))
        # 一次调用可能产生多个事件（如火山 join 的连接态 + 房间态），event_id 必须按事件唯一，
        # 否则第二个事件会被服务端按重复 event_id 丢弃。
        callback_packet = {
            "common": {
                "action": "callbackEventRequest",
                "op_id": f"{event_nonce}-{event_function}-callback",
                "timestamp_ms": 2,
            },
            "data": {
                "event_id": f"{event_nonce}-{event_function}-event",
                "node_id": packet["data"]["node_id"],
                "lease_id": self._lease_id,
                "run_id": extra.get("run_id", "run-e2e"),
                "case_id": extra.get("case_id", "TC-E2E"),
                "step_id": extra.get("step_id", "join"),
                **({"device_role": extra["device_role"]} if "device_role" in extra else {}),
                "event_target": event_target,
                "payload": payload,
            },
        }
        rule_key = target_key(event_target)
        rule = self._callback_rules.get(rule_key)
        if rule is not None:
            results = []
            for call in rule["call_elements"]:
                target = call["target"]
                if target.get("sdk") == "mock_echo" and target.get("function") == "getLastEcho":
                    results.append({"target": target, "error": 0, "message": "ok", "return_value": json.dumps({"message": self._last_echo})})
                elif target.get("sdk") == "beacon_system" and target.get("interface") == "clock" and target.get("function") == "waitInMs":
                    results.append({"target": target, "error": 0, "message": "waited", "return_value": '{"waited":true}'})
                else:
                    results.append({"target": target, "error": 400, "message": "unknown deferred call", "return_value": "{}"})
            callback_packet["data"]["callback_execution"] = {
                "defer_matched": True,
                "defer_executed": bool(results) and all(item["error"] == 0 for item in results),
                "call_results": results,
            }
            remaining = int(rule["repeat"])
            if remaining == 1:
                self._callback_rules.pop(rule_key)
            elif remaining > 1:
                rule["repeat"] = remaining - 1
        return callback_packet

    async def _handle_callback_request(self, packet: dict[str, object]) -> None:
        for rule in packet["data"]["list"]:
            self._callback_rules[target_key(rule["event_target"])] = rule
        await self._websocket.send(json.dumps({
            "common": {"action": "callbackResponse", "op_id": packet["common"]["op_id"], "timestamp_ms": 1},
            "data": {"node_id": packet["data"]["node_id"], "lease_id": self._lease_id, "code": 0, "message": "installed"},
        }))

    def _handle_volcengine(
        self,
        packet: dict[str, object],
        target: dict[str, object],
        params: dict[str, object],
        extra: dict[str, object],
    ) -> tuple[int, str, str, list[dict[str, object]]]:
        """火山 RTC mock：只覆盖 L1 声明的 4 个 op，并按真实 SDK 语义回事件。

        事件目标必须与 `sdk_adapters/volcengine_rtc` 的声明一致：
        房间级 onRoomStateChanged / onLeaveRoom 走 byte_rtc_room，引擎级
        onConnectionStateChanged 走 byte_rtc_engine。
        """
        function = str(target.get("function", ""))
        room_delegate = {
            "sdk": "volcengine_rtc",
            "interface": "byte_rtc_room",
            "class_name": "ByteRTCRoomDelegate",
        }
        if function == "createRTCEngine":
            # 与真实 SDK 一致：连接态回调在创建引擎时到达（终态 3 = Connected）。
            engine_delegate = {
                "sdk": "volcengine_rtc",
                "interface": "byte_rtc_engine",
                "class_name": "ByteRTCEngineDelegate",
            }
            return (
                0,
                "engine created",
                '{"created":true}',
                [
                    self._callback_event(
                        packet,
                        extra,
                        {**engine_delegate, "function": "onConnectionStateChanged"},
                        {"state": 3},
                    )
                ],
            )
        if function == "destroyRTCEngine":
            return 0, "engine destroyed", '{"destroyed":true}', []
        if function in {"startVideoCapture", "stopVideoCapture", "startSyntheticVideo", "stopSyntheticVideo"}:
            return 0, "video source updated", "{}", []
        if target.get("interface") == "visual_probe":
            view_role = str(params.get("view_role", ""))
            if function == "bindLocalVideo":
                self._volc_local_views.add(view_role)
                return 0, "bound", "{}", []
            if function == "bindRemoteVideo":
                remote_user = str(params.get("uid", ""))
                if self._volc_room_id is None or remote_user not in self._room_members.get(self._volc_room_id, set()):
                    return 404, "remote publisher is not joined", "{}", []
                self._volc_remote_views[view_role] = remote_user
                return 0, "bound", "{}", [self._callback_event(
                    packet, extra,
                    {"sdk": "volcengine_rtc", "interface": "byte_rtc_engine", "class_name": "ByteRTCEngineDelegate", "function": "onFirstRemoteVideoFrame"},
                    {"uid": remote_user, "width": 320, "height": 180},
                )]
            if function == "captureSnapshot":
                if view_role not in self._volc_local_views and view_role not in self._volc_remote_views:
                    return 404, "view is not bound", "{}", []
                return 0, "snapshot accepted", "{}", [self._callback_event(
                    packet, extra,
                    {"sdk": "volcengine_rtc", "interface": "byte_rtc_engine", "class_name": "ByteRTCEngineDelegate", "function": "onSnapshotTaken"},
                    {"view_role": view_role, "err_code": 0},
                )]
            if function == "releaseView":
                self._volc_local_views.discard(view_role)
                self._volc_remote_views.pop(view_role, None)
                return 0, "released", "{}", []
        if function == "leaveRoom":
            room_id = self._volc_room_id or str(params.get("room_id", "volcengine-l1-room"))
            user_id = self._volc_user_id or str(params.get("user_id", "volcengine-l1-user"))
            self._room_members.get(room_id, set()).discard(user_id)
            self._volc_room_id = None
            self._volc_user_id = None
            return (
                0,
                "left",
                '{"left":true}',
                [
                    # 与真实 SDK 一致：leaveRoom 返回后 onLeaveRoom 与房间态 state=2 都会到达。
                    self._callback_event(
                        packet,
                        extra,
                        {**room_delegate, "function": "onLeaveRoom"},
                        {"room_id": room_id},
                    ),
                    self._callback_event(
                        packet,
                        extra,
                        {**room_delegate, "function": "onRoomStateChanged"},
                        {"room_id": room_id, "uid": user_id, "state": 2},
                    ),
                ],
            )
        if function == "joinRoom":
            if extra.get("token_fixture") == "invalid_for_testing" or params.get("token") == "invalid-token":
                return 401, "invalid token", "{}", []
            room_id = str(params.get("room_id", "volcengine-l1-room"))
            user_id = str(params.get("user_id", "volcengine-l1-user"))
            self._volc_room_id = room_id
            self._volc_user_id = user_id
            self._room_members.setdefault(room_id, set()).add(user_id)
            return (
                0,
                "joined",
                '{"joined":true}',
                [
                    # 与真实 SDK 一致：join 只报房间态 state=0；连接态回调属于创建引擎那一步
                    # （见 createRTCEngine 分支），join 路径不得重复伪造它。
                    self._callback_event(
                        packet,
                        extra,
                        {**room_delegate, "function": "onRoomStateChanged"},
                        {"room_id": room_id, "uid": user_id, "state": 0, "elapsed_ms": 0},
                    ),
                ],
            )
        return 400, f"unknown volcengine handler: {function}", "{}", []

    def _handle_zego(
        self,
        packet: dict[str, object],
        target: dict[str, object],
        params: dict[str, object],
        extra: dict[str, object],
    ) -> tuple[int, str, str, list[dict[str, object]]]:
        """按 ZEGO 声明的房间事件目标模拟 L1 引擎与登录状态。"""
        function = target.get("function")
        if function in {"createEngineWithProfile", "destroyEngine", "startSyntheticVideo", "stopSyntheticVideo"}:
            return 0, "ok", "{}", []
        if function == "startPreview":
            self._zego_views.add(str(params["view_role"]))
            return 0, "preview started", "{}", []
        if function == "stopPreview":
            return 0, "preview stopped", "{}", []
        if function == "releaseView":
            self._zego_views.discard(str(params["view_role"]))
            return 0, "view released", "{}", []
        if function == "startPublishingStream":
            stream_id = str(params["stream_id"])
            self._zego_published_stream = stream_id
            if self._zego_room_id is not None:
                self._room_members.setdefault(self._zego_room_id, set()).add(stream_id)
            callback = self._callback_event(
                packet, extra,
                {"sdk": "zego_express", "interface": "zego_publisher", "class_name": "ZegoEventHandler", "function": "onPublisherStateUpdate"},
                {"stream_id": stream_id, "error_code": 0},
            )
            return 0, "publishing", "{}", [callback]
        if function == "stopPublishingStream":
            if self._zego_room_id is not None and self._zego_published_stream is not None:
                self._room_members.get(self._zego_room_id, set()).discard(self._zego_published_stream)
            self._zego_published_stream = None
            return 0, "publication stopped", "{}", []
        if function == "startPlayingStream":
            stream_id = str(params["stream_id"])
            if self._zego_room_id is None or stream_id not in self._room_members.get(self._zego_room_id, set()):
                return 404, "remote stream is not published", "{}", []
            self._zego_views.add(str(params["view_role"]))
            callback = self._callback_event(
                packet, extra,
                {"sdk": "zego_express", "interface": "zego_player", "class_name": "ZegoEventHandler", "function": "onPlayerRenderVideoFirstFrame"},
                {"stream_id": stream_id},
            )
            return 0, "playing", "{}", [callback]
        if function == "stopPlayingStream":
            return 0, "playback stopped", "{}", []
        if function == "captureSnapshot":
            view_role = str(params["view_role"])
            if view_role not in self._zego_views:
                return 404, "view is not bound", "{}", []
            callback = self._callback_event(
                packet, extra,
                {"sdk": "zego_express", "interface": "zego_visual_probe", "class_name": "BeaconZegoVisualProbe", "function": "onRenderedViewSnapshot"},
                {"view_role": view_role, "err_code": 0},
            )
            return 0, "snapshot accepted", "{}", [callback]
        if function == "loginRoom":
            self._zego_room_id = str(params["room_id"])
            state = 2
        elif function == "logoutRoom" and self._zego_room_id is not None:
            if self._zego_published_stream is not None:
                self._room_members.get(self._zego_room_id, set()).discard(self._zego_published_stream)
            state = 0
        else:
            return 400, f"unknown zego handler: {function}", "{}", []
        callback = self._callback_event(
            packet,
            extra,
            {"sdk": "zego_express", "interface": "zego_room", "class_name": "ZegoEventHandler", "function": "onRoomStateUpdate"},
            {"room_id": self._zego_room_id, "state": state, "error_code": 0},
        )
        if state == 0:
            self._zego_room_id = None
            self._zego_published_stream = None
            self._zego_views.clear()
            if self._own_channel is not None and self._own_uid is not None:
                self._room_members.get(self._own_channel, set()).discard(self._own_uid)
            if self._volc_room_id is not None and self._volc_user_id is not None:
                self._room_members.get(self._volc_room_id, set()).discard(self._volc_user_id)
            self._own_channel = None
            self._own_uid = None
            self._local_views.clear()
            self._remote_views.clear()
        return 0, "ok", "{}", [callback]

    async def _handle_invoke(self, packet: dict[str, object]) -> None:
        call = packet["data"]["list"][0]
        extra = call.get("extra", {})
        if isinstance(extra, str):
            extra = json.loads(extra)
        params = call.get("params", {})
        if isinstance(params, str):
            params = json.loads(params)
        target = call.get("target", {})
        if not isinstance(target, dict):
            target = {}
        if not isinstance(extra, dict):
            extra = {}
        if not isinstance(params, dict):
            params = {}
        key = target_key(target)
        handler = self._handlers.get(key)
        callback_packets: list[dict[str, object]] = []
        if self.target_mode and target.get("sdk") == "beacon_system" and target.get("function") == "resetSession":
            self.reset_phases.append(str(extra.get("runtime_phase")))
            self._last_applied = {"value": "", "revision": 0}
            self._last_echo = None
            self._callback_rules.clear()
            if self._own_channel is not None and self._own_uid is not None:
                self._room_members.get(self._own_channel, set()).discard(self._own_uid)
            self._joined = False
            self._previewing = False
            self._zego_room_id = None
            self._zego_published_stream = None
            self._zego_views.clear()
            self._volc_room_id = None
            self._volc_user_id = None
            self._volc_local_views.clear()
            self._volc_remote_views.clear()
            self._own_channel = None
            self._own_uid = None
            self._local_views.clear()
            self._remote_views.clear()
            code, message, result = 0, "reset", "{}"
        elif handler is not None:
            self.handled_target_keys.append(key)
            code, message, result, callback_packet = handler(packet, params, extra)
            if callback_packet is not None:
                callback_packets.append(callback_packet)
        elif target.get("sdk") == "volcengine_rtc":
            code, message, result, callback_packets = self._handle_volcengine(packet, target, params, extra)
        elif self.target_mode and target.get("sdk") == "zego_express":
            code, message, result, callback_packets = self._handle_zego(packet, target, params, extra)
        elif self.target_mode and target.get("sdk") == "beacon_system" and target.get("function") == "waitInMs":
            code, message, result = 0, "mock clock elapsed", "{}"
        elif self.target_mode and target.get("sdk") == "beacon_system" and target.get("interface") == "video_host" and target.get("function") in {"show", "hide"}:
            code, message, result = 0, "host visibility updated", "{}"
        elif target.get("sdk") == "mock_complex_sdk":
            code, message, result = 400, "unknown mock complex handler", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") == "isJoined":
            code, message, result = 0, "ok", json.dumps(self._joined)
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") == "getConnectionState":
            code, message, result = 0, "ok", json.dumps({"state": "connected" if self._joined else "idle"})
            if self._joined:
                callback_packets = [self._callback_event(
                    packet,
                    extra,
                    {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onRtcStats"},
                    {"duration": 1, "tx_bytes": 1, "rx_bytes": 1, "tx_audio_kbitrate": 64, "rx_audio_kbitrate": 64},
                )]
                for remote_uid in self._room_members.get(self._own_channel or "", set()) - {self._own_uid}:
                    callback_packets.append(self._callback_event(
                        packet, extra,
                        {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onRemoteAudioStats"},
                        {"uid": remote_uid, "received_bitrate": 64},
                    ))
                    if remote_uid in self._remote_views.values():
                        callback_packets.append(self._callback_event(
                            packet, extra,
                            {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onRemoteVideoStats"},
                            {"uid": remote_uid, "width": 320, "height": 180, "received_bitrate": 150, "rx_stream_type": 0},
                        ))
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") == "leaveChannel":
            self._joined = False
            if self._own_channel is not None and self._own_uid is not None:
                self._room_members.get(self._own_channel, set()).discard(self._own_uid)
            self._own_channel = None
            self._own_uid = None
            code, message, result = 0, "left", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") in {"loadSDK", "unloadSDK"}:
            code, message, result = 0, "ok", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") == "renewToken":
            code, message, result = 0, "token renewed", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") == "setDualStreamMode":
            code, message, result = 0, "dual stream updated", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") == "setRemoteVideoStream":
            uid = int(params["uid"])
            if uid not in self._remote_views.values():
                code, message, result = 404, "remote view is not bound", "{}"
            else:
                low = params["stream_type"] == "low"
                code, message, result = 0, "remote layer selected", "{}"
                callback_packets = [self._callback_event(
                    packet, extra,
                    {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onRemoteVideoStats"},
                    {"uid": uid, "width": 480 if low else 960, "height": 200 if low else 400, "received_bitrate": 150 if low else 400, "rx_stream_type": 1 if low else 0},
                )]
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("function") in {"startSyntheticVideo", "stopSyntheticVideo", "enableLocalAudio"}:
            code, message, result = 0, "media state updated", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("interface") == "media_player":
            function = target.get("function")
            state = {"openMediaPlayer": 2, "playMediaPlayer": 3, "pauseMediaPlayer": 4, "resumeMediaPlayer": 3, "stopMediaPlayer": 0}.get(function)
            if state is None:
                code, message, result = 400, f"unknown media player handler: {function}", "{}"
            else:
                code, message, result = 0, "media player state updated", "{}"
                callback_packets = [self._callback_event(
                    packet, extra,
                    {"sdk": "agora_rtc", "interface": "media_player", "class_name": "AgoraRtcMediaPlayerDelegate", "function": "onMediaPlayerStateChanged"},
                    {"state": state, "reason": 0},
                )]
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("interface") == "video_preview":
            function = target.get("function")
            if function == "startPreview" and extra.get("permission_fixture") == "deny_media_for_testing":
                code, message, result = 402, "permission denied", "{}"
            elif function == "startPreview":
                self._previewing = True
                code, message, result = 0, "preview started", "{}"
                if self._joined and self._local_views:
                    callback_packets = [self._callback_event(
                        packet, extra,
                        {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onLocalVideoStats"},
                        {"capture_frame_rate": 12, "sent_frame_rate": 15, "sent_bitrate": 150, "source_type": 0},
                    )]
            elif function == "stopPreview":
                self._previewing = False
                code, message, result = 0, "preview stopped", "{}"
            elif function == "isPreviewing":
                code, message, result = 0, "ok", json.dumps(self._previewing)
            else:
                code, message, result = 400, f"unknown preview handler: {function}", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("interface") == "visual_probe" and target.get("function") == "bindRemoteVideo":
            remote_uid = params.get("uid")
            if self._own_channel is None or remote_uid not in self._room_members.get(self._own_channel, set()):
                code, message, result = 404, "remote publisher is not joined", "{}"
            else:
                code, message, result = 0, "bound", "{}"
                self._remote_views[str(params["view_role"])] = int(remote_uid)
                callback_packets = [self._callback_event(
                    packet, extra,
                    {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onFirstRemoteVideoFrame"},
                    {"uid": remote_uid, "width": 320, "height": 180},
                ), self._callback_event(
                    packet, extra,
                    {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onRemoteVideoStats"},
                    {"uid": remote_uid, "width": 320, "height": 180, "received_bitrate": 150, "rx_stream_type": 0},
                )]
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("interface") == "visual_probe" and target.get("function") == "bindLocalVideo":
            self._local_views.add(str(params["view_role"]))
            code, message, result = 0, "bound", "{}"
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("interface") == "visual_probe" and target.get("function") == "captureSnapshot":
            view_role = str(params["view_role"])
            if view_role not in self._local_views and view_role not in self._remote_views:
                code, message, result = 404, "view is not bound", "{}"
            else:
                code, message, result = 0, "snapshot accepted", "{}"
                callback_packets = [self._callback_event(
                    packet, extra,
                    {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onSnapshotTaken"},
                    {"view_role": view_role, "err_code": 0},
                )]
        elif self.target_mode and target.get("sdk") == "agora_rtc" and target.get("interface") == "visual_probe" and target.get("function") == "releaseView":
            view_role = str(params["view_role"])
            self._local_views.discard(view_role)
            self._remote_views.pop(view_role, None)
            code, message, result = 0, "released", "{}"
        elif not self.target_mode or (target.get("sdk") == "agora_rtc" and target.get("function") == "joinChannel"):
            channel = params.get("channel", "smoke")
            uid = params.get("uid", 1001)
            invalid_agora_token = self.target_mode and params.get("token") in {"invalid-token", "expired-token"}
            if self.target_mode and extra.get("permission_fixture") == "deny_media_for_testing":
                code, message, result = 402, "permission denied", "{}"
            elif invalid_agora_token:
                code, message, result = 0, "join requested", "{}"
            else:
                code, message, result = 0, "ok", "{}"
                if self.target_mode:
                    self._joined = True
                    self._own_channel = str(channel)
                    self._own_uid = int(uid)
                    self._room_members.setdefault(self._own_channel, set()).add(self._own_uid)
            if code == 0 and not invalid_agora_token and extra.get("callback_fixture") != "suppress_join_success_for_testing":
                callback_packets = [
                    self._callback_event(
                        packet,
                        extra,
                        {
                            "sdk": "agora_rtc",
                            "interface": "rtc_engine",
                            "class_name": "AgoraRtcEngineDelegate",
                            "function": "onJoinChannelSuccess",
                        },
                        {"channel": channel, "uid": uid, "elapsed_ms": 3},
                    ),
                    self._callback_event(
                        packet,
                        extra,
                        {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onConnectionStateChanged"},
                        {"state": 3, "reason": 0},
                    ),
                ]
            elif invalid_agora_token:
                callback_packets = [self._callback_event(
                    packet,
                    extra,
                    {"sdk": "agora_rtc", "interface": "rtc_engine", "class_name": "AgoraRtcEngineDelegate", "function": "onError"},
                    {"code": 110, "message": "invalid token"},
                )]
        else:
            code, message, result = 400, f"unknown target handler: {key}", "{}"
        if self.target_mode and params.get("value") == "signal-target-1":
            for callback_packet in callback_packets:
                self.callback_events.append(callback_packet)
                await self._websocket.send(json.dumps(callback_packet))
            callback_packets.clear()
        await self._websocket.send(
            json.dumps(
                {
                    "common": {
                        "action": "invokeResponse",
                        "op_id": packet["common"]["op_id"],
                        "timestamp_ms": 1,
                    },
                    "data": {
                        "node_id": packet["data"]["node_id"],
                        "lease_id": self._lease_id,
                        "code": code,
                        "message": message,
                        "result": result,
                    },
                }
            )
        )
        for callback_packet in callback_packets:
            if self.target_mode and params.get("value") == "signal-late" and self.callback_gate is not None:
                asyncio.create_task(self._send_gated_callback(callback_packet))
            else:
                self.callback_events.append(callback_packet)
                await self._websocket.send(json.dumps(callback_packet))

    async def _send_gated_callback(self, packet: dict[str, object]) -> None:
        assert self.callback_gate is not None
        if not await asyncio.to_thread(self.callback_gate.wait, 5):
            return
        self.callback_events.append(packet)
        await self._websocket.send(json.dumps(packet))

def main() -> int:
    """Run the production Runner mock E2E and preserve the standard report gate."""
    from scripts.validation.run_target_mock_tracer import main as run_production_tracer

    try:
        result = run_production_tracer()
    except Exception as exc:
        traceback.print_exc()
        sys.argv = ["generate_report.py", "failed", "E2E-MAC-MOCK", str(exc)]
        generate_report_main()
        sys.argv = ["write_junit.py", "reports/latest/e2e_mock.junit.xml", "E2E-MAC-MOCK", "failed"]
        write_junit_main()
        return 1
    status = "passed" if result == 0 else "failed"
    sys.argv = ["generate_report.py", status, "E2E-MAC-MOCK", "production-mock-e2e"]
    generate_report_main()
    sys.argv = ["write_junit.py", "reports/latest/e2e_mock.junit.xml", "E2E-MAC-MOCK", status]
    write_junit_main()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
