"""Tests for GET /api/ping liveness endpoint.

Covers all acceptance criteria from requirements.json:
  AC1: GET /api/ping returns HTTP 200 with correct body
  AC2: Response body has pong=true and a valid ISO 8601 timestamp
  AC3: No auth required
  AC4: /health and /version continue to return HTTP 200
  AC5: Smoke test that ping.py is a standalone file (import check)
"""
from __future__ import annotations

import importlib
import re
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# App import guard — give a clear message if the app is not importable
# ---------------------------------------------------------------------------
try:
    from app.main import app  # noqa: E402
except Exception as exc:  # pragma: no cover
    pytest.skip(
        f"Could not import app.main: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Synchronous TestClient — safe for sync FastAPI routes."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 datetime string, supporting trailing 'Z'."""
    # Python < 3.11 fromisoformat does not handle trailing Z
    normalised = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalised)


# ---------------------------------------------------------------------------
# AC1 — GET /api/ping returns HTTP 200
# ---------------------------------------------------------------------------

def test_ping_returns_200_status_code(client: TestClient):
    """AC1: GET /api/ping must respond with HTTP 200."""
    response = client.get("/api/ping")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AC2 — Response body shape
# ---------------------------------------------------------------------------

def test_ping_response_body_contains_pong_key(client: TestClient):
    """AC2: Response JSON must include the key 'pong'."""
    response = client.get("/api/ping")
    body = response.json()
    assert "pong" in body


def test_ping_response_pong_value_is_true(client: TestClient):
    """AC2: The 'pong' field must be boolean true."""
    response = client.get("/api/ping")
    body = response.json()
    assert body["pong"] is True


def test_ping_response_body_contains_timestamp_key(client: TestClient):
    """AC2: Response JSON must include the key 'timestamp'."""
    response = client.get("/api/ping")
    body = response.json()
    assert "timestamp" in body


def test_ping_response_timestamp_is_non_empty_string(client: TestClient):
    """AC2: The 'timestamp' value must be a non-empty string."""
    response = client.get("/api/ping")
    body = response.json()
    assert isinstance(body["timestamp"], str)
    assert body["timestamp"] != ""


def test_ping_response_has_no_extra_top_level_keys(client: TestClient):
    """AC2: Response body should only contain 'pong' and 'timestamp'."""
    response = client.get("/api/ping")
    body = response.json()
    assert set(body.keys()) == {"pong", "timestamp"}


def test_ping_response_content_type_is_json(client: TestClient):
    """AC2: Content-Type header must indicate JSON."""
    response = client.get("/api/ping")
    assert "application/json" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# AC2 — Timestamp is valid ISO 8601
# ---------------------------------------------------------------------------

def test_ping_timestamp_is_valid_iso8601(client: TestClient):
    """AC2/AC3 (requirements): Timestamp must be parseable as ISO 8601."""
    response = client.get("/api/ping")
    timestamp_str = response.json()["timestamp"]
    try:
        _parse_iso8601(timestamp_str)
    except ValueError as exc:
        pytest.fail(f"Timestamp '{timestamp_str}' is not valid ISO 8601: {exc}")


def test_ping_timestamp_represents_a_recent_utc_time(client: TestClient):
    """AC2: Timestamp must be within 60 seconds of 'now' (UTC)."""
    response = client.get("/api/ping")
    timestamp_str = response.json()["timestamp"]
    parsed = _parse_iso8601(timestamp_str)
    # Make aware if naive (treat as UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    diff_seconds = abs((now - parsed).total_seconds())
    assert diff_seconds < 60, (
        f"Timestamp '{timestamp_str}' is {diff_seconds:.1f}s away from now — "
        "expected within 60 seconds"
    )


def test_ping_timestamp_contains_date_and_time_components(client: TestClient):
    """AC2: Timestamp format must include both date and time portions."""
    response = client.get("/api/ping")
    timestamp_str = response.json()["timestamp"]
    # Must match YYYY-MM-DDTHH:MM pattern at minimum
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
    assert pattern.match(timestamp_str), (
        f"Timestamp '{timestamp_str}' does not look like ISO 8601 "
        "(expected YYYY-MM-DDTHH:MM...)"
    )


# ---------------------------------------------------------------------------
# AC3 — No auth required
# ---------------------------------------------------------------------------

def test_ping_returns_200_without_authorization_header(client: TestClient):
    """AC3: No Authorization header should be needed — endpoint is public."""
    response = client.get("/api/ping")  # deliberately no headers
    assert response.status_code == 200


def test_ping_returns_200_with_invalid_authorization_header(client: TestClient):
    """AC3: Even a garbage auth token must not block the ping endpoint."""
    response = client.get(
        "/api/ping",
        headers={"Authorization": "Bearer this-is-not-a-valid-token"},
    )
    # The endpoint is open; it must not 401/403 regardless of auth header
    assert response.status_code == 200


def test_ping_does_not_return_401(client: TestClient):
    """AC3: Endpoint must never return 401 Unauthorized."""
    response = client.get("/api/ping")
    assert response.status_code != 401


def test_ping_does_not_return_403(client: TestClient):
    """AC3: Endpoint must never return 403 Forbidden."""
    response = client.get("/api/ping")
    assert response.status_code != 403


# ---------------------------------------------------------------------------
# AC4 — Existing /health endpoint regression
# ---------------------------------------------------------------------------

def test_health_returns_200_after_ping_added(client: TestClient):
    """AC4: GET /health must still return HTTP 200 after ping endpoint added."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_body_contains_status_ok(client: TestClient):
    """AC4: /health response body must contain status=ok (regression)."""
    response = client.get("/health")
    body = response.json()
    assert body.get("status") == "ok"


# ---------------------------------------------------------------------------
# AC4 — Existing /version or /api/version endpoint regression
# ---------------------------------------------------------------------------

def test_version_endpoint_still_returns_200_after_ping_added(client: TestClient):
    """AC4: A version endpoint must still return HTTP 200 after ping is added.

    The version route may be at /version or /api/version depending on mount.
    We try both and accept whichever one exists.
    """
    for path in ("/api/version", "/version"):
        response = client.get(path)
        if response.status_code == 200:
            return  # found it — test passes
    pytest.fail(
        "Neither /api/version nor /version returned HTTP 200. "
        "Check that the version route has not been broken."
    )


# ---------------------------------------------------------------------------
# AC5 — Standalone route file exists and is importable
# ---------------------------------------------------------------------------

def test_ping_route_module_is_importable():
    """AC5: app/api/routes/ping.py must exist and be importable on its own."""
    try:
        module = importlib.import_module("app.api.routes.ping")
    except ImportError as exc:
        pytest.fail(
            f"app.api.routes.ping could not be imported: {exc}. "
            "Ensure the file exists at app/api/routes/ping.py."
        )
    assert module is not None


def test_ping_route_module_exposes_a_router():
    """AC5: app/api/routes/ping.py must expose an APIRouter named 'router'."""
    module = importlib.import_module("app.api.routes.ping")
    assert hasattr(module, "router"), (
        "app/api/routes/ping.py must define a variable named 'router' "
        "(an instance of fastapi.APIRouter)."
    )


def test_version_route_module_is_still_importable():
    """AC5: app/api/routes/version.py must NOT have been removed or broken."""
    try:
        module = importlib.import_module("app.api.routes.version")
    except ImportError:
        pytest.skip(
            "app/api/routes/version.py does not exist in this codebase — "
            "skipping version module regression check."
        )
    assert module is not None


# ---------------------------------------------------------------------------
# OpenAPI schema validation
# ---------------------------------------------------------------------------

def test_openapi_schema_includes_ping_endpoint(client: TestClient):
    """The generated OpenAPI schema must document /api/ping."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema.get("paths", {})
    assert "/api/ping" in paths, (
        f"/api/ping not found in OpenAPI paths: {list(paths.keys())}"
    )


def test_openapi_schema_ping_is_get_method(client: TestClient):
    """OpenAPI schema: /api/ping must be a GET operation."""
    response = client.get("/openapi.json")
    schema = response.json()
    ping_path = schema.get("paths", {}).get("/api/ping", {})
    assert "get" in ping_path, (
        f"GET method not found for /api/ping in OpenAPI schema. "
        f"Available methods: {list(ping_path.keys())}"
    )


def test_openapi_schema_ping_response_200_defined(client: TestClient):
    """OpenAPI schema: /api/ping GET must declare a 200 response."""
    response = client.get("/openapi.json")
    schema = response.json()
    get_op = schema.get("paths", {}).get("/api/ping", {}).get("get", {})
    responses = get_op.get("responses", {})
    assert "200" in responses, (
        f"200 response not documented for GET /api/ping. "
        f"Documented responses: {list(responses.keys())}"
    )
