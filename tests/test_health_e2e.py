"""End-to-end tests for GET /api/health using an in-process ASGI transport.

These tests simulate a real HTTP client hitting the running application,
covering the critical user journey: \'can the system confirm it is alive?\'

No database, no mocking — pure HTTP contract verification.
"""
import os
import pytest

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

requires_httpx = pytest.mark.skipif(
    not HTTPX_AVAILABLE,
    reason="httpx is not installed — skipping ASGI e2e tests"
)


@requires_httpx
class TestHealthEndpointE2E:
    """Critical user journey: smoke test confirms the service is alive."""

    @pytest.fixture(scope="class")
    def asgi_client(self):
        """Sync HTTPX client using ASGI transport against the real app."""
        from app.main import app
        from starlette.testclient import TestClient
        with TestClient(app) as c:
            yield c

    def test_e2e_health_returns_200_when_service_running(self, asgi_client):
        response = asgi_client.get("/api/health")
        assert response.status_code == 200

    def test_e2e_health_returns_ok_status_when_service_running(self, asgi_client):
        response = asgi_client.get("/api/health")
        assert response.json()["status"] == "ok"

    def test_e2e_health_returns_version_when_service_running(self, asgi_client):
        response = asgi_client.get("/api/health")
        assert "version" in response.json()

    def test_e2e_health_content_type_is_json_when_service_running(self, asgi_client):
        response = asgi_client.get("/api/health")
        assert "application/json" in response.headers["content-type"]

    def test_e2e_health_no_auth_required_when_called_without_header(self, asgi_client):
        response = asgi_client.get("/api/health")
        assert response.status_code not in (401, 403)

    def test_e2e_health_body_exact_match_when_default_version(self, asgi_client):
        response = asgi_client.get("/api/health")
        assert response.json() == {"status": "ok", "version": "1.0.0"}

    def test_e2e_health_not_found_returns_404_for_wrong_path(self, asgi_client):
        response = asgi_client.get("/api/healthz")
        assert response.status_code == 404

    def test_e2e_health_root_not_found_when_called(self, asgi_client):
        response = asgi_client.get("/")
        assert response.status_code != 200 or response.json() != {"status": "ok", "version": "1.0.0"}
