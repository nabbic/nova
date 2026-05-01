"""Security-focused tests for the health endpoint.

Verifies that:
  - no sensitive environment variable values appear in the response
  - no internal metadata is exposed
  - response size is within a reasonable bound (no accidental data dump)
  - CORS / header hygiene
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
def sec_client():
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


def test_security_response_body_does_not_contain_traceback(sec_client):
    response = sec_client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    assert "Traceback" not in text
    assert "traceback" not in text


def test_security_response_body_does_not_contain_database_url(sec_client):
    response = sec_client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    # Common DB URL schemes
    for scheme in ["postgres://", "postgresql://", "mysql://", "sqlite://", "mongodb://"]:
        assert scheme not in text, f"DB URL scheme '{scheme}' leaked in response"


def test_security_response_body_does_not_contain_env_var_names(sec_client):
    response = sec_client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    for var in ["DATABASE_URL", "SECRET_KEY", "AWS_SECRET_ACCESS_KEY", "COGNITO"]:
        assert var not in text, f"Env var name '{var}' found in response"


def test_security_response_body_does_not_contain_internal_ip_ranges(sec_client):
    response = sec_client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    for prefix in ["192.168.", "10.", "172.16.", "172.17.", "172.18.",
                   "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
                   "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
                   "172.29.", "172.30.", "172.31."]:
        assert prefix not in text, f"Internal IP prefix '{prefix}' found in response"


def test_security_response_body_size_is_within_reasonable_bound(sec_client):
    """Response must not be an accidental data dump — keep it tiny."""
    response = sec_client.get("/api/health")
    text = response.get_data(as_text=True) if hasattr(response, "get_data") else response.text
    # {"status":"ok","version":"1.0.0"} is ~36 chars; allow up to 512 bytes
    assert len(text.encode("utf-8")) <= 512, "Response unexpectedly large — possible data leak"


def test_security_response_does_not_expose_server_header_details(sec_client):
    """Server header should not expose framework version details."""
    response = sec_client.get("/api/health")
    server_header = response.headers.get("Server", "")
    # We do not require a Server header, but if present it must not include
    # verbose version strings like 'Werkzeug/2.3.0' or 'uvicorn/0.x'
    for sensitive_token in ["Werkzeug/", "uvicorn/", "gunicorn/", "Python/"]:
        assert sensitive_token not in server_header, (
            f"Server header exposes internal detail: '{server_header}'"
        )


def test_security_patch_method_not_allowed(sec_client):
    """PATCH must also be rejected to minimise attack surface."""
    response = sec_client.patch("/api/health")
    assert response.status_code == 405


def test_security_options_method_does_not_expose_unexpected_allows(sec_client):
    """OPTIONS (preflight) must only advertise GET (and HEAD/OPTIONS by convention)."""
    response = sec_client.options("/api/health")
    if response.status_code == 200 or response.status_code == 204:
        allow = response.headers.get("Allow", "").upper()
        if allow:
            for unexpected in ["POST", "PUT", "DELETE", "PATCH"]:
                assert unexpected not in allow, (
                    f"OPTIONS Allow header advertises unexpected method: {unexpected}"
                )
