"""Unit tests for the deterministic sizing rubric.

Per spec §2.2.1, the rubric MUST emit a hard_blocker with reason
`feature_too_large` when ANY of these are exceeded:
  - total_stories > 4
  - total_acceptance_criteria > 12
  - distinct domains touched > 2
  - estimated_files_changed > 25 (HARD threshold; > 15 is SOFT)

It MUST NOT block at the SOFT thresholds, only emit a risk_flag.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))

from common.sizing import evaluate  # noqa: E402


def _prd(*, stories=1, criteria_per=1, domains=("backend",), files_estimate=5) -> dict:
    return {
        "stories": [
            {
                "id": f"s{i+1}",
                "description": f"story {i+1}",
                "acceptance_criteria": [f"criterion {j+1}" for j in range(criteria_per)],
                "passes": False,
            }
            for i in range(stories)
        ],
        "scope": {
            "touches_db":       "db" in domains,
            "touches_frontend": "frontend" in domains,
            "touches_infra":    "infra" in domains,
            "files_in_scope":   [],
        },
        "_estimated_files_changed": files_estimate,
    }


def test_trivial_passes():
    result = evaluate(_prd())
    assert result["hard_blockers"] == []
    assert result["risk_flags"] == []


def test_too_many_stories_blocks():
    result = evaluate(_prd(stories=5, criteria_per=1))
    assert any(b["reason"] == "feature_too_large" for b in result["hard_blockers"])


def test_exactly_four_stories_passes():
    result = evaluate(_prd(stories=4, criteria_per=1))
    assert result["hard_blockers"] == []


def test_too_many_criteria_blocks():
    result = evaluate(_prd(stories=2, criteria_per=7))  # 14 > 12
    assert any(b["reason"] == "feature_too_large" for b in result["hard_blockers"])


def test_exactly_twelve_criteria_passes():
    result = evaluate(_prd(stories=4, criteria_per=3))  # 12 == 12
    assert result["hard_blockers"] == []


def test_three_domains_blocks():
    result = evaluate(_prd(domains=("db", "frontend", "infra")))
    assert any(b["reason"] == "feature_too_large" for b in result["hard_blockers"])


def test_two_domains_passes():
    """backend is implicit (always counted) — see impl. Spec §2.2.1 lists 4
    domains: db / backend / frontend / infra. With backend + infra that's 2."""
    result = evaluate(_prd(domains=("backend", "infra")))
    assert result["hard_blockers"] == []


def test_soft_files_threshold_emits_risk_flag_only():
    result = evaluate(_prd(files_estimate=20))  # > 15, < 25
    assert result["hard_blockers"] == []
    assert "many_files" in result["risk_flags"]


def test_hard_files_threshold_blocks():
    result = evaluate(_prd(files_estimate=30))  # > 25
    assert any(b["reason"] == "feature_too_large" for b in result["hard_blockers"])


def test_blocker_includes_details_string():
    result = evaluate(_prd(stories=10))
    blocker = result["hard_blockers"][0]
    assert blocker["reason"] == "feature_too_large"
    assert isinstance(blocker.get("details"), str)
    assert len(blocker["details"]) > 0
