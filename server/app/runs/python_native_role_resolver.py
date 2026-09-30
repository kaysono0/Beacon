"""Python-native 设备角色解析。

作者在 case 中使用 `primary`、`secondary` 等角色；执行时必须从当前在线
`Device` 列表中找到实际 node_id。本模块只做角色到设备的映射，不发送命令。
"""

from __future__ import annotations

from app.devices.device_models import Device, DeviceSelector
from app.common.interfaces import DeviceRegistryProtocol
from app.runs.python_native_models import NativeTestCase


def is_primary_candidate(device: Device) -> bool:
    """判断设备是否属于 primary 的候选集合。"""
    return "role:primary" in device.tags or not any(tag.startswith("role:") for tag in device.tags)


def ordered_devices(devices: list[Device]) -> list[Device]:
    return sorted(devices, key=lambda device: (0 if is_primary_candidate(device) else 1, device.node_id))


def resolve_primary_device(devices: list[Device]) -> Device:
    """按显式 primary、无角色标签、首设备的既有优先级解析 primary。"""
    explicit = next((device for device in devices if "role:primary" in device.tags), None)
    if explicit is not None:
        return explicit
    untagged = next((device for device in devices if not any(tag.startswith("role:") for tag in device.tags)), None)
    if untagged is not None:
        return untagged
    return devices[0]


class RoleResolver:
    """根据 selector 和 role tag 选择/解析设备。"""

    def __init__(self, registry: DeviceRegistryProtocol) -> None:
        self._registry = registry

    async def select_devices_for_cases(self, cases: list[NativeTestCase], selector: DeviceSelector) -> list[Device]:
        """为一组 case 选择候选设备。

        当 case 需要非 primary 角色时，会从 primary 所在 group 扩展出同组设备。
        """
        requires_non_primary = any(role != "primary" for case in cases for role in case.devices)
        if not selector.node_id or not requires_non_primary:
            return ordered_devices([session.device for session in await self._registry.list(selector)])

        primary_session = await self._registry.get(selector.node_id)
        if primary_session is None:
            return []

        primary_device = primary_session.device
        expanded_selector = DeviceSelector(
            platform=selector.platform or primary_device.platform,
            group_id=selector.group_id or primary_device.group_id,
            tags=[tag for tag in selector.tags if not tag.startswith("role:")],
        )
        return ordered_devices([session.device for session in await self._registry.list(expanded_selector)])

    def resolve_device(self, devices: list[Device], role: str) -> tuple[Device | None, dict[str, object] | None]:
        """在已选择设备列表中解析单个角色。"""
        if not devices:
            return None, {"code": 404, "message": "no selected device"}
        if role == "primary":
            return resolve_primary_device(devices), None
        matches = [device for device in devices if f"role:{role}" in device.tags]
        if matches:
            return matches[0], None
        return None, {"code": 404, "message": f"device role not found: {role}"}
