"""Server smoke 和基础 API 响应模型。

运行时模型放在 device_models 和 test_models；这里保留启动状态和认证 smoke 的响应结构。
"""

from pydantic import BaseModel


class StatusResponse(BaseModel):
    service: str
    status: str
    version: str


class ProtectedSmokeResponse(BaseModel):
    status: str
