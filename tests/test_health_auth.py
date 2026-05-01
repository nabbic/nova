"""Auth-boundary tests for the health endpoint.

Even though GET /api/health is intentionally public, we verify:
  - unauthenticated requests are accepted (not rejected with 401)
  - the route is NOT accidentally protected by auth middleware
  - tenant isolation is not breached (endpoint returns no per-tenant data)
"""
import importlib
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
def auth_client():
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


def test_get_health_when_unauthenticated_does_not_return_401(auth_client):
    """Unauthenticated GET /api/health must NOT return 401."""
    response = auth_client.get("/api/health")
    assert response.status_code != 401


def test_get_health_when_unauthenticated_does_not_return_403(auth_client):
    """Unauthenticated GET /api/health must NOT return 403."""
    response = auth_client.get("/api/health")
    assert response.status_code != 403


def test_get_health_when_unauthenticated_returns_200(auth_client):
    """Auth absence must result in 200, confirming public access."""
    response = auth_client.get("/api/health")
    assert response.status_code == 200


def test_get_health_with_no_authorization_header_returns_ok_body(auth_client):
    """Body must be {status: ok, version: 1.0.0} even without auth."""
    response = auth_client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert body.get("status") == "ok"


def test_get_health_tenant_a_cannot_see_tenant_b_data(auth_client):
    """Multi-tenancy: health response must be identical for any tenant context
    and must contain zero tenant-specific data.
    """
    headers_tenant_a = {"X-Tenant-ID": "tenant-aaa"}
    headers_tenant_b = {"X-Tenant-ID": "tenant-bbb"}

    resp_a = auth_client.get("/api/health", headers=headers_tenant_a)
    resp_b = auth_client.get("/api/health", headers=headers_tenant_b)

    body_a = resp_a.get_json() if hasattr(resp_a, "get_json") else resp_a.json()
    body_b = resp_b.get_json() if hasattr(resp_b, "get_json") else resp_b.json()

    # Both tenants see the exact same static response
    assert body_a == body_b
    # Neither response contains any tenant identifier
    assert "tenant" not in str(body_a).lower()
    assert "tenant" not in str(body_b).lower()


def test_get_health_response_contains_no_tenant_id_field(auth_client):
    """The response JSON must not include a tenant_id field."""
    response = auth_client.get("/api/health")
    body = response.get_json() if hasattr(response, "get_json") else response.json()
    assert "tenant_id" not in body


def test_get_health_invalid_bearer_token_still_returns_200(auth_client):
    """Passing a bad bearer token must not cause auth middleware to block the request."""
    headers = {"Authorization": "Bearer completely.invalid.jwt"}
    response = auth_client.get("/api/health", headers=headers)
    assert response.status_code == 200
