"""Generated from sdk_registry/compiled; do not edit by hand."""

from __future__ import annotations

from typing import Any, Literal
from beacon_test.target_session import BeaconSession, CallResult, ObservationHandle, ResourceRef

class ZegoExpressFacade:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    @property
    def zego_engine(self) -> ZegoExpressZegoEngineInterface:
        return ZegoExpressZegoEngineInterface(self._session, self._role)

    @property
    def zego_player(self) -> ZegoExpressZegoPlayerInterface:
        return ZegoExpressZegoPlayerInterface(self._session, self._role)

    @property
    def zego_preview(self) -> ZegoExpressZegoPreviewInterface:
        return ZegoExpressZegoPreviewInterface(self._session, self._role)

    @property
    def zego_publisher(self) -> ZegoExpressZegoPublisherInterface:
        return ZegoExpressZegoPublisherInterface(self._session, self._role)

    @property
    def zego_room(self) -> ZegoExpressZegoRoomInterface:
        return ZegoExpressZegoRoomInterface(self._session, self._role)

    @property
    def zego_visual_probe(self) -> ZegoExpressZegoVisualProbeInterface:
        return ZegoExpressZegoVisualProbeInterface(self._session, self._role)


class ZegoExpressZegoEngineInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def create_engine_with_profile(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'createEngineWithProfile', 'interface': 'zego_engine', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def destroy_engine(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'destroyEngine', 'interface': 'zego_engine', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)


class ZegoExpressZegoPlayerInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def start_playing_stream(self, *, stream_id: str, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['stream_id'] = stream_id
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'startPlayingStream', 'interface': 'zego_player', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_playing_stream(self, *, stream_id: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['stream_id'] = stream_id
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'stopPlayingStream', 'interface': 'zego_player', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_player_render_video_first_frame(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ZegoEventHandler', 'function': 'onPlayerRenderVideoFirstFrame', 'interface': 'zego_player', 'sdk': 'zego_express'})

    @property
    def on_player_state_update(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ZegoEventHandler', 'function': 'onPlayerStateUpdate', 'interface': 'zego_player', 'sdk': 'zego_express'})


class ZegoExpressZegoPreviewInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def start_preview(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'startPreview', 'interface': 'zego_preview', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_preview(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'stopPreview', 'interface': 'zego_preview', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)


class ZegoExpressZegoPublisherInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def start_publishing_stream(self, *, stream_id: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['stream_id'] = stream_id
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'startPublishingStream', 'interface': 'zego_publisher', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def start_synthetic_video(self, *, width: int, height: int, fps: int, pattern: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['width'] = width
        params['height'] = height
        params['fps'] = fps
        params['pattern'] = pattern
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'startSyntheticVideo', 'interface': 'zego_publisher', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_publishing_stream(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'stopPublishingStream', 'interface': 'zego_publisher', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def stop_synthetic_video(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'stopSyntheticVideo', 'interface': 'zego_publisher', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_publisher_state_update(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ZegoEventHandler', 'function': 'onPublisherStateUpdate', 'interface': 'zego_publisher', 'sdk': 'zego_express'})


class ZegoExpressZegoRoomInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def login_room(self, *, room_id: str, user_id: str, token: str | None = None, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['room_id'] = room_id
        params['user_id'] = user_id
        if token is not None:
            params['token'] = token
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'loginRoom', 'interface': 'zego_room', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def logout_room(self, *, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        return self._session.call(self._role, {'class_name': 'ZegoExpressEngine', 'function': 'logoutRoom', 'interface': 'zego_room', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_room_state_update(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'ZegoEventHandler', 'function': 'onRoomStateUpdate', 'interface': 'zego_room', 'sdk': 'zego_express'})


class ZegoExpressZegoVisualProbeInterface:
    def __init__(self, session: BeaconSession, role: str) -> None:
        self._session = session
        self._role = role

    def capture_snapshot(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ZegoVisualProbe', 'function': 'captureSnapshot', 'interface': 'zego_visual_probe', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    def release_view(self, *, view_role: str, check: bool = True, timeout_s: float = 5.0, resource: ResourceRef | None = None, create_resource: bool = False) -> CallResult[Any]:
        params: dict[str, Any] = {}
        params['view_role'] = view_role
        return self._session.call(self._role, {'class_name': 'ZegoVisualProbe', 'function': 'releaseView', 'interface': 'zego_visual_probe', 'sdk': 'zego_express'}, params, check=check, timeout_s=timeout_s, resource=resource, create_resource=create_resource)

    @property
    def on_rendered_view_snapshot(self) -> ObservationHandle:
        return ObservationHandle(self._session, self._role, 'callback', {'class_name': 'BeaconZegoVisualProbe', 'function': 'onRenderedViewSnapshot', 'interface': 'zego_visual_probe', 'sdk': 'zego_express'})
