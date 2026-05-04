"""Tests for the RalphTurn filesystem allowlist (sandbox boundary 4)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas" / "containers" / "ralph_turn"))

from allowlist import classify, partition, ALLOWED, DENIED  # noqa: E402


def test_normal_app_path_allowed():
    assert classify("app/api/routes/version.py") is ALLOWED


def test_test_path_allowed():
    assert classify("tests/test_version.py") is ALLOWED


def test_docs_path_allowed():
    assert classify("docs/openapi.json") is ALLOWED


def test_factory_done_sentinel_allowed():
    assert classify(".factory/_DONE_") is ALLOWED


def test_other_factory_path_denied():
    assert classify(".factory/prd.schema.json") is DENIED
    assert classify(".factory/implementer-system.md") is DENIED


def test_workflow_path_denied():
    assert classify(".github/workflows/factory.yml") is DENIED
    assert classify(".github/workflows/quality-gates.yml") is DENIED


def test_other_github_paths_allowed():
    """We allow .github/CODEOWNERS, .github/pull_request_template.md, etc.
    Only the workflows/ subdirectory is sensitive."""
    assert classify(".github/CODEOWNERS") is ALLOWED


def test_factory_infra_denied():
    assert classify("infra/factory/main.tf") is DENIED
    assert classify("infra/factory/state-machine-v2.json.tpl") is DENIED


def test_other_infra_paths_allowed():
    assert classify("infra/webhook-relay/main.tf") is ALLOWED
    assert classify("infra/staging/main.tf") is ALLOWED


def test_dotdot_denied():
    assert classify("../etc/passwd") is DENIED
    assert classify("app/../../etc/passwd") is DENIED


def test_absolute_path_denied():
    assert classify("/etc/passwd") is DENIED


def test_filter_returns_two_lists():
    allowed, denied = partition([
        "app/api/routes/foo.py",
        ".factory/_DONE_",
        ".github/workflows/evil.yml",
        ".factory/prd.schema.json",
        "../etc/shadow",
        "infra/factory/main.tf",
        "tests/test_foo.py",
    ])
    assert sorted(allowed) == [".factory/_DONE_", "app/api/routes/foo.py", "tests/test_foo.py"]
    assert sorted(denied) == [
        "../etc/shadow", ".factory/prd.schema.json", ".github/workflows/evil.yml", "infra/factory/main.tf",
    ]
