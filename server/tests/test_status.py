from fastapi.testclient import TestClient

from app.main import app


def test_it_srv_001_status_returns_service_state():
    client = TestClient(app)
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "beacon-server"
