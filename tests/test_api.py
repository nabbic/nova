import pytest
from starlette.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_version2_returns_200(client):
    response = client.get("/api/version2")
    assert response.status_code == 200


def test_version2_returns_correct_body(client):
    response = client.get("/api/version2")
    assert response.json() == {"version": "2.0.0"}


def test_version2_no_auth_required(client):
    """Endpoint must be accessible without any Authorization header."""
    response = client.get("/api/version2")
    assert response.status_code == 200


def test_version2_response_is_valid_json(client):
    response = client.get("/api/version2")
    data = response.json()
    assert isinstance(data, dict)
    assert "version" in data


def test_version2_version_field_is_string(client):
    response = client.get("/api/version2")
    data = response.json()
    assert isinstance(data["version"], str)


def test_version2_version_value_is_2_0_0(client):
    response = client.get("/api/version2")
    assert response.json()["version"] == "2.0.0"
