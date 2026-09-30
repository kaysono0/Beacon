"""SDK 专有的控制面扩展装配点。

控制面模块只实现平台无关机制：占位符 resolver 注册表、runtime isolation 判定入口和
测试端点装配循环。具体 SDK 的名字、凭证环境变量和端点路径只允许出现在这里，
按 ADR-002 不得散落到 `app.python_native*` 或 `app.main`。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from pydantic import BaseModel

from app.sdk.agora_token import AgoraTokenResponse, create_agora_token
from app.sdk.volcengine_token import VolcengineTokenResponse, create_volcengine_token
from app.runs.python_native_runtime import (
    PlaceholderResolver,
    RuntimeParamResolver,
    declared_runtime_isolation,
)

AGORA_RTC_TOKEN_PLACEHOLDER = "{{AGORA_RTC_TOKEN}}"
VOLCENGINE_RTC_TOKEN_PLACEHOLDER = "{{VOLCENGINE_RTC_TOKEN}}"

# token map 环境变量与键格式是占位符契约的一部分：装配方（本地 runner）与消费方（Server）都从这里取。
TOKEN_MAP_ENV = "BEACON_AGORA_RTC_TOKEN_MAP"
VOLCENGINE_TOKEN_MAP_ENV = "BEACON_VOLCENGINE_RTC_TOKEN_MAP"

# 仅传递影响用例身份的非秘密配置，SDK 凭证与 Token 继续由 Server 持有。
SDK_RUNNER_ENVIRONMENT_NAMES = ("VOLCENGINE_RTC_ROOM_ID", "VOLCENGINE_RTC_USER_ID")

# 未声明 runtime isolation 的 case 沿用这条默认策略：只有 Agora RTC target 会在长驻
# Agent 上留下跨 case 的引擎状态，因此需要 case 前后各 reset 一次。
ISOLATION_REQUIRED_SDKS = frozenset({"agora_rtc", "volcengine_rtc"})


def token_map_key(channel: str, uid: int) -> str:
    """BEACON_AGORA_RTC_TOKEN_MAP 的键格式：`{channel}#{uid}`。"""
    return f"{channel}#{uid}"


def resolve_mapped_token(
    params: dict[str, Any],
    *,
    identity_fields: tuple[str, str],
    token_map_env: str,
    fallback_token_env: str,
) -> str:
    """按两个 adapter 声明的身份字段解析 token map，并保留原有环境变量契约。"""
    first = params.get(identity_fields[0])
    second = params.get(identity_fields[1])
    token_map_text = os.environ.get(token_map_env, "")
    if token_map_text and isinstance(first, str) and isinstance(second, (str, int)):
        try:
            token_map = json.loads(token_map_text)
        except json.JSONDecodeError:
            token_map = {}
        token = token_map.get(f"{first}#{second}")
        if isinstance(token, str) and token:
            return token
    return os.environ.get(fallback_token_env, "")


def resolve_agora_rtc_token(params: dict[str, Any]) -> str:
    """按 `{channel}#{uid}` token map 取值，未命中回退 `AGORA_RTC_TOKEN`，缺失则为空串。"""
    return resolve_mapped_token(
        params,
        identity_fields=("channel", "uid"),
        token_map_env=TOKEN_MAP_ENV,
        fallback_token_env="AGORA_RTC_TOKEN",
    )


def volcengine_token_map_key(room_id: str, user_id: str) -> str:
    """BEACON_VOLCENGINE_RTC_TOKEN_MAP 的键格式：`{room_id}#{user_id}`。"""
    return f"{room_id}#{user_id}"


def resolve_volcengine_rtc_token(params: dict[str, Any]) -> str:
    """按 `{room_id}#{user_id}` token map 取值，未命中回退 `VOLCENGINE_RTC_TOKEN`，缺失则为空串。"""
    return resolve_mapped_token(
        params,
        identity_fields=("room_id", "user_id"),
        token_map_env=VOLCENGINE_TOKEN_MAP_ENV,
        fallback_token_env="VOLCENGINE_RTC_TOKEN",
    )


SDK_PARAM_RESOLVERS: dict[str, PlaceholderResolver] = {
    AGORA_RTC_TOKEN_PLACEHOLDER: resolve_agora_rtc_token,
    VOLCENGINE_RTC_TOKEN_PLACEHOLDER: resolve_volcengine_rtc_token,
}


def build_param_resolver() -> RuntimeParamResolver:
    """装配带全部已注册 SDK 占位符的运行期参数解析器。"""
    return RuntimeParamResolver(SDK_PARAM_RESOLVERS)


def default_runtime_isolation(targets: Iterable[dict[str, Any]]) -> bool:
    """case 未声明 runtime isolation 时的默认判定。"""
    return any(target.get("sdk") in ISOLATION_REQUIRED_SDKS for target in targets)


def case_requires_runtime_isolation(tags: Iterable[str], sdk_names: Iterable[str]) -> bool:
    """case 级 runtime isolation 的统一判定：tag 声明优先，未声明回退 SDK 装配默认策略。

    与执行链 `_requires_runtime_isolation` 共用 tag 语义，但把最终判定投影给 Console，
    使 App 端 cleanup 触发不依赖任何具体 SDK 名。
    """
    declared = declared_runtime_isolation(tags)
    if declared is not None:
        return declared
    return bool(ISOLATION_REQUIRED_SDKS.intersection(sdk_names))


@dataclass(frozen=True)
class TestEndpoint:
    """SDK 专有测试端点的声明式装配描述。"""

    path: str
    method: str
    response_model: type[BaseModel]
    handler: Callable[[Any], Any]
    # FastAPI 用路由名推导 OpenAPI operationId 与 summary；不显式声明就会跟随 handler 函数名漂移。
    name: str


SDK_TEST_ENDPOINTS: tuple[TestEndpoint, ...] = (
    TestEndpoint(
        path="/api/v1/agora/token",
        method="POST",
        response_model=AgoraTokenResponse,
        handler=create_agora_token,
        name="agora_token",
    ),
    TestEndpoint(
        path="/api/v1/volcengine/token",
        method="POST",
        response_model=VolcengineTokenResponse,
        handler=create_volcengine_token,
        name="volcengine_token",
    ),
)
