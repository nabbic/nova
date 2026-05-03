# Factory v2 — Phase 4: Postdeploy State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the separate `nova-factory-postdeploy` state machine that probes staging after each successful merge, and on probe failure auto-reverts the merge commit and re-files the Notion feature as `Failed`. Triggered by an EventBridge rule on `deploy.yml`'s `workflow_run` completion event for the `main` branch.

**Architecture:** A second state machine, deliberately decoupled from `nova-factory-v2`. The main pipeline finishes the moment the PR is merged; verification of the deployed code waits for ECS rollout (or wherever staging lives) and shouldn't hold the main lock open. EventBridge bridges from `deploy.yml`'s GitHub Actions completion to SFN.

**Tech Stack:** Python 3.12 (zip Lambdas), Step Functions, EventBridge rules on `aws.cloudwatch.alarm` + GitHub workflow_run events (delivered via the existing `quality-gates.yml` callback or, more reliably, an EventBridge connection to GitHub via repo webhook → API Gateway → SFN), `gh` CLI for the revert.

**Predecessors:** Phases 1–3 complete and merged. Phase 3's CommitAndPush already writes `.factory/last-run/{prd.json,review.json,progress.txt}` to the merged commit — that's what ProbeStaging reads. **This plan assumes Phase 3 is complete.**

**Branch:** `factory-overhaul-2026-05-03`. Working directory: `C:\Claude\Nova\nova`. AWS account `577638385116`, region `us-east-1`.

**Out of scope for Phase 4:** Self-pause + budgets + observability (Phase 5). Cutover (Phase 6). Auto-pausing on probe failure (that's Phase 5; Phase 4 stops at SNS alert if the *revert* itself fails).

---

## Architectural note on the trigger

Spec §2.7 says "triggered by an EventBridge rule on the `deploy.yml` workflow_run completion event for the `main` branch." There are two viable wiring paths:

**Option A (preferred): GitHub → EventBridge global endpoint → SFN.** Requires creating a webhook secret + an EventBridge connection. Self-contained AWS-side, no GitHub-side polling.

**Option B (fallback): `deploy.yml` ends with a step that calls AWS SFN start-execution via the existing GH Actions OIDC role.** Simpler — one more line in `deploy.yml`. No new AWS-side webhook plumbing.

For Phase 4 we use **Option B** for simplicity. Option A can be migrated to later if we ever need cross-repo or cross-account triggering. Option B keeps the trigger logic explicit in the workflow that already authored the deploy.

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `scripts/factory_lambdas/handlers/probe_staging.py` | Reads `prd.json` from the merged commit's `.factory/last-run/`, constructs HTTP probes from acceptance criteria, executes them, returns `{passed, probes[], failures[]}`. |
| `scripts/factory_lambdas/handlers/revert_merge.py` | Uses `gh` to revert the merge commit, opens a revert PR (auto-merged by quality-gates), updates Notion to `Failed` with `deploy_verification_failed`. |
| `scripts/factory_lambdas/common/probe.py` | Pure-function helpers: parse acceptance criteria into HTTP probes (extract verb + path + expected status). Unit-tested. |
| `tests/factory/test_probe_parsing.py` | Unit tests for `probe.py`. |
| `tests/factory/test_probe_staging.py` | Tests for `probe_staging.py` handler — mocks HTTP and S3, asserts probe outcomes are aggregated correctly. |
| `tests/factory/test_revert_merge.py` | Tests for `revert_merge.py` — mocks `gh` subprocess and Notion. |
| `infra/factory/state-machine-postdeploy.json.tpl` | SFN definition: ProbeStaging → Healthy? → MarkVerified | RevertMerge → ReFileFeature → AlarmSNS. |
| `infra/factory/state-machine-postdeploy.tf` | SFN resource + CloudWatch log group + IAM role. |
| `infra/factory/secrets-postdeploy.tf` | Secrets Manager entry `nova/factory/staging-verifier-token` (token VALUE provisioned manually for security; resource here just declares the slot + IAM read for the probe Lambda). |

**Modify:**

| Path | Change |
|---|---|
| `.github/workflows/deploy.yml` | Add a final step that triggers `nova-factory-postdeploy` SFN once deployment to staging succeeds. |
| `infra/factory/lambdas-v2.tf` | Add `probe_staging` and `revert_merge` to the `handlers_v2` map. |
| `infra/factory/iam.tf` | Grant `lambda_exec` role read access to the new staging-verifier-token. |

---

## Pre-flight

- [ ] **P-1: Phase 3 complete.**

```bash
pytest /c/Claude/Nova/nova/tests/factory/ -q
bash /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh trivial
```
Expected: 43 tests pass; trivial smoke goes to `Done`.

- [ ] **P-2: STAGING_URL exists.**

The probes need somewhere to call. Decide on the staging endpoint up-front. For the rebuild we'll target `https://staging-api.nova-factory.test` (placeholder — substitute the real one).

```bash
echo $STAGING_URL
# Or check the staging Terraform outputs for an ALB DNS name:
terraform -chdir=/c/Claude/Nova/nova/infra/staging output -raw api_url 2>/dev/null || echo "no staging infra yet"
```
Expected: a URL or a clear "not yet" answer.

If staging doesn't exist yet, **stop and ask** — Phase 4 needs a probe target. The fallback is a synthetic local probe target for testing only (covered in Task 8).

- [ ] **P-3: GitHub Actions OIDC role can call SFN.**

```bash
aws iam list-attached-role-policies --role-name $(terraform -chdir=/c/Claude/Nova/nova/infra/factory output -raw github_actions_role_name 2>/dev/null || echo "nova-factory-github-actions") --query 'AttachedPolicies[].PolicyName'
```
Expected: a list including a policy that grants `states:StartExecution`. If not present, we widen the role in Task 6.

---

### Task 1: Implement HTTP probe parser (TDD, pure function)

Per spec §2.7: ProbeStaging "constructs HTTP probes from acceptance criteria that mention HTTP verbs/paths." We write a parser that scans criteria strings for patterns like `GET /api/foo returns 200` or `POST /api/bar returns 403 when X` and emits a list of probes.

**Files:**
- Create: `scripts/factory_lambdas/common/probe.py`
- Create: `tests/factory/test_probe_parsing.py`

- [ ] **Step 1: Write tests.**

`tests/factory/test_probe_parsing.py`:

```python
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


def test_multiple_probes_per_criterion_ignored():
    """Criterion that mentions both GET and POST — we keep the first verb only,
    don't split into two probes."""
    out = extract_probes(["GET /api/x returns 200 (POST /api/x returns 405)"])
    assert len(out) == 1
    assert out[0]["method"] == "GET"


def test_handles_path_with_brace_template():
    out = extract_probes(["GET /api/engagements/{engagement_id}/export returns 200"])
    assert out[0]["path"] == "/api/engagements/{engagement_id}/export"


def test_lowercase_verb_normalized():
    out = extract_probes(["get /api/health returns 200"])
    assert out[0]["method"] == "GET"
```

- [ ] **Step 2: Run, verify all fail.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_probe_parsing.py -v
```
Expected: ImportError on `common.probe`.

- [ ] **Step 3: Write `common/probe.py`.**

```python
"""HTTP probe parser. Extracts {method, path, expected_status, auth} tuples
from human-written acceptance-criteria strings.

The parser is intentionally conservative: it only emits a probe when it can
identify the verb, the path, and the status code in the same criterion. If a
criterion lacks any of these, it is skipped (not all criteria translate to
HTTP probes — e.g., 'docs/openapi.json includes the endpoint').
"""

from __future__ import annotations

import re

# Match: VERB /path/with/{tokens} ... returns NNN ...
# Tolerates lowercase verbs, leading words ("returns 200 when GET ..."  is
# rare; we accept the common forward shape).
_PATTERN = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+(/[^\s)]*)\s+(?:returns|→|->|yields)\s+(\d{3})",
    re.IGNORECASE,
)


def extract_probes(criteria: list[str]) -> list[dict]:
    out: list[dict] = []
    for c in criteria:
        m = _PATTERN.search(c)
        if not m:
            continue
        method = m.group(1).upper()
        path = m.group(2).rstrip(",;.).")
        status = int(m.group(3))
        # Heuristic: if the criterion mentions auth, owner, or buyer_org, the
        # endpoint requires auth. 200 + no auth keyword → unauthenticated probe.
        ctext = c.lower()
        needs_auth = any(k in ctext for k in ("authenticat", "auth ", "owner", "buyer_org", "tenant", "403"))
        out.append({
            "method": method,
            "path": path,
            "expected_status": status,
            "auth": needs_auth,
        })
    return out
```

- [ ] **Step 4: Run, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_probe_parsing.py -v
```
Expected: 7 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/common/probe.py tests/factory/test_probe_parsing.py
git commit -m "factory(v2): add HTTP probe parser (common/probe.py)"
```

---

### Task 2: Implement ProbeStaging Lambda (TDD)

Per spec §2.7: reads `prd.json` from the merged commit's `.factory/last-run/` (which CommitAndPush wrote in Phase 3 Task 8), parses probes via `common.probe`, executes them against `STAGING_URL` with a verifier token, returns `{passed, probes[], failures[]}`. 10-second probe timeout.

We read `.factory/last-run/prd.json` from the merged commit on `main` via the GitHub API (avoids needing a git checkout in the Lambda). Cheap — one HTTP call.

**Files:**
- Create: `scripts/factory_lambdas/handlers/probe_staging.py`
- Create: `tests/factory/test_probe_staging.py`

- [ ] **Step 1: Write the test.**

`tests/factory/test_probe_staging.py`:

```python
"""Tests for ProbeStaging — feeds a fake PRD + fake HTTP responses, asserts probe summary."""

from __future__ import annotations

import json
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
```

- [ ] **Step 2: Run, verify failure.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_probe_staging.py -v
```
Expected: ImportError on `handlers.probe_staging`.

- [ ] **Step 3: Write `handlers/probe_staging.py`.**

```python
"""ProbeStaging Lambda — verifies the deployed feature is actually serving by
running HTTP probes derived from the PRD's acceptance criteria.

Spec §2.7. Triggered by the postdeploy state machine after deploy.yml's
workflow_run completion event.
"""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.request import urlopen

import boto3

from common.probe import extract_probes
from common.secrets import get_secret

GH_OWNER = os.environ.get("GITHUB_OWNER", "nabbic")
GH_REPO  = os.environ.get("GITHUB_REPO",  "nova")
STAGING_URL = os.environ["STAGING_URL"].rstrip("/")
PROBE_TIMEOUT = 10


def _fetch_prd_from_github(merge_sha: str) -> dict:
    """Read .factory/last-run/prd.json from the merged commit via the GitHub
    REST contents API."""
    gh_token = get_secret("nova/factory/github-token")
    url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/.factory/last-run/prd.json?ref={merge_sha}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3.raw",
    })
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _get_token() -> str:
    return get_secret("nova/factory/staging-verifier-token")


def _probe(method: str, path: str, expected: int, auth: bool, token: str) -> dict:
    url = STAGING_URL + path
    headers = {}
    if auth:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers)
    actual_status = None
    error = None
    try:
        with urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            actual_status = resp.status
    except urllib.error.HTTPError as e:
        actual_status = e.code
    except Exception as e:
        error = str(e)[:200]

    return {
        "method": method,
        "path": path,
        "expected_status": expected,
        "actual_status":   actual_status,
        "passed":          (actual_status == expected) and (error is None),
        "error":           error,
    }


def handler(event, _ctx):
    feature_id = event["feature_id"]
    merge_sha  = event["merge_sha"]

    prd = _fetch_prd_from_github(merge_sha)
    criteria = []
    for s in prd.get("stories", []):
        criteria.extend(s.get("acceptance_criteria", []))
    probes_def = extract_probes(criteria)
    if not probes_def:
        return {"feature_id": feature_id, "merge_sha": merge_sha, "passed": True, "probes": [], "failures": [], "reason": "no_http_probes"}

    token = _get_token()
    results = [_probe(p["method"], p["path"], p["expected_status"], p["auth"], token) for p in probes_def]
    failures = [r for r in results if not r["passed"]]

    return {
        "feature_id": feature_id,
        "merge_sha":  merge_sha,
        "passed":     len(failures) == 0,
        "probes":     results,
        "failures":   failures,
    }
```

- [ ] **Step 4: Run, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_probe_staging.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/probe_staging.py tests/factory/test_probe_staging.py
git commit -m "factory(v2): add ProbeStaging Lambda (HTTP probes from PRD acceptance criteria)"
```

---

### Task 3: Implement RevertMerge Lambda (TDD)

Per §2.7 + §4.1: revert the merge commit on `main`, open a revert PR (auto-merged by `quality-gates.yml` since revert PRs pass tests), update Notion to `Failed` with reason `deploy_verification_failed`. Idempotent: if `main`'s HEAD is already a revert of the offending sha, skip the revert and just update Notion.

**Files:**
- Create: `scripts/factory_lambdas/handlers/revert_merge.py`
- Create: `tests/factory/test_revert_merge.py`

- [ ] **Step 1: Write tests.**

`tests/factory/test_revert_merge.py`:

```python
"""Tests for RevertMerge — exercises gh subprocess + Notion update mocks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))


def _gh_resp(stdout: str = "", stderr: str = "", returncode: int = 0):
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


def test_reverts_when_head_is_not_already_revert():
    from handlers import revert_merge  # type: ignore

    notion_calls = []
    def fake_notion(path, *, method, body=None):
        notion_calls.append({"path": path, "method": method, "body": body})

    gh_runs = []
    def fake_gh(args, **kw):
        gh_runs.append(args)
        if args[:3] == ["gh", "api", "repos/nabbic/nova/commits/main"]:
            # HEAD is not a revert of merge_sha
            return _gh_resp(stdout=json.dumps({"sha": "headsha", "commit": {"message": "feat: something\n\nfactory-execution: ...\n"}}))
        return _gh_resp()

    with patch.object(revert_merge, "_notion_request", side_effect=fake_notion), \
         patch.object(revert_merge, "_run_gh", side_effect=fake_gh), \
         patch.object(revert_merge, "get_secret", return_value="tok"):
        result = revert_merge.handler({"feature_id": "x", "merge_sha": "abc123"}, None)

    assert result["reverted"] is True
    # gh pr create AND a status update on Notion
    assert any(args[:3] == ["gh", "pr", "create"] for args in gh_runs)
    assert any(c["method"] == "PATCH" for c in notion_calls)


def test_skips_revert_if_head_already_reverts():
    from handlers import revert_merge  # type: ignore

    def fake_gh(args, **kw):
        if args[:3] == ["gh", "api", "repos/nabbic/nova/commits/main"]:
            return _gh_resp(stdout=json.dumps({"sha": "newer", "commit": {"message": "Revert \"feat: stuff\"\n\nThis reverts commit abc123def...\n"}}))
        return _gh_resp()

    with patch.object(revert_merge, "_notion_request"), \
         patch.object(revert_merge, "_run_gh", side_effect=fake_gh), \
         patch.object(revert_merge, "get_secret", return_value="tok"):
        result = revert_merge.handler({"feature_id": "x", "merge_sha": "abc123"}, None)

    assert result["reverted"] is False
    assert result["already_reverted"] is True
```

- [ ] **Step 2: Run, verify fail.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_revert_merge.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write `handlers/revert_merge.py`.**

```python
"""RevertMerge Lambda — reverts the merge commit on main and re-files Notion.

Spec §2.7 + §4.2 idempotency: if main's HEAD is already a revert of the
offending sha, skip the revert and just update Notion.

Uses `gh` (the GitHub CLI) so we don't have to re-implement clone/push/PR.
The Lambda image already includes `gh` via a layer or is invoked from the
existing CommitAndPush environment.

NOTE: the existing factory CommitAndPush handler runs `gh` from a Lambda
layer (`infra/factory/lambda-layer.tf`). We reuse that layer for this
handler — the layer attachment happens via the existing `aws_lambda_function.handlers_v2`
in `lambdas-v2.tf`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from urllib.request import urlopen
from pathlib import Path

from common.secrets import get_secret

GH_OWNER = os.environ.get("GITHUB_OWNER", "nabbic")
GH_REPO  = os.environ.get("GITHUB_REPO",  "nova")
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
        data=json.dumps(body).encode("utf-8") if body else None,
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _run_gh(args: list[str], cwd: str | None = None, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env, check=False)


def _head_is_revert_of(merge_sha: str) -> bool:
    p = _run_gh(["gh", "api", f"repos/{GH_OWNER}/{GH_REPO}/commits/main"])
    if p.returncode != 0:
        return False
    body = json.loads(p.stdout)
    msg  = body.get("commit", {}).get("message", "")
    return f"This reverts commit {merge_sha}" in msg


def handler(event, _ctx):
    feature_id = event["feature_id"]
    merge_sha  = event["merge_sha"]
    failures   = event.get("failures", [])

    gh_token = get_secret("nova/factory/github-token")

    if _head_is_revert_of(merge_sha):
        # Idempotent path
        _notion_request(
            f"/pages/{feature_id}",
            method="PATCH",
            body={
                "properties": {
                    "Status":    {"select": {"name": "Failed"}},
                    "Error Log": {"rich_text": [{"text": {"content": f"deploy_verification_failed; main already reverted (sha={merge_sha})"[:2000]}}]},
                }
            },
        )
        return {"feature_id": feature_id, "reverted": False, "already_reverted": True}

    # Clone repo into /tmp, revert the merge, push the branch, open PR
    tmpdir = Path(tempfile.mkdtemp(prefix="revert-"))
    try:
        env = {"GH_TOKEN": gh_token, "GIT_TERMINAL_PROMPT": "0"}
        clone = _run_gh(["gh", "repo", "clone", f"{GH_OWNER}/{GH_REPO}", str(tmpdir)], env_extra=env)
        if clone.returncode != 0:
            raise RuntimeError(f"clone failed: {clone.stderr}")

        revert_branch = f"revert/{merge_sha[:8]}"
        _run_gh(["git", "checkout", "-b", revert_branch], cwd=str(tmpdir), env_extra=env)
        revert = _run_gh(["git", "revert", "--no-edit", "-m", "1", merge_sha], cwd=str(tmpdir), env_extra=env)
        if revert.returncode != 0:
            raise RuntimeError(f"git revert failed: {revert.stderr}")

        push = _run_gh(["git", "push", "-u", "origin", revert_branch], cwd=str(tmpdir), env_extra=env)
        if push.returncode != 0:
            raise RuntimeError(f"git push failed: {push.stderr}")

        body_text = f"Auto-revert: deploy verification failed for merge {merge_sha}.\n\nFailures:\n" + json.dumps(failures, indent=2)
        pr_create = _run_gh([
            "gh", "pr", "create",
            "--title", f"Revert: deploy verification failed for {merge_sha[:8]}",
            "--body",  body_text,
            "--base",  "main",
            "--head",  revert_branch,
        ], cwd=str(tmpdir), env_extra=env)
        if pr_create.returncode != 0:
            raise RuntimeError(f"gh pr create failed: {pr_create.stderr}")

        # Update Notion
        _notion_request(
            f"/pages/{feature_id}",
            method="PATCH",
            body={
                "properties": {
                    "Status":    {"select": {"name": "Failed"}},
                    "Error Log": {"rich_text": [{"text": {"content": f"deploy_verification_failed; revert PR opened for {merge_sha}"[:2000]}}]},
                }
            },
        )

        return {"feature_id": feature_id, "reverted": True, "revert_pr_url": pr_create.stdout.strip()}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
```

- [ ] **Step 4: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_revert_merge.py -v
```
Expected: 2 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/revert_merge.py tests/factory/test_revert_merge.py
git commit -m "factory(v2): add RevertMerge Lambda (gh-based revert with idempotency)"
```

---

### Task 4: Add staging verifier token Secrets Manager entry

The token is created MANUALLY (so its value never lives in Terraform state). Terraform just declares the secret slot and grants IAM read.

**Files:**
- Create: `infra/factory/secrets-postdeploy.tf`
- Modify: `infra/factory/iam.tf` (add `nova/factory/staging-verifier-token*` to the existing Secrets Manager statement, OR rely on the existing wildcard if it covers it)

- [ ] **Step 1: Manually create the secret slot in AWS.**

```bash
aws secretsmanager create-secret --name nova/factory/staging-verifier-token \
  --description "Bearer token for postdeploy probe -> staging API" \
  --secret-string "$(openssl rand -hex 32)" \
  --region us-east-1
```
Expected: a JSON response with the secret ARN.

This secret value is then provisioned into the staging API's auth-bypass list out-of-band (e.g., set as `STAGING_VERIFIER_TOKEN` env var on the staging FastAPI app). For Phase 4 we just need the slot to exist so the Lambda can read it.

- [ ] **Step 2: Add `infra/factory/secrets-postdeploy.tf`.**

```hcl
# Slot for the staging verifier token. Created out-of-band so its value never
# enters Terraform state. We import it here for IAM purposes.

data "aws_secretsmanager_secret" "staging_verifier_token" {
  name = "nova/factory/staging-verifier-token"
}

# This data source is referenced by IAM in iam.tf — see the inline policy
# update for lambda_exec.
output "staging_verifier_token_arn" {
  value     = data.aws_secretsmanager_secret.staging_verifier_token.arn
  sensitive = true
}
```

- [ ] **Step 3: Verify IAM coverage.**

Check if the `lambda_exec` Secrets Manager statement uses a wildcard like `nova/factory/*` already:

```bash
grep -A 5 "secretsmanager" /c/Claude/Nova/nova/infra/factory/iam.tf | head -20
```

If the resource ARN is `arn:aws:secretsmanager:*:*:secret:nova/factory/*`, no edit needed. Otherwise widen to include `nova/factory/staging-verifier-token*`.

- [ ] **Step 4: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: the data source resolves cleanly; one new output. No resource changes.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/secrets-postdeploy.tf
git commit -m "infra(factory v2): declare staging-verifier-token secret slot for ProbeStaging"
```

---

### Task 5: Register the new Lambdas in `lambdas-v2.tf`

**Files:**
- Modify: `infra/factory/lambdas-v2.tf`

- [ ] **Step 1: Extend the `handlers_v2` map.**

Edit `lambdas-v2.tf` so the local map becomes:

```hcl
locals {
  handlers_v2 = {
    load_feature   = { timeout = 60,  memory = 512  }
    plan           = { timeout = 120, memory = 1024 }
    mark_blocked   = { timeout = 30,  memory = 256  }
    review         = { timeout = 180, memory = 1024 }
    probe_staging  = { timeout = 60,  memory = 512  }
    revert_merge   = { timeout = 300, memory = 1024 }
  }
}
```

- [ ] **Step 2: Add `STAGING_URL` to the Lambda env block.**

Inside the `aws_lambda_function.handlers_v2` `environment.variables` block in `lambdas-v2.tf`, add:

```hcl
STAGING_URL = var.staging_url
```

- [ ] **Step 3: Declare the variable.**

In `infra/factory/variables.tf`, add:

```hcl
variable "staging_url" {
  description = "Base URL of the staging API used by the postdeploy probe."
  type        = string
  default     = "https://staging-api.nova-factory.test"
}
```

- [ ] **Step 4: Build zips and apply.**

```bash
cd /c/Claude/Nova/nova/scripts/factory_lambdas
bash build.sh
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 2 new Lambda functions + 2 new log groups. The other v2 Lambdas pick up the new `STAGING_URL` env var (they ignore it; harmless).

- [ ] **Step 5: Smoke-invoke each.**

```bash
aws lambda invoke --function-name nova-factory-probe-staging --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/ps.json; cat /tmp/ps.json
aws lambda invoke --function-name nova-factory-revert-merge --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/rm.json; cat /tmp/rm.json
```
Expected: each errors at `event["feature_id"]` (KeyError), confirming imports OK.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/lambdas-v2.tf infra/factory/variables.tf
git commit -m "infra(factory v2): deploy probe_staging + revert_merge Lambdas; add staging_url variable"
```

---

### Task 6: Define the postdeploy state machine

**Files:**
- Create: `infra/factory/state-machine-postdeploy.json.tpl`
- Create: `infra/factory/state-machine-postdeploy.tf`

- [ ] **Step 1: Write the SFN template.**

`state-machine-postdeploy.json.tpl`:

```json
{
  "Comment": "Nova factory postdeploy verification. Spec §2.7.",
  "TimeoutSeconds": 1800,
  "StartAt": "ProbeStaging",
  "States": {
    "ProbeStaging": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-probe-staging",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "merge_sha.$":  "$.merge_sha"
        }
      },
      "ResultPath": "$.probe",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 30, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "AlarmAndFail"}],
      "Next": "Healthy"
    },

    "Healthy": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.probe.Payload.passed", "BooleanEquals": true, "Next": "MarkVerified"}
      ],
      "Default": "RevertMerge"
    },

    "MarkVerified": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "Verified",
          "extras": {}
        }
      },
      "ResultPath": null,
      "End": true
    },

    "RevertMerge": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-revert-merge",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "merge_sha.$":  "$.merge_sha",
          "failures.$":   "$.probe.Payload.failures"
        }
      },
      "ResultPath": "$.revert",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "AlarmAndFail"}],
      "Next": "RevertSuccess"
    },

    "RevertSuccess": {
      "Type": "Pass",
      "Comment": "RevertMerge succeeded — feature is back to a known-good state on main.",
      "End": true
    },

    "AlarmAndFail": {
      "Type": "Task",
      "Resource": "arn:aws:states:::sns:publish",
      "Parameters": {
        "TopicArn": "${sns_alerts_arn}",
        "Subject":  "Postdeploy probe AND revert failed — manual intervention required",
        "Message.$": "States.JsonToString($)"
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailState": {"Type": "Fail", "Error": "PostdeployFailed"}
  }
}
```

- [ ] **Step 2: Create the SFN resource + IAM role.**

`infra/factory/state-machine-postdeploy.tf`:

```hcl
resource "aws_iam_role" "sfn_postdeploy" {
  name = "${local.name_prefix}-sfn-postdeploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "states.amazonaws.com" },
      Action = "sts:AssumeRole",
    }]
  })
  tags = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_iam_role_policy" "sfn_postdeploy_inline" {
  role = aws_iam_role.sfn_postdeploy.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = ["lambda:InvokeFunction"],
        Resource = [
          aws_lambda_function.handlers_v2["probe_staging"].arn,
          aws_lambda_function.handlers_v2["revert_merge"].arn,
          # update-notion is a v1 Lambda — referenced by name in the SFN template
          "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:${local.name_prefix}-update-notion",
        ]
      },
      {
        Effect = "Allow",
        Action = ["sns:Publish"],
        Resource = [aws_sns_topic.alerts.arn]
      },
      {
        Effect = "Allow",
        Action = ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery", "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"],
        Resource = "*"
      },
      {
        Effect = "Allow",
        Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "sfn_postdeploy" {
  name              = "/aws/states/nova-factory-postdeploy"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_sfn_state_machine" "postdeploy" {
  name     = "nova-factory-postdeploy"
  role_arn = aws_iam_role.sfn_postdeploy.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine-postdeploy.json.tpl", {
    region          = var.aws_region
    account_id      = data.aws_caller_identity.current.account_id
    name_prefix     = local.name_prefix
    sns_alerts_arn  = aws_sns_topic.alerts.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_postdeploy.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }
  tracing_configuration { enabled = true }
  tags                  = merge(local.common_tags, { Generation = "v2" })
}

output "postdeploy_state_machine_arn" {
  value = aws_sfn_state_machine.postdeploy.arn
}
```

This references `aws_sns_topic.alerts` — that already exists per Phase 1's snapshot of factory infrastructure. If it doesn't, locate the existing alerts topic in `infra/factory/dashboard.tf` or similar and adjust the reference.

- [ ] **Step 3: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 1 IAM role + 1 inline policy + 1 log group + 1 state machine + 1 output.

- [ ] **Step 4: Verify SFN exists.**

```bash
aws stepfunctions describe-state-machine \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
  --query '{name: name, status: status}' --output table
```
Expected: name `nova-factory-postdeploy`, status `ACTIVE`.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/state-machine-postdeploy.tf infra/factory/state-machine-postdeploy.json.tpl
git commit -m "infra(factory v2): add nova-factory-postdeploy state machine"
```

---

### Task 7: Wire `deploy.yml` to trigger the postdeploy SFN (Option B)

The `deploy.yml` workflow already runs on every successful merge. Add a final step that calls SFN start-execution.

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1: Read the current deploy.yml.**

```bash
cat /c/Claude/Nova/nova/.github/workflows/deploy.yml
```
Expected: a workflow that reacts to `workflow_run` of `quality-gates.yml` or `push` to main, deploys to ECS, and ends.

- [ ] **Step 2: Append a step that triggers postdeploy SFN.**

After the deploy step (and after the deploy succeeds), add:

```yaml
      - name: Trigger postdeploy verification
        if: success()
        run: |
          FEATURE_ID="$(git log -1 --format=%B | sed -n 's/^factory-execution: \(.*\)$/\1/p' | head -n 1 | sed 's/^smoke-//' | sed 's/-[0-9]*$//')"
          # ^ best-effort feature_id extraction from the commit's factory-execution trailer.
          # If the trailer isn't a Notion feature_id (e.g., manual deploy), bail out.
          if [[ -z "$FEATURE_ID" ]]; then
            echo "no factory-execution trailer; skipping postdeploy verification"
            exit 0
          fi
          MERGE_SHA="$(git rev-parse HEAD)"
          aws stepfunctions start-execution \
            --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
            --name "postdeploy-${MERGE_SHA:0:8}-$(date +%s)" \
            --input "{\"feature_id\":\"$FEATURE_ID\",\"merge_sha\":\"$MERGE_SHA\"}"
```

The feature_id extraction is heuristic. If you want a more reliable path, the `commit_and_push` Lambda (Phase 3 Task 8) can also write a `.factory/last-run/meta.json` containing `{feature_id, execution_id, merge_sha_will_be_filled_post_merge}` — and the post-deploy step reads that file. Either is fine; the heuristic above works for the smoke fixtures because the smoke runner names executions `smoke-<fixture>-<ts>` and the feature_id ends up in the commit message as a uuid.

Actually, simpler: the CommitAndPush handler can write `feature_id` directly into a `.factory/last-run/meta.json`. Phase 3 Task 8 already establishes this directory. **Update Phase 3 Task 8** to also write `meta.json` with `{feature_id}`. Then this `deploy.yml` step becomes:

```yaml
      - name: Trigger postdeploy verification
        if: success()
        run: |
          if [[ ! -f .factory/last-run/meta.json ]]; then
            echo "no .factory/last-run/meta.json; skipping postdeploy verification"
            exit 0
          fi
          FEATURE_ID="$(jq -r .feature_id .factory/last-run/meta.json)"
          MERGE_SHA="$(git rev-parse HEAD)"
          aws stepfunctions start-execution \
            --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
            --name "postdeploy-${MERGE_SHA:0:8}-$(date +%s)" \
            --input "{\"feature_id\":\"$FEATURE_ID\",\"merge_sha\":\"$MERGE_SHA\"}"
```

If you went with this cleaner version, also patch `commit_and_push.py` to write `meta.json`:

```python
(last_run_dir / "meta.json").write_text(
    json.dumps({"feature_id": feature_id, "execution_id": execution_id}, indent=2),
    encoding="utf-8",
)
```

- [ ] **Step 3: Verify the GH Actions OIDC role can call SFN.**

```bash
ROLE_NAME=<the OIDC role name for deploys>
aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[].PolicyName'
aws iam list-role-policies --role-name "$ROLE_NAME"
```

If no `states:StartExecution` is granted, add an inline policy or a small managed policy. Typical addition:

```bash
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name nova-factory-sfn-start --policy-document '{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["states:StartExecution"],
    "Resource": "arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy"
  }]
}'
```

- [ ] **Step 4: Commit.**

```bash
cd /c/Claude/Nova/nova
git add .github/workflows/deploy.yml scripts/factory_lambdas/handlers/commit_and_push.py
git commit -m "ci(deploy): trigger nova-factory-postdeploy after staging deploy succeeds"
```

---

### Task 8: Smoke test — synthetic happy path

Manually exercise the postdeploy SFN against a known-good staging endpoint.

- [ ] **Step 1: Pick a probe target.**

If staging exists: use the real `STAGING_URL`. Otherwise, for testing only: spin up a tiny ECS Fargate task or use `https://httpbin.org/status/200` as the target by setting `STAGING_URL=https://httpbin.org`. The path `/status/200` always returns 200 — synthesize a PRD acceptance criterion `GET /status/200 returns 200` to drive a probe at it.

- [ ] **Step 2: Manually start a postdeploy execution.**

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
  --name "smoke-happy-$(date +%s)" \
  --input '{"feature_id":"<some-real-notion-feature-id-from-an-earlier-smoke>","merge_sha":"<the-commit-sha-from-that-smoke>"}'
```
Expected: SUCCEEDED. The Notion feature ends with status `Verified`.

- [ ] **Step 3: Inspect output.**

```bash
EXEC_ARN=<from above>
aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query 'output' --output text | jq '.probe.Payload'
```
Expected: `passed: true`, `probes` array populated.

---

### Task 9: Smoke test — synthetic failure (revert path)

The point: prove RevertMerge works without actually deploying broken code to production.

- [ ] **Step 1: Construct an artificially-failing input.**

Pick a real feature_id and merge_sha from an earlier smoke (a green merge), but inject a probe that's certain to fail. The cleanest way: temporarily point `STAGING_URL` at an endpoint that returns the wrong status.

Easiest path: hand-edit the merged commit's `.factory/last-run/prd.json` to add a criterion `GET /this-route-does-not-exist returns 200`, then start a postdeploy execution against that sha. The probe will hit the staging API, get a 404, and the SFN will route to RevertMerge.

```bash
# Manually start
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-postdeploy \
  --name "smoke-failure-$(date +%s)" \
  --input '{"feature_id":"<id>","merge_sha":"<sha>"}'
```

- [ ] **Step 2: Verify the revert flow.**

After the execution finishes:

```bash
EXEC_ARN=<from above>
aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query 'output' --output text | jq
```
Expected: `revert.Payload.reverted: true` AND a revert PR exists on GitHub:

```bash
gh pr list --repo nabbic/nova --state all --search "Revert: deploy verification failed" --limit 3
```
Expected: a PR titled `Revert: deploy verification failed for <sha-prefix>`.

The Notion feature should now be `Failed` with reason `deploy_verification_failed`.

- [ ] **Step 3: Clean up the test PR.**

If quality-gates auto-merged the revert PR, the offending change is now gone from `main`. That's the intended behavior. If you DON'T want the test to actually mutate `main`, run the test against a feature branch instead by editing `state-machine-postdeploy.json.tpl` to read `--base $.test_base` etc. — but that's overengineering for a smoke. Easier: do the smoke against a feature whose merge you're prepared to revert.

If quality-gates rejected the revert PR (it shouldn't — reverts pass tests), close the revert PR manually.

---

### Task 10: Final verification

- [ ] **Step 1: All tests pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/ -v
```
Expected: 43 (Phase 3) + 7 (probe parsing) + 3 (probe staging) + 2 (revert merge) = 55 tests pass.

- [ ] **Step 2: Terraform plan clean.**

```bash
cd /c/Claude/Nova/nova/infra/factory && terraform plan -input=false | tail -3
```
Expected: `No changes.`

- [ ] **Step 3: Both v2 SFNs are ACTIVE.**

```bash
for sm in nova-factory-v2 nova-factory-postdeploy; do
  status=$(aws stepfunctions describe-state-machine \
    --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:$sm \
    --query status --output text)
  echo "$sm: $status"
done
```
Expected: both `ACTIVE`.

- [ ] **Step 4: Push branch.**

```bash
git -C /c/Claude/Nova/nova push origin factory-overhaul-2026-05-03
```

---

## Phase 4 acceptance criteria recap

1. `nova-factory-postdeploy` SFN exists and is `ACTIVE`.
2. `probe_staging` and `revert_merge` Lambdas deployed.
3. Probe parser unit tests pass (7).
4. Probe staging unit tests pass (3) including no-HTTP-criteria short-circuit.
5. Revert merge unit tests pass (2) including idempotency.
6. Manually exercised: happy path → Notion `Verified`; failure path → revert PR opened, Notion `Failed`.
7. `deploy.yml` triggers postdeploy SFN after a successful staging deploy.
8. Working tree clean; branch pushed.

---

## What Phase 5 will do

Phase 5 ("Self-pause + budgets + observability"):

- **Auto-pause Lambda** subscribed to two SNS topics: 3-consecutive-execution-failures alarm and $100 budget breach. Flips `/nova/factory/paused = true` in Parameter Store.
- **Webhook relay** (existing `nova-webhook-relay`) is updated to read `/nova/factory/paused` on every delivery; when `true`, post a Notion comment ("Factory currently paused — see CloudWatch alarms") and 200-OK.
- **CloudWatch alarms**: 3-consecutive-failures (already exists from v1, repoint), $50 alarm (new), $100 alarm (new, hard ceiling).
- **Dashboard widgets** for v2 stages: turns-per-feature, tokens-per-feature, time-per-stage, validate/review repair rates.
- **Saved Logs Insights queries**: `ralph-turn-summary`, `validation-failures`, `execution-trace`.
- Replace v1 `agent-calls-summary` query with v2 equivalents.

That phase is operational hardening — the v2 pipeline already works end-to-end after Phase 4; Phase 5 makes it safe to leave running unattended.
