"""Generated from sdk_registry/compiled; do not edit by hand."""

from __future__ import annotations

from typing import Any, Literal
from beacon_test.target_session import BeaconSession, CallResult, ObservationHandle, ResourceRef

class AgoraRtcFacade:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def media_player(self) -> AgoraRtcMediaPlayerInterface:
        return AgoraRtcMediaPlayerInterface(self._session, self._role)

    @property
    def rtc_engine(self) -> AgoraRtcRtcEngineInterface:
        return AgoraRtcRtcEngineInterface(self._session, self._role)

    @property
    def video_preview(self) -> AgoraRtcVideoPreviewInterface:
        return AgoraRtcVideoPreviewInterface(self._session, self._role)

    @property
    def visual_probe(self) -> AgoraRtcVisualProbeInterface:
        return AgoraRtcVisualProbeInterface(self._session, self._role)


class AgoraRtcMediaPlayerInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def open_media_player(self, *, source_path: str, start_pos_ms: int = 0, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['source_path'] = source_path
        params['start_pos_ms'] = start_pos_ms
        return self._session.call(self._role, {'class_name': 'AgoraRtcMediaPlayerProtocol', 'function': 'openMediaPlayer', 'interface': 'media_player', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def pause_media_player(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcMediaPlayerProtocol', 'function': 'pauseMediaPlayer', 'interface': 'media_player', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def play_media_player(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcMediaPlayerProtocol', 'function': 'playMediaPlayer', 'interface': 'media_player', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def resume_media_player(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcMediaPlayerProtocol', 'function': 'resumeMediaPlayer', 'interface': 'media_player', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_media_player(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcMediaPlayerProtocol', 'function': 'stopMediaPlayer', 'interface': 'media_player', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_media_player_state_changed(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcMediaPlayerDelegate', 'function': 'onMediaPlayerStateChanged', 'interface': 'media_player', 'sdk': 'agora_rtc'})


class AgoraRtcRtcEngineInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def enable_local_audio(self, *, enabled: bool, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['enabled'] = enabled
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'enableLocalAudio', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def get_connection_state(self, *, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'getConnectionState', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def join_channel(self, *, channel: str, uid: int, token: str | None = None, auto_subscribe_audio: bool | None = None, auto_subscribe_video: bool | None = None, publish_camera: bool | None = None, publish_microphone: bool | None = None, publish_media_player: bool | None = None, publish_synthetic_audio: bool | None = None, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['channel'] = channel
        params['uid'] = uid
        if token is not None:
            params['token'] = token
        if auto_subscribe_audio is not None:
            params['auto_subscribe_audio'] = auto_subscribe_audio
        if auto_subscribe_video is not None:
            params['auto_subscribe_video'] = auto_subscribe_video
        if publish_camera is not None:
            params['publish_camera'] = publish_camera
        if publish_microphone is not None:
            params['publish_microphone'] = publish_microphone
        if publish_media_player is not None:
            params['publish_media_player'] = publish_media_player
        if publish_synthetic_audio is not None:
            params['publish_synthetic_audio'] = publish_synthetic_audio
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'joinChannel', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def leave_channel(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'leaveChannel', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def load_sdk(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'SDKLifecycle', 'function': 'loadSDK', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def renew_token(self, *, token: str, uid: int | None = None, channel: str | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['token'] = token
        if uid is not None:
            params['uid'] = uid
        if channel is not None:
            params['channel'] = channel
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'renewToken', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def set_dual_stream_mode(self, *, mode: Literal['auto', 'enabled', 'disabled'], low_bitrate: int | None = None, low_fps: int | None = None, low_height: int | None = None, low_width: int | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['mode'] = mode
        if low_bitrate is not None:
            params['low_bitrate'] = low_bitrate
        if low_fps is not None:
            params['low_fps'] = low_fps
        if low_height is not None:
            params['low_height'] = low_height
        if low_width is not None:
            params['low_width'] = low_width
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'setDualStreamMode', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def set_remote_video_stream(self, *, uid: int, stream_type: Literal['high', 'low'], check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['uid'] = uid
        params['stream_type'] = stream_type
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'setRemoteVideoStream', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def start_synthetic_video(self, *, fps: int = 15, height: int = 180, pattern: Literal['animated_clip', 'paired_media_clip', 'bars', 'moving_stripe'] = 'animated_clip', width: int = 320, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['fps'] = fps
        params['height'] = height
        params['pattern'] = pattern
        params['width'] = width
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'startSyntheticVideo', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_synthetic_video(self, *, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'stopSyntheticVideo', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def unload_sdk(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'SDKLifecycle', 'function': 'unloadSDK', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_connection_state_changed(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onConnectionStateChanged', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_error(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onError', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_first_remote_video_frame(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onFirstRemoteVideoFrame', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_join_channel_success(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onJoinChannelSuccess', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_local_video_stats(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onLocalVideoStats', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_remote_audio_stats(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onRemoteAudioStats', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_remote_video_stats(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onRemoteVideoStats', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_rtc_stats(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onRtcStats', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_snapshot_requested(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onSnapshotRequested', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    @property
    def on_snapshot_taken(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'AgoraRtcEngineDelegate', 'function': 'onSnapshotTaken', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})

    def is_joined(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'isJoined', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def is_joined_observations(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'state', {'class_name': 'AgoraRtcEngineKit', 'function': 'isJoined', 'interface': 'rtc_engine', 'sdk': 'agora_rtc'})


class AgoraRtcVideoPreviewInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def start_preview(self, *, _extra: dict[str, Any] | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        if _extra is not None:
            params['_extra'] = _extra
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'startPreview', 'interface': 'video_preview', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_preview(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'stopPreview', 'interface': 'video_preview', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def is_previewing(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'AgoraRtcEngineKit', 'function': 'isPreviewing', 'interface': 'video_preview', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def is_previewing_observations(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'state', {'class_name': 'AgoraRtcEngineKit', 'function': 'isPreviewing', 'interface': 'video_preview', 'sdk': 'agora_rtc'})


class AgoraRtcVisualProbeInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def bind_local_video(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'AgoraVisualProbe', 'function': 'bindLocalVideo', 'interface': 'visual_probe', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def bind_remote_video(self, *, uid: int, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['uid'] = uid
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'AgoraVisualProbe', 'function': 'bindRemoteVideo', 'interface': 'visual_probe', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def capture_snapshot(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'AgoraVisualProbe', 'function': 'captureSnapshot', 'interface': 'visual_probe', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def release_view(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'AgoraVisualProbe', 'function': 'releaseView', 'interface': 'visual_probe', 'sdk': 'agora_rtc'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)
