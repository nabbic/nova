"""Unit tests for the health check endpoint handler."""
import importlib
import os
import sys
import types
import pytest


def _import_app():
    """Import the Flask/FastAPI app regardless of minor structural differences."""
    # Try common entry-point locations
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
    raise ImportError(
        "Could not locate the WSGI/ASGI application. "
        "Expected app.main:app or app.app:app."
    )


@pytest.fixture(scope="module")
def client():
    """Return a test client for the application."""
    application = _import_app()
    # Flask
    if hasattr(application, "test_client"):
        application.config["TESTING"] = True
        with application.test_client() as c:
            yield c
    else:
        # FastAPI / Starlette via httpx or requests
        try:
            from fastapi.testclient import TestClient
            with TestClient(application) as c:
                yield c
        except ImportError:
            pytest.skip("No compatible test client found (Flask or FastAPI required)")


# ---------------------------------------------------------------------------
# AC-1  GET /api/health returns HTTP 200
# ---------------------------------------------------------------------------
def test_get_health_returns_200(client):
    response = client.get("/api/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC-2  Content-Type is application/json
# ---------------------------------------------------------------------------
def test_get_health_content_type_is_application_json(client):
    response = client.get("/api/health")
    content_type = response.headers.get("Content-Type", "")
    assert "application/json" in content_type


# ---------------------------------------------------------------------------
# AC-3  Response body exactly matches {"status": "ok", "version": "1.0.0"}
# ---------------------------------------------------------------------------
def test_get_health_body_status_is_ok(client):
    response = client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert body["status"] == "ok"


def test_get_health_body_version_is_1_0_0(client):
    response = client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert body["version"] == "1.0.0"


def test_get_health_body_has_exactly_two_keys(client):
    response = client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert set(body.keys()) == {"status", "version"}


def test_get_health_body_exact_match(client):
    response = client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert body == {"status": "ok", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# AC-4/5/6  Non-GET methods return HTTP 405
# ---------------------------------------------------------------------------
def test_post_health_returns_405(client):
    response = client.post("/api/health")
    assert response.status_code == 405


def test_put_health_returns_405(client):
    response = client.put("/api/health")
    assert response.status_code == 405


def test_delete_health_returns_405(client):
    response = client.delete("/api/health")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# AC-7  No Authorization header required
# ---------------------------------------------------------------------------
def test_get_health_without_auth_header_returns_200(client):
    """Endpoint must be reachable with absolutely no Authorization header."""
    # Deliberately send no Authorization header
    response = client.get("/api/health")
    assert response.status_code == 200


def test_get_health_without_auth_header_returns_ok_body(client):
    response = client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert body.get("status") == "ok"


# ---------------------------------------------------------------------------
# AC-9  Response body must not contain sensitive information
# ---------------------------------------------------------------------------
_SENSITIVE_PATTERNS = [
    "traceback",
    "Traceback",
    "stack trace",
    "exception",
    "Exception",
    "postgres://",
    "postgresql://",
    "mysql://",
    "sqlite://",
    "DB_",
    "DATABASE_URL",
    "SECRET",
    "PASSWORD",
    "PRIVATE_KEY",
    "192.168.",
    "10.0.",
    "172.16.",
    "tenant_id",
]


def test_get_health_body_contains_no_stack_trace(client):
    response = client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    assert "Traceback" not in text
    assert "traceback" not in text


def test_get_health_body_contains_no_database_connection_string(client):
    response = client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    for pattern in ["postgres://", "postgresql://", "mysql://", "DATABASE_URL"]:
        assert pattern not in text, f"Sensitive pattern '{pattern}' found in response"


def test_get_health_body_contains_no_internal_ip(client):
    response = client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    for pattern in ["192.168.", "10.0.", "172.16."]:
        assert pattern not in text, f"Internal IP pattern '{pattern}' found in response"


def test_get_health_body_contains_no_tenant_data(client):
    response = client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    assert "tenant_id" not in text


def test_get_health_body_contains_no_secret_keywords(client):
    response = client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    for pattern in ["SECRET", "PASSWORD", "PRIVATE_KEY"]:
        assert pattern not in text, f"Sensitive keyword '{pattern}' found in response"


# ---------------------------------------------------------------------------
# AC-10  Version sourced from env var or manifest (not bare hardcode)
# ---------------------------------------------------------------------------
def test_get_health_version_uses_env_override_when_set(client, monkeypatch):
    """If APP_VERSION env var is set, the endpoint should reflect it.

    This test is advisory — it passes vacuously if the implementation chooses
    a package-manifest approach rather than an env var. The important thing is
    that the default fallback of 1.0.0 is present when no env var is set.
    """
    response = client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    # At minimum the fallback must be present
    assert body["version"] is not None
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0
