"""Review Lambda — single Sonnet call producing structured blockers/warnings.

Spec §2.5. Reads prd.json + diff (rendered by upstream task) + system prompt.
Returns a JSON object schema-validated by this handler.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import boto3
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from common.anthropic import messages_create

REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", "claude-sonnet-4-6")
REVIEWER_MAX_TOKENS = int(os.environ.get("REVIEWER_MAX_TOKENS", "3000"))
DIFF_CAP_BYTES = 50_000
BUCKET = os.environ["WORKSPACE_BUCKET"]

_s3 = boto3.client("s3")
_FENCED = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)

REVIEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["passed", "blockers", "warnings"],
    "properties": {
        "passed":   {"type": "boolean"},
        "blockers": {"type": "array", "items": {
            "type": "object",
            "required": ["category", "description"],
            "properties": {
                "category":    {"type": "string", "enum": ["security", "tenancy", "spec", "migration"]},
                "file":        {"type": "string"},
                "line":        {"type": "integer"},
                "description": {"type": "string", "minLength": 1},
                "fix":         {"type": "string"},
            },
        }},
        "warnings": {"type": "array", "items": {"type": "object"}},
    },
}
_VALIDATOR = Draft202012Validator(REVIEW_SCHEMA)


def _find_reviewer_prompt() -> str:
    here = Path(__file__).resolve()
    candidates: list[Path] = [here.parent / ".factory" / "reviewer-system.md"]
    for ancestor in here.parents:
        candidate = ancestor / ".factory" / "reviewer-system.md"
        if candidate not in candidates:
            candidates.append(candidate)
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise RuntimeError(f"reviewer-system.md not found in any of: {candidates}")


def _read(execution_id: str, key: str) -> str:
    obj = _s3.get_object(Bucket=BUCKET, Key=f"{execution_id}/{key}")
    return obj["Body"].read().decode("utf-8")


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCED.search(text)
    if m:
        return json.loads(m.group(1))
    raise json.JSONDecodeError("no JSON object", text, 0)


def _format_repair(blockers: list[dict]) -> str:
    parts = ["# Reviewer blockers (must address before merging)\n"]
    for b in blockers:
        loc = f"{b.get('file', '?')}:{b.get('line', '?')}"
        parts.append(f"## [{b['category']}] {loc}\n\n{b['description']}\n")
        if b.get("fix"):
            parts.append(f"_Suggested fix:_ {b['fix']}\n")
    return "\n".join(parts)


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]

    prd = json.loads(_read(execution_id, "plan/prd.json"))
    try:
        diff = _read(execution_id, "workspace/diff.patch")
    except Exception:
        diff = "<no diff.patch present in workspace>"
    if len(diff.encode("utf-8")) > DIFF_CAP_BYTES:
        diff = diff[:DIFF_CAP_BYTES] + "\n<diff truncated at 50KB>"

    user_prompt = (
        f"# prd.json\n\n```json\n{json.dumps(prd, indent=2)}\n```\n\n"
        f"# git_diff (main..HEAD)\n\n```diff\n{diff}\n```\n"
    )

    resp = messages_create(
        model=REVIEWER_MODEL,
        system=_find_reviewer_prompt(),
        user=user_prompt,
        max_tokens=REVIEWER_MAX_TOKENS,
    )
    review = _extract_json(resp["text"])
    try:
        _VALIDATOR.validate(review)
    except ValidationError as e:
        raise RuntimeError(f"Review output failed schema: {e.message}") from e

    # Self-consistency: if blockers non-empty, passed MUST be false.
    if review["blockers"] and review["passed"]:
        review["passed"] = False

    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/review/blockers.json",
        Body=json.dumps(review, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    if not review["passed"]:
        repair = _format_repair(review["blockers"])
        _s3.put_object(
            Bucket=BUCKET,
            Key=f"{execution_id}/workspace/repair_context.md",
            Body=repair.encode("utf-8"),
            ContentType="text/markdown",
        )

    return {
        "passed":            review["passed"],
        "blockers":          review["blockers"],
        "blocker_count":     len(review["blockers"]),
        "warning_count":     len(review.get("warnings", [])),
        "input_tokens":      resp["input_tokens"],
        "output_tokens":     resp["output_tokens"],
    }
