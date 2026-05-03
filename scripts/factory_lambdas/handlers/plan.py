"""Plan Lambda — Haiku 4.5 turns spec_raw.md into prd.json.

Spec §2.2. After Haiku returns, runs the deterministic sizing rubric
(common.sizing.evaluate) and merges its output. Validates against
.factory/prd.schema.json before writing to S3.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import boto3
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from common.anthropic import messages_create
from common.sizing import evaluate as evaluate_sizing

BUCKET = os.environ["WORKSPACE_BUCKET"]
HAIKU_MODEL = os.environ.get("PLAN_MODEL", "claude-haiku-4-5")
PLAN_MAX_TOKENS = int(os.environ.get("PLAN_MAX_TOKENS", "4096"))

_s3 = boto3.client("s3")
_FENCED = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)

# Schema lookup is robust across Lambda runtime + local test contexts
_SCHEMA_PATH_CANDIDATES = [
    Path(__file__).resolve().parent / ".factory" / "prd.schema.json",                     # Lambda runtime: /var/task/.factory/
    Path(__file__).resolve().parents[3] / ".factory" / "prd.schema.json",                 # repo root from scripts/factory_lambdas/handlers/
]
_SCHEMA: dict | None = None
for _p in _SCHEMA_PATH_CANDIDATES:
    if _p.exists():
        _SCHEMA = json.loads(_p.read_text(encoding="utf-8"))
        break
if _SCHEMA is None:
    raise RuntimeError(f"prd.schema.json not found in any of: {_SCHEMA_PATH_CANDIDATES}")
_VALIDATOR = Draft202012Validator(_SCHEMA)

SYSTEM_PROMPT = """You are the Plan stage of the Nova Factory.

Read the spec_raw.md and the project's CLAUDE.md, then produce a structured
PRD as JSON conforming to the schema you are given. The PRD has these
top-level fields: feature_id, title, narrative_md, stories[], scope,
hard_blockers[], risk_flags[], suggested_split[].

Hard rules:
- Return ONLY a valid JSON object. No prose, no code fences. Just the object.
- Each story has id (s1, s2, ...), description, acceptance_criteria[] (≥1),
  passes (always false at plan time).
- scope.files_in_scope lists likely paths the implementer will touch.
- Always include feature_id verbatim from feature_meta.json.
- Always include the original narrative_md verbatim from spec_raw.md.

If the feature is clearly too large, you may populate `suggested_split` —
the orchestrator's deterministic rubric will set the actual hard_blockers.
You should NOT set hard_blockers yourself — leave that to the orchestrator.

Set `_estimated_files_changed` (a private field) to your best guess of how
many distinct files the implementer would need to modify. The orchestrator
uses this for sizing.
"""


def _read_text(execution_id: str, key: str) -> str:
    obj = _s3.get_object(Bucket=BUCKET, Key=f"{execution_id}/{key}")
    return obj["Body"].read().decode("utf-8")


def _read_repo_claude_md() -> str:
    """The Lambda zip ships with .factory/ but not the repo root CLAUDE.md
    (too large + changes too often). For Phase 2 we hardcode a short
    summary sufficient for Haiku to size the feature. Phase 3 will inject
    a slimmed CLAUDE.md from the workspace S3 prefix."""
    return (
        "Nova is a Tech DD platform. Backend = FastAPI, frontend = React+TS, "
        "DB = RDS Postgres, infra = Terraform on AWS. Multi-tenant by "
        "buyer_org_id. All endpoints have OpenAPI schemas. See repo "
        "CLAUDE.md for full details."
    )


def _extract_json(text: str) -> dict:
    """Try plain parse, then ```json fenced extraction."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCED.search(text)
    if m:
        return json.loads(m.group(1))
    raise json.JSONDecodeError("no JSON object found", text, 0)


def _call_haiku(spec_md: str, claude_md: str, repair_note: str | None = None) -> dict:
    schema_str = json.dumps(_SCHEMA, indent=2)
    user = (
        f"# spec_raw.md\n\n{spec_md}\n\n"
        f"# CLAUDE.md (project context)\n\n{claude_md}\n\n"
        f"# .factory/prd.schema.json (your output must match)\n\n```json\n{schema_str}\n```"
    )
    if repair_note:
        user += f"\n\n# REPAIR NOTE\n\n{repair_note}"
    return messages_create(
        model=HAIKU_MODEL,
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=PLAN_MAX_TOKENS,
    )


def _ask_and_parse(spec_md: str, claude_md: str, repair_note: str | None = None) -> tuple[dict, dict]:
    resp = _call_haiku(spec_md, claude_md, repair_note)
    return _extract_json(resp["text"]), resp


def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]

    spec_md   = _read_text(execution_id, "intake/spec_raw.md")
    meta      = json.loads(_read_text(execution_id, "intake/feature_meta.json"))
    claude_md = _read_repo_claude_md()

    # First call
    try:
        prd, _resp = _ask_and_parse(spec_md, claude_md)
    except json.JSONDecodeError:
        prd, _resp = _ask_and_parse(spec_md, claude_md, repair_note="Your previous response could not be parsed as JSON. Emit ONLY the JSON object, no prose, no fences.")

    # Apply deterministic sizing rubric BEFORE schema validation —
    # _estimated_files_changed is read by sizing but not allowed by the schema.
    sizing = evaluate_sizing(prd)
    prd.pop("_estimated_files_changed", None)
    prd["hard_blockers"] = list(prd.get("hard_blockers", [])) + sizing["hard_blockers"]
    prd["risk_flags"]    = sorted(set(prd.get("risk_flags", [])) | set(sizing["risk_flags"]))

    # Force feature_id from intake — Haiku might miscopy.
    prd["feature_id"] = feature_id
    prd["title"]      = prd.get("title") or meta["title"]

    # Validate. If fail, one repair turn (which itself may include the field again).
    try:
        _VALIDATOR.validate(prd)
    except ValidationError as e:
        prd, _resp = _ask_and_parse(spec_md, claude_md, repair_note=f"Your previous output failed schema validation: {e.message}. Re-emit a valid PRD as JSON only.")
        prd.pop("_estimated_files_changed", None)
        # Re-merge sizing for the retry
        sizing = evaluate_sizing(prd)
        prd["hard_blockers"] = list(prd.get("hard_blockers", [])) + sizing["hard_blockers"]
        prd["risk_flags"]    = sorted(set(prd.get("risk_flags", [])) | set(sizing["risk_flags"]))
        prd["feature_id"]    = feature_id
        prd["title"]         = prd.get("title") or meta["title"]
        try:
            _VALIDATOR.validate(prd)
        except ValidationError as e2:
            raise RuntimeError(f"Plan output invalid after repair: {e2.message}") from e2

    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/plan/prd.json",
        Body=json.dumps(prd, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return {
        "feature_id":      feature_id,
        "hard_blockers":   prd["hard_blockers"],
        "suggested_split": prd["suggested_split"],
        "scope":           prd["scope"],
        "blocked":         len(prd["hard_blockers"]) > 0,
    }
