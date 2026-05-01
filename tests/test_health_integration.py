"""Integration tests for the GET /api/health endpoint.

These tests spin up the FastAPI application via TestClient (no mocking)
and exercise the HTTP contract end-to-end within the process.
No database is involved — the endpoint is stateless.
"""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """Provide a TestClient scoped to the module."""
    # Ensure VERSION is not set so we get the default
    os.environ.pop("VERSION", None)
    from app.main import app  # import after env manipulation
    return TestClient(app)


# ---------------------------------------------------------------------------
# Acceptance criterion 1:
# Given the service is running, when GET /api/health is called without an
# Authorization header, then the response status code is 200.
# ---------------------------------------------------------------------------

class TestHealthStatusCode:
    def test_health_returns_200_when_called_without_auth_header(self, client):
        """GET /api/health returns HTTP 200 with no Authorization header."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_returns_200_when_called_with_no_headers_at_all(self, client):
        """GET /api/health returns HTTP 200 even when only minimal headers are sent."""
        response = client.get("/api/health", headers={})
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Acceptance criterion 2:
# Given the service is running, when GET /api/health is called, then the
# response body is exactly {"status": "ok", "version": "1.0.0"}.
# ---------------------------------------------------------------------------

class TestHealthResponseBody:
    def test_health_body_status_is_ok_when_version_env_not_set(self, client):
        """Response body field 'status' equals 'ok'."""
        response = client.get("/api/health")
        assert response.json()["status"] == "ok"

    def test_health_body_version_is_1_0_0_when_version_env_not_set(self, client):
        """Response body field 'version' equals '1.0.0' when VERSION env is absent."""
        response = client.get("/api/health")
        assert response.json()["version"] == "1.0.0"

    def test_health_body_is_exact_dict_when_version_env_not_set(self, client):
        """Response body is exactly {status: ok, version: 1.0.0} — no extra keys."""
        response = client.get("/api/health")
        assert response.json() == {"status": "ok", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Acceptance criterion 3:
# Given the service is running, when GET /api/health is called, then the
# Content-Type response header is application/json.
# ---------------------------------------------------------------------------

class TestHealthContentType:
    def test_health_content_type_is_application_json_when_called(self, client):
        """Content-Type header must be application/json."""
        response = client.get("/api/health")
        assert "application/json" in response.headers["content-type"]

    def test_health_content_type_header_present_when_called(self, client):
        """A Content-Type header is present on the response."""
        response = client.get("/api/health")
        assert "content-type" in response.headers


# ---------------------------------------------------------------------------
# Acceptance criterion 4:
# Given no Authorization header is present, when GET /api/health is called,
# then the endpoint responds successfully without returning a 401 or 403.
# ---------------------------------------------------------------------------

class TestHealthNoAuthRequired:
    def test_health_does_not_return_401_when_no_auth_header(self, client):
        """Endpoint must NOT require authentication — 401 is forbidden."""
        response = client.get("/api/health")
        assert response.status_code != 401

    def test_health_does_not_return_403_when_no_auth_header(self, client):
        """Endpoint must NOT require authorization — 403 is forbidden."""
        response = client.get("/api/health")
        assert response.status_code != 403

    def test_health_succeeds_when_bogus_authorization_header_present(self, client):
        """Endpoint must ignore (not reject) a present but invalid auth header."""
        response = client.get("/api/health", headers={"Authorization": "Bearer bogus"})
        # Should still return 200 — no auth enforcement on this route
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Acceptance criterion 5:
# Given the endpoint is serving a response, when the response is inspected,
# then it does not contain env var values, stack traces, internal IPs, or
# any system metadata beyond the declared version field.
# ---------------------------------------------------------------------------

class TestHealthResponseSecurity:
    def test_health_response_does_not_contain_traceback_when_called(self, client):
        """Response must not contain Python stack trace text."""
        response = client.get("/api/health")
        assert "Traceback" not in response.text

    def test_health_response_does_not_contain_exception_when_called(self, client):
        """Response must not contain exception class names."""
        response = client.get("/api/health")
        assert "Exception" not in response.text
        assert "Error" not in response.text

    def test_health_response_does_not_leak_path_env_var_when_called(self, client):
        """Response text must not contain the value of the PATH env var."""
        path_value = os.environ.get("PATH", "")
        if path_value:
            response = client.get("/api/health")
            assert path_value not in response.text

    def test_health_response_does_not_contain_private_ip_ranges(self, client):
        """Response must not contain any RFC-1918 private IP address."""
        import re
        response = client.get("/api/health")
        private = re.compile(
            r'(10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
            r'|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}'
            r'|192\.168\.\d{1,3}\.\d{1,3})'
        )
        assert not private.search(response.text)

    def test_health_response_has_only_declared_fields_when_called(self, client):
        """No system metadata appears in the response — only status and version."""
        response = client.get("/api/health")
        body = response.json()
        assert set(body.keys()) == {"status", "version"}


# ---------------------------------------------------------------------------
# Acceptance criterion 6:
# Given the version value in the response, when it is evaluated, then it
# matches the value of the VERSION env var if set, or defaults to 1.0.0.
# ---------------------------------------------------------------------------

class TestHealthVersionEnvVar:
    def test_health_version_defaults_to_1_0_0_when_version_env_absent(self):
        """When VERSION is not in environment, version field is '1.0.0'."""
        import importlib
        import app.main as main_module
        os.environ.pop("VERSION", None)
        importlib.reload(main_module)
        c = TestClient(main_module.app)
        response = c.get("/api/health")
        assert response.json()["version"] == "1.0.0"

    def test_health_version_reflects_version_env_var_when_set(self):
        """When VERSION env var is set, version field matches it."""
        import importlib
        import app.main as main_module
        os.environ["VERSION"] = "3.1.4"
        try:
            importlib.reload(main_module)
            c = TestClient(main_module.app)
            response = c.get("/api/health")
            assert response.json()["version"] == "3.1.4"
        finally:
            del os.environ["VERSION"]
            importlib.reload(main_module)

    def test_health_version_changes_when_env_var_changes(self):
        """Reloading the app with a different VERSION env var changes the version."""
        import importlib
        import app.main as main_module

        os.environ["VERSION"] = "0.0.1"
        importlib.reload(main_module)
        c1 = TestClient(main_module.app)
        v1 = c1.get("/api/health").json()["version"]

        os.environ["VERSION"] = "9.9.9"
        importlib.reload(main_module)
        c2 = TestClient(main_module.app)
        v2 = c2.get("/api/health").json()["version"]

        assert v1 == "0.0.1"
        assert v2 == "9.9.9"

        # Cleanup
        del os.environ["VERSION"]
        importlib.reload(main_module)


# ---------------------------------------------------------------------------
# Acceptance criterion 7:
# Given the endpoint handler, when it processes a request, then it performs
# no database queries and maintains no local state between requests.
# ---------------------------------------------------------------------------

class TestHealthStatelessness:
    def test_health_returns_same_body_on_repeated_calls_when_env_unchanged(
        self, client
    ):
        """Repeated calls return identical bodies — no per-request mutation."""
        r1 = client.get("/api/health").json()
        r2 = client.get("/api/health").json()
        r3 = client.get("/api/health").json()
        assert r1 == r2 == r3

    def test_health_returns_200_on_concurrent_calls_when_called(self, client):
        """Multiple sequential requests all succeed — no state corruption."""
        for _ in range(10):
            response = client.get("/api/health")
            assert response.status_code == 200


# ---------------------------------------------------------------------------
# HTTP method enforcement
# ---------------------------------------------------------------------------

class TestHealthMethodEnforcement:
    def test_health_returns_405_when_post_is_called(self, client):
        """POST /api/health must be rejected — only GET is allowed."""
        response = client.post("/api/health")
        assert response.status_code == 405

    def test_health_returns_405_when_put_is_called(self, client):
        """PUT /api/health must be rejected — only GET is allowed."""
        response = client.put("/api/health")
        assert response.status_code == 405

    def test_health_returns_405_when_delete_is_called(self, client):
        """DELETE /api/health must be rejected — only GET is allowed."""
        response = client.delete("/api/health")
        assert response.status_code == 405

    def test_health_returns_405_when_patch_is_called(self, client):
        """PATCH /api/health must be rejected — only GET is allowed."""
        response = client.patch("/api/health")
        assert response.status_code == 405
