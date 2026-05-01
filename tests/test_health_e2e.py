"""End-to-end smoke tests using pytest + requests (no browser required for an API).

These tests require the application to be running and the base URL to be
specified via the E2E_BASE_URL environment variable (e.g. http://localhost:8000).
If the variable is not set the test module is skipped so that the suite remains
green in CI environments where the server is not started.
"""
import os
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "")


def _requests():
    try:
        import requests
        return requests
    except ImportError:
        pytest.skip("'requests' library not installed — skipping e2e tests")


if not BASE_URL:
    pytest.skip(
        "E2E_BASE_URL not set — skipping end-to-end tests",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def health_url():
    return BASE_URL.rstrip("/") + "/api/health"


def test_e2e_get_health_when_server_running_returns_200(health_url):
    requests = _requests()
    response = requests.get(health_url, timeout=5)
    assert response.status_code == 200


def test_e2e_get_health_content_type_is_application_json(health_url):
    requests = _requests()
    response = requests.get(health_url, timeout=5)
    assert "application/json" in response.headers.get("Content-Type", "")


def test_e2e_get_health_body_exactly_matches_spec(health_url):
    requests = _requests()
    response = requests.get(health_url, timeout=5)
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_e2e_post_health_returns_405(health_url):
    requests = _requests()
    response = requests.post(health_url, timeout=5)
    assert response.status_code == 405


def test_e2e_put_health_returns_405(health_url):
    requests = _requests()
    response = requests.put(health_url, timeout=5)
    assert response.status_code == 405


def test_e2e_delete_health_returns_405(health_url):
    requests = _requests()
    response = requests.delete(health_url, timeout=5)
    assert response.status_code == 405


def test_e2e_get_health_without_auth_header_returns_200(health_url):
    requests = _requests()
    response = requests.get(health_url, headers={}, timeout=5)
    assert response.status_code == 200


def test_e2e_get_health_response_body_contains_no_sensitive_data(health_url):
    requests = _requests()
    response = requests.get(health_url, timeout=5)
    text = response.text
    for pattern in [
        "Traceback", "traceback", "postgres://", "postgresql://",
        "DATABASE_URL", "SECRET", "PASSWORD", "192.168.", "10.0.",
        "172.16.", "tenant_id",
    ]:
        assert pattern not in text, f"Sensitive pattern '{pattern}' found in live response"


def test_e2e_get_health_response_size_is_small(health_url):
    requests = _requests()
    response = requests.get(health_url, timeout=5)
    assert len(response.content) <= 512
