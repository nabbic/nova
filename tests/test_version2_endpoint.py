"""Tests for GET /api/version2 endpoint.

Covers all acceptance criteria from requirements.json:
  - Response status is 200
  - Response body is exactly {"version": "2.0.0"}
  - Unauthenticated request returns 200 with version JSON
"""
import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Unit / route-level tests
# ---------------------------------------------------------------------------

def test_get_version2_returns_200(client):
    """GET /api/version2 should respond with HTTP 200."""
    response = client.get("/api/version2")
    assert response.status_code == 200


def test_get_version2_returns_correct_version_field(client):
    """GET /api/version2 response body must contain version == '2.0.0'."""
    response = client.get("/api/version2")
    data = response.json()
    assert data["version"] == "2.0.0"


def test_get_version2_response_body_is_exact(client):
    """GET /api/version2 response body must be exactly {"version": "2.0.0"} with no extra fields."""
    response = client.get("/api/version2")
    data = response.json()
    assert data == {"version": "2.0.0"}


def test_get_version2_content_type_is_json(client):
    """GET /api/version2 must return Content-Type application/json."""
    response = client.get("/api/version2")
    assert "application/json" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Auth / public access tests
# ---------------------------------------------------------------------------

def test_get_version2_unauthenticated_returns_200(client):
    """GET /api/version2 with no auth header must return 200 (public endpoint)."""
    response = client.get("/api/version2", headers={})
    assert response.status_code == 200


def test_get_version2_unauthenticated_returns_version_json(client):
    """Unauthenticated GET /api/version2 must still return the correct JSON payload."""
    response = client.get("/api/version2", headers={})
    assert response.json() == {"version": "2.0.0"}


def test_get_version2_with_bogus_auth_header_still_returns_200(client):
    """GET /api/version2 with an invalid Bearer token should still return 200 (no auth enforced)."""
    response = client.get("/api/version2", headers={"Authorization": "Bearer totally-invalid-token"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# HTTP method tests
# ---------------------------------------------------------------------------

def test_post_version2_returns_405(client):
    """POST /api/version2 should return 405 Method Not Allowed (only GET is defined)."""
    response = client.post("/api/version2")
    assert response.status_code == 405


def test_put_version2_returns_405(client):
    """PUT /api/version2 should return 405 Method Not Allowed."""
    response = client.put("/api/version2")
    assert response.status_code == 405


def test_delete_version2_returns_405(client):
    """DELETE /api/version2 should return 405 Method Not Allowed."""
    response = client.delete("/api/version2")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# Integration-style: response does not leak debug info
# ---------------------------------------------------------------------------

def test_get_version2_response_has_no_debug_keys(client):
    """GET /api/version2 response body must not contain debug / internal keys."""
    response = client.get("/api/version2")
    data = response.json()
    forbidden_keys = {"traceback", "detail", "debug", "internal", "error", "exception"}
    assert forbidden_keys.isdisjoint(set(data.keys()))


def test_get_version2_version_value_is_string(client):
    """GET /api/version2 'version' field must be a string, not an int or other type."""
    response = client.get("/api/version2")
    data = response.json()
    assert isinstance(data["version"], str)


def test_get_version2_version_matches_semver_pattern(client):
    """GET /api/version2 'version' must match semver pattern X.Y.Z."""
    import re
    response = client.get("/api/version2")
    version = response.json()["version"]
    assert re.match(r"^\d+\.\d+\.\d+$", version), f"'{version}' does not match semver X.Y.Z"
