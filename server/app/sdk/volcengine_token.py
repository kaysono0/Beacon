"""火山引擎 RTC token 签发服务。

签发实现来自 vendored 的官方 Python 示例（`server/vendor/volcengine_rtc_token/`），
本模块只做凭证读取与响应投影；凭证与 token 不写入日志。
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class VolcengineTokenRequest(BaseModel):
    room_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    ttl_seconds: int | None = Field(default=None, gt=0)


class VolcengineTokenResponse(BaseModel):
    app_id: str
    token: str
    room_id: str
    user_id: str
    expires_at: str


class VolcengineAccessTokenSigner:
    """惰性导入 vendored builder：缺失时给出明确错误而不是 ImportError 透传。"""

    def _import_builder(self) -> Any:
        try:
            from vendor.volcengine_rtc_token import AccessToken
        except ImportError as exc:
            raise RuntimeError("missing volcengine token builder") from exc
        return AccessToken

    def build_rtc_token(self, app_id: str, app_key: str, room_id: str, user_id: str, ttl_seconds: int) -> str:
        builder = self._import_builder()
        if builder is None:
            raise RuntimeError("missing volcengine token builder")
        expire_at = int(time.time()) + ttl_seconds
        token = builder.AccessToken(app_id, app_key, room_id, user_id)
        token.add_privilege(builder.PrivSubscribeStream, expire_at)
        token.add_privilege(builder.PrivPublishStream, expire_at)
        token.expire_time(expire_at)
        return token.serialize()


token_signer: Any = VolcengineAccessTokenSigner()


def create_volcengine_token(request: VolcengineTokenRequest) -> VolcengineTokenResponse:
    if os.environ.get("BEACON_ENABLE_TEST_ENDPOINTS") != "true":
        raise HTTPException(status_code=404, detail="not found")
    app_id = os.environ.get("VOLCENGINE_RTC_ID")
    app_key = os.environ.get("VOLCENGINE_RTC_APPKEY")
    if not app_id or not app_key:
        raise HTTPException(status_code=500, detail="missing volcengine credentials")
    ttl_seconds = request.ttl_seconds or int(os.environ.get("VOLCENGINE_TOKEN_TTL_SECONDS", "3600"))
    try:
        token = token_signer.build_rtc_token(app_id, app_key, request.room_id, request.user_id, ttl_seconds)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    return VolcengineTokenResponse(
        app_id="<redacted>",
        token=token,
        room_id=request.room_id,
        user_id=request.user_id,
        expires_at=expires_at.isoformat().replace("+00:00", "Z"),
    )
