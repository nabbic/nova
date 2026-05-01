"""Integration tests for GET /api/health.

These tests spin up the real application (no mocking of the database or any
middleware layer) and exercise the endpoint over HTTP using a test client.
"""
import importlib
import os
import pytest


def _import_app():
    candidates = [
        ("app.main", "app"),
        ("app.main", "application"),
        ("app.app", "app"),
        ("app.app", "application"),
        ("main", "app"),
        ("main", "application"),
    ]
    for module_path, attr in candidates:
        try:
            mod = importlib.import_module(module_path)
            application = getattr(mod, attr, None)
            if application is not None:
                return application
        except ModuleNotFoundError:
            continue
    raise ImportError("Could not locate the WSGI/ASGI application.")


@pytest.fixture(scope="module")
def integration_client():
    application = _import_app()
    if hasattr(application, "test_client"):
        application.config["TESTING"] = True
        with application.test_client() as c:
            yield c
    else:
        try:
            from fastapi.testclient import TestClient
            with TestClient(application) as c:
                yield c
        except ImportError:
            pytest.skip("No compatible test client found")


# ---------------------------------------------------------------------------
# Full acceptance-criteria coverage (integration layer)
# ---------------------------------------------------------------------------

def test_integration_get_health_when_server_running_returns_200(integration_client):
    """AC: GET /api/health returns HTTP 200."""
    response = integration_client.get("/api/health")
    assert response.status_code == 200


def test_integration_get_health_when_200_returns_application_json_content_type(integration_client):
    """AC: Content-Type header is application/json."""
    response = integration_client.get("/api/health")
    assert "application/json" in response.headers.get("Content-Type", "")


def test_integration_get_health_when_parsed_body_exactly_matches_spec(integration_client):
    """AC: Body exactly matches {\"status\":\"ok\",\"version\":\"1.0.0\"}."""
    response = integration_client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert body == {"status": "ok", "version": "1.0.0"}


def test_integration_post_health_when_method_not_allowed_returns_405(integration_client):
    """AC: POST /api/health returns HTTP 405."""
    response = integration_client.post("/api/health")
    assert response.status_code == 405


def test_integration_put_health_when_method_not_allowed_returns_405(integration_client):
    """AC: PUT /api/health returns HTTP 405."""
    response = integration_client.put("/api/health")
    assert response.status_code == 405


def test_integration_delete_health_when_method_not_allowed_returns_405(integration_client):
    """AC: DELETE /api/health returns HTTP 405."""
    response = integration_client.delete("/api/health")
    assert response.status_code == 405


def test_integration_get_health_when_no_auth_header_returns_200(integration_client):
    """AC: Endpoint accessible with no Authorization header — no auth required."""
    response = integration_client.get("/api/health")
    assert response.status_code == 200


def test_integration_get_health_when_bogus_auth_header_still_returns_200(integration_client):
    """Public endpoint must not reject requests due to a missing/invalid token."""
    headers = {"Authorization": "Bearer invalid-token-xyz"}
    response = integration_client.get("/api/health", headers=headers)
    # A public route should not return 401/403 regardless of the token value
    assert response.status_code == 200


def test_integration_get_health_when_body_inspected_contains_no_sensitive_data(integration_client):
    """AC: Body must not expose stack traces, env vars, DB URLs, IPs, or tenant data."""
    response = integration_client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    sensitive = [
        "Traceback", "traceback", "postgres://", "postgresql://",
        "DATABASE_URL", "SECRET", "PASSWORD", "192.168.", "10.0.",
        "172.16.", "tenant_id",
    ]
    for token in sensitive:
        assert token not in text, f"Response contains sensitive token: '{token}'"


def test_integration_get_health_when_version_field_present_is_non_empty_string(integration_client):
    """AC: version field is a non-empty string (sourced from env or manifest)."""
    response = integration_client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert isinstance(body.get("version"), str)
    assert len(body["version"]) > 0
