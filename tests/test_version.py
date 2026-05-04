from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_version_v2_returns_200():
    response = client.get("/api/version-v2")
    assert response.status_code == 200


def test_version_v2_returns_correct_body():
    response = client.get("/api/version-v2")
    assert response.json() == {"version": "2.0"}


def test_version_v2_no_auth_required():
    response = client.get("/api/version-v2", headers={})
    assert response.status_code == 200


def test_version_v1_still_works():
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json() == {"version": "1.0"}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
