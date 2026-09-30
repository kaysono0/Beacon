"""Generated from sdk_registry/compiled; do not edit by hand."""

from __future__ import annotations

from typing import Any, Literal
from beacon_test.target_session import BeaconSession, CallResult, ObservationHandle, ResourceRef

class VolcengineRtcFacade:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def byte_rtc_engine(self) -> VolcengineRtcByteRtcEngineInterface:
        return VolcengineRtcByteRtcEngineInterface(self._session, self._role)

    @property
    def byte_rtc_room(self) -> VolcengineRtcByteRtcRoomInterface:
        return VolcengineRtcByteRtcRoomInterface(self._session, self._role)

    @property
    def visual_probe(self) -> VolcengineRtcVisualProbeInterface:
        return VolcengineRtcVisualProbeInterface(self._session, self._role)


class VolcengineRtcByteRtcEngineInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def create_rtc_engine(self, *, app_id: str | None = None, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        if app_id is not None:
            params['app_id'] = app_id
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'ByteRTCEngine', 'function': 'createRTCEngine', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def destroy_rtc_engine(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ByteRTCEngine', 'function': 'destroyRTCEngine', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def start_synthetic_video(self, *, fps: int = 15, height: int = 180, pattern: Literal['animated_clip', 'bars', 'moving_stripe'] = 'animated_clip', width: int = 320, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['fps'] = fps
        params['height'] = height
        params['pattern'] = pattern
        params['width'] = width
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'ByteRTCEngine', 'function': 'startSyntheticVideo', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def start_video_capture(self, *, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'ByteRTCEngine', 'function': 'startVideoCapture', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_synthetic_video(self, *, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'ByteRTCEngine', 'function': 'stopSyntheticVideo', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_video_capture(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ByteRTCEngine', 'function': 'stopVideoCapture', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_connection_state_changed(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCEngineDelegate', 'function': 'onConnectionStateChanged', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'})

    @property
    def on_error(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCEngineDelegate', 'function': 'onError', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'})

    @property
    def on_first_remote_video_frame(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCEngineDelegate', 'function': 'onFirstRemoteVideoFrame', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'})

    @property
    def on_snapshot_requested(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCEngineDelegate', 'function': 'onSnapshotRequested', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'})

    @property
    def on_snapshot_taken(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCEngineDelegate', 'function': 'onSnapshotTaken', 'interface': 'byte_rtc_engine', 'sdk': 'volcengine_rtc'})


class VolcengineRtcByteRtcRoomInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def join_room(self, *, room_id: str, user_id: str, token: str, auto_subscribe_audio: bool = True, auto_subscribe_video: bool = False, publish_audio: bool = True, publish_video: bool = False, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['room_id'] = room_id
        params['user_id'] = user_id
        params['token'] = token
        params['auto_subscribe_audio'] = auto_subscribe_audio
        params['auto_subscribe_video'] = auto_subscribe_video
        params['publish_audio'] = publish_audio
        params['publish_video'] = publish_video
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'ByteRTCRoom', 'function': 'joinRoom', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def leave_room(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ByteRTCRoom', 'function': 'leaveRoom', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_leave_room(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCRoomDelegate', 'function': 'onLeaveRoom', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'})

    @property
    def on_local_video_stats(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCRoomDelegate', 'function': 'onLocalVideoStats', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'})

    @property
    def on_remote_video_stats(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCRoomDelegate', 'function': 'onRemoteVideoStats', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'})

    @property
    def on_room_state_changed(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCRoomDelegate', 'function': 'onRoomStateChanged', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'})

    @property
    def on_rtc_stats(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ByteRTCRoomDelegate', 'function': 'onRtcStats', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'})

    def on_room_state_changed_with_reason(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ByteRTCRoom', 'function': 'onRoomStateChangedWithReason', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_room_state_changed_with_reason_observations(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'state', {'class_name': 'ByteRTCRoom', 'function': 'onRoomStateChangedWithReason', 'interface': 'byte_rtc_room', 'sdk': 'volcengine_rtc'})


class VolcengineRtcVisualProbeInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def bind_local_video(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ByteRTCVisualProbe', 'function': 'bindLocalVideo', 'interface': 'visual_probe', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def bind_remote_video(self, *, uid: str, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['uid'] = uid
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ByteRTCVisualProbe', 'function': 'bindRemoteVideo', 'interface': 'visual_probe', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def capture_snapshot(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ByteRTCVisualProbe', 'function': 'captureSnapshot', 'interface': 'visual_probe', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def release_view(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ByteRTCVisualProbe', 'function': 'releaseView', 'interface': 'visual_probe', 'sdk': 'volcengine_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)
