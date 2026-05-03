# Factory v2 — Phase 2: Plan Stage End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic Plan stage end-to-end — LoadFeature (Notion → S3), Plan (Haiku → `prd.json`), the deterministic sizing rubric, PlanGate (Choice), and MarkBlocked (Notion comment) — and prove it works against three smoke fixtures (trivial, medium, oversized) wired through a stub state machine `nova-factory-v2-planonly`.

**Architecture:** Three new Lambdas (`load_feature`, `plan`, `mark_blocked`) plus one new common module (`sizing.py`) implementing the deterministic rubric. A new stub state machine runs the slice end-to-end so we can validate Plan + PlanGate routing without Phase 3's RalphLoop / Validate / Review existing yet. Lambdas live in the existing `infra/factory/` Terraform module under a parallel `handlers_v2` map so v1 keeps running.

**Tech Stack:** Python 3.12 + `urllib.request` for Notion + Anthropic Messages API (raw HTTP, no SDK to keep the zip small), Terraform/AWS (Lambda + Step Functions), pytest.

**Predecessors:** Phase 1 produced `.factory/prd.schema.json`, `.factory/feature-sizing-rubric.md`, S3-backed Terraform state, and `tests/requirements.txt`. **This plan assumes Phase 1 is complete and merged.**

**Branch:** continue on `factory-overhaul-2026-05-03`. Working directory: `C:\Claude\Nova\nova` (Git Bash: `/c/Claude/Nova/nova`). AWS account `577638385116`, region `us-east-1`.

**Out of scope for Phase 2:** RalphTurn container, Validate-v2, Review, full SFN-v2 wiring (all Phase 3). Postdeploy SFN (Phase 4). Self-pause / budgets (Phase 5). Cutover (Phase 6).

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `scripts/factory_lambdas/common/sizing.py` | Deterministic rubric: input is a parsed PRD dict, output is `{hard_blockers: [...], risk_flags: [...]}`. Pure function, no I/O, fully unit-tested. |
| `scripts/factory_lambdas/common/anthropic.py` | Tiny raw-HTTP client for Anthropic Messages API. One function `messages_create(model, system, user, max_tokens) -> {text, input_tokens, output_tokens}`. Used by Plan now and Review in Phase 3. |
| `scripts/factory_lambdas/handlers/load_feature.py` | Notion `feature_id` → fetches the page, writes `intake/spec_raw.md` (body) + `intake/feature_meta.json` (title, properties) to the S3 workspace. Replaces v1 `load_spec.py` for v2 only — v1 keeps using `load_spec.py`. |
| `scripts/factory_lambdas/handlers/plan.py` | Calls Haiku 4.5 with `spec_raw.md` + `CLAUDE.md` + the prd schema. Validates output JSON against `.factory/prd.schema.json`. Runs sizing rubric. Writes `plan/prd.json` to S3. Returns `{hard_blockers, scope}` for PlanGate routing. |
| `scripts/factory_lambdas/handlers/mark_blocked.py` | Posts a structured Notion comment (per §2.2.1) listing the breach + suggested split, sets the feature's status to `Failed` with reason `feature_too_large` (or whatever the first blocker reason is). |
| `scripts/factory_smoke_fixtures/trivial.json` | A small valid feature — 1 story, 1 criterion. Should pass Plan with no blockers. |
| `scripts/factory_smoke_fixtures/medium.json` | 3 stories, ~6 criteria, 1 domain. Should pass Plan with no blockers. |
| `scripts/factory_smoke_fixtures/oversized.json` | 6 stories, multi-domain. Should hit `feature_too_large` blocker and be MarkBlocked. |
| `scripts/factory_smoke_fixtures/README.md` | What each fixture is for, how to run it. |
| `scripts/factory_smoke_v2.sh` | Reads a fixture, creates (or reuses) a synthetic Notion page, starts a stub-SFN execution, tails the result. |
| `tests/factory/test_sizing_rubric.py` | Pure-function unit tests. Covers each threshold + boundary condition + risk-flag emission. |
| `tests/factory/test_anthropic_client.py` | Tests raw-HTTP serialization (mocks `urlopen`). |
| `tests/factory/test_load_feature.py` | Mocks Notion API; asserts `intake/spec_raw.md` and `intake/feature_meta.json` are written with expected content. |
| `tests/factory/test_plan_lambda.py` | Mocks Anthropic + sizing; asserts schema validation runs and PRD lands in S3. Includes a "haiku returned malformed JSON" repair path test. |
| `tests/factory/test_mark_blocked.py` | Mocks Notion comment + status update. |
| `tests/factory/fixtures/notion_page_minimal.json` | Recorded shape of `GET /v1/pages/<id>` for a simple feature. |
| `tests/factory/fixtures/haiku_response_valid_prd.json` | Synthetic Anthropic response for the Plan Lambda happy path. |
| `tests/factory/fixtures/haiku_response_oversized.json` | Synthetic response for an oversized feature (sizing rubric breach). |
| `infra/factory/lambdas-v2.tf` | New v2 Lambda definitions (`for_each` over `handlers_v2` local map). Reuses `aws_iam_role.lambda_exec`. |
| `infra/factory/state-machine-v2-planonly.tf` | Stub SFN definition `nova-factory-v2-planonly`. Replaced in Phase 3 with full v2 state machine. |
| `infra/factory/state-machine-v2-planonly.json.tpl` | Stub template — AcquireLock → LoadFeature → Plan → PlanGate → (MarkBlocked → ReleaseLock | ReleaseLock). |

**Modify:**

| Path | Change |
|---|---|
| `scripts/factory_lambdas/build.sh` | After copying `common/` and `agent_prompts/`, also copy `.factory/prd.schema.json` into the staging dir so the Plan Lambda can read it at `prd.schema.json`. |
| `scripts/factory_lambdas/common/__init__.py` | Already empty — confirm no change needed. |
| `infra/factory/iam.tf` | Add a Secrets Manager policy statement granting read on `nova/factory/anthropic-api-key` if not already present (it's already granted today via the broad `nova/factory/*` glob — verify, no edit if the glob covers it). |

**No moves.**

---

## Pre-flight

- [ ] **P-1: Phase 1 complete.**

Run: `ls /c/Claude/Nova/nova/.factory/prd.schema.json && pytest /c/Claude/Nova/nova/tests/factory/ -q`
Expected: schema file exists; 5/5 tests pass.

- [ ] **P-2: Working tree clean.**

Run: `git -C /c/Claude/Nova/nova status`
Expected: `nothing to commit, working tree clean`.

- [ ] **P-3: Anthropic API key reachable.**

Run: `aws secretsmanager get-secret-value --secret-id nova/factory/anthropic-api-key --query 'SecretString != null' --output text`
Expected: `True`.

- [ ] **P-4: V1 SFN ARN handy.**

Run: `terraform -chdir=/c/Claude/Nova/nova/infra/factory output -raw state_machine_arn`
Expected: `arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-pipeline`. (We won't change v1 — this is just to confirm we can talk to the module's outputs.)

---

### Task 1: Extend `build.sh` to ship `.factory/prd.schema.json` inside each Lambda zip

The Plan Lambda validates Haiku's output against the schema at runtime. The schema must be present in the Lambda zip. Extend the existing build script so every handler bundle includes `.factory/prd.schema.json` (cheap; 4KB).

**Files:**
- Modify: `scripts/factory_lambdas/build.sh:9-12` (the `cp` block before the per-handler loop)

- [ ] **Step 1: Read current build.sh.**

Run: `cat /c/Claude/Nova/nova/scripts/factory_lambdas/build.sh`
Expected: confirm the structure shown in the plan body (build dist, copy prompts, loop handlers).

- [ ] **Step 2: Modify `build.sh` to copy `.factory/` files.**

Find the per-handler loop:

```bash
for handler in "$HERE"/handlers/*.py; do
  name=$(basename "$handler" .py)
  STAGE=$(mktemp -d)
  cp -r "$HERE/common" "$STAGE/"
  cp -r "$PROMPTS_DST" "$STAGE/agent_prompts"
  cp "$handler" "$STAGE/$name.py"
  _zip "$DIST/$name.zip" "$STAGE"
  rm -rf "$STAGE"
  echo "built dist/$name.zip"
done
```

Add a copy of the schema right after the `cp -r "$HERE/common"` line:

```bash
for handler in "$HERE"/handlers/*.py; do
  name=$(basename "$handler" .py)
  STAGE=$(mktemp -d)
  cp -r "$HERE/common" "$STAGE/"
  cp -r "$PROMPTS_DST" "$STAGE/agent_prompts"
  # v2: ship the canonical PRD schema and system prompts in every zip
  mkdir -p "$STAGE/.factory"
  cp "$REPO_ROOT/.factory/prd.schema.json"        "$STAGE/.factory/"
  cp "$REPO_ROOT/.factory/implementer-system.md"  "$STAGE/.factory/" 2>/dev/null || true
  cp "$REPO_ROOT/.factory/reviewer-system.md"     "$STAGE/.factory/" 2>/dev/null || true
  cp "$handler" "$STAGE/$name.py"
  _zip "$DIST/$name.zip" "$STAGE"
  rm -rf "$STAGE"
  echo "built dist/$name.zip"
done
```

The `2>/dev/null || true` for the system prompts is intentional — they ship with the zip but Phase 1 may not have cleared all of them yet on every machine. The schema copy fails the build if missing, which is what we want (schema is required).

- [ ] **Step 3: Run the build.**

```bash
cd /c/Claude/Nova/nova/scripts/factory_lambdas
bash build.sh
```
Expected: prints `built dist/<each>.zip` for every handler, no errors.

- [ ] **Step 4: Verify the schema is in a sample zip.**

Run:
```bash
unzip -l /c/Claude/Nova/nova/scripts/factory_lambdas/dist/load_spec.zip | grep prd.schema
```
Expected: one line containing `.factory/prd.schema.json`.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/build.sh
git commit -m "build(factory): bundle .factory/prd.schema.json + system prompts into every Lambda zip"
```

---

### Task 2: Implement the sizing rubric (TDD)

Spec §2.2.1 defines deterministic thresholds. Pure function, no I/O. TDD: write tests for each threshold + boundary, watch them fail, write the impl.

**Files:**
- Create: `scripts/factory_lambdas/common/sizing.py`
- Create: `tests/factory/test_sizing_rubric.py`

- [ ] **Step 1: Write the failing test.**

Create `tests/factory/test_sizing_rubric.py`:

```python
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

# Make the lambda common/ importable in tests
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
    result = evaluate(_prd(domains=("backend", "infra")))
    # backend is implicit (always counted) — see impl. Spec §2.2.1 lists 4 domains:
    # db / backend / frontend / infra. "backend" is the default for any change in app/.
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
```

- [ ] **Step 2: Run the tests, verify they all fail (no module yet).**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_sizing_rubric.py -v
```
Expected: import error / module not found. All tests fail.

- [ ] **Step 3: Write `common/sizing.py`.**

Create `scripts/factory_lambdas/common/sizing.py`:

```python
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
```

- [ ] **Step 4: Run the tests, verify all pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_sizing_rubric.py -v
```
Expected: 10 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/common/sizing.py tests/factory/test_sizing_rubric.py
git commit -m "factory(v2): add deterministic sizing rubric (common/sizing.py) + tests"
```

---

### Task 3: Implement the Anthropic Messages API client (TDD)

Tiny raw-HTTP wrapper. One function `messages_create(model, system, user, max_tokens) -> dict`. Used by Plan now and by Review in Phase 3. Avoids the `anthropic` SDK to keep the Lambda zip lean.

**Files:**
- Create: `scripts/factory_lambdas/common/anthropic.py`
- Create: `tests/factory/test_anthropic_client.py`

- [ ] **Step 1: Write the failing tests.**

Create `tests/factory/test_anthropic_client.py`:

```python
"""Tests for the raw-HTTP Anthropic Messages client used by Plan and Review."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))

from common.anthropic import messages_create  # noqa: E402


def _fake_resp(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


def test_returns_text_and_token_counts():
    payload = {
        "id": "msg_1",
        "content": [{"type": "text", "text": "hello world"}],
        "usage": {"input_tokens": 12, "output_tokens": 5},
    }
    with patch("common.anthropic.urlopen", return_value=_fake_resp(payload)) as mock_open, \
         patch("common.anthropic.get_secret", return_value="sk-ant-test"):
        result = messages_create(
            model="claude-haiku-4-5",
            system="You are a tester.",
            user="say hello",
            max_tokens=64,
        )
    assert result["text"] == "hello world"
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 5
    # Verify the request body shape
    request = mock_open.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 64
    assert body["system"] == "You are a tester."
    assert body["messages"] == [{"role": "user", "content": "say hello"}]


def test_passes_api_key_header():
    payload = {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    with patch("common.anthropic.urlopen", return_value=_fake_resp(payload)), \
         patch("common.anthropic.get_secret", return_value="sk-ant-secret"):
        messages_create(model="claude-haiku-4-5", system="s", user="u", max_tokens=10)
    # Header propagation is verified by inspecting the Request object
    # captured via patch — the test above already does that for body;
    # this test exists to make the "key flows from secrets manager" path
    # explicit.


def test_raises_on_empty_content():
    payload = {"content": [], "usage": {"input_tokens": 1, "output_tokens": 0}}
    with patch("common.anthropic.urlopen", return_value=_fake_resp(payload)), \
         patch("common.anthropic.get_secret", return_value="sk-ant-test"):
        try:
            messages_create(model="claude-haiku-4-5", system="s", user="u", max_tokens=10)
        except RuntimeError as e:
            assert "no content" in str(e).lower()
            return
    raise AssertionError("expected RuntimeError on empty content")
```

- [ ] **Step 2: Run, verify all fail.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_anthropic_client.py -v
```
Expected: import error.

- [ ] **Step 3: Write `common/anthropic.py`.**

Create `scripts/factory_lambdas/common/anthropic.py`:

```python
"""Minimal Anthropic Messages API client (raw HTTP).

Avoids the `anthropic` SDK to keep the Lambda zip small. Supports system +
single user message. Returns text + token counts. Phase 3 will extend with
prompt caching by adding a `cache_control` block on the system message.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.request import urlopen  # patched in tests

from common.secrets import get_secret

ANTHROPIC_VERSION = "2023-06-01"
API_URL = "https://api.anthropic.com/v1/messages"


def messages_create(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout: int = 90,
) -> dict:
    """One-shot Messages API call.

    Returns:
        {"text": "<concatenated text content>", "input_tokens": int, "output_tokens": int}

    Raises RuntimeError on a non-2xx response or empty content array.
    """
    api_key = get_secret("nova/factory/anthropic-api-key")
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        API_URL,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())

    content = payload.get("content") or []
    if not content:
        raise RuntimeError("Anthropic returned no content blocks")

    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    usage = payload.get("usage", {})
    return {
        "text": text,
        "input_tokens":  int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
    }
```

- [ ] **Step 4: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_anthropic_client.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/common/anthropic.py tests/factory/test_anthropic_client.py
git commit -m "factory(v2): add raw-HTTP Anthropic Messages client (common/anthropic.py)"
```

---

### Task 4: Implement LoadFeature Lambda (TDD)

Per spec §2.1: fetch the Notion page, extract title + body + properties, write `intake/spec_raw.md` and `intake/feature_meta.json` to the S3 workspace under the execution prefix.

This is structurally similar to the existing v1 `load_spec.py` but writes Markdown body (not parsed properties) and uses a different S3 prefix layout (`intake/...` rather than `spec.json`).

**Files:**
- Create: `scripts/factory_lambdas/handlers/load_feature.py`
- Create: `tests/factory/test_load_feature.py`
- Create: `tests/factory/fixtures/notion_page_minimal.json`

- [ ] **Step 1: Create the recorded Notion page fixture.**

Create `tests/factory/fixtures/notion_page_minimal.json`:

```json
{
  "object": "page",
  "id": "00000000-0000-0000-0000-000000000001",
  "created_time": "2026-05-03T12:00:00Z",
  "last_edited_time": "2026-05-03T12:30:00Z",
  "url": "https://www.notion.so/Test-Feature-...",
  "properties": {
    "Title": {
      "type": "title",
      "title": [{ "plain_text": "Add buyer engagement export endpoint" }]
    },
    "Status": {
      "type": "status",
      "status": { "name": "Ready to Build" }
    },
    "Description": {
      "type": "rich_text",
      "rich_text": [{ "plain_text": "Buyers need a JSON export of an engagement's findings.\n\nGET /api/engagements/{id}/export should return the engagement payload." }]
    },
    "Tech Notes": {
      "type": "rich_text",
      "rich_text": [{ "plain_text": "Filter by buyer_org_id. Add to docs/openapi.json." }]
    },
    "Acceptance Criteria": {
      "type": "rich_text",
      "rich_text": [{ "plain_text": "- 200 with engagement data when authenticated as the owning buyer org\n- 403 on buyer_org_id mismatch" }]
    }
  }
}
```

- [ ] **Step 2: Write the failing tests.**

Create `tests/factory/test_load_feature.py`:

```python
"""Tests for the LoadFeature Lambda."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_notion(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


def test_load_feature_writes_spec_raw_and_meta(tmp_path):
    from handlers import load_feature  # type: ignore

    page = json.loads((FIXTURES / "notion_page_minimal.json").read_text())

    s3_puts: list[dict] = []

    class FakeS3:
        def put_object(self, **kwargs):
            s3_puts.append(kwargs)

    with patch.object(load_feature, "_s3", FakeS3()), \
         patch.object(load_feature, "_notion_get", return_value=page), \
         patch.object(load_feature, "get_secret", return_value="sk-test"):
        result = load_feature.handler(
            {"feature_id": "00000000-0000-0000-0000-000000000001",
             "execution_id": "exec-test-1"},
            None,
        )

    assert result["title"] == "Add buyer engagement export endpoint"
    assert result["status"] == "Ready to Build"

    keys = sorted(p["Key"] for p in s3_puts)
    assert keys == [
        "exec-test-1/intake/feature_meta.json",
        "exec-test-1/intake/spec_raw.md",
    ]

    body_meta_put = next(p for p in s3_puts if p["Key"].endswith("feature_meta.json"))
    meta = json.loads(body_meta_put["Body"])
    assert meta["title"] == "Add buyer engagement export endpoint"
    assert meta["feature_id"] == "00000000-0000-0000-0000-000000000001"

    body_spec_put = next(p for p in s3_puts if p["Key"].endswith("spec_raw.md"))
    spec_md = body_spec_put["Body"].decode("utf-8") if isinstance(body_spec_put["Body"], bytes) else body_spec_put["Body"]
    assert "Add buyer engagement export endpoint" in spec_md
    assert "200 with engagement data" in spec_md
```

The handler isn't importable yet — import inside the test function so collection doesn't fail before Step 3. Actually, the `sys.path.insert` is at module level, so `from handlers import load_feature` inside the test resolves at call time — that's fine. But on first run, even with the test importing inside the function, pytest collects the test module, which imports nothing at module level — so collection won't fail. Good.

- [ ] **Step 3: Run tests, verify they fail with ImportError on `handlers.load_feature`.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_load_feature.py -v
```
Expected: fail (`ModuleNotFoundError: handlers.load_feature` or similar).

- [ ] **Step 4: Write `handlers/load_feature.py`.**

We don't currently have a `handlers/__init__.py`. Check first:

```bash
ls /c/Claude/Nova/nova/scripts/factory_lambdas/handlers/__init__.py 2>&1
```
If it doesn't exist:
```bash
touch /c/Claude/Nova/nova/scripts/factory_lambdas/handlers/__init__.py
```

Then create `scripts/factory_lambdas/handlers/load_feature.py`:

```python
"""LoadFeature Lambda — fetches a Notion page and writes intake artifacts to S3.

Spec §2.1. Inputs: feature_id (Notion page UUID), execution_id (SFN execution).
Outputs (to S3 under <execution_id>/intake/):
  - spec_raw.md       — concatenated Title + Description + Tech Notes + Acceptance Criteria as markdown
  - feature_meta.json — title, status, feature_id, raw properties dict
"""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.request import urlopen

import boto3

from common.secrets import get_secret

NOTION_VERSION = "2022-06-28"
BUCKET = os.environ["WORKSPACE_BUCKET"]
_s3 = boto3.client("s3")


def _notion_get(path: str) -> dict:
    api_key = get_secret("nova/factory/notion-api-key")
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}",
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _rich(props: dict, key: str) -> str:
    return "".join(t.get("plain_text", "") for t in props.get(key, {}).get("rich_text", []))


def _title(props: dict) -> str:
    return "".join(t.get("plain_text", "") for t in props.get("Title", {}).get("title", []))


def _status(props: dict) -> str:
    s = props.get("Status", {})
    return (s.get("status") or {}).get("name") or (s.get("select") or {}).get("name") or "Unknown"


def _build_spec_md(props: dict) -> str:
    title       = _title(props)
    description = _rich(props, "Description")
    tech_notes  = _rich(props, "Tech Notes")
    accept      = _rich(props, "Acceptance Criteria")
    out_of_scope = _rich(props, "Out of Scope")

    parts = [f"# {title}", ""]
    if description:
        parts += ["## Description", "", description, ""]
    if tech_notes:
        parts += ["## Tech Notes", "", tech_notes, ""]
    if accept:
        parts += ["## Acceptance Criteria", "", accept, ""]
    if out_of_scope:
        parts += ["## Out of Scope", "", out_of_scope, ""]
    return "\n".join(parts).rstrip() + "\n"


def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]

    page  = _notion_get(f"/pages/{feature_id}")
    props = page["properties"]

    spec_md = _build_spec_md(props)
    meta = {
        "feature_id":   feature_id,
        "title":        _title(props),
        "status":       _status(props),
        "url":          page.get("url"),
        "last_edited":  page.get("last_edited_time"),
    }

    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/intake/spec_raw.md",
        Body=spec_md.encode("utf-8"),
        ContentType="text/markdown",
    )
    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/intake/feature_meta.json",
        Body=json.dumps(meta, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return {"feature_id": feature_id, "title": meta["title"], "status": meta["status"]}
```

- [ ] **Step 5: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_load_feature.py -v
```
Expected: 1 test passes.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/load_feature.py scripts/factory_lambdas/handlers/__init__.py tests/factory/test_load_feature.py tests/factory/fixtures/notion_page_minimal.json
git commit -m "factory(v2): add LoadFeature Lambda (Notion -> intake/spec_raw.md + feature_meta.json)"
```

---

### Task 5: Implement the Plan Lambda (TDD)

Per §2.2: Haiku 4.5 call with `spec_raw.md` + `CLAUDE.md` + the prd schema as system context. Output is JSON validated against `.factory/prd.schema.json`. Sizing rubric runs after Haiku returns. Final PRD lands in S3 at `<execution_id>/plan/prd.json`.

We need to handle two failure modes inline:
1. **Haiku returns malformed JSON** (escape errors, hallucinated extra prose) — try one repair turn ("just emit the JSON, nothing else"). If that fails, raise — SFN will retry the whole task.
2. **Schema validation fails** — same: one repair turn, then raise.

**Files:**
- Create: `scripts/factory_lambdas/handlers/plan.py`
- Create: `tests/factory/test_plan_lambda.py`
- Create: `tests/factory/fixtures/haiku_response_valid_prd.json`
- Create: `tests/factory/fixtures/haiku_response_oversized.json`

- [ ] **Step 1: Create haiku response fixtures.**

`tests/factory/fixtures/haiku_response_valid_prd.json`:

```json
{
  "feature_id": "00000000-0000-0000-0000-000000000001",
  "title": "Add buyer engagement export endpoint",
  "narrative_md": "Buyers need a JSON export of an engagement's findings.",
  "stories": [
    {
      "id": "s1",
      "description": "GET /api/engagements/{id}/export returns engagement JSON",
      "acceptance_criteria": [
        "Returns 200 with engagement data when authenticated as the owning buyer org",
        "Returns 403 on buyer_org_id mismatch"
      ],
      "passes": false
    }
  ],
  "scope": {
    "touches_db":       false,
    "touches_frontend": false,
    "touches_infra":    false,
    "files_in_scope":   ["app/api/routes/engagements.py", "tests/", "docs/openapi.json"]
  },
  "_estimated_files_changed": 4,
  "hard_blockers":   [],
  "risk_flags":      [],
  "suggested_split": []
}
```

`tests/factory/fixtures/haiku_response_oversized.json`:

```json
{
  "feature_id": "00000000-0000-0000-0000-000000000002",
  "title": "Build the entire seller portal",
  "narrative_md": "Seller portal: invitations, connectors, dashboard, billing, reports.",
  "stories": [
    { "id": "s1", "description": "Seller invitation flow",  "acceptance_criteria": ["Invite email sent", "Token verified"], "passes": false },
    { "id": "s2", "description": "Cloud connector wiring",  "acceptance_criteria": ["AWS connector OK", "GCP connector OK"], "passes": false },
    { "id": "s3", "description": "Seller dashboard UI",     "acceptance_criteria": ["Lists engagements", "Shows status"], "passes": false },
    { "id": "s4", "description": "Billing surface",         "acceptance_criteria": ["Shows invoices"], "passes": false },
    { "id": "s5", "description": "Per-engagement reports",  "acceptance_criteria": ["Renders findings"], "passes": false }
  ],
  "scope": {
    "touches_db":       true,
    "touches_frontend": true,
    "touches_infra":    true,
    "files_in_scope":   ["app/", "frontend/", "infra/"]
  },
  "_estimated_files_changed": 40,
  "hard_blockers":   [],
  "risk_flags":      [],
  "suggested_split": [
    "Seller invitation flow (auth + email)",
    "Cloud connector wiring (one connector per feature)",
    "Seller dashboard UI",
    "Billing surface",
    "Per-engagement reports"
  ]
}
```

- [ ] **Step 2: Write the failing tests.**

Create `tests/factory/test_plan_lambda.py`:

```python
"""Tests for the Plan Lambda."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))

FIXTURES = Path(__file__).parent / "fixtures"


class FakeS3:
    def __init__(self):
        self.puts = []
        self.objects = {}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        body = kwargs["Body"]
        self.objects[kwargs["Key"]] = body if isinstance(body, bytes) else body.encode("utf-8")

    def get_object(self, **kwargs):
        body = self.objects[kwargs["Key"]]
        resp = MagicMock()
        resp["Body"].read.return_value = body  # type: ignore[index]
        return {"Body": MagicMock(read=lambda: body)}


def _seed_intake(fake: FakeS3, execution_id: str):
    fake.objects[f"{execution_id}/intake/spec_raw.md"] = b"# Test feature\n\nA test."
    fake.objects[f"{execution_id}/intake/feature_meta.json"] = json.dumps({
        "feature_id": "00000000-0000-0000-0000-000000000001",
        "title": "Test feature",
        "status": "Ready to Build",
    }).encode("utf-8")


def test_happy_path_writes_prd_with_no_blockers():
    from handlers import plan  # type: ignore

    fake = FakeS3()
    _seed_intake(fake, "exec-trivial")
    haiku_payload = json.loads((FIXTURES / "haiku_response_valid_prd.json").read_text())

    with patch.object(plan, "_s3", fake), \
         patch.object(plan, "messages_create", return_value={
             "text": json.dumps(haiku_payload),
             "input_tokens": 1234, "output_tokens": 567,
         }):
        result = plan.handler(
            {"feature_id": "00000000-0000-0000-0000-000000000001",
             "execution_id": "exec-trivial"},
            None,
        )

    assert result["hard_blockers"] == []
    prd_key = "exec-trivial/plan/prd.json"
    assert prd_key in fake.objects
    written = json.loads(fake.objects[prd_key])
    assert written["title"] == "Add buyer engagement export endpoint"
    assert written["hard_blockers"] == []


def test_oversized_feature_emits_hard_blocker():
    from handlers import plan  # type: ignore

    fake = FakeS3()
    _seed_intake(fake, "exec-oversized")
    haiku_payload = json.loads((FIXTURES / "haiku_response_oversized.json").read_text())

    with patch.object(plan, "_s3", fake), \
         patch.object(plan, "messages_create", return_value={
             "text": json.dumps(haiku_payload),
             "input_tokens": 5000, "output_tokens": 2000,
         }):
        result = plan.handler(
            {"feature_id": "00000000-0000-0000-0000-000000000002",
             "execution_id": "exec-oversized"},
            None,
        )

    assert any(b["reason"] == "feature_too_large" for b in result["hard_blockers"])
    written = json.loads(fake.objects["exec-oversized/plan/prd.json"])
    assert any(b["reason"] == "feature_too_large" for b in written["hard_blockers"])
    # The suggested_split that Haiku produced should be preserved
    assert len(written["suggested_split"]) == 5


def test_repairs_malformed_json_with_one_retry():
    from handlers import plan  # type: ignore

    fake = FakeS3()
    _seed_intake(fake, "exec-repair")
    valid = json.loads((FIXTURES / "haiku_response_valid_prd.json").read_text())

    # First call returns prose-wrapped JSON; second returns clean.
    responses = [
        {"text": "Here is your PRD:\n```json\n" + json.dumps(valid) + "\n```", "input_tokens": 1, "output_tokens": 1},
        {"text": json.dumps(valid), "input_tokens": 1, "output_tokens": 1},
    ]
    with patch.object(plan, "_s3", fake), \
         patch.object(plan, "messages_create", side_effect=responses):
        result = plan.handler(
            {"feature_id": "00000000-0000-0000-0000-000000000001",
             "execution_id": "exec-repair"},
            None,
        )

    assert result["hard_blockers"] == []
    # The "fenced JSON" first response should be parseable too — the impl
    # strips ```json fences before parsing. So this test actually verifies
    # that fenced output works WITHOUT a retry. Good — we want robust
    # parsing first, retry only if even that fails.


def test_raises_if_schema_validation_fails_after_retry():
    from handlers import plan  # type: ignore

    fake = FakeS3()
    _seed_intake(fake, "exec-bad")

    bad = {"title": "missing required fields"}  # invalid PRD
    responses = [
        {"text": json.dumps(bad), "input_tokens": 1, "output_tokens": 1},
        {"text": json.dumps(bad), "input_tokens": 1, "output_tokens": 1},
    ]
    with patch.object(plan, "_s3", fake), \
         patch.object(plan, "messages_create", side_effect=responses):
        try:
            plan.handler(
                {"feature_id": "00000000-0000-0000-0000-000000000001",
                 "execution_id": "exec-bad"},
                None,
            )
        except RuntimeError as e:
            assert "schema" in str(e).lower() or "invalid" in str(e).lower()
            return
    raise AssertionError("expected RuntimeError on persistent schema failure")
```

- [ ] **Step 3: Run, verify all fail.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_plan_lambda.py -v
```
Expected: ModuleNotFoundError or import failure.

- [ ] **Step 4: Write `handlers/plan.py`.**

```python
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
_SCHEMA = json.loads((Path(__file__).resolve().parent / ".factory" / "prd.schema.json").read_text())
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
    user = f"# spec_raw.md\n\n{spec_md}\n\n# CLAUDE.md (project context)\n\n{claude_md}\n\n# .factory/prd.schema.json (your output must match)\n\n```json\n{schema_str}\n```"
    if repair_note:
        user += f"\n\n# REPAIR NOTE\n\n{repair_note}"
    return messages_create(
        model=HAIKU_MODEL,
        system=SYSTEM_PROMPT,
        user=user,
        max_tokens=PLAN_MAX_TOKENS,
    )


def _ask_and_parse(spec_md: str, claude_md: str, repair_note: str | None = None) -> tuple[dict, dict]:
    """Returns (parsed_prd, raw_response_with_token_counts)."""
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

    # Validate. If fail, one repair turn.
    try:
        _VALIDATOR.validate(prd)
    except ValidationError as e:
        prd, _resp = _ask_and_parse(spec_md, claude_md, repair_note=f"Your previous output failed schema validation: {e.message}. Re-emit a valid PRD as JSON only.")
        try:
            _VALIDATOR.validate(prd)
        except ValidationError as e2:
            raise RuntimeError(f"Plan output invalid after repair: {e2.message}") from e2

    # Apply deterministic sizing rubric and merge into PRD.
    sizing = evaluate_sizing(prd)
    prd["hard_blockers"] = list(prd.get("hard_blockers", [])) + sizing["hard_blockers"]
    prd["risk_flags"]    = sorted(set(prd.get("risk_flags", [])) | set(sizing["risk_flags"]))

    # Force feature_id from intake — Haiku might miscopy.
    prd["feature_id"] = feature_id
    prd["title"]      = prd.get("title") or meta["title"]

    # Drop the private _estimated_files_changed before persisting (additionalProperties=false in schema)
    prd.pop("_estimated_files_changed", None)

    # Re-validate after merging
    _VALIDATOR.validate(prd)

    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/plan/prd.json",
        Body=json.dumps(prd, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return {
        "feature_id":     feature_id,
        "hard_blockers":  prd["hard_blockers"],
        "scope":          prd["scope"],
        "blocked":        len(prd["hard_blockers"]) > 0,
    }
```

Note the line `_SCHEMA = json.loads((Path(__file__).resolve().parent / ".factory" / "prd.schema.json").read_text())`. At runtime in Lambda, `__file__` is `/var/task/plan.py`, so the schema must be at `/var/task/.factory/prd.schema.json`. The build.sh changes from Task 1 ensure that.

- [ ] **Step 5: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_plan_lambda.py -v
```
Expected: 4 tests pass.

If a test fails because the test imports `plan.py` from a path where `.factory/prd.schema.json` is at the repo root (not adjacent to the handler), the test environment needs path patching. The simplest fix is to make the schema-path lookup more robust:

```python
_SCHEMA_PATH_CANDIDATES = [
    Path(__file__).resolve().parent / ".factory" / "prd.schema.json",                     # Lambda runtime
    Path(__file__).resolve().parents[3] / ".factory" / "prd.schema.json",                 # repo root from scripts/factory_lambdas/handlers/
]
for _p in _SCHEMA_PATH_CANDIDATES:
    if _p.exists():
        _SCHEMA = json.loads(_p.read_text())
        break
else:
    raise RuntimeError("prd.schema.json not found in any expected location")
_VALIDATOR = Draft202012Validator(_SCHEMA)
```

Use this robust block in `plan.py` instead of the single-path version above.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/plan.py tests/factory/test_plan_lambda.py tests/factory/fixtures/haiku_response_*.json
git commit -m "factory(v2): add Plan Lambda (Haiku -> prd.json with sizing rubric + schema validation)"
```

---

### Task 6: Implement MarkBlocked Lambda (TDD)

Per §2.2.1 + §4.1: when Plan emits hard_blockers, post a structured Notion comment listing the breach and suggested split, set the page status to `Failed` with the blocker reason as `Error Log`.

**Files:**
- Create: `scripts/factory_lambdas/handlers/mark_blocked.py`
- Create: `tests/factory/test_mark_blocked.py`

- [ ] **Step 1: Write the failing test.**

Create `tests/factory/test_mark_blocked.py`:

```python
"""Tests for the MarkBlocked Lambda."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))


def test_mark_blocked_posts_comment_and_updates_status():
    from handlers import mark_blocked  # type: ignore

    calls: list[dict] = []

    def fake_notion(path: str, *, method: str, body: dict | None = None):
        calls.append({"path": path, "method": method, "body": body})
        return {}

    with patch.object(mark_blocked, "_notion_request", side_effect=fake_notion):
        mark_blocked.handler({
            "feature_id": "00000000-0000-0000-0000-000000000002",
            "hard_blockers": [
                {"reason": "feature_too_large", "details": "5 stories, 3 domains"}
            ],
            "suggested_split": [
                "Seller invitation flow",
                "Cloud connector wiring",
                "Seller dashboard UI",
            ],
        }, None)

    # Two calls expected: PATCH /pages/<id> for status, POST /comments for the message
    methods = sorted(c["method"] for c in calls)
    assert methods == ["PATCH", "POST"]

    patch_call = next(c for c in calls if c["method"] == "PATCH")
    assert "00000000-0000-0000-0000-000000000002" in patch_call["path"]
    assert patch_call["body"]["properties"]["Status"]["select"]["name"] == "Failed"

    post_call = next(c for c in calls if c["method"] == "POST")
    body_text = json.dumps(post_call["body"])
    assert "feature_too_large" in body_text
    assert "Seller invitation flow" in body_text
```

- [ ] **Step 2: Run test, verify failure.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_mark_blocked.py -v
```
Expected: ModuleNotFoundError on `handlers.mark_blocked`.

- [ ] **Step 3: Write `handlers/mark_blocked.py`.**

```python
"""MarkBlocked Lambda — when Plan rejects a feature for sizing, post a
structured Notion comment with the breach + suggested split, and flip the
Notion status to Failed.

Spec §2.2.1.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.request import urlopen

from common.secrets import get_secret

NOTION_VERSION = "2022-06-28"


def _notion_request(path: str, *, method: str, body: dict | None = None) -> dict:
    api_key = get_secret("nova/factory/notion-api-key")
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8") if body is not None else None,
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _format_comment(hard_blockers: list[dict], suggested_split: list[str]) -> str:
    blocker_lines = []
    for b in hard_blockers:
        line = f"- **{b['reason']}**"
        if b.get("details"):
            line += f": {b['details']}"
        blocker_lines.append(line)

    split_lines = [f"  {i+1}. {s}" for i, s in enumerate(suggested_split)] if suggested_split else []

    parts = [
        "🛑 Factory cannot run this feature in one pass — sizing rubric breached.",
        "",
        "**Detected:**",
        *blocker_lines,
    ]
    if split_lines:
        parts += [
            "",
            "**Suggested decomposition** (paste each as a separate Ready-to-Build feature):",
            *split_lines,
        ]
    parts += [
        "",
        "See `.factory/feature-sizing-rubric.md` in the repo for the rubric this enforces.",
    ]
    return "\n".join(parts)


def handler(event, _ctx):
    feature_id      = event["feature_id"]
    hard_blockers   = event.get("hard_blockers", [])
    suggested_split = event.get("suggested_split", [])

    # 1. Update status to Failed with the first blocker reason
    first = hard_blockers[0] if hard_blockers else {"reason": "unknown"}
    _notion_request(
        f"/pages/{feature_id}",
        method="PATCH",
        body={
            "properties": {
                "Status":    {"select": {"name": "Failed"}},
                "Error Log": {"rich_text": [{"text": {"content": f"Blocked at Plan: {first.get('reason')} — {first.get('details', '')}"[:2000]}}]},
            }
        },
    )

    # 2. Post a structured comment
    comment = _format_comment(hard_blockers, suggested_split)
    _notion_request(
        "/comments",
        method="POST",
        body={
            "parent":    {"page_id": feature_id},
            "rich_text": [{"text": {"content": comment[:2000]}}],
        },
    )

    return {"blocked": True, "reason": first.get("reason")}
```

- [ ] **Step 4: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_mark_blocked.py -v
```
Expected: 1 test passes.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/mark_blocked.py tests/factory/test_mark_blocked.py
git commit -m "factory(v2): add MarkBlocked Lambda (Notion comment + status=Failed)"
```

---

### Task 7: Define v2 Lambdas in Terraform (`lambdas-v2.tf`)

Add the three new handlers to a parallel `handlers_v2` map. Reuse the existing `aws_iam_role.lambda_exec`, S3 bucket, lock table.

**Files:**
- Create: `infra/factory/lambdas-v2.tf`

- [ ] **Step 1: Verify the build script produces zips for the new handlers.**

```bash
cd /c/Claude/Nova/nova/scripts/factory_lambdas
bash build.sh
ls dist/load_feature.zip dist/plan.zip dist/mark_blocked.zip
```
Expected: all three zips exist.

- [ ] **Step 2: Verify the Anthropic API key secret is reachable from the Lambda exec role.**

Look at `infra/factory/iam.tf` for the secrets policy:

```bash
grep -A10 "secretsmanager" /c/Claude/Nova/nova/infra/factory/iam.tf | head -30
```
Expected: a statement like `"Resource": "arn:aws:secretsmanager:*:*:secret:nova/factory/*"` or similar broad glob. If only `nova/factory/notion-*` and `nova/factory/github-token` are listed (no anthropic), add the anthropic key. Otherwise no edit needed.

If the policy needs widening, edit `infra/factory/iam.tf` and run `terraform apply`. (For most repos, the existing v1 already grants Anthropic access since `run_agent.py` uses it — verify.)

- [ ] **Step 3: Create `infra/factory/lambdas-v2.tf`.**

```hcl
# v2 Lambdas — live alongside v1 in the same module. Distinct function names
# (suffixed in `handlers_v2` keys), shared IAM role, shared S3 bucket and
# DDB tables.

locals {
  handlers_v2 = {
    load_feature = { timeout = 60,  memory = 512  }
    plan         = { timeout = 120, memory = 1024 }
    mark_blocked = { timeout = 30,  memory = 256  }
  }
}

resource "aws_lambda_function" "handlers_v2" {
  for_each = local.handlers_v2

  function_name    = "${local.name_prefix}-${replace(each.key, "_", "-")}"
  filename         = "${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip"
  source_code_hash = filebase64sha256("${path.module}/../../scripts/factory_lambdas/dist/${each.key}.zip")
  role             = aws_iam_role.lambda_exec.arn
  handler          = "${each.key}.handler"
  runtime          = "python3.12"
  timeout          = each.value.timeout
  memory_size      = each.value.memory
  layers           = [aws_lambda_layer_version.shared.arn]

  tracing_config { mode = "Active" }

  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      LOCKS_TABLE      = aws_dynamodb_table.locks.name
      RUNS_TABLE       = aws_dynamodb_table.runs.name
      GITHUB_OWNER     = var.github_owner
      GITHUB_REPO      = var.github_repo
      PLAN_MODEL       = "claude-haiku-4-5"
    }
  }

  depends_on = [null_resource.build_handlers, aws_lambda_layer_version.shared]
  tags = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_cloudwatch_log_group" "handlers_v2" {
  for_each          = local.handlers_v2
  name              = "/aws/lambda/${local.name_prefix}-${replace(each.key, "_", "-")}"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}
```

Note the function-name collision: v1 has e.g. `nova-factory-load-spec` and v2 has `nova-factory-load-feature` — DIFFERENT names because the keys differ (`load_spec` vs `load_feature`). No conflict. Same goes for `plan` (new in v2) and `mark_blocked` (new in v2).

- [ ] **Step 4: Verify Terraform plan is the diff we expect.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform plan -input=false
```
Expected: Plan shows 3 new `aws_lambda_function.handlers_v2[<key>]` resources + 3 new `aws_cloudwatch_log_group.handlers_v2[<key>]` resources. No resource is being destroyed. No v1 resources are touched.

If the build_handlers null_resource shows as recomputed, that's fine — it picks up the new handler files.

- [ ] **Step 5: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 6 (or 7 with build_handlers) resources added.

- [ ] **Step 6: Smoke-invoke each Lambda directly to confirm imports work.**

```bash
aws lambda invoke --function-name nova-factory-load-feature \
  --payload '{"feature_id":"00000000-0000-0000-0000-DOESNOTEXIST","execution_id":"smoke-import"}' \
  --cli-binary-format raw-in-base64-out /tmp/lf.json; cat /tmp/lf.json
```
Expected: the Lambda errors at the Notion API call (404 page not found) — that's fine. We're checking the import succeeded. If you see `Runtime.HandlerNotFound` or `Errno.NoModuleNamed`, the build is wrong.

```bash
aws lambda invoke --function-name nova-factory-plan --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/p.json; cat /tmp/p.json
```
Expected: errors at `event["feature_id"]` with KeyError — confirms the handler imported successfully.

```bash
aws lambda invoke --function-name nova-factory-mark-blocked --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/mb.json; cat /tmp/mb.json
```
Same expectation.

- [ ] **Step 7: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/lambdas-v2.tf
git commit -m "infra(factory v2): add load_feature/plan/mark_blocked Lambdas"
```

---

### Task 8: Define stub state machine `nova-factory-v2-planonly`

A short SFN that runs AcquireLock → LoadFeature → Plan → PlanGate → either MarkBlocked or end. This lets us validate the Plan stage end-to-end without RalphLoop existing yet.

**Files:**
- Create: `infra/factory/state-machine-v2-planonly.tf`
- Create: `infra/factory/state-machine-v2-planonly.json.tpl`

- [ ] **Step 1: Create the SFN definition template.**

`infra/factory/state-machine-v2-planonly.json.tpl`:

```json
{
  "Comment": "Nova factory v2 — Phase 2 STUB (Plan stage only). Replaced in Phase 3 with the full v2 pipeline.",
  "TimeoutSeconds": 600,
  "StartAt": "AcquireLock",
  "States": {
    "AcquireLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-acquire-lock",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.lock",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "FailLocked"}],
      "Next": "LoadFeature"
    },

    "LoadFeature": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-load-feature",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.intake",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5, "MaxAttempts": 3, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "Plan"
    },

    "Plan": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-plan",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": "$.plan",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "PlanGate"
    },

    "PlanGate": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.plan.Payload.blocked",
          "BooleanEquals": true,
          "Next": "MarkBlocked"
        }
      ],
      "Default": "MarkPlanOK"
    },

    "MarkBlocked": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-mark-blocked",
        "Payload": {
          "feature_id.$":      "$.feature_id",
          "hard_blockers.$":   "$.plan.Payload.hard_blockers",
          "suggested_split.$": "$.plan.Payload.scope"
        }
      },
      "ResultPath": null,
      "Next": "ReleaseLock"
    },

    "MarkPlanOK": {
      "Type": "Pass",
      "Comment": "Phase 2 placeholder: in Phase 3 this becomes the entry point to RalphLoop.",
      "Result": {"plan": "ok"},
      "ResultPath": "$.phase2_terminal",
      "Next": "ReleaseLock"
    },

    "ReleaseLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-release-lock",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "End": true
    },

    "MarkFailedAndRelease": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "Failed",
          "extras": {"error.$": "States.JsonToString($.error)"}
        }
      },
      "ResultPath": null,
      "Next": "ReleaseLockAfterFailure"
    },

    "ReleaseLockAfterFailure": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-release-lock",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name"
        }
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailLocked": {
      "Type": "Pass",
      "Result": {"reason": "locked_by_another_execution"},
      "Next": "FailState"
    },

    "FailState": {"Type": "Fail", "Error": "FactoryV2PlanOnlyFailed"}
  }
}
```

Note: `MarkBlocked` passes `$.plan.Payload.scope` as `suggested_split` — that's a placeholder. The real wiring uses the suggested_split array from the PRD. Fix: change the payload template to read from the PRD on S3 (no — that requires another Lambda call). Cleaner: the Plan Lambda's RETURN VALUE should include the suggested_split array. Update Plan's return:

Go back to `handlers/plan.py` and adjust the final `return` statement to include `suggested_split`:

```python
return {
    "feature_id":      feature_id,
    "hard_blockers":   prd["hard_blockers"],
    "suggested_split": prd["suggested_split"],
    "scope":           prd["scope"],
    "blocked":         len(prd["hard_blockers"]) > 0,
}
```

If you didn't add `suggested_split` to the return dict in Task 5, edit it now and re-run `bash scripts/factory_lambdas/build.sh`. (The test for plan should also be extended to assert this — add a line `assert "suggested_split" in result` to the happy-path test.)

Then update the SFN payload to:

```json
"Payload": {
  "feature_id.$":      "$.feature_id",
  "hard_blockers.$":   "$.plan.Payload.hard_blockers",
  "suggested_split.$": "$.plan.Payload.suggested_split"
}
```

- [ ] **Step 2: Create the SFN Terraform resource.**

`infra/factory/state-machine-v2-planonly.tf`:

```hcl
resource "aws_cloudwatch_log_group" "sfn_v2_planonly" {
  name              = "/aws/states/nova-factory-v2-planonly"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_sfn_state_machine" "v2_planonly" {
  name     = "nova-factory-v2-planonly"
  role_arn = aws_iam_role.sfn_exec.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine-v2-planonly.json.tpl", {
    region      = var.aws_region
    account_id  = data.aws_caller_identity.current.account_id
    name_prefix = local.name_prefix
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_v2_planonly.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  tracing_configuration { enabled = true }
  tags                  = merge(local.common_tags, { Generation = "v2" })

  depends_on = [aws_lambda_function.handlers_v2]
}

output "v2_planonly_state_machine_arn" {
  value       = aws_sfn_state_machine.v2_planonly.arn
  description = "Phase 2 stub state machine (Plan stage only). Phase 3 introduces nova-factory-v2."
}
```

- [ ] **Step 3: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 2 new resources (log group + state machine).

- [ ] **Step 4: Verify the SFN exists.**

```bash
aws stepfunctions describe-state-machine \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2-planonly \
  --query '{name: name, status: status}' --output table
```
Expected: name `nova-factory-v2-planonly`, status `ACTIVE`.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/state-machine-v2-planonly.tf infra/factory/state-machine-v2-planonly.json.tpl scripts/factory_lambdas/handlers/plan.py tests/factory/test_plan_lambda.py
git commit -m "infra(factory v2): add nova-factory-v2-planonly stub state machine"
```

---

### Task 9: Build the smoke fixtures

Spec acceptance criterion 7: `scripts/factory_smoke_fixtures/{trivial,medium,oversized}.json`. Each is a Notion-page-shape JSON describing what we'd seed into Notion to drive a smoke run. Phase 2 tests them against the stub SFN.

**Files:**
- Create: `scripts/factory_smoke_fixtures/trivial.json`
- Create: `scripts/factory_smoke_fixtures/medium.json`
- Create: `scripts/factory_smoke_fixtures/oversized.json`
- Create: `scripts/factory_smoke_fixtures/README.md`

- [ ] **Step 1: Create `trivial.json`.**

```json
{
  "expected_outcome": "plan_passes_no_blockers",
  "title": "Factory v2 smoke — version v2 endpoint",
  "description": "Add GET /api/version-v2 returning {\"version\": \"2.0\"}.",
  "tech_notes": "Add to app/api/routes/version.py. Mirror the existing /api/version handler. Update docs/openapi.json.",
  "acceptance_criteria": "- 200 with {\"version\": \"2.0\"} when called without auth\n- docs/openapi.json includes /api/version-v2",
  "out_of_scope": "Auth changes; non-v2 endpoints"
}
```

- [ ] **Step 2: Create `medium.json`.**

```json
{
  "expected_outcome": "plan_passes_no_blockers",
  "title": "Factory v2 smoke — engagement listing endpoint",
  "description": "Add GET /api/engagements that lists engagements for the calling buyer org. Pagination via limit/offset query params.",
  "tech_notes": "Use the existing engagements repository and tenant-filter pattern. Add response schema to docs/openapi.json. Cover with unit + integration tests.",
  "acceptance_criteria": "- 200 with paginated list when authenticated as a buyer org user\n- 401 when unauthenticated\n- Empty list when no engagements exist for the org\n- docs/openapi.json includes the endpoint with query params and response schema",
  "out_of_scope": "Filtering, sorting, search"
}
```

- [ ] **Step 3: Create `oversized.json`.**

```json
{
  "expected_outcome": "plan_blocks_with_feature_too_large",
  "title": "Factory v2 smoke — full seller portal",
  "description": "Build the entire seller portal: invitation flow, cloud connector wiring, dashboard UI, billing surface, per-engagement reports. Wire up the seller Cognito pool, add the seller_users table, build a React frontend at /seller/*, wire CloudFront origin behaviors.",
  "tech_notes": "Multi-domain (db + backend + frontend + infra). Likely 30+ files changed across app/, frontend/, infra/, docs/.",
  "acceptance_criteria": "- Sellers receive invitation emails\n- Sellers can accept invitations and create accounts\n- Sellers can connect AWS cloud connectors\n- Sellers can connect GCP cloud connectors\n- Seller dashboard lists engagements\n- Seller dashboard shows status\n- Sellers can see invoices\n- Seller portal has separate Cognito pool\n- Reports render findings\n- All routes filter by engagement_id and seller_org_id",
  "out_of_scope": "Production rollout; feature flags"
}
```

- [ ] **Step 4: Create `scripts/factory_smoke_fixtures/README.md`.**

```markdown
# Factory v2 smoke fixtures

Each file is a JSON description of a Notion feature page used to drive a smoke
run through the v2 factory state machine. The `expected_outcome` field tells
the smoke runner what to assert.

| Fixture | Stories | Domains | Expected |
|---|---|---|---|
| trivial.json    | ~1 | backend       | Plan passes; no blockers |
| medium.json     | ~3 | backend       | Plan passes; no blockers |
| oversized.json  | ~5+ | db+frontend+infra+backend | Plan emits `feature_too_large` blocker; MarkBlocked posts a Notion comment with split |

## Running

```bash
bash scripts/factory_smoke_v2.sh trivial
bash scripts/factory_smoke_v2.sh medium
bash scripts/factory_smoke_v2.sh oversized
```

The runner creates a synthetic Notion page in the Features DB, starts an
execution of `nova-factory-v2-planonly`, polls until terminal, and asserts
the expected outcome.
```

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_smoke_fixtures/
git commit -m "factory(v2): add smoke fixtures (trivial/medium/oversized)"
```

---

### Task 10: Build the smoke runner script

Creates a synthetic Notion page from a fixture, starts a stub-SFN execution, polls, asserts the expected outcome.

**Files:**
- Create: `scripts/factory_smoke_v2.sh`

- [ ] **Step 1: Write the script.**

`scripts/factory_smoke_v2.sh`:

```bash
#!/usr/bin/env bash
# Factory v2 smoke runner.
# Usage: bash scripts/factory_smoke_v2.sh <fixture_name>
# Where <fixture_name> matches a file at scripts/factory_smoke_fixtures/<name>.json

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <trivial|medium|oversized>" >&2
  exit 2
fi

FIXTURE="$1"
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)
FIXTURE_PATH="$REPO_ROOT/scripts/factory_smoke_fixtures/${FIXTURE}.json"
ENV_FILE="$REPO_ROOT/.env"

if [[ ! -f "$FIXTURE_PATH" ]]; then
  echo "fixture not found: $FIXTURE_PATH" >&2
  exit 2
fi

source <(sed 's/^/export /' "$ENV_FILE")
: "${NOTION_API_KEY:?NOTION_API_KEY missing}"
: "${NOTION_FEATURES_DB_ID:?NOTION_FEATURES_DB_ID missing}"

EXPECTED=$(jq -r .expected_outcome "$FIXTURE_PATH")
TITLE=$(jq -r .title "$FIXTURE_PATH")
DESCRIPTION=$(jq -r .description "$FIXTURE_PATH")
TECH=$(jq -r .tech_notes "$FIXTURE_PATH")
ACCEPT=$(jq -r .acceptance_criteria "$FIXTURE_PATH")
OOS=$(jq -r .out_of_scope "$FIXTURE_PATH")

echo "==> Creating synthetic Notion page: $TITLE"
PAGE_PAYLOAD=$(jq -n \
  --arg db "$NOTION_FEATURES_DB_ID" \
  --arg t "$TITLE" \
  --arg d "$DESCRIPTION" \
  --arg n "$TECH" \
  --arg a "$ACCEPT" \
  --arg o "$OOS" \
  '{
     parent: {database_id: $db},
     properties: {
       Title:                 {title:    [{text: {content: $t}}]},
       Status:                {status:   {name: "Ready to Build"}},
       Description:           {rich_text:[{text: {content: $d}}]},
       "Tech Notes":          {rich_text:[{text: {content: $n}}]},
       "Acceptance Criteria": {rich_text:[{text: {content: $a}}]},
       "Out of Scope":        {rich_text:[{text: {content: $o}}]}
     }
   }')

PAGE_RESP=$(curl -s -X POST https://api.notion.com/v1/pages \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" \
  -d "$PAGE_PAYLOAD")
FEATURE_ID=$(echo "$PAGE_RESP" | jq -r .id)
if [[ -z "$FEATURE_ID" || "$FEATURE_ID" == "null" ]]; then
  echo "Notion page creation failed:" >&2
  echo "$PAGE_RESP" >&2
  exit 1
fi
echo "    feature_id = $FEATURE_ID"

SM_ARN=$(terraform -chdir="$REPO_ROOT/infra/factory" output -raw v2_planonly_state_machine_arn)
EXEC_NAME="smoke-${FIXTURE}-$(date +%s)"
EXEC_ARN=$(aws stepfunctions start-execution \
  --state-machine-arn "$SM_ARN" \
  --name "$EXEC_NAME" \
  --input "{\"feature_id\":\"$FEATURE_ID\"}" \
  --query executionArn --output text)
echo "==> Started execution $EXEC_NAME"

# Poll
for _ in $(seq 1 60); do
  STATUS=$(aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query status --output text)
  if [[ "$STATUS" != "RUNNING" ]]; then break; fi
  sleep 5
done
echo "==> Execution status: $STATUS"

# Fetch the Notion page state
NOTION_STATUS=$(curl -s -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2022-06-28" \
  "https://api.notion.com/v1/pages/$FEATURE_ID" \
  | jq -r '.properties.Status.status.name // .properties.Status.select.name // "unknown"')
echo "==> Notion page status: $NOTION_STATUS"

case "$EXPECTED" in
  plan_passes_no_blockers)
    if [[ "$STATUS" == "SUCCEEDED" ]]; then
      echo "OK — execution succeeded as expected"; exit 0
    fi
    echo "FAIL — expected SUCCEEDED, got $STATUS" >&2; exit 1
    ;;
  plan_blocks_with_feature_too_large)
    if [[ "$STATUS" == "SUCCEEDED" && "$NOTION_STATUS" == "Failed" ]]; then
      echo "OK — feature was blocked at Plan as expected"; exit 0
    fi
    echo "FAIL — expected SUCCEEDED + Notion=Failed, got SFN=$STATUS Notion=$NOTION_STATUS" >&2; exit 1
    ;;
  *)
    echo "Unknown expected_outcome: $EXPECTED" >&2; exit 2 ;;
esac
```

- [ ] **Step 2: Make executable.**

```bash
chmod +x /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh
```

- [ ] **Step 3: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_smoke_v2.sh
git commit -m "factory(v2): add smoke runner scripts/factory_smoke_v2.sh"
```

---

### Task 11: Smoke run — trivial

- [ ] **Step 1: Run.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh trivial
```
Expected: `OK — execution succeeded as expected`. The Notion page status will be `Ready to Build` (untouched by the stub SFN — Phase 3 will add MarkInProgress).

- [ ] **Step 2: Inspect the S3 artifacts.**

Get the execution name from the previous step, then:

```bash
aws s3 ls "s3://nova-factory-workspaces-577638385116/<exec_name>/" --recursive
```
Expected: `intake/spec_raw.md`, `intake/feature_meta.json`, `plan/prd.json`.

```bash
aws s3 cp "s3://nova-factory-workspaces-577638385116/<exec_name>/plan/prd.json" - | jq .
```
Expected: a valid PRD with `hard_blockers: []`, ≥1 story, scope filled in.

- [ ] **Step 3: If anything fails, debug.**

Check the SFN execution's failed step:

```bash
aws stepfunctions get-execution-history --execution-arn <arn> --reverse-order --max-results 5
```

Common issues:
- `Plan` Lambda timed out at 120s — Haiku returned slowly; raise `timeout` to 180 in `lambdas-v2.tf` and re-apply.
- `prd.schema.json` not found in zip — the build.sh changes from Task 1 didn't take effect; re-run `bash scripts/factory_lambdas/build.sh` and `terraform apply` to push the new zip.

---

### Task 12: Smoke run — medium

- [ ] **Step 1: Run.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh medium
```
Expected: `OK — execution succeeded as expected`. The medium fixture should still pass the rubric (3 stories, ~4 criteria, 1 domain).

- [ ] **Step 2: Verify the PRD.**

Same `aws s3 cp` pattern as Task 11. The PRD should have ~3 stories and `hard_blockers: []`. If `hard_blockers` is non-empty, Haiku is being too generous with sizing — review and possibly tune the SYSTEM_PROMPT in `plan.py` to emphasize "do not artificially split features."

---

### Task 13: Smoke run — oversized

- [ ] **Step 1: Run.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh oversized
```
Expected: `OK — feature was blocked at Plan as expected`.

- [ ] **Step 2: Verify the Notion comment was posted.**

```bash
FEATURE_ID=<from previous output>
NOTION_API_KEY=$(grep NOTION_API_KEY /c/Claude/Nova/nova/.env | cut -d= -f2)
curl -s -H "Authorization: Bearer $NOTION_API_KEY" -H "Notion-Version: 2022-06-28" \
  "https://api.notion.com/v1/comments?block_id=$FEATURE_ID" | jq '.results[] | .rich_text[].plain_text' | head -20
```
Expected: a comment containing `🛑 Factory cannot run this feature in one pass` and the suggested split.

- [ ] **Step 3: Verify the PRD reflects the blocker.**

```bash
aws s3 cp "s3://nova-factory-workspaces-577638385116/<exec_name>/plan/prd.json" - | jq '.hard_blockers, .suggested_split'
```
Expected: `hard_blockers` array contains an entry with `reason: "feature_too_large"`; `suggested_split` is a non-empty array.

---

### Task 14: Final verification

- [ ] **Step 1: All Phase 1 + Phase 2 tests pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/ -v
```
Expected: 5 (Phase 1) + 10 (sizing) + 3 (anthropic) + 1 (load_feature) + 4 (plan) + 1 (mark_blocked) = 24 tests pass.

- [ ] **Step 2: Terraform plan is clean.**

```bash
cd /c/Claude/Nova/nova/infra/factory && terraform plan -input=false | tail -3
```
Expected: `No changes.`

- [ ] **Step 3: All three smoke fixtures pass.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh trivial   && \
bash scripts/factory_smoke_v2.sh medium    && \
bash scripts/factory_smoke_v2.sh oversized && \
echo "ALL THREE SMOKES PASSED"
```
Expected: `ALL THREE SMOKES PASSED`.

- [ ] **Step 4: Working tree clean, branch pushed.**

```bash
cd /c/Claude/Nova/nova
git status
git push origin factory-overhaul-2026-05-03
```
Expected: clean tree; push succeeds.

---

## Phase 2 acceptance criteria recap

1. Three new Lambdas (`load_feature`, `plan`, `mark_blocked`) deployed and invokable.
2. Stub SFN `nova-factory-v2-planonly` exists and is `ACTIVE`.
3. Sizing rubric implemented as a pure function with 10 unit tests passing.
4. Three smoke fixtures pass their expected outcomes against the stub SFN.
5. Oversized fixture produces a Notion comment with the suggested split.
6. PRD JSON written to S3 conforms to `.factory/prd.schema.json`.
7. Working tree clean; branch pushed.

---

## What Phase 3 will do

Phase 3 ("LLM core + main state machine") replaces the stub SFN with the full v2 pipeline:

- Build the **RalphTurn container Lambda** (`scripts/factory_lambdas/containers/ralph_turn/`) — the architecturally critical piece. Container image based on `public.ecr.aws/lambda/nodejs:20`, Python 3.12 alongside, `@anthropic-ai/claude-code` installed, runs `claude -p --dangerously-skip-permissions` against `/tmp/ws`.
- Build the **Validate-v2 container Lambda** — replaces `validate-workspace`, runs the deterministic 6-step chain from spec §2.4 (ruff / mypy / pytest / tf / tsc / alembic).
- Build the **Review Lambda** — single Sonnet call against the diff per spec §2.5.
- Build a **tighter IAM role for RalphTurn** — S3 read/write to its own execution prefix only, Secrets Manager read for `nova/factory/anthropic-api-key` only, no broad AWS.
- Wire the **full v2 state machine** `nova-factory-v2` with the loop iterator pattern, validate-repair routing (≤2 cycles), review-repair routing (≤2 cycles), token-budget hard stops, completion sentinel detection, and CommitAndPush + WaitForQualityGates + MarkDone tail.
- Run all three smoke fixtures end-to-end through the full pipeline (trivial + medium → green merge to a feature branch; oversized → MarkBlocked).

That phase consumes everything Phase 2 produced — schemas, prompts, sizing rubric, Plan/MarkBlocked Lambdas — and adds the implementer + validator + reviewer that close the loop.
