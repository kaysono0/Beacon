"""火山引擎 RTC 服务端装配测试：签发端点、占位符、隔离默认策略与 vendored builder。"""

import time

import pytest
from fastapi.testclient import TestClient

import app.sdk.sdk_extensions as sdk_extensions
import app.sdk.volcengine_token as volcengine_token
from app.main import app
from vendor.volcengine_rtc_token import AccessToken

AUTH = {"Authorization": "Bearer local-test-token"}

APP_ID = "0123456789abcdef01234567"
APP_KEY = "abcdef0123456789abcdef0123456789"


class FixedSigner:
    def build_rtc_token(self, app_id: str, app_key: str, room_id: str, user_id: str, ttl_seconds: int) -> str:
        assert app_id == APP_ID
        assert app_key == APP_KEY
        assert room_id == "beacon-room-001"
        assert user_id == "beacon-user-001"
        assert ttl_seconds == 3600
        return "runtime-volcengine-token"


def test_IT_VOLCENGINE_01_token_endpoint_returns_runtime_token(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    monkeypatch.setenv("VOLCENGINE_RTC_ID", APP_ID)
    monkeypatch.setenv("VOLCENGINE_RTC_APPKEY", APP_KEY)
    monkeypatch.setattr(volcengine_token, "token_signer", FixedSigner())
    client = TestClient(app)

    response = client.post(
        "/api/v1/volcengine/token",
        headers=AUTH,
        json={"room_id": "beacon-room-001", "user_id": "beacon-user-001", "ttl_seconds": 3600},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["app_id"] == "<redacted>"
    assert body["token"] == "runtime-volcengine-token"
    assert body["room_id"] == "beacon-room-001"
    assert body["user_id"] == "beacon-user-001"
    assert body["expires_at"]
    assert APP_KEY not in response.text


def test_IT_VOLCENGINE_02_token_endpoint_rejects_missing_credentials(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    monkeypatch.delenv("VOLCENGINE_RTC_ID", raising=False)
    monkeypatch.delenv("VOLCENGINE_RTC_APPKEY", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/v1/volcengine/token", headers=AUTH, json={"room_id": "beacon-room-001", "user_id": "beacon-user-001"}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "missing volcengine credentials"


def test_IT_VOLCENGINE_03_token_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    client = TestClient(app)

    response = client.post("/api/v1/volcengine/token", json={"room_id": "beacon-room-001", "user_id": "beacon-user-001"})

    assert response.status_code == 401


def test_IT_VOLCENGINE_04_token_endpoint_requires_test_mode(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.delenv("BEACON_ENABLE_TEST_ENDPOINTS", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/v1/volcengine/token", headers=AUTH, json={"room_id": "beacon-room-001", "user_id": "beacon-user-001"}
    )

    assert response.status_code == 404


def test_IT_VOLCENGINE_05_token_endpoint_rejects_missing_builder(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    monkeypatch.setenv("VOLCENGINE_RTC_ID", APP_ID)
    monkeypatch.setenv("VOLCENGINE_RTC_APPKEY", APP_KEY)
    monkeypatch.setattr(volcengine_token, "token_signer", volcengine_token.VolcengineAccessTokenSigner())
    monkeypatch.setattr(volcengine_token.VolcengineAccessTokenSigner, "_import_builder", lambda self: None)
    client = TestClient(app)

    response = client.post(
        "/api/v1/volcengine/token", headers=AUTH, json={"room_id": "beacon-room-001", "user_id": "beacon-user-001"}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "missing volcengine token builder"


def test_IT_VOLCENGINE_06_vendored_builder_signs_a_verifiable_token():
    """vendored builder 逐字来自官方示例：签出的 token 必须能用同一 app key 验签。"""
    token = volcengine_token.VolcengineAccessTokenSigner().build_rtc_token(
        APP_ID, APP_KEY, "beacon-room-001", "beacon-user-001", 3600
    )

    assert isinstance(token, str) and token
    assert token.startswith("001")
    assert token[3 : 3 + len(APP_ID)] == APP_ID

    parsed = AccessToken.parse(token)
    assert parsed is not None
    assert parsed.room_id == "beacon-room-001"
    assert parsed.user_id == "beacon-user-001"
    assert parsed.expire_at > int(time.time())
    assert parsed.verify(APP_KEY) is True
    assert parsed.verify("wrong-key") is False


def test_IT_VOLCENGINE_07_placeholder_resolves_token_map_then_falls_back_to_env(monkeypatch):
    monkeypatch.setenv(
        sdk_extensions.VOLCENGINE_TOKEN_MAP_ENV,
        '{"beacon-room-001#beacon-user-001": "mapped-token"}',
    )
    monkeypatch.setenv("VOLCENGINE_RTC_TOKEN", "fallback-token")

    assert sdk_extensions.resolve_volcengine_rtc_token(
        {"room_id": "beacon-room-001", "user_id": "beacon-user-001"}
    ) == "mapped-token"
    # 键不命中 → 回退环境变量；参数不完整 → 同样回退。
    assert sdk_extensions.resolve_volcengine_rtc_token({"room_id": "other", "user_id": "beacon-user-001"}) == "fallback-token"
    assert sdk_extensions.resolve_volcengine_rtc_token({"room_id": "beacon-room-001"}) == "fallback-token"

    monkeypatch.delenv("VOLCENGINE_RTC_TOKEN", raising=False)
    assert sdk_extensions.resolve_volcengine_rtc_token({}) == ""


def test_IT_VOLCENGINE_08_placeholder_is_registered_in_the_assembly_resolver():
    resolver = sdk_extensions.build_param_resolver()

    assert sdk_extensions.VOLCENGINE_RTC_TOKEN_PLACEHOLDER in sdk_extensions.SDK_PARAM_RESOLVERS
    assert resolver is not None


def test_IT_VOLCENGINE_09_default_runtime_isolation_covers_volcengine_targets():
    assert sdk_extensions.default_runtime_isolation([{"sdk": "volcengine_rtc"}]) is True
    assert sdk_extensions.case_requires_runtime_isolation([], ["volcengine_rtc"]) is True
    assert sdk_extensions.default_runtime_isolation([{"sdk": "mock_echo"}]) is False
