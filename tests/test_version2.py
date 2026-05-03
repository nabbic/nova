import pytest
from starlette.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_get_version2_returns_200_status_code(client):
    response = client.get("/api/version2")
    assert response.status_code == 200


def test_get_version2_returns_json_body_with_version_field(client):
    response = client.get("/api/version2")
    body = response.json()
    assert "version" in body


def test_get_version2_returns_version_value_2_0_0(client):
    response = client.get("/api/version2")
    body = response.json()
    assert body["version"] == "2.0.0"


def test_get_version2_returns_exact_json_body(client):
    response = client.get("/api/version2")
    assert response.json() == {"version": "2.0.0"}


def test_get_version2_returns_content_type_json(client):
    response = client.get("/api/version2")
    assert "application/json" in response.headers.get("content-type", "")


def test_get_version2_does_not_require_auth_returns_200_without_token(client):
    response = client.get("/api/version2")
    assert response.status_code == 200


def test_get_version2_unauthenticated_request_does_not_return_401(client):
    response = client.get("/api/version2")
    assert response.status_code != 401


def test_get_version2_unauthenticated_request_does_not_return_403(client):
    response = client.get("/api/version2")
    assert response.status_code != 403


def test_health_endpoint_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_returns_status_ok(client):
    response = client.get("/health")
    assert response.json() == {"status": "ok"}
