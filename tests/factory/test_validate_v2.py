"""Smoke tests for validate_v2 step functions (no S3 — exercise locally)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas" / "containers" / "validate_v2"))

import validate_v2  # noqa: E402


def test_ruff_flags_syntax_error(tmp_path, monkeypatch):
    monkeypatch.setattr(validate_v2, "WS_ROOT", tmp_path)
    (tmp_path / "broken.py").write_text("def bad(\n")  # syntax error
    issues = validate_v2._step_ruff()
    assert any(i["tool"] == "ruff" for i in issues)


def test_clean_workspace_passes_ruff(tmp_path, monkeypatch):
    monkeypatch.setattr(validate_v2, "WS_ROOT", tmp_path)
    (tmp_path / "ok.py").write_text("def good():\n    return 1\n")
    issues = validate_v2._step_ruff()
    assert issues == []
