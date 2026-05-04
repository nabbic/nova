"""Tests for the probe parser — extracts HTTP probes from acceptance criteria."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))

from common.probe import extract_probes  # noqa: E402


def test_simple_get_returns_status():
    out = extract_probes(["GET /api/version returns 200 with {\"version\": ...}"])
    assert out == [{"method": "GET", "path": "/api/version", "expected_status": 200, "auth": False}]


def test_post_with_body_keyword():
    out = extract_probes(["POST /api/engagements returns 201 when authenticated"])
    assert out == [{"method": "POST", "path": "/api/engagements", "expected_status": 201, "auth": True}]


def test_403_with_when_clause():
    out = extract_probes(["GET /api/engagements/{id} returns 403 on buyer_org_id mismatch"])
    assert out == [{"method": "GET", "path": "/api/engagements/{id}", "expected_status": 403, "auth": True}]


def test_skips_non_http_criterion():
    out = extract_probes([
        "docs/openapi.json includes the endpoint",
        "Returns 200 with engagement data",
    ])
    assert out == []


def test_multiple_probes_per_criterion_keeps_first():
    """Criterion that mentions both GET and POST — we keep the first verb only."""
    out = extract_probes(["GET /api/x returns 200 (POST /api/x returns 405)"])
    assert len(out) == 1
    assert out[0]["method"] == "GET"


def test_handles_path_with_brace_template():
    out = extract_probes(["GET /api/engagements/{engagement_id}/export returns 200"])
    assert out[0]["path"] == "/api/engagements/{engagement_id}/export"


def test_lowercase_verb_normalized():
    out = extract_probes(["get /api/health returns 200"])
    assert out[0]["method"] == "GET"
