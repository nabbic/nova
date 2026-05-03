"""Integration tests for GET /api/version2 endpoint."""
import pytest
from starlette.testclient import TestClient


def get_app():
    """Import the FastAPI app, skipping if not available."""
    return pytest.importorskip("app.main", reason="app.main not found").app


@pytest.fixture(scope="module")
def client():
    app = get_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Acceptance criterion:
# Given an unauthenticated client, when GET /api/version2 is called,
# then the response is 200 OK with JSON body {"version": "2.0.0"}
# ---------------------------------------------------------------------------

def test_version2_returns_200_status(client):
    """GET /api/version2 should respond with HTTP 200."""
    response = client.get("/api/version2")
    assert response.status_code == 200


def test_version2_returns_json_content_type(client):
    """GET /api/version2 should return a JSON content-type header."""
    response = client.get("/api/version2")
    assert "application/json" in response.headers.get("content-type", "")


def test_version2_body_contains_version_key(client):
    """GET /api/version2 response body must contain the 'version' key."""
    response = client.get("/api/version2")
    body = response.json()
    assert "version" in body


def test_version2_body_version_value_is_2_0_0(client):
    """GET /api/version2 response body must have version equal to '2.0.0'."""
    response = client.get("/api/version2")
    body = response.json()
    assert body["version"] == "2.0.0"


def test_version2_body_has_no_extra_unexpected_keys(client):
    """GET /api/version2 response body should match the declared schema exactly."""
    response = client.get("/api/version2")
    body = response.json()
    assert set(body.keys()) == {"version"}


def test_version2_no_auth_header_required(client):
    """GET /api/version2 must succeed without any Authorization header."""
    response = client.get("/api/version2", headers={})
    assert response.status_code == 200


def test_version2_with_unexpected_auth_header_still_returns_200(client):
    """GET /api/version2 should ignore (not reject) an Authorization header."""
    response = client.get(
        "/api/version2",
        headers={"Authorization": "Bearer some-random-token"},
    )
    assert response.status_code == 200


def test_version2_version_is_string(client):
    """The 'version' field in the response body must be a string."""
    response = client.get("/api/version2")
    body = response.json()
    assert isinstance(body["version"], str)


def test_version2_full_acceptance_criterion(client):
    """End-to-end smoke test: unauthenticated GET returns 200 + {version: 2.0.0}."""
    response = client.get("/api/version2")
    assert response.status_code == 200
    assert response.json() == {"version": "2.0.0"}


# ---------------------------------------------------------------------------
# Health endpoint — required by CLAUDE.md for ECS
# ---------------------------------------------------------------------------

def test_health_endpoint_returns_200(client):
    """GET /health must return 200 (ECS health check)."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_returns_ok_status(client):
    """GET /health must return {status: ok}."""
    response = client.get("/health")
    body = response.json()
    assert body.get("status") == "ok"
