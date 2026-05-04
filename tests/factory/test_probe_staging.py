"""Tests for ProbeStaging — feeds a fake PRD + fake HTTP responses, asserts probe summary."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("STAGING_URL", "https://staging-api.test")
os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))


def _prd(criteria: list[str]) -> dict:
    return {
        "feature_id": "x", "title": "t", "narrative_md": "n",
        "stories": [{"id": "s1", "description": "d", "acceptance_criteria": criteria, "passes": True}],
        "scope": {"touches_db": False, "touches_frontend": False, "touches_infra": False, "files_in_scope": []},
        "hard_blockers": [], "risk_flags": [], "suggested_split": []
    }


def _fake_resp(status: int, body: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


def test_all_probes_pass():
    from handlers import probe_staging  # type: ignore

    prd = _prd(["GET /api/version returns 200 with {\"version\": \"2.0\"}"])
    with patch.object(probe_staging, "_fetch_prd_from_github", return_value=prd), \
         patch.object(probe_staging, "_get_token", return_value="tok"), \
         patch.object(probe_staging, "urlopen", return_value=_fake_resp(200, b'{"version": "2.0"}')):
        result = probe_staging.handler({"feature_id": "x", "merge_sha": "abc123"}, None)
    assert result["passed"] is True
    assert len(result["probes"]) == 1
    assert result["failures"] == []


def test_one_probe_fails():
    from handlers import probe_staging  # type: ignore

    prd = _prd(["GET /api/version returns 200"])
    with patch.object(probe_staging, "_fetch_prd_from_github", return_value=prd), \
         patch.object(probe_staging, "_get_token", return_value="tok"), \
         patch.object(probe_staging, "urlopen", return_value=_fake_resp(500, b'oops')):
        result = probe_staging.handler({"feature_id": "x", "merge_sha": "abc123"}, None)
    assert result["passed"] is False
    assert len(result["failures"]) == 1
    assert result["failures"][0]["expected_status"] == 200
    assert result["failures"][0]["actual_status"] == 500


def test_no_probes_skips_with_passed_true():
    """If the PRD has no HTTP-shaped acceptance criteria, the postdeploy probe
    has nothing to check — pass through."""
    from handlers import probe_staging  # type: ignore

    prd = _prd(["docs/openapi.json includes the endpoint"])
    with patch.object(probe_staging, "_fetch_prd_from_github", return_value=prd):
        result = probe_staging.handler({"feature_id": "x", "merge_sha": "abc123"}, None)
    assert result["passed"] is True
    assert result["probes"] == []
