"""Beacon Server 认证入口。

服务端只从环境变量读取本地测试 token，业务路由通过 Depends 注入认证检查。
"""

import os
from typing import Annotated

from fastapi import Header, HTTPException


def require_auth(authorization: Annotated[str | None, Header()] = None) -> None:
    """校验 HTTP Authorization header。

    认证失败统一返回 401，不伪装成协议错误或设备离线。
    """
    token = os.environ.get("BEACON_AUTH_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="missing server token")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="invalid authorization")
