import pytest
from fastapi.testclient import TestClient

import app.sdk.agora_token as agora_token
from app.main import app


AUTH = {"Authorization": "Bearer local-test-token"}


class FixedSigner:
    def build_rtc_token(self, app_id: str, app_cert: str, channel: str, uid: int, role: str, ttl_seconds: int) -> str:
        assert app_id == "app-123"
        assert app_cert == "cert-123"
        assert channel == "beacon-smoke-001"
        assert uid == 1001
        assert role == "publisher"
        assert ttl_seconds == 3600
        return "runtime-token"


def test_IT_AGORA_01_token_endpoint_returns_runtime_token(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    monkeypatch.setenv("AGORA_APP_ID", "app-123")
    monkeypatch.setenv("AGORA_APP_CERT", "cert-123")
    monkeypatch.setattr(agora_token, "token_signer", FixedSigner())
    client = TestClient(app)

    response = client.post(
        "/api/v1/agora/token",
        headers=AUTH,
        json={"channel": "beacon-smoke-001", "uid": 1001, "role": "publisher", "ttl_seconds": 3600},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["app_id"] == "<redacted>"
    assert body["token"] == "runtime-token"
    assert body["channel"] == "beacon-smoke-001"
    assert body["uid"] == 1001
    assert body["expires_at"]
    assert "cert-123" not in response.text


def test_IT_AGORA_02_token_endpoint_rejects_missing_credentials(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    monkeypatch.delenv("AGORA_APP_ID", raising=False)
    monkeypatch.delenv("AGORA_APP_CERT", raising=False)
    client = TestClient(app)

    response = client.post("/api/v1/agora/token", headers=AUTH, json={"channel": "beacon-smoke-001", "uid": 1001})

    assert response.status_code == 500
    assert response.json()["detail"] == "missing agora credentials"


def test_IT_AGORA_03_token_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    client = TestClient(app)

    response = client.post("/api/v1/agora/token", json={"channel": "beacon-smoke-001", "uid": 1001})

    assert response.status_code == 401


def test_IT_AGORA_04_token_endpoint_requires_test_mode(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.delenv("BEACON_ENABLE_TEST_ENDPOINTS", raising=False)
    client = TestClient(app)

    response = client.post("/api/v1/agora/token", headers=AUTH, json={"channel": "beacon-smoke-001", "uid": 1001})

    assert response.status_code == 404


def test_IT_AGORA_05_token_endpoint_rejects_missing_signer(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    monkeypatch.setenv("BEACON_ENABLE_TEST_ENDPOINTS", "true")
    monkeypatch.setenv("AGORA_APP_ID", "app-123")
    monkeypatch.setenv("AGORA_APP_CERT", "cert-123")
    monkeypatch.setattr(agora_token, "token_signer", agora_token.AgoraAccessTokenSigner())
    monkeypatch.setattr(agora_token.AgoraAccessTokenSigner, "_import_builder", lambda self: None)
    client = TestClient(app)

    response = client.post("/api/v1/agora/token", headers=AUTH, json={"channel": "beacon-smoke-001", "uid": 1001})

    assert response.status_code == 500
    assert response.json()["detail"] == "missing token signer"


def test_IT_AGORA_06_token_signer_uses_installed_builder():
    # agora-token-builder 是可选 extra（beacon-server[agora]）；未安装时跳过真实签发验证。
    pytest.importorskip("agora_token_builder")
    token = agora_token.AgoraAccessTokenSigner().build_rtc_token(
        "0123456789abcdef0123456789abcdef",
        "abcdef0123456789abcdef0123456789",
        "beacon-smoke-001",
        1001,
        "publisher",
        3600,
    )

    assert isinstance(token, str)
    assert token
