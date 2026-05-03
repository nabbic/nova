"""Validates that .factory/prd.schema.json is correct and that fixtures
round-trip against it. The schema is the contract every later phase relies on
(Plan Lambda emits prd.json; RalphTurn reads it; Validate / Review consume it)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / ".factory" / "prd.schema.json"
FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_file_exists():
    assert SCHEMA_PATH.is_file(), f"missing PRD schema at {SCHEMA_PATH}"


def test_schema_is_valid_jsonschema():
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)


def test_minimal_valid_prd_passes():
    schema = _load_json(SCHEMA_PATH)
    fixture = _load_json(FIXTURES / "prd_valid_minimal.json")
    Draft202012Validator(schema).validate(fixture)


def test_blocked_valid_prd_passes():
    """A PRD with hard_blockers populated (the shape PlanGate routes on)
    must still validate as a structurally well-formed PRD."""
    schema = _load_json(SCHEMA_PATH)
    fixture = _load_json(FIXTURES / "prd_valid_blocked.json")
    Draft202012Validator(schema).validate(fixture)


def test_invalid_prd_is_rejected():
    schema = _load_json(SCHEMA_PATH)
    fixture = _load_json(FIXTURES / "prd_invalid_missing_field.json")
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(fixture)
