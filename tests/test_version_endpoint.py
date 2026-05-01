"""Unit and integration tests for GET /version endpoint."""
import os
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# AC1: endpoint returns HTTP 200 without authentication
# ---------------------------------------------------------------------------

def test_version_returns_200_ok(client: TestClient) -> None:
    """GET /version returns HTTP 200 OK without any auth header."""
    response = client.get("/version")
    assert response.status_code == 200


def test_version_requires_no_auth_header(client: TestClient) -> None:
    """GET /version succeeds even when no Authorization header is provided."""
    response = client.get("/version", headers={})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC2: response body is valid JSON with required fields
# ---------------------------------------------------------------------------

def test_version_response_is_json(client: TestClient) -> None:
    """GET /version returns a JSON content-type response."""
    response = client.get("/version")
    assert "application/json" in response.headers["content-type"]


def test_version_response_contains_version_field(client: TestClient) -> None:
    """GET /version response body includes the 'version' field."""
    response = client.get("/version")
    assert "version" in response.json()


def test_version_response_contains_build_sha_field(client: TestClient) -> None:
    """GET /version response body includes the 'build_sha' field."""
    response = client.get("/version")
    assert "build_sha" in response.json()


def test_version_response_contains_environment_field(client: TestClient) -> None:
    """GET /version response body includes the 'environment' field."""
    response = client.get("/version")
    assert "environment" in response.json()


def test_version_response_has_exactly_required_fields(client: TestClient) -> None:
    """GET /version response body contains all three required fields."""
    body = client.get("/version").json()
    required = {"version", "build_sha", "environment"}
    assert required.issubset(body.keys())


# ---------------------------------------------------------------------------
# AC3: APP_VERSION env var is reflected in response
# ---------------------------------------------------------------------------

def test_version_reflects_app_version_env_var(client: TestClient) -> None:
    """Given APP_VERSION='1.2.3', response.version equals '1.2.3'."""
    with patch.dict(os.environ, {"APP_VERSION": "1.2.3"}):
        response = client.get("/version")
    assert response.json()["version"] == "1.2.3"


def test_version_reflects_different_app_version_env_var(client: TestClient) -> None:
    """Given APP_VERSION='9.9.9', response.version equals '9.9.9'."""
    with patch.dict(os.environ, {"APP_VERSION": "9.9.9"}):
        response = client.get("/version")
    assert response.json()["version"] == "9.9.9"


# ---------------------------------------------------------------------------
# AC4: BUILD_SHA env var is reflected in response
# ---------------------------------------------------------------------------

def test_version_reflects_build_sha_env_var(client: TestClient) -> None:
    """Given BUILD_SHA='abc1234', response.build_sha equals 'abc1234'."""
    with patch.dict(os.environ, {"BUILD_SHA": "abc1234"}):
        response = client.get("/version")
    assert response.json()["build_sha"] == "abc1234"


def test_version_reflects_long_build_sha_env_var(client: TestClient) -> None:
    """Given BUILD_SHA='abc1234def5678', response.build_sha equals the full value."""
    with patch.dict(os.environ, {"BUILD_SHA": "abc1234def5678"}):
        response = client.get("/version")
    assert response.json()["build_sha"] == "abc1234def5678"


# ---------------------------------------------------------------------------
# AC5: ENVIRONMENT env var is reflected in response
# ---------------------------------------------------------------------------

def test_version_reflects_environment_env_var_staging(client: TestClient) -> None:
    """Given ENVIRONMENT='staging', response.environment equals 'staging'."""
    with patch.dict(os.environ, {"ENVIRONMENT": "staging"}):
        response = client.get("/version")
    assert response.json()["environment"] == "staging"


def test_version_reflects_environment_env_var_production(client: TestClient) -> None:
    """Given ENVIRONMENT='production', response.environment equals 'production'."""
    with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
        response = client.get("/version")
    assert response.json()["environment"] == "production"


# ---------------------------------------------------------------------------
# AC6: APP_VERSION missing → safe default, no error
# ---------------------------------------------------------------------------

def test_version_when_app_version_unset_returns_unknown(client: TestClient) -> None:
    """Given APP_VERSION is not set, version field defaults to 'unknown'."""
    env = {k: v for k, v in os.environ.items() if k != "APP_VERSION"}
    with patch.dict(os.environ, env, clear=True):
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["version"] == "unknown"


def test_version_when_app_version_unset_returns_no_stack_trace(client: TestClient) -> None:
    """Given APP_VERSION is not set, response does not contain 'Traceback'."""
    env = {k: v for k, v in os.environ.items() if k != "APP_VERSION"}
    with patch.dict(os.environ, env, clear=True):
        response = client.get("/version")
    assert "Traceback" not in response.text


# ---------------------------------------------------------------------------
# AC7: BUILD_SHA missing → safe default, no error
# ---------------------------------------------------------------------------

def test_version_when_build_sha_unset_returns_unknown(client: TestClient) -> None:
    """Given BUILD_SHA is not set, build_sha field defaults to 'unknown'."""
    env = {k: v for k, v in os.environ.items() if k != "BUILD_SHA"}
    with patch.dict(os.environ, env, clear=True):
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["build_sha"] == "unknown"


def test_version_when_build_sha_unset_returns_no_stack_trace(client: TestClient) -> None:
    """Given BUILD_SHA is not set, response does not contain 'Traceback'."""
    env = {k: v for k, v in os.environ.items() if k != "BUILD_SHA"}
    with patch.dict(os.environ, env, clear=True):
        response = client.get("/version")
    assert "Traceback" not in response.text


# ---------------------------------------------------------------------------
# AC8: ENVIRONMENT missing → safe default, no error
# ---------------------------------------------------------------------------

def test_version_when_environment_unset_returns_unknown(client: TestClient) -> None:
    """Given ENVIRONMENT is not set, environment field defaults to 'unknown'."""
    env = {k: v for k, v in os.environ.items() if k != "ENVIRONMENT"}
    with patch.dict(os.environ, env, clear=True):
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["environment"] == "unknown"


def test_version_when_environment_unset_returns_no_stack_trace(client: TestClient) -> None:
    """Given ENVIRONMENT is not set, response does not contain 'Traceback'."""
    env = {k: v for k, v in os.environ.items() if k != "ENVIRONMENT"}
    with patch.dict(os.environ, env, clear=True):
        response = client.get("/version")
    assert "Traceback" not in response.text


# ---------------------------------------------------------------------------
# AC9: no sensitive information in response
# ---------------------------------------------------------------------------

def test_version_response_does_not_leak_secret_values(client: TestClient) -> None:
    """GET /version response does not expose a field named 'secret'."""
    body = client.get("/version").json()
    lowered_keys = {k.lower() for k in body.keys()}
    assert "secret" not in lowered_keys


def test_version_response_does_not_contain_traceback(client: TestClient) -> None:
    """GET /version response text does not contain a Python traceback."""
    response = client.get("/version")
    assert "Traceback" not in response.text
    assert "traceback" not in response.text


def test_version_response_does_not_expose_password_field(client: TestClient) -> None:
    """GET /version response body does not include a 'password' field."""
    body = client.get("/version").json()
    assert "password" not in body


def test_version_response_does_not_expose_token_field(client: TestClient) -> None:
    """GET /version response body does not include a 'token' field."""
    body = client.get("/version").json()
    assert "token" not in body


def test_version_response_field_values_are_strings(client: TestClient) -> None:
    """GET /version response fields version, build_sha, environment are all strings."""
    body = client.get("/version").json()
    assert isinstance(body["version"], str)
    assert isinstance(body["build_sha"], str)
    assert isinstance(body["environment"], str)


# ---------------------------------------------------------------------------
# AC11: no hardcoded values — env vars drive all three fields independently
# ---------------------------------------------------------------------------

def test_version_all_fields_independently_controlled_by_env_vars(
    client: TestClient,
) -> None:
    """All three fields change independently when env vars change."""
    env_a = {"APP_VERSION": "1.0.0", "BUILD_SHA": "sha111", "ENVIRONMENT": "staging"}
    env_b = {"APP_VERSION": "2.0.0", "BUILD_SHA": "sha222", "ENVIRONMENT": "production"}

    with patch.dict(os.environ, env_a):
        body_a = client.get("/version").json()

    with patch.dict(os.environ, env_b):
        body_b = client.get("/version").json()

    assert body_a["version"] == "1.0.0"
    assert body_b["version"] == "2.0.0"
    assert body_a["build_sha"] == "sha111"
    assert body_b["build_sha"] == "sha222"
    assert body_a["environment"] == "staging"
    assert body_b["environment"] == "production"


def test_version_app_version_env_var_change_is_reflected(client: TestClient) -> None:
    """Changing APP_VERSION between requests changes the returned version value."""
    with patch.dict(os.environ, {"APP_VERSION": "0.1.0"}):
        body_first = client.get("/version").json()
    with patch.dict(os.environ, {"APP_VERSION": "0.2.0"}):
        body_second = client.get("/version").json()
    assert body_first["version"] != body_second["version"]


# ---------------------------------------------------------------------------
# HTTP method constraints
# ---------------------------------------------------------------------------

def test_version_post_method_not_allowed(client: TestClient) -> None:
    """POST /version is not a supported method."""
    response = client.post("/version")
    assert response.status_code == 405


def test_version_put_method_not_allowed(client: TestClient) -> None:
    """PUT /version is not a supported method."""
    response = client.put("/version")
    assert response.status_code == 405


def test_version_delete_method_not_allowed(client: TestClient) -> None:
    """DELETE /version is not a supported method."""
    response = client.delete("/version")
    assert response.status_code == 405
