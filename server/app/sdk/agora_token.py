"""Agora token 签发服务。

该模块只从运行时环境读取测试凭证，不把 app cert 或 token 写入日志。
"""

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class AgoraTokenRequest(BaseModel):
    channel: str = Field(min_length=1)
    uid: int = Field(ge=0)
    role: str = "publisher"
    ttl_seconds: int | None = Field(default=None, gt=0)


class AgoraTokenResponse(BaseModel):
    app_id: str
    token: str
    channel: str
    uid: int
    expires_at: str


class AgoraAccessTokenSigner:
    def _import_builder(self) -> Any:
        try:
            from agora_token_builder import RtcTokenBuilder
        except ImportError as exc:
            raise RuntimeError("missing token signer") from exc
        return RtcTokenBuilder

    def build_rtc_token(self, app_id: str, app_cert: str, channel: str, uid: int, role: str, ttl_seconds: int) -> str:
        builder = self._import_builder()
        if builder is None:
            raise RuntimeError("missing token signer")
        role_value = 1 if role == "publisher" else 2
        expire_at = int(time.time()) + ttl_seconds
        return builder.buildTokenWithUid(app_id, app_cert, channel, uid, role_value, expire_at)


token_signer: Any = AgoraAccessTokenSigner()


def create_agora_token(request: AgoraTokenRequest) -> AgoraTokenResponse:
    if os.environ.get("BEACON_ENABLE_TEST_ENDPOINTS") != "true":
        raise HTTPException(status_code=404, detail="not found")
    app_id = os.environ.get("AGORA_APP_ID")
    app_cert = os.environ.get("AGORA_APP_CERT")
    if not app_id or not app_cert:
        raise HTTPException(status_code=500, detail="missing agora credentials")
    ttl_seconds = request.ttl_seconds or int(os.environ.get("AGORA_TOKEN_TTL_SECONDS", "3600"))
    try:
        token = token_signer.build_rtc_token(app_id, app_cert, request.channel, request.uid, request.role, ttl_seconds)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    return AgoraTokenResponse(
        app_id="<redacted>",
        token=token,
        channel=request.channel,
        uid=request.uid,
        expires_at=expires_at.isoformat().replace("+00:00", "Z"),
    )
