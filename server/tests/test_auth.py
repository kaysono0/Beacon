from fastapi.testclient import TestClient

from app.main import app


def test_it_srv_002_protected_route_rejects_missing_auth(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/protected-smoke")

    assert response.status_code == 401


def test_it_srv_003_protected_route_rejects_wrong_auth(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/protected-smoke", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_it_srv_004_protected_route_accepts_valid_auth(monkeypatch):
    monkeypatch.setenv("BEACON_AUTH_TOKEN", "local-test-token")
    client = TestClient(app)

    response = client.get("/api/v1/protected-smoke", headers={"Authorization": "Bearer local-test-token"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
