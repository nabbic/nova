from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_info_returns_200():
    response = client.get("/api/health-info")
    assert response.status_code == 200


def test_health_info_returns_correct_body():
    response = client.get("/api/health-info")
    assert response.json() == {"factory_generation": "v2", "cutover_at": "2026-05-04"}


def test_health_info_no_auth_required():
    response = client.get("/api/health-info", headers={})
    assert response.status_code == 200
