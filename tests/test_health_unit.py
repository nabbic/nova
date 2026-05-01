"""Unit tests for the /api/health endpoint handler."""
import os
import pytest


class TestHealthHandlerUnit:
    """Unit tests for the health check handler logic."""

    def test_health_returns_status_ok_when_called(self):
        """The health handler must include status: ok in its response."""
        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.json()["status"] == "ok"

    def test_health_returns_version_field_when_called(self):
        """The health handler must include a version field in its response."""
        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.get("/api/health")
        assert "version" in response.json()

    def test_health_version_defaults_to_1_0_0_when_env_var_not_set(self):
        """Version defaults to 1.0.0 when VERSION env var is absent."""
        env = os.environ.copy()
        env.pop("VERSION", None)

        import importlib
        import app.main as main_module

        original_version = os.environ.pop("VERSION", None)
        try:
            importlib.reload(main_module)
            from fastapi.testclient import TestClient
            client = TestClient(main_module.app)
            response = client.get("/api/health")
            assert response.json()["version"] == "1.0.0"
        finally:
            if original_version is not None:
                os.environ["VERSION"] = original_version
            importlib.reload(main_module)

    def test_health_version_uses_env_var_when_set(self):
        """Version reflects the VERSION environment variable when set."""
        import importlib
        import app.main as main_module

        os.environ["VERSION"] = "2.5.1"
        try:
            importlib.reload(main_module)
            from fastapi.testclient import TestClient
            client = TestClient(main_module.app)
            response = client.get("/api/health")
            assert response.json()["version"] == "2.5.1"
        finally:
            del os.environ["VERSION"]
            importlib.reload(main_module)

    def test_health_response_contains_exactly_two_fields_when_called(self):
        """Response body contains exactly status and version — no extra fields."""
        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.get("/api/health")
        body = response.json()
        assert set(body.keys()) == {"status", "version"}

    def test_health_response_has_no_stack_trace_when_called(self):
        """Response body must not contain a stack trace."""
        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.get("/api/health")
        raw = response.text
        assert "Traceback" not in raw
        assert "traceback" not in raw

    def test_health_response_has_no_internal_ip_when_called(self):
        """Response body must not leak internal IP addresses."""
        import re
        from app.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        response = client.get("/api/health")
        raw = response.text
        # Match private IP ranges
        private_ip_pattern = re.compile(
            r'(10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+)'
        )
        assert not private_ip_pattern.search(raw)

    def test_health_response_has_no_env_var_leakage_when_called(self):
        """Response body must not contain values of sensitive environment variables."""
        from app.main import app
        from fastapi.testclient import TestClient
        # Set a canary env var that should never appear in the response
        os.environ["SECRET_CANARY"] = "s3cr3t-canary-v4lue"
        try:
            client = TestClient(app)
            response = client.get("/api/health")
            assert "s3cr3t-canary-v4lue" not in response.text
        finally:
            del os.environ["SECRET_CANARY"]
