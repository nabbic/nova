"""Deterministic feature-sizing rubric for the Plan Lambda.

Spec §2.2.1: the Plan Lambda calls evaluate() on the parsed PRD AFTER Haiku
returns it, before writing prd.json to S3. Any breach populates
`hard_blockers` so PlanGate can route the run to MarkBlocked without burning
Ralph turns.

This module is pure — no I/O, no external dependencies. All thresholds are
constants for easy auditing.
"""

from __future__ import annotations

from typing import Any

# Spec §2.2.1 thresholds
MAX_STORIES = 4
MAX_TOTAL_CRITERIA = 12
MAX_DOMAINS = 2
SOFT_FILES_THRESHOLD = 15
HARD_FILES_THRESHOLD = 25


def _domains(scope: dict[str, Any]) -> set[str]:
    out = {"backend"}  # any feature touches backend by default
    if scope.get("touches_db"):
        out.add("db")
    if scope.get("touches_frontend"):
        out.add("frontend")
    if scope.get("touches_infra"):
        out.add("infra")
    return out


def evaluate(prd: dict[str, Any]) -> dict[str, Any]:
    """Apply the rubric to a PRD dict.

    Returns:
        {
          "hard_blockers": [{reason, details, suggested_split?}, ...],
          "risk_flags":    ["many_files", ...]
        }

    The caller (Plan Lambda) merges these into the PRD it writes to S3.
    """
    stories = prd.get("stories", [])
    scope = prd.get("scope", {}) or {}
    files_estimate = prd.get("_estimated_files_changed", 0)

    n_stories = len(stories)
    n_criteria = sum(len(s.get("acceptance_criteria", [])) for s in stories)
    domains = _domains(scope)
    n_domains = len(domains)

    hard_blockers: list[dict[str, Any]] = []
    risk_flags: list[str] = []
    breaches: list[str] = []

    if n_stories > MAX_STORIES:
        breaches.append(f"{n_stories} stories (max {MAX_STORIES})")

    if n_criteria > MAX_TOTAL_CRITERIA:
        breaches.append(f"{n_criteria} acceptance criteria (max {MAX_TOTAL_CRITERIA})")

    if n_domains > MAX_DOMAINS:
        breaches.append(f"{n_domains} domains touched: {sorted(domains)} (max {MAX_DOMAINS})")

    if files_estimate > HARD_FILES_THRESHOLD:
        breaches.append(f"~{files_estimate} files changed (hard max {HARD_FILES_THRESHOLD})")
    elif files_estimate > SOFT_FILES_THRESHOLD:
        risk_flags.append("many_files")

    if breaches:
        hard_blockers.append({
            "reason":  "feature_too_large",
            "details": "; ".join(breaches),
        })

    return {
        "hard_blockers": hard_blockers,
        "risk_flags":    risk_flags,
    }
