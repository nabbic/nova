# Factory v2 — Phase 3: LLM Core + Main State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the LLM core of the v2 factory — RalphTurn (container Lambda, the architecturally critical piece), Validate-v2 (deterministic container), Review (Sonnet zip Lambda), CommitAndPush v2 — and replace the Phase 2 stub state machine with the full `nova-factory-v2` SFN that drives them, with loop iteration, repair routing, token budgets, and CommitAndPush + WaitForQualityGates + MarkDone tail. End state: trivial and medium smoke fixtures complete `Done` end-to-end (PR opened, quality-gates pass, merged); oversized still blocks at Plan.

**Architecture:** The state machine becomes the deterministic orchestrator (per spec §0.1). LLMs only run inside three stages: Plan (Phase 2, Haiku), RalphTurn (Phase 3, Sonnet, looped ≤6×), Review (Phase 3, Sonnet, single call). Validate-v2 is purely deterministic. RalphTurn is a container Lambda based on the python:3.12 Lambda runtime with Node + `@anthropic-ai/claude-code` layered on (deviating from the spec's "nodejs:20 base" wording to match the existing `validate_workspace` container pattern; functional outcome is identical — see Task 6 note).

**Tech Stack:** Python 3.12, Anthropic Messages API + Claude Code CLI, Docker, ECR, Lambda container images, Step Functions (loop iterator pattern), Terraform/AWS.

**Predecessors:** Phases 1 + 2 complete and merged. Phase 2 produced the Plan Lambda, sizing rubric, MarkBlocked, and the stub SFN `nova-factory-v2-planonly` — that stub is *replaced* by the full v2 SFN in this phase, not extended.

**Branch:** `factory-overhaul-2026-05-03`. Working directory: `C:\Claude\Nova\nova`. AWS account `577638385116`, region `us-east-1`.

**Out of scope for Phase 3:** Postdeploy SFN (Phase 4). Self-pause + budgets + observability (Phase 5). Cutover (Phase 6). Bedrock-native invocation (deferred indefinitely per spec §8).

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `scripts/factory_lambdas/containers/ralph_turn/Dockerfile` | Python 3.12 Lambda base + Node 20 + `@anthropic-ai/claude-code` + Python tooling. |
| `scripts/factory_lambdas/containers/ralph_turn/build.sh` | Build, tag, push to ECR (mirrors `validate_workspace/build.sh`). |
| `scripts/factory_lambdas/containers/ralph_turn/ralph_turn.py` | The Lambda handler. Materializes workspace from S3, restores `.git`, composes prompt, invokes `claude -p`, scans changes, applies allowlist, re-uploads, returns telemetry. |
| `scripts/factory_lambdas/containers/ralph_turn/allowlist.py` | Pure-function module enforcing the §4.3 sandbox allowlist (testable in isolation). |
| `scripts/factory_lambdas/containers/ralph_turn/git_io.py` | `.git` tarball pack/unpack helpers (testable). |
| `scripts/factory_lambdas/containers/validate_v2/Dockerfile` | Deterministic 6-step validator (ruff/mypy/pytest/tf/tsc/alembic). |
| `scripts/factory_lambdas/containers/validate_v2/build.sh` | Build, tag, push to ECR. |
| `scripts/factory_lambdas/containers/validate_v2/validate_v2.py` | Handler running the 6-step chain; emits `issues.json`. |
| `scripts/factory_lambdas/handlers/review.py` | Single Sonnet call. Reads `prd.json`, the diff, and `.factory/reviewer-system.md`. Validates output JSON. |
| `tests/factory/test_allowlist.py` | Unit tests for the filesystem allowlist. |
| `tests/factory/test_git_io.py` | Unit tests for `.git` tarball round-trip. |
| `tests/factory/test_review.py` | Unit tests for the Review Lambda (mocks Sonnet, validates output schema). |
| `tests/factory/test_validate_v2.py` | Smoke test: synthetic broken workspace → expected issues. |
| `tests/factory/fixtures/sonnet_review_clean.json` | Sonnet response for the happy path (`passed: true`, no blockers). |
| `tests/factory/fixtures/sonnet_review_tenancy_blocker.json` | Sonnet response with one tenancy blocker. |
| `infra/factory/iam-ralph.tf` | Tightened IAM role `nova-factory-ralph-turn-exec` (S3 prefix scoped, narrow Secrets Manager). |
| `infra/factory/lambdas-v2-images.tf` | Container Lambda definitions for `ralph_turn` and `validate_v2` (parallel to `lambdas-image.tf`). |
| `infra/factory/state-machine-v2.tf` | Full v2 state machine `nova-factory-v2`. |
| `infra/factory/state-machine-v2.json.tpl` | Full v2 SFN template — replaces the Phase 2 stub. |

**Modify:**

| Path | Change |
|---|---|
| `scripts/factory_lambdas/handlers/commit_and_push.py` | Write `.factory/last-run/{prd.json,review.json,progress.txt}` to the workspace before `git add -A` so the postdeploy probe (Phase 4) can read them from the merged commit. |
| `infra/factory/lambdas-v2.tf` | Add `review` to the `handlers_v2` map. |
| `scripts/factory_lambdas/build.sh` | Already handles `.factory/` from Phase 2 — no change. (Verify the schema is in the new `review.zip`.) |

**Delete:**

| Path | Reason |
|---|---|
| `infra/factory/state-machine-v2-planonly.tf` | Replaced by `state-machine-v2.tf`. |
| `infra/factory/state-machine-v2-planonly.json.tpl` | Same. |

The Phase 2 stub SFN is *replaced*, not removed — its name slot is freed by deleting the old TF and reusing the v2 lambdas.

---

## Pre-flight

- [ ] **P-1: Phases 1 + 2 complete.**

```bash
pytest /c/Claude/Nova/nova/tests/factory/ -q
bash /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh trivial && \
bash /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh oversized
```
Expected: 24 tests pass; both smokes pass.

- [ ] **P-2: Docker daemon running.**

Run: `docker ps`
Expected: a (possibly empty) table of running containers, no error.

- [ ] **P-3: ECR access.**

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 577638385116.dkr.ecr.us-east-1.amazonaws.com
```
Expected: `Login Succeeded`.

- [ ] **P-4: Anthropic API key.**

```bash
aws secretsmanager get-secret-value --secret-id nova/factory/anthropic-api-key --query 'SecretString != null' --output text
```
Expected: `True`.

---

### Task 1: Implement the filesystem allowlist (TDD, pure function)

Spec §2.3.2 step 6 + §4.3 layer 4: after Claude Code exits, every changed path is checked. Anything under `.github/workflows/`, `.factory/` (except the literal `.factory/_DONE_`), `infra/factory/`, or any `..`/absolute path is REJECTED — removed from the upload set and surfaced as `DENIED:` in `repair_context.md`.

This is a pure string-list filter. No I/O. TDD.

**Files:**
- Create: `scripts/factory_lambdas/containers/ralph_turn/allowlist.py`
- Create: `tests/factory/test_allowlist.py`

- [ ] **Step 1: Write failing tests.**

`tests/factory/test_allowlist.py`:

```python
"""Tests for the RalphTurn filesystem allowlist (sandbox boundary 4)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas" / "containers" / "ralph_turn"))

from allowlist import classify, ALLOWED, DENIED  # noqa: E402


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
    Only the workflows/ subdirectory is sensitive (the factory PAT can't push
    workflow changes anyway, but defense in depth)."""
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
    from allowlist import partition
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
```

- [ ] **Step 2: Run, verify all fail.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_allowlist.py -v
```
Expected: ImportError on `allowlist`.

- [ ] **Step 3: Write `allowlist.py`.**

Create `scripts/factory_lambdas/containers/ralph_turn/allowlist.py`:

```python
"""Filesystem allowlist for the RalphTurn post-execution upload.

Spec §4.3 sandbox boundary 4. Pure string-classification — no I/O.

A path is DENIED if any of:
- Contains '..' anywhere
- Starts with '/'
- Is under .github/workflows/
- Is under infra/factory/
- Is under .factory/ AND is not exactly '.factory/_DONE_'

Otherwise it is ALLOWED.
"""

from __future__ import annotations

from typing import Iterable

ALLOWED = "ALLOWED"
DENIED  = "DENIED"

_DENIED_PREFIXES = (
    ".github/workflows/",
    "infra/factory/",
)
_FACTORY_DONE_SENTINEL = ".factory/_DONE_"


def classify(path: str) -> str:
    if path.startswith("/"):
        return DENIED
    if ".." in path.split("/"):
        return DENIED
    if path.startswith(".factory/"):
        return ALLOWED if path == _FACTORY_DONE_SENTINEL else DENIED
    for prefix in _DENIED_PREFIXES:
        if path.startswith(prefix):
            return DENIED
    return ALLOWED


def partition(paths: Iterable[str]) -> tuple[list[str], list[str]]:
    allowed: list[str] = []
    denied:  list[str] = []
    for p in paths:
        (allowed if classify(p) is ALLOWED else denied).append(p)
    return allowed, denied
```

- [ ] **Step 4: Run, verify all pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_allowlist.py -v
```
Expected: 12 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/containers/ralph_turn/allowlist.py tests/factory/test_allowlist.py
git commit -m "factory(v2): add RalphTurn filesystem allowlist (sandbox boundary 4)"
```

---

### Task 2: Implement `.git` tarball helpers (TDD)

Per spec §2.3.2 step 1: between turns, the workspace's `.git` directory is preserved as a tarball in S3. We need pack and unpack functions that round-trip a `.git` directory cleanly.

**Files:**
- Create: `scripts/factory_lambdas/containers/ralph_turn/git_io.py`
- Create: `tests/factory/test_git_io.py`

- [ ] **Step 1: Write tests.**

`tests/factory/test_git_io.py`:

```python
"""Tests for git tarball pack/unpack."""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas" / "containers" / "ralph_turn"))

from git_io import pack_git, unpack_git  # noqa: E402


def test_pack_then_unpack_preserves_git_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "x.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    sha_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True).stdout.strip()

    tarball = tmp_path / "git.tar.gz"
    pack_git(repo, tarball)
    assert tarball.exists() and tarball.stat().st_size > 0

    # Wipe and unpack into a new dir
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    (repo2 / "x.txt").write_text("hello\n")  # the workspace tree is restored separately; we only restore .git
    unpack_git(tarball, repo2)
    sha_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo2, check=True, capture_output=True).stdout.strip()

    assert sha_after == sha_before


def test_pack_only_includes_git_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "junk.txt").write_text("not a git file")

    tarball = tmp_path / "git.tar.gz"
    pack_git(repo, tarball)

    with tarfile.open(tarball, "r:gz") as tf:
        names = tf.getnames()
    assert all(n == ".git" or n.startswith(".git/") for n in names), names
```

- [ ] **Step 2: Run, verify failure.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_git_io.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write `git_io.py`.**

```python
"""Pack and unpack the .git directory of a workspace as a tarball.

The RalphTurn Lambda preserves git history across turns by tarring up .git
into S3 between invocations. The full code tree is also re-materialized
each turn but its history-bearing state lives only in .git.
"""

from __future__ import annotations

import tarfile
from pathlib import Path


def pack_git(repo_root: Path, out_tarball: Path) -> None:
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        raise FileNotFoundError(f"{git_dir} is not a git directory")
    out_tarball.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_tarball, "w:gz") as tf:
        tf.add(git_dir, arcname=".git")


def unpack_git(tarball: Path, repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tf:
        for member in tf.getmembers():
            # Reject paths attempting traversal
            if member.name.startswith("..") or "/.." in member.name or member.name.startswith("/"):
                raise RuntimeError(f"refusing to extract suspicious path: {member.name}")
        tf.extractall(repo_root)
```

- [ ] **Step 4: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_git_io.py -v
```
Expected: 2 tests pass.

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/containers/ralph_turn/git_io.py tests/factory/test_git_io.py
git commit -m "factory(v2): add git tarball pack/unpack helpers for RalphTurn"
```

---

### Task 3: Build the RalphTurn handler (assembled, not TDD-able as a unit)

The handler is the orchestration glue: download workspace from S3, materialize on disk, restore `.git`, build the prompt, run `claude -p`, scan changes, apply allowlist, re-upload. Most pieces are tested individually (allowlist, git_io); the integration is exercised by smoke tests in Tasks 11–13.

**Files:**
- Create: `scripts/factory_lambdas/containers/ralph_turn/ralph_turn.py`

- [ ] **Step 1: Write the handler.**

```python
"""RalphTurn — one Claude Code turn against a feature workspace.

Spec §2.3.2. Per-turn flow:
1. Download S3 workspace tree to /tmp/ws. Restore .git from .git.tar.gz if present.
2. Read prd.json, progress.txt, repair_context.md (if any).
3. Compose prompt: system = repo CLAUDE.md + .factory/implementer-system.md;
                   user   = prd.json + progress.txt + repair_context.md.
4. Invoke `claude -p --model claude-sonnet-4-6 --max-turns 30 \
                    --output-format json --dangerously-skip-permissions`
5. Parse JSON output for token counts; scan workspace for changed paths.
6. Apply filesystem allowlist; rejected paths are reverted in-tree and added
   to repair_context.md as `DENIED:` lines.
7. Pack updated .git into .git.tar.gz; re-upload everything to S3.
8. Return telemetry.

The handler is invoked once per loop iteration. Nothing persists in /tmp/ across
invocations — Lambda may reuse the container, but /tmp is wiped (or treated as
wiped). Always restore from S3.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

import boto3

# Lambda task root holds the system prompt files we ship in the image
TASK_ROOT = Path(os.environ.get("LAMBDA_TASK_ROOT", "/var/task"))
sys.path.insert(0, str(TASK_ROOT))

from allowlist import partition  # noqa: E402
from git_io import pack_git, unpack_git  # noqa: E402

BUCKET   = os.environ["WORKSPACE_BUCKET"]
WS_ROOT  = Path("/tmp/ws")
GIT_TGZ  = "workspace/.git.tar.gz"
RALPH_MODEL = os.environ.get("RALPH_MODEL", "claude-sonnet-4-6")
RALPH_MAX_INNER_TURNS = os.environ.get("RALPH_MAX_INNER_TURNS", "30")
SYSTEM_PROMPT_PATH = TASK_ROOT / ".factory" / "implementer-system.md"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "/opt/node/lib/node_modules/@anthropic-ai/claude-code/cli.js")

_s3 = boto3.client("s3")


def _list_s3(prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def _download_workspace(execution_id: str) -> None:
    """Mirror s3://<bucket>/<execution_id>/workspace/ → /tmp/ws."""
    if WS_ROOT.exists():
        shutil.rmtree(WS_ROOT)
    WS_ROOT.mkdir(parents=True)
    prefix = f"{execution_id}/workspace/"
    keys = _list_s3(prefix)
    for key in keys:
        rel = key[len(prefix):]
        if not rel or rel.endswith("/"):
            continue
        if rel == ".git.tar.gz":
            continue  # handled separately below
        dest = WS_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        _s3.download_file(BUCKET, key, str(dest))

    git_tgz_key = f"{execution_id}/{GIT_TGZ}"
    git_tarball = Path("/tmp/.git.tar.gz")
    try:
        _s3.download_file(BUCKET, git_tgz_key, str(git_tarball))
        unpack_git(git_tarball, WS_ROOT)
    except _s3.exceptions.ClientError:
        # First turn — no prior tarball. Initialize an empty git repo.
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=WS_ROOT, check=True)
        subprocess.run(["git", "config", "user.email", "factory@nova"], cwd=WS_ROOT, check=True)
        subprocess.run(["git", "config", "user.name", "Nova Factory"], cwd=WS_ROOT, check=True)
        # Stage and commit anything that was downloaded so future diffs are
        # against the initial state, not "everything is new."
        subprocess.run(["git", "add", "-A"], cwd=WS_ROOT, check=True)
        result = subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "factory: initial workspace state"], cwd=WS_ROOT)
        if result.returncode != 0:
            # Empty repo — that's fine.
            subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "factory: initial empty workspace"], cwd=WS_ROOT, check=True)


def _read_prd() -> dict:
    return json.loads((WS_ROOT.parent / "ws" / "prd.json").read_text() if (WS_ROOT / "prd.json").exists() else _read_s3_json_fallback())


def _read_s3_json_fallback() -> str:
    raise FileNotFoundError("prd.json missing from workspace")


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _build_user_prompt(prd: dict, progress: str, repair: str) -> str:
    parts = [
        "# prd.json (the authoritative spec for this feature)",
        "",
        "```json",
        json.dumps(prd, indent=2),
        "```",
    ]
    if progress.strip():
        parts += ["", "# progress.txt (running notes from prior turns)", "", progress]
    if repair.strip():
        parts += ["", "# repair_context.md (issues raised by Validate or Review last turn — address these first)", "", repair]
    return "\n".join(parts)


def _system_prompt() -> str:
    impl = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    claude_md = ""
    repo_claude = WS_ROOT / "CLAUDE.md"
    if repo_claude.is_file():
        claude_md = repo_claude.read_text(encoding="utf-8")
    if claude_md:
        return f"{impl}\n\n# REPO CLAUDE.md\n\n{claude_md}"
    return impl


def _run_claude(user_prompt: str) -> dict:
    """Invoke claude -p and return the parsed JSON output.

    The Claude Code CLI (--output-format json) emits a JSON object on stdout
    with at least: {result, total_cost_usd?, usage?{input_tokens, output_tokens}, ...}.
    """
    env = {
        **os.environ,
        "ANTHROPIC_API_KEY": _get_api_key(),
    }
    cmd = [
        "node", CLAUDE_BIN,
        "-p", user_prompt,
        "--model", RALPH_MODEL,
        "--max-turns", str(RALPH_MAX_INNER_TURNS),
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--system-prompt", _system_prompt(),
    ]
    started = time.time()
    proc = subprocess.run(cmd, cwd=WS_ROOT, env=env, capture_output=True, text=True, timeout=780)
    elapsed = time.time() - started
    if proc.returncode != 0:
        raise RuntimeError(f"claude exit {proc.returncode}: stderr=\n{proc.stderr[-4000:]}\nstdout=\n{proc.stdout[-2000:]}")

    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude returned non-JSON: {proc.stdout[-2000:]}")
    out["_elapsed_s"] = elapsed
    return out


def _get_api_key() -> str:
    """Cached secrets read."""
    sm = boto3.client("secretsmanager")
    return sm.get_secret_value(SecretId="nova/factory/anthropic-api-key")["SecretString"]


def _scan_changed_paths() -> list[str]:
    """Anything in the working tree (relative to WS_ROOT) that git considers different from HEAD."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z"],
        cwd=WS_ROOT, capture_output=True, text=True, check=True,
    )
    paths: list[str] = []
    for line in out.stdout.split("\0"):
        if not line:
            continue
        # Format: "XY path" — first 2 chars are status codes
        path = line[3:].strip()
        if path:
            paths.append(path)
    return paths


def _enforce_allowlist(changed: list[str], repair_context_path: Path) -> tuple[list[str], list[str]]:
    allowed, denied = partition(changed)
    if denied:
        # Revert denied paths in the working tree
        for p in denied:
            full = WS_ROOT / p
            if full.is_file():
                full.unlink()
            # Restore from index (if it was tracked) or just leave deleted
            subprocess.run(["git", "checkout", "--", p], cwd=WS_ROOT, capture_output=True)

        # Append DENIED entries to repair_context.md
        existing = repair_context_path.read_text(encoding="utf-8") if repair_context_path.is_file() else ""
        new_lines = "\n".join(f"DENIED: {p} — outside RalphTurn sandbox (see .factory/implementer-system.md)" for p in denied)
        repair_context_path.write_text(
            (existing.rstrip() + "\n\n" if existing.strip() else "") + new_lines + "\n",
            encoding="utf-8",
        )
    return allowed, denied


def _commit_intra_turn() -> None:
    """Stage everything, commit once with a turn-scoped message. Idempotent if there's nothing staged."""
    subprocess.run(["git", "add", "-A"], cwd=WS_ROOT, check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=WS_ROOT)
    if result.returncode == 1:
        subprocess.run(["git", "commit", "-q", "-m", "factory(ralph): turn"], cwd=WS_ROOT, check=True)


def _detect_completion() -> bool:
    """Two-of-two completion signal per spec §2.3.2:
       - .factory/_DONE_ exists, OR
       - every story in prd.json has passes: true.
    """
    if (WS_ROOT / ".factory" / "_DONE_").exists():
        return True
    prd_path = WS_ROOT / "prd.json"
    if not prd_path.exists():
        return False
    try:
        prd = json.loads(prd_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    stories = prd.get("stories") or []
    return bool(stories) and all(s.get("passes") is True for s in stories)


def _upload_workspace(execution_id: str) -> None:
    prefix = f"{execution_id}/workspace/"
    # Tar .git first
    tarball = Path("/tmp/.git.tar.gz")
    if tarball.exists():
        tarball.unlink()
    pack_git(WS_ROOT, tarball)
    _s3.upload_file(str(tarball), BUCKET, f"{execution_id}/{GIT_TGZ}")

    # Upload everything else (skip .git itself — it's in the tarball)
    for f in WS_ROOT.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(WS_ROOT).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        _s3.upload_file(str(f), BUCKET, f"{prefix}{rel}")


def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]
    iter_num     = int(event.get("iter", 0))

    # 1+2: download, restore, read inputs
    _download_workspace(execution_id)

    # The Plan stage wrote prd.json to s3://.../<exec>/plan/prd.json — make sure it's
    # present in the workspace too. Copy if needed.
    plan_prd = f"{execution_id}/plan/prd.json"
    ws_prd_path = WS_ROOT / "prd.json"
    if not ws_prd_path.exists():
        local = Path("/tmp/prd.json")
        _s3.download_file(BUCKET, plan_prd, str(local))
        ws_prd_path.write_bytes(local.read_bytes())

    prd = json.loads(ws_prd_path.read_text(encoding="utf-8"))
    progress_path = WS_ROOT / "progress.txt"
    repair_path   = WS_ROOT / "repair_context.md"
    progress = _read_optional(progress_path)
    repair   = _read_optional(repair_path)

    # 3+4: build prompt, invoke Claude
    user_prompt = _build_user_prompt(prd, progress, repair)
    claude_out  = _run_claude(user_prompt)

    # 5: scan changes
    changed = _scan_changed_paths()

    # 6: allowlist
    allowed, denied = _enforce_allowlist(changed, repair_path)

    # Append turn entry to progress.txt
    new_progress = progress.rstrip()
    new_progress += f"\n\n## Turn {iter_num + 1}\n"
    new_progress += f"- elapsed: {claude_out.get('_elapsed_s', 0):.0f}s\n"
    new_progress += f"- changed (allowed): {sorted(allowed)}\n"
    if denied:
        new_progress += f"- changed (DENIED, surfaced as repair): {sorted(denied)}\n"
    progress_path.write_text(new_progress.lstrip() + "\n", encoding="utf-8")

    # 7: stage + commit + upload
    _commit_intra_turn()
    _upload_workspace(execution_id)

    # Repair file should NOT auto-clear; the next iteration's Validate/Review
    # writes a new repair_context.md if needed. But we DO clear it after a
    # turn that ran for the purpose of repair, so failures don't compound.
    # Strategy: if repair existed BEFORE this turn, delete it after upload.
    # Validate/Review will rewrite it if issues persist.
    if repair.strip():
        try:
            _s3.delete_object(Bucket=BUCKET, Key=f"{execution_id}/workspace/repair_context.md")
        except Exception:
            pass

    completion = _detect_completion()

    usage = claude_out.get("usage") or {}
    return {
        "iter":              iter_num + 1,
        "completion_signal": completion,
        "files_changed":     sorted(allowed),
        "files_denied":      sorted(denied),
        "input_tokens":      int(usage.get("input_tokens",  0)),
        "output_tokens":     int(usage.get("output_tokens", 0)),
        "claude_session_id": claude_out.get("session_id"),
    }
```

The handler is intentionally a single file (~250 lines). Easier to reason about than splitting. The pure-function pieces (`allowlist`, `git_io`) are isolated and tested.

- [ ] **Step 2: No tests for this file (integration-tested via smoke). Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/containers/ralph_turn/ralph_turn.py
git commit -m "factory(v2): add RalphTurn container handler (S3 round-trip + claude -p invocation)"
```

---

### Task 4: Write the RalphTurn Dockerfile + build script

**Files:**
- Create: `scripts/factory_lambdas/containers/ralph_turn/Dockerfile`
- Create: `scripts/factory_lambdas/containers/ralph_turn/build.sh`

- [ ] **Step 1: Write the Dockerfile.**

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

# Node 20 + Claude Code CLI
RUN dnf install -y nodejs npm git tar gzip && \
    npm install -g @anthropic-ai/claude-code --prefix /opt/node && \
    ln -sf /opt/node/lib/node_modules/@anthropic-ai/claude-code/cli.js /opt/bin/claude

# Lightweight Python deps the implementer's tests may need pre-installed
# (matches the validate_v2 image — keeps cold-start work down).
RUN pip install --no-cache-dir ruff mypy pytest pytest-asyncio httpx anyio alembic \
    fastapi pydantic pydantic-settings sqlalchemy asyncpg python-jose[cryptography] strenum

# .factory artifacts (system prompts, schema)
COPY ../../../../.factory/  ${LAMBDA_TASK_ROOT}/.factory/

# Container code
COPY allowlist.py    ${LAMBDA_TASK_ROOT}/
COPY git_io.py       ${LAMBDA_TASK_ROOT}/
COPY ralph_turn.py   ${LAMBDA_TASK_ROOT}/

CMD ["ralph_turn.handler"]
```

The `COPY ../../../../.factory/` is a relative path from the Dockerfile location — it needs the build context to be the repo root, not the Dockerfile dir. Build script handles that.

- [ ] **Step 2: Write `build.sh`.**

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../../../.." && pwd)

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
REPO="nova-factory-ralph-turn"
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}"

# Ensure ECR repo exists (Terraform creates this; this is a defensive fallback)
aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO"

# Build with repo root as context so we can COPY .factory/
docker build \
  -f "$HERE/Dockerfile" \
  -t "$ECR_REPO:latest" \
  "$REPO_ROOT"

docker push "$ECR_REPO:latest"
echo "Pushed $ECR_REPO:latest"
```

- [ ] **Step 3: Make build.sh executable.**

```bash
chmod +x /c/Claude/Nova/nova/scripts/factory_lambdas/containers/ralph_turn/build.sh
```

- [ ] **Step 4: Adjust the Dockerfile COPY paths.**

Since the build context is the repo root, COPY paths are repo-relative:

```dockerfile
COPY .factory/                                                      ${LAMBDA_TASK_ROOT}/.factory/
COPY scripts/factory_lambdas/containers/ralph_turn/allowlist.py     ${LAMBDA_TASK_ROOT}/
COPY scripts/factory_lambdas/containers/ralph_turn/git_io.py        ${LAMBDA_TASK_ROOT}/
COPY scripts/factory_lambdas/containers/ralph_turn/ralph_turn.py    ${LAMBDA_TASK_ROOT}/
```

Replace the previous COPY block in the Dockerfile with the above (drop the `../../../../.factory/` since the context is now the repo root).

- [ ] **Step 5: Commit (image not built/pushed yet — that's done in Task 7 after the ECR repo exists).**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/containers/ralph_turn/Dockerfile scripts/factory_lambdas/containers/ralph_turn/build.sh
git commit -m "factory(v2): add Dockerfile + build script for RalphTurn container"
```

---

### Task 5: Build the Validate-v2 container

Per spec §2.4: deterministic 6-step chain, no per-agent routing. Cribs from the existing `validate_workspace` image — the build pipeline is identical; the handler logic is simpler (one chain, not per-phase routing).

**Files:**
- Create: `scripts/factory_lambdas/containers/validate_v2/Dockerfile`
- Create: `scripts/factory_lambdas/containers/validate_v2/build.sh`
- Create: `scripts/factory_lambdas/containers/validate_v2/validate_v2.py`
- Create: `tests/factory/test_validate_v2.py`

- [ ] **Step 1: Write the Dockerfile.**

`scripts/factory_lambdas/containers/validate_v2/Dockerfile`:

```dockerfile
FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y unzip wget tar gzip git nodejs npm && \
    wget -q https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip && \
    unzip -q terraform_1.7.5_linux_amd64.zip && \
    mkdir -p /opt/bin && mv terraform /opt/bin/terraform && \
    rm terraform_1.7.5_linux_amd64.zip && \
    npm install -g typescript@5 --prefix /opt/node && \
    ln -sf /opt/node/lib/node_modules/typescript/bin/tsc /opt/bin/tsc

RUN pip install --no-cache-dir ruff mypy pytest pytest-asyncio httpx anyio alembic \
    fastapi pydantic pydantic-settings sqlalchemy asyncpg python-jose[cryptography] strenum

COPY scripts/factory_lambdas/common/                                ${LAMBDA_TASK_ROOT}/common/
COPY scripts/factory_lambdas/containers/validate_v2/validate_v2.py  ${LAMBDA_TASK_ROOT}/

CMD ["validate_v2.handler"]
```

- [ ] **Step 2: Write `build.sh`.**

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../../../.." && pwd)

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
REPO="nova-factory-validator"
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}"

aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "$REPO" --region "$REGION"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO"

docker build -f "$HERE/Dockerfile" -t "$ECR_REPO:latest" "$REPO_ROOT"
docker push "$ECR_REPO:latest"
echo "Pushed $ECR_REPO:latest"
```

```bash
chmod +x /c/Claude/Nova/nova/scripts/factory_lambdas/containers/validate_v2/build.sh
```

- [ ] **Step 3: Write the handler.**

`scripts/factory_lambdas/containers/validate_v2/validate_v2.py`:

```python
"""Validate-v2 — deterministic 6-step validation chain. Spec §2.4.

Runs in a Lambda container with ruff/mypy/pytest/terraform/tsc/alembic
pre-installed. Materializes the workspace from S3, runs each step, collects
issues, and writes issues.json back. No LLM, no per-agent routing.

Stops AT THE FIRST FAILING STEP — there's no value in running mypy if ruff
flagged 30 syntax errors. Caller (SFN) will route to ValidateRepair on any
non-empty issues array.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import boto3

BUCKET = os.environ["WORKSPACE_BUCKET"]
WS_ROOT = Path("/tmp/ws")

_s3 = boto3.client("s3")


def _materialize(execution_id: str) -> None:
    if WS_ROOT.exists():
        shutil.rmtree(WS_ROOT)
    WS_ROOT.mkdir(parents=True)
    prefix = f"{execution_id}/workspace/"
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix):]
            if not rel or rel.endswith("/") or rel == ".git.tar.gz":
                continue
            dest = WS_ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            _s3.download_file(BUCKET, key, str(dest))


def _issue(tool: str, file: str, line: int, output: str, hint: str = "") -> dict:
    return {"tool": tool, "file": file, "line": line, "output": output[:1000], "hint": hint}


def _run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _step_ruff() -> list[dict]:
    rc, out, err = _run(["ruff", "check", "--output-format=json", "."], WS_ROOT)
    if rc == 0:
        return []
    try:
        items = json.loads(out)
    except Exception:
        return [_issue("ruff", "?", 0, (out + err)[:1000], "ruff stdout unparseable")]
    return [_issue("ruff", i.get("filename", "?"), i.get("location", {}).get("row", 0),
                   f"{i.get('code')}: {i.get('message')}", i.get("fix", {}).get("message", "") if i.get("fix") else "")
            for i in items]


def _step_mypy() -> list[dict]:
    if not (WS_ROOT / "app").exists():
        return []
    rc, out, err = _run(["mypy", "--explicit-package-bases", "--no-color-output", "app/"], WS_ROOT)
    if rc == 0:
        return []
    issues: list[dict] = []
    for line in (out + err).splitlines():
        # "path:line: error: msg"
        parts = line.split(":", 3)
        if len(parts) < 4 or "error" not in parts[2]:
            continue
        try:
            ln = int(parts[1])
        except ValueError:
            ln = 0
        issues.append(_issue("mypy", parts[0], ln, parts[3].strip(), ""))
    if not issues and rc != 0:
        issues.append(_issue("mypy", "?", 0, (out + err)[:1000], ""))
    return issues


def _step_pytest() -> list[dict]:
    if not (WS_ROOT / "tests").exists():
        return [_issue("pytest", "tests/", 0, "tests/ directory missing", "RalphTurn must add tests")]
    # Install repo + tests deps if requirements.txt(s) present
    for req in [WS_ROOT / "requirements.txt", WS_ROOT / "tests" / "requirements.txt"]:
        if req.is_file():
            _run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], WS_ROOT)
    rc, out, err = _run(["pytest", "tests/", "-x", "-q", "--tb=short"], WS_ROOT)
    if rc == 0:
        return []
    return [_issue("pytest", "tests/", 0, (out + err)[-2000:], "Failing test(s); RalphTurn must fix before re-validation")]


def _step_terraform() -> list[dict]:
    tf_dirs = sorted({p.parent for p in WS_ROOT.rglob("*.tf")})
    issues: list[dict] = []
    for d in tf_dirs:
        if d.is_relative_to(WS_ROOT / "infra" / "factory"):
            continue  # factory infra is sandboxed and not editable by Ralph
        rc, out, err = _run(["terraform", "fmt", "-check"], d)
        if rc != 0:
            issues.append(_issue("terraform fmt", str(d.relative_to(WS_ROOT)), 0, (out+err)[:1000], "Run `terraform fmt`"))
        rc, out, err = _run(["terraform", "init", "-backend=false", "-input=false"], d)
        if rc != 0:
            issues.append(_issue("terraform init", str(d.relative_to(WS_ROOT)), 0, (out+err)[-1000:], ""))
            continue
        rc, out, err = _run(["terraform", "validate", "-no-color"], d)
        if rc != 0:
            issues.append(_issue("terraform validate", str(d.relative_to(WS_ROOT)), 0, (out+err)[-1000:], ""))
    return issues


def _step_tsc() -> list[dict]:
    fe = WS_ROOT / "frontend"
    if not fe.is_dir() or not (fe / "tsconfig.json").is_file():
        return []
    rc, out, err = _run(["tsc", "--noEmit", "-p", str(fe / "tsconfig.json")], WS_ROOT)
    if rc == 0:
        return []
    return [_issue("tsc", "frontend/", 0, (out+err)[-2000:], "")]


def _step_alembic() -> list[dict]:
    mig = WS_ROOT / "app" / "db" / "migrations"
    if not mig.is_dir():
        return []
    rc, out, err = _run(["alembic", "check"], WS_ROOT)
    if rc == 0:
        return []
    return [_issue("alembic", "app/db/migrations/", 0, (out+err)[-1000:], "Migration check failed")]


def handler(event, _ctx):
    execution_id = event["execution_id"]
    _materialize(execution_id)

    issues: list[dict] = []
    for step in (_step_ruff, _step_mypy, _step_pytest, _step_terraform, _step_tsc, _step_alembic):
        step_issues = step()
        issues.extend(step_issues)
        if step_issues:
            break  # short-circuit on first failure

    passed = len(issues) == 0
    payload = {"passed": passed, "issues": issues}

    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/validate/issues.json",
        Body=json.dumps(payload, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    if not passed:
        # Compose repair_context.md so the next RalphTurn sees structured guidance
        body = "# Validate failures (must address before re-validation)\n\n"
        for it in issues:
            body += f"## {it['tool']} — {it['file']}:{it['line']}\n\n{it['output']}\n\n"
            if it.get("hint"):
                body += f"_Hint:_ {it['hint']}\n\n"
        _s3.put_object(
            Bucket=BUCKET,
            Key=f"{execution_id}/workspace/repair_context.md",
            Body=body.encode("utf-8"),
            ContentType="text/markdown",
        )

    return payload
```

- [ ] **Step 4: Write a smoke test for validate_v2.**

`tests/factory/test_validate_v2.py`:

```python
"""Smoke test for validate_v2 — runs the steps against a synthetic broken
workspace materialized in /tmp. We test the step functions directly (no S3)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas" / "containers" / "validate_v2"))

import validate_v2  # noqa: E402


def test_ruff_flags_syntax_error(tmp_path, monkeypatch):
    monkeypatch.setattr(validate_v2, "WS_ROOT", tmp_path)
    (tmp_path / "broken.py").write_text("def bad(\n")  # syntax error / unclosed paren
    issues = validate_v2._step_ruff()
    assert any(i["tool"] == "ruff" for i in issues)


def test_clean_workspace_passes_ruff(tmp_path, monkeypatch):
    monkeypatch.setattr(validate_v2, "WS_ROOT", tmp_path)
    (tmp_path / "ok.py").write_text("def good():\n    return 1\n")
    issues = validate_v2._step_ruff()
    assert issues == []
```

This test requires `ruff` installed locally — `tests/requirements.txt` already pins ruff via the wider tooling. If ruff isn't on the dev machine, install: `pip install ruff`.

- [ ] **Step 5: Run tests.**

```bash
cd /c/Claude/Nova/nova
pip install ruff   # if needed
pytest tests/factory/test_validate_v2.py -v
```
Expected: 2 tests pass.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/containers/validate_v2/ tests/factory/test_validate_v2.py
git commit -m "factory(v2): add validate_v2 container (deterministic 6-step chain)"
```

---

### Task 6: Build the Review Lambda (TDD)

Per spec §2.5: a single Sonnet call with `prd.json` + `git diff` + `CLAUDE.md` + the reviewer system prompt. Output is structured JSON validated against an inline schema. Issues drive RepairLoop in the SFN.

**Files:**
- Create: `scripts/factory_lambdas/handlers/review.py`
- Create: `tests/factory/test_review.py`
- Create: `tests/factory/fixtures/sonnet_review_clean.json`
- Create: `tests/factory/fixtures/sonnet_review_tenancy_blocker.json`

- [ ] **Step 1: Write the response fixtures.**

`tests/factory/fixtures/sonnet_review_clean.json`:

```json
{ "passed": true, "blockers": [], "warnings": [] }
```

`tests/factory/fixtures/sonnet_review_tenancy_blocker.json`:

```json
{
  "passed": false,
  "blockers": [
    {
      "category": "tenancy",
      "file":     "app/repositories/engagement.py",
      "line":     42,
      "description": "list_engagements does not filter by buyer_org_id",
      "fix":      "Add WHERE buyer_org_id = :buyer_org_id to the query"
    }
  ],
  "warnings": []
}
```

- [ ] **Step 2: Write tests.**

`tests/factory/test_review.py`:

```python
"""Tests for the Review Lambda."""

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
        self.objects = {}
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        body = kwargs["Body"]
        self.objects[kwargs["Key"]] = body if isinstance(body, bytes) else body.encode("utf-8")

    def get_object(self, **kwargs):
        body = self.objects[kwargs["Key"]]
        return {"Body": MagicMock(read=lambda: body)}


def _seed(fake: FakeS3, execution_id: str, *, prd: dict, diff: str):
    fake.objects[f"{execution_id}/plan/prd.json"]    = json.dumps(prd).encode("utf-8")
    fake.objects[f"{execution_id}/workspace/diff.patch"] = diff.encode("utf-8")


def test_clean_review_passes_through():
    from handlers import review  # type: ignore

    fake = FakeS3()
    _seed(fake, "exec-clean",
          prd={"feature_id": "x", "title": "t", "narrative_md": "n",
               "stories": [{"id": "s1", "description": "d", "acceptance_criteria": ["a"], "passes": True}],
               "scope": {"touches_db": False, "touches_frontend": False, "touches_infra": False, "files_in_scope": []},
               "hard_blockers": [], "risk_flags": [], "suggested_split": []},
          diff="--- a/app/foo.py\n+++ b/app/foo.py\n@@\n+def foo(): return 1\n")
    response = json.loads((FIXTURES / "sonnet_review_clean.json").read_text())

    with patch.object(review, "_s3", fake), \
         patch.object(review, "messages_create", return_value={
             "text": json.dumps(response), "input_tokens": 1000, "output_tokens": 50,
         }):
        result = review.handler({"execution_id": "exec-clean", "feature_id": "x"}, None)

    assert result["passed"] is True
    written = json.loads(fake.objects["exec-clean/review/blockers.json"])
    assert written == response


def test_tenancy_blocker_propagates():
    from handlers import review  # type: ignore

    fake = FakeS3()
    _seed(fake, "exec-bad",
          prd={"feature_id": "x", "title": "t", "narrative_md": "n",
               "stories": [{"id": "s1", "description": "d", "acceptance_criteria": ["a"], "passes": True}],
               "scope": {"touches_db": True, "touches_frontend": False, "touches_infra": False, "files_in_scope": []},
               "hard_blockers": [], "risk_flags": [], "suggested_split": []},
          diff="--- a/app/repositories/engagement.py\n@@\n+def list_engagements(): return query.all()\n")
    response = json.loads((FIXTURES / "sonnet_review_tenancy_blocker.json").read_text())

    with patch.object(review, "_s3", fake), \
         patch.object(review, "messages_create", return_value={
             "text": json.dumps(response), "input_tokens": 1000, "output_tokens": 80,
         }):
        result = review.handler({"execution_id": "exec-bad", "feature_id": "x"}, None)

    assert result["passed"] is False
    assert any(b["category"] == "tenancy" for b in result["blockers"])
    # Repair context written
    assert "exec-bad/workspace/repair_context.md" in fake.objects
    rc = fake.objects["exec-bad/workspace/repair_context.md"].decode("utf-8")
    assert "tenancy" in rc.lower()


def test_invalid_review_output_raises():
    from handlers import review  # type: ignore

    fake = FakeS3()
    _seed(fake, "exec-bad-out", prd={
        "feature_id": "x", "title": "t", "narrative_md": "n",
        "stories": [{"id": "s1", "description": "d", "acceptance_criteria": ["a"], "passes": True}],
        "scope": {"touches_db": False, "touches_frontend": False, "touches_infra": False, "files_in_scope": []},
        "hard_blockers": [], "risk_flags": [], "suggested_split": []
    }, diff="--- a/x\n+++ b/x\n")
    bad = {"some": "shape", "not": "review"}

    with patch.object(review, "_s3", fake), \
         patch.object(review, "messages_create", return_value={
             "text": json.dumps(bad), "input_tokens": 100, "output_tokens": 30,
         }):
        try:
            review.handler({"execution_id": "exec-bad-out", "feature_id": "x"}, None)
        except RuntimeError as e:
            assert "review" in str(e).lower() or "schema" in str(e).lower()
            return
    raise AssertionError("expected RuntimeError on invalid review JSON")
```

- [ ] **Step 3: Run, verify fail.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_review.py -v
```
Expected: ImportError on `handlers.review`.

- [ ] **Step 4: Write `handlers/review.py`.**

```python
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

# System prompt is shipped in the Lambda zip at .factory/reviewer-system.md
SYSTEM_PROMPT_PATH_CANDIDATES = [
    Path("/var/task/.factory/reviewer-system.md"),
    Path(__file__).resolve().parents[3] / ".factory" / "reviewer-system.md",
]


def _system_prompt() -> str:
    for p in SYSTEM_PROMPT_PATH_CANDIDATES:
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise RuntimeError("reviewer-system.md not found")


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
    diff = _read(execution_id, "workspace/diff.patch")
    if len(diff.encode("utf-8")) > DIFF_CAP_BYTES:
        diff = diff[:DIFF_CAP_BYTES] + "\n<diff truncated at 50KB>"

    user_prompt = (
        f"# prd.json\n\n```json\n{json.dumps(prd, indent=2)}\n```\n\n"
        f"# git_diff (main..HEAD)\n\n```diff\n{diff}\n```\n"
    )

    resp = messages_create(
        model=REVIEWER_MODEL,
        system=_system_prompt(),
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
```

- [ ] **Step 5: Run tests, verify pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/test_review.py -v
```
Expected: 3 tests pass.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/review.py tests/factory/test_review.py tests/factory/fixtures/sonnet_review_*.json
git commit -m "factory(v2): add Review Lambda (single Sonnet call -> blockers/warnings JSON)"
```

---

### Task 7: Add the tightened RalphTurn IAM role and ECR repos

Spec §4.3 layer 3: RalphTurn gets a dedicated IAM role scoped to its execution prefix only.

**Files:**
- Create: `infra/factory/iam-ralph.tf`
- Create: `infra/factory/lambdas-v2-images.tf`

- [ ] **Step 1: Add `iam-ralph.tf`.**

```hcl
# Tightened IAM role for RalphTurn — scoped to its own execution S3 prefix
# and Anthropic API key only. Spec §4.3 layer 3.

resource "aws_iam_role" "ralph_turn_exec" {
  name = "${local.name_prefix}-ralph-turn-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action = "sts:AssumeRole",
    }]
  })
  tags = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_iam_role_policy_attachment" "ralph_turn_basic" {
  role       = aws_iam_role.ralph_turn_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "ralph_turn_xray" {
  role       = aws_iam_role.ralph_turn_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy" "ralph_turn_inline" {
  role = aws_iam_role.ralph_turn_exec.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        # S3: read+write+delete inside the workspaces bucket only.
        # The bucket itself is already scoped per-execution by SFN execution name
        # in the key — but we keep the IAM policy at the bucket level since each
        # invocation has a different prefix and we don't issue per-execution roles.
        Effect = "Allow",
        Action = [
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:ListBucket"
        ],
        Resource = [
          aws_s3_bucket.workspaces.arn,
          "${aws_s3_bucket.workspaces.arn}/*",
        ]
      },
      {
        # Secrets Manager: ONLY the Anthropic API key.
        Effect = "Allow",
        Action = ["secretsmanager:GetSecretValue"],
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:nova/factory/anthropic-api-key*"
      }
    ]
  })
}
```

- [ ] **Step 2: Add `lambdas-v2-images.tf`.**

```hcl
# Container Lambdas: ralph_turn (RalphTurn) and validate_v2 (Validate-v2)

resource "aws_ecr_repository" "ralph_turn" {
  name                 = "nova-factory-ralph-turn"
  image_tag_mutability = "MUTABLE"
  tags                 = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_ecr_repository" "validate_v2" {
  name                 = "nova-factory-validator"
  image_tag_mutability = "MUTABLE"
  tags                 = merge(local.common_tags, { Generation = "v2" })
}

# Hash-triggered builds
locals {
  ralph_turn_src_hash = sha256(join("", [
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/Dockerfile"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/ralph_turn.py"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/allowlist.py"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/git_io.py"),
    filemd5("${path.module}/../../.factory/implementer-system.md"),
  ]))
  validate_v2_src_hash = sha256(join("", [
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/validate_v2/Dockerfile"),
    filemd5("${path.module}/../../scripts/factory_lambdas/containers/validate_v2/validate_v2.py"),
  ]))
}

resource "null_resource" "build_ralph_turn" {
  triggers = { src_hash = local.ralph_turn_src_hash }
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "AWS_REGION=${var.aws_region} bash ${path.module}/../../scripts/factory_lambdas/containers/ralph_turn/build.sh"
  }
  depends_on = [aws_ecr_repository.ralph_turn]
}

resource "null_resource" "build_validate_v2" {
  triggers = { src_hash = local.validate_v2_src_hash }
  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "AWS_REGION=${var.aws_region} bash ${path.module}/../../scripts/factory_lambdas/containers/validate_v2/build.sh"
  }
  depends_on = [aws_ecr_repository.validate_v2]
}

resource "aws_lambda_function" "ralph_turn" {
  function_name = "${local.name_prefix}-ralph-turn"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.ralph_turn.repository_url}:latest"
  role          = aws_iam_role.ralph_turn_exec.arn
  timeout       = 840   # 14 minutes (1-min headroom under Lambda's 15-min cap)
  memory_size   = 3008
  ephemeral_storage { size = 10240 }
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
      RALPH_MODEL      = "claude-sonnet-4-6"
    }
  }
  depends_on = [null_resource.build_ralph_turn]
  tags       = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_lambda_function" "validate_v2" {
  function_name = "${local.name_prefix}-validate-v2"
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.validate_v2.repository_url}:latest"
  role          = aws_iam_role.lambda_exec.arn  # uses shared role; deterministic, no API keys
  timeout       = 600
  memory_size   = 3008
  ephemeral_storage { size = 4096 }
  tracing_config { mode = "Active" }
  environment {
    variables = {
      WORKSPACE_BUCKET = aws_s3_bucket.workspaces.bucket
    }
  }
  depends_on = [null_resource.build_validate_v2]
  tags       = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_cloudwatch_log_group" "ralph_turn"  { name = "/aws/lambda/${local.name_prefix}-ralph-turn"  retention_in_days = 30 }
resource "aws_cloudwatch_log_group" "validate_v2" { name = "/aws/lambda/${local.name_prefix}-validate-v2" retention_in_days = 30 }
```

- [ ] **Step 3: Apply (this WILL build images — takes a few minutes).**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 2 ECR repos + 2 builds (`null_resource`s) + 2 Lambdas + 2 log groups + 1 IAM role + 2 IAM attachments + 1 inline policy.

If a docker build fails because the base image isn't pulled, run `docker pull public.ecr.aws/lambda/python:3.12` first and re-apply.

- [ ] **Step 4: Smoke-invoke each container Lambda.**

```bash
aws lambda invoke --function-name nova-factory-validate-v2 \
  --payload '{"execution_id":"smoke-import"}' \
  --cli-binary-format raw-in-base64-out /tmp/v.json; cat /tmp/v.json
```
Expected: errors at the S3 download (no such prefix) — that's fine, confirms the import + handler works.

```bash
aws lambda invoke --function-name nova-factory-ralph-turn \
  --payload '{"feature_id":"x","execution_id":"smoke-import","iter":0}' \
  --cli-binary-format raw-in-base64-out /tmp/r.json; cat /tmp/r.json
```
Expected: errors at S3 download — confirms import OK.

- [ ] **Step 5: Add the Review Lambda to `lambdas-v2.tf`.**

Edit `infra/factory/lambdas-v2.tf` — extend the `handlers_v2` map:

```hcl
locals {
  handlers_v2 = {
    load_feature = { timeout = 60,  memory = 512  }
    plan         = { timeout = 120, memory = 1024 }
    mark_blocked = { timeout = 30,  memory = 256  }
    review       = { timeout = 180, memory = 1024 }
  }
}
```

```bash
cd /c/Claude/Nova/nova/scripts/factory_lambdas
bash build.sh   # rebuild zips so review.zip exists
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 1 new Lambda (`review`) + 1 log group.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add infra/factory/iam-ralph.tf infra/factory/lambdas-v2-images.tf infra/factory/lambdas-v2.tf
git commit -m "infra(factory v2): deploy ralph_turn + validate_v2 containers and Review Lambda; tightened IAM"
```

---

### Task 8: Update CommitAndPush v2 — write `.factory/last-run/` files

Spec §2.6: CommitAndPush writes `.factory/last-run/{prd.json,review.json,progress.txt}` to the workspace before `git add -A`. The Phase 4 postdeploy probe reads them from the merged commit.

**Files:**
- Modify: `scripts/factory_lambdas/handlers/commit_and_push.py`

- [ ] **Step 1: Read current commit_and_push.py.**

```bash
cat /c/Claude/Nova/nova/scripts/factory_lambdas/handlers/commit_and_push.py
```
Expected: an existing handler that materializes the workspace, runs `git add -A` + `git commit` + `git push`, and creates a PR.

- [ ] **Step 2: Add `.factory/last-run/` writes before `git add -A`.**

In `commit_and_push.py`, before the existing `subprocess.run(["git", "add", "-A"], ...)` call, insert a block that:
1. Reads `<execution_id>/plan/prd.json` from S3, writes to `<workspace>/.factory/last-run/prd.json`.
2. Reads `<execution_id>/review/blockers.json` from S3, writes to `<workspace>/.factory/last-run/review.json` (only if it exists — non-fatal if review hasn't been run yet for some reason).
3. Reads `<workspace>/progress.txt` (already in workspace from Ralph turns), copies to `<workspace>/.factory/last-run/progress.txt`.

```python
# --- new block: write .factory/last-run/ artifacts for the postdeploy probe ---
last_run_dir = Path(workspace_root) / ".factory" / "last-run"
last_run_dir.mkdir(parents=True, exist_ok=True)

# prd.json — required
prd_obj = _s3.get_object(Bucket=BUCKET, Key=f"{execution_id}/plan/prd.json")
(last_run_dir / "prd.json").write_bytes(prd_obj["Body"].read())

# review.json — best-effort
try:
    rev_obj = _s3.get_object(Bucket=BUCKET, Key=f"{execution_id}/review/blockers.json")
    (last_run_dir / "review.json").write_bytes(rev_obj["Body"].read())
except _s3.exceptions.ClientError:
    pass

# progress.txt — copy from workspace if present
prog_path = Path(workspace_root) / "progress.txt"
if prog_path.is_file():
    (last_run_dir / "progress.txt").write_bytes(prog_path.read_bytes())
# --- end new block ---
```

Adjust variable names (`workspace_root`, `BUCKET`, `_s3`) to match the existing handler's locals.

- [ ] **Step 3: Update commit message format per spec §2.6.**

The commit message is now deterministic. Replace whatever the existing handler builds with:

```python
title = prd_payload.get("title", "feature update")
narrative = prd_payload.get("narrative_md", "")[:4000]
commit_msg = (
    f"feat(factory): {title}\n\n"
    f"{narrative}\n\n"
    f"factory-execution: {execution_id}\n"
)
```

- [ ] **Step 4: Rebuild zips and verify.**

```bash
cd /c/Claude/Nova/nova/scripts/factory_lambdas
bash build.sh
ls -la dist/commit_and_push.zip   # confirm rebuilt
```

- [ ] **Step 5: Commit.**

```bash
cd /c/Claude/Nova/nova
git add scripts/factory_lambdas/handlers/commit_and_push.py
git commit -m "factory(v2): commit_and_push writes .factory/last-run/ for postdeploy probe + deterministic commit message"
```

---

### Task 9: Wire the full v2 state machine

Spec §1 + §2.3.1: replace the Phase 2 stub with the full pipeline. The state machine becomes the heart of the factory.

**Files:**
- Create: `infra/factory/state-machine-v2.json.tpl`
- Create: `infra/factory/state-machine-v2.tf`
- Delete: `infra/factory/state-machine-v2-planonly.tf`
- Delete: `infra/factory/state-machine-v2-planonly.json.tpl`

- [ ] **Step 1: Write the full SFN definition.**

`infra/factory/state-machine-v2.json.tpl`:

```json
{
  "Comment": "Nova factory v2 — full pipeline. Spec §1 + §2.3.1.",
  "TimeoutSeconds": 7200,
  "StartAt": "AcquireLock",
  "States": {
    "AcquireLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-acquire-lock",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.lock",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "FailLocked"}],
      "Next": "MarkInProgress"
    },

    "MarkInProgress": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {"feature_id.$": "$.feature_id", "status": "Building"}
      },
      "ResultPath": null,
      "Next": "LoadFeature"
    },

    "LoadFeature": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-load-feature",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
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
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.plan",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "PlanGate"
    },

    "PlanGate": {
      "Type": "Choice",
      "Choices": [{"Variable": "$.plan.Payload.blocked", "BooleanEquals": true, "Next": "MarkBlocked"}],
      "Default": "LoopInit"
    },

    "MarkBlocked": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-mark-blocked",
        "Payload": {
          "feature_id.$":      "$.feature_id",
          "hard_blockers.$":   "$.plan.Payload.hard_blockers",
          "suggested_split.$": "$.plan.Payload.suggested_split"
        }
      },
      "ResultPath": null,
      "Next": "ReleaseLock"
    },

    "LoopInit": {
      "Type": "Pass",
      "Parameters": {
        "iter":                  0,
        "input_tokens":          0,
        "output_tokens":         0,
        "completion_signal":     false,
        "validate_repair_count": 0,
        "review_repair_count":   0
      },
      "ResultPath": "$.loop",
      "Next": "LoopChoice"
    },

    "LoopChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.loop.completion_signal", "BooleanEquals": true,        "Next": "Validate"},
        {"Variable": "$.loop.iter",              "NumericGreaterThanEquals": 6, "Next": "MarkBudgetExceeded"},
        {"Variable": "$.loop.input_tokens",      "NumericGreaterThanEquals": 2000000, "Next": "MarkBudgetExceeded"}
      ],
      "Default": "RalphTurn"
    },

    "RalphTurn": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-ralph-turn",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name",
          "iter.$":         "$.loop.iter"
        }
      },
      "ResultPath": "$.turn",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "LoopBump"
    },

    "LoopBump": {
      "Type": "Pass",
      "Parameters": {
        "iter.$":                "$.turn.Payload.iter",
        "input_tokens.$":        "States.MathAdd($.loop.input_tokens,  $.turn.Payload.input_tokens)",
        "output_tokens.$":       "States.MathAdd($.loop.output_tokens, $.turn.Payload.output_tokens)",
        "completion_signal.$":   "$.turn.Payload.completion_signal",
        "validate_repair_count.$": "$.loop.validate_repair_count",
        "review_repair_count.$":   "$.loop.review_repair_count"
      },
      "ResultPath": "$.loop",
      "Next": "LoopChoice"
    },

    "Validate": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-validate-v2",
        "Payload": {"execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.validate",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateChoice"
    },

    "ValidateChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.validate.Payload.passed", "BooleanEquals": true, "Next": "Review"},
        {"Variable": "$.loop.validate_repair_count", "NumericGreaterThanEquals": 2, "Next": "MarkValidateFailed"}
      ],
      "Default": "ValidateRepairTurn"
    },

    "ValidateRepairTurn": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-ralph-turn",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name",
          "iter.$":         "$.loop.iter"
        }
      },
      "ResultPath": "$.turn",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ValidateRepairBump"
    },

    "ValidateRepairBump": {
      "Type": "Pass",
      "Parameters": {
        "iter.$":                  "$.turn.Payload.iter",
        "input_tokens.$":          "States.MathAdd($.loop.input_tokens,  $.turn.Payload.input_tokens)",
        "output_tokens.$":         "States.MathAdd($.loop.output_tokens, $.turn.Payload.output_tokens)",
        "completion_signal.$":     "$.turn.Payload.completion_signal",
        "validate_repair_count.$": "States.MathAdd($.loop.validate_repair_count, 1)",
        "review_repair_count.$":   "$.loop.review_repair_count"
      },
      "ResultPath": "$.loop",
      "Next": "Validate"
    },

    "Review": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-review",
        "Payload": {"execution_id.$": "$$.Execution.Name", "feature_id.$": "$.feature_id"}
      },
      "ResultPath": "$.review",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ReviewChoice"
    },

    "ReviewChoice": {
      "Type": "Choice",
      "Choices": [
        {"Variable": "$.review.Payload.passed", "BooleanEquals": true, "Next": "CommitAndPush"},
        {"Variable": "$.loop.review_repair_count", "NumericGreaterThanEquals": 2, "Next": "MarkReviewFailed"}
      ],
      "Default": "ReviewRepairTurn"
    },

    "ReviewRepairTurn": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-ralph-turn",
        "Payload": {
          "feature_id.$":   "$.feature_id",
          "execution_id.$": "$$.Execution.Name",
          "iter.$":         "$.loop.iter"
        }
      },
      "ResultPath": "$.turn",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "ReviewRepairBump"
    },

    "ReviewRepairBump": {
      "Type": "Pass",
      "Parameters": {
        "iter.$":                  "$.turn.Payload.iter",
        "input_tokens.$":          "States.MathAdd($.loop.input_tokens,  $.turn.Payload.input_tokens)",
        "output_tokens.$":         "States.MathAdd($.loop.output_tokens, $.turn.Payload.output_tokens)",
        "completion_signal.$":     "$.turn.Payload.completion_signal",
        "validate_repair_count.$": "$.loop.validate_repair_count",
        "review_repair_count.$":   "States.MathAdd($.loop.review_repair_count, 1)"
      },
      "ResultPath": "$.loop",
      "Next": "Validate"
    },

    "CommitAndPush": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-commit-and-push",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": "$.commit",
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 10, "MaxAttempts": 2, "BackoffRate": 2.0}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "WaitForQualityGates"
    },

    "WaitForQualityGates": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke.waitForTaskToken",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-trigger-quality-gates",
        "Payload": {
          "branch.$":     "$.commit.Payload.branch",
          "pr_number.$":  "$.commit.Payload.pr_number",
          "task_token.$": "$$.Task.Token"
        }
      },
      "TimeoutSeconds": 5400,
      "ResultPath": "$.quality",
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "MarkFailedAndRelease"}],
      "Next": "MarkDone"
    },

    "MarkDone": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-update-notion",
        "Payload": {
          "feature_id.$": "$.feature_id",
          "status": "Done",
          "extras": {"pr_url.$": "$.commit.Payload.pr_url"}
        }
      },
      "ResultPath": null,
      "Next": "ReleaseLock"
    },

    "ReleaseLock": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "arn:aws:lambda:${region}:${account_id}:function:${name_prefix}-release-lock",
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": null,
      "End": true
    },

    "MarkValidateFailed": {
      "Type": "Pass",
      "Parameters": {"reason": "validate_failed_after_repairs"},
      "ResultPath": "$.error",
      "Next": "MarkFailedAndRelease"
    },

    "MarkReviewFailed": {
      "Type": "Pass",
      "Parameters": {"reason": "review_failed_after_repairs"},
      "ResultPath": "$.error",
      "Next": "MarkFailedAndRelease"
    },

    "MarkBudgetExceeded": {
      "Type": "Pass",
      "Parameters": {"reason": "ralph_budget_exceeded"},
      "ResultPath": "$.error",
      "Next": "MarkFailedAndRelease"
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
        "Payload": {"feature_id.$": "$.feature_id", "execution_id.$": "$$.Execution.Name"}
      },
      "ResultPath": null,
      "Next": "FailState"
    },

    "FailLocked": {"Type": "Pass", "Result": {"reason": "locked_by_another_execution"}, "Next": "FailState"},
    "FailState":  {"Type": "Fail", "Error": "FactoryV2Failed"}
  }
}
```

- [ ] **Step 2: Add `state-machine-v2.tf`.**

```hcl
resource "aws_cloudwatch_log_group" "sfn_v2" {
  name              = "/aws/states/nova-factory-v2"
  retention_in_days = 30
  tags              = merge(local.common_tags, { Generation = "v2" })
}

resource "aws_sfn_state_machine" "v2" {
  name     = "nova-factory-v2"
  role_arn = aws_iam_role.sfn_exec.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine-v2.json.tpl", {
    region      = var.aws_region
    account_id  = data.aws_caller_identity.current.account_id
    name_prefix = local.name_prefix
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_v2.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }
  tracing_configuration { enabled = true }
  tags                  = merge(local.common_tags, { Generation = "v2" })

  depends_on = [
    aws_lambda_function.handlers_v2,
    aws_lambda_function.ralph_turn,
    aws_lambda_function.validate_v2,
  ]
}

output "v2_state_machine_arn" {
  value = aws_sfn_state_machine.v2.arn
}
```

- [ ] **Step 3: Delete the Phase 2 stub files.**

```bash
cd /c/Claude/Nova/nova
rm infra/factory/state-machine-v2-planonly.tf infra/factory/state-machine-v2-planonly.json.tpl
```

- [ ] **Step 4: Update the smoke runner to use the new SFN ARN output.**

```bash
sed -i 's/v2_planonly_state_machine_arn/v2_state_machine_arn/' /c/Claude/Nova/nova/scripts/factory_smoke_v2.sh
```

- [ ] **Step 5: Apply.**

```bash
cd /c/Claude/Nova/nova/infra/factory
terraform apply -auto-approve
```
Expected: 1 destroy (the planonly SFN), 1 destroy (its log group), 1 add (`nova-factory-v2` SFN), 1 add (its log group). The output `v2_planonly_state_machine_arn` is removed; `v2_state_machine_arn` is added.

- [ ] **Step 6: Commit.**

```bash
cd /c/Claude/Nova/nova
git add -A   # captures the deletes
git commit -m "infra(factory v2): replace stub SFN with full nova-factory-v2 (RalphLoop + Validate + Review + Ship tail)"
```

---

### Task 10: Smoke run — trivial end-to-end

Should: AcquireLock → MarkInProgress → LoadFeature → Plan → LoopInit → RalphTurn (1× or 2×) → completion → Validate → (pass) → Review → (pass) → CommitAndPush → WaitForQualityGates → MarkDone → ReleaseLock. Notion ends `Done`. PR is merged on `main`.

- [ ] **Step 1: Run.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh trivial
```
Expected: `OK — execution succeeded as expected`. The Notion page should end at status `Done` (not `Building`); a PR has been opened, quality-gates have passed, and the PR has been auto-merged.

- [ ] **Step 2: Inspect the SFN execution if anything is unexpected.**

```bash
EXEC_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --max-results 1 --query 'executions[0].executionArn' --output text)
aws stepfunctions get-execution-history --execution-arn "$EXEC_ARN" --reverse-order --max-results 30
```

Common first-run issues:
- **RalphTurn timeout**: a single turn took > 14 min. Reduce `--max-turns` from 30 to 15 in `ralph_turn.py`. The Ralph cap of 6 outer turns × ~10–14 min each is the design budget; one turn shouldn't push 14 min unless something is degenerate.
- **Validate fails on missing requirements.txt**: the trivial fixture's spec doesn't mention deps. The factory's pytest step `pip install -r requirements.txt` should still succeed because the existing repo's `requirements.txt` exists. If it fails, check the workspace upload — the workspace tree should mirror the repo at the time RalphTurn ran.
- **Review false-positive blocker**: trivial fixture might trigger a tenancy false-positive because the prompt is generic. If so, examine the blocker in `s3://.../<exec>/review/blockers.json`. If it's clearly wrong, tighten the reviewer prompt (`.factory/reviewer-system.md`) and re-run.

- [ ] **Step 3: Verify Notion + GitHub reflect Done.**

```bash
# Status from Notion
NOTION_API_KEY=$(grep NOTION_API_KEY /c/Claude/Nova/nova/.env | cut -d= -f2)
FEATURE_ID=<from previous output>
curl -s -H "Authorization: Bearer $NOTION_API_KEY" -H "Notion-Version: 2022-06-28" \
  "https://api.notion.com/v1/pages/$FEATURE_ID" \
  | jq -r '.properties.Status.status.name // .properties.Status.select.name'
```
Expected: `Done`.

```bash
# Latest merge on main
git -C /c/Claude/Nova/nova fetch origin
git -C /c/Claude/Nova/nova log origin/main --oneline -3
```
Expected: top commit is `feat(factory): Factory v2 smoke — version v2 endpoint` (or similar) with a `factory-execution: smoke-trivial-...` trailer.

---

### Task 11: Smoke run — medium end-to-end

- [ ] **Step 1: Run.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh medium
```
Expected: `OK`. Notion ends `Done`. PR merged.

- [ ] **Step 2: Sanity-check token spend.**

```bash
EXEC_ARN=$(aws stepfunctions list-executions \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-v2 \
  --max-results 1 --query 'executions[0].executionArn' --output text)
aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query 'output' --output text | jq '.loop'
```
Expected: `iter` ≤ 6, `input_tokens` ≪ 2,000,000, `output_tokens` ≪ 200,000. Per spec §5.1, medium should land near $0.61–$1.38 in Sonnet costs.

---

### Task 12: Smoke run — oversized still blocks at Plan

- [ ] **Step 1: Run.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh oversized
```
Expected: `OK — feature was blocked at Plan as expected`. The pipeline routes Plan → MarkBlocked → ReleaseLock and never enters RalphLoop. Cost should be ~$0.013 (one Haiku call only).

- [ ] **Step 2: Verify the PR was NOT created.**

The oversized fixture should NOT produce a feature branch.
```bash
git -C /c/Claude/Nova/nova fetch origin
git -C /c/Claude/Nova/nova ls-remote --heads origin 'feature/<the-feature-id>'
```
Expected: no output (no such branch on remote).

---

### Task 13: Verify the v1 pipeline is still intact and untouched

We've added v2 alongside v1. v1 remains the one the webhook routes to.

- [ ] **Step 1: Confirm v1 SFN still ACTIVE.**

```bash
aws stepfunctions describe-state-machine \
  --state-machine-arn arn:aws:states:us-east-1:577638385116:stateMachine:nova-factory-pipeline \
  --query '{name: name, status: status}' --output table
```
Expected: still `ACTIVE`.

- [ ] **Step 2: Confirm v1 lambdas still exist.**

```bash
aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `nova-factory-`) && !contains(FunctionName, `v2`) && !contains(FunctionName, `ralph-turn`) && !contains(FunctionName, `load-feature`) && !contains(FunctionName, `mark-blocked`) && !contains(FunctionName, `review`)].FunctionName' --output table
```
Expected: 16 v1 functions listed (`nova-factory-acquire-lock`, etc.).

- [ ] **Step 3: Confirm webhook still routes to v1.**

```bash
aws lambda get-function-configuration --function-name $(terraform -chdir=/c/Claude/Nova/nova/infra/webhook-relay output -raw relay_lambda_name 2>/dev/null || echo "nova-webhook-relay") \
  --query 'Environment.Variables.FACTORY_BACKEND' --output text
```
Expected: `step-functions` (v1) — NOT `step-functions-v2`. The flip to v2 is Phase 6.

---

### Task 14: Final verification

- [ ] **Step 1: All tests pass.**

```bash
cd /c/Claude/Nova/nova
pytest tests/factory/ -v
```
Expected: 24 (Phase 1+2) + 12 (allowlist) + 2 (git_io) + 3 (review) + 2 (validate_v2) = 43 tests pass.

- [ ] **Step 2: Terraform plan clean.**

```bash
cd /c/Claude/Nova/nova/infra/factory && terraform plan -input=false | tail -3
```
Expected: `No changes.`

- [ ] **Step 3: Three smokes still all pass.**

```bash
cd /c/Claude/Nova/nova
bash scripts/factory_smoke_v2.sh trivial   && \
bash scripts/factory_smoke_v2.sh medium    && \
bash scripts/factory_smoke_v2.sh oversized && \
echo "ALL THREE END-TO-END SMOKES PASSED"
```

- [ ] **Step 4: Push branch.**

```bash
git -C /c/Claude/Nova/nova push origin factory-overhaul-2026-05-03
```

---

## Phase 3 acceptance criteria recap

1. RalphTurn container image is built, pushed to ECR (`nova-factory-ralph-turn:latest`), deployed as a Lambda, and produces commits in the in-Lambda `.git` when invoked.
2. The filesystem allowlist is enforced; the synthetic "tries-to-edit-workflows" verifying scenario produces a `DENIED:` line in `repair_context.md`. (Verify by running a turn manually with a workspace containing `.github/workflows/evil.yml` and confirming it's rejected.)
3. Validate-v2 runs the 6-step deterministic chain; emits `issues.json` with structured fields.
4. Review emits a JSON blockers/warnings object schema-validated by the handler; the tenancy fixture produces a tenancy blocker.
5. Three synthetic smokes complete:
   - trivial → `Done` end-to-end (PR merged on `main`)
   - medium → `Done` end-to-end
   - oversized → blocked at Plan with Notion comment
6. Token budget hard-stop fires correctly (force a ≥2M-token state in a synthetic run via injection — covered by the `MarkBudgetExceeded` choice).
7. v1 pipeline still ACTIVE and untouched.
8. `pytest tests/factory/ -v` passes 43 tests.

---

## What Phase 4 will do

Phase 4 ("Postdeploy SFN") adds the *separate* state machine `nova-factory-postdeploy`:

- **ProbeStaging Lambda** — reads `.factory/last-run/prd.json` from the merged commit (Task 8 of this phase wrote it). Constructs HTTP probes from acceptance criteria mentioning HTTP verbs/paths. Executes against `STAGING_URL` with a Secrets Manager–stored verifier token.
- **RevertMerge Lambda** — uses `gh` to revert the merge commit on `main`, opens a revert PR, updates Notion to `Failed` with reason `deploy_verification_failed`.
- **EventBridge rule** subscribed to `deploy.yml`'s `workflow_run` completion event, triggering the postdeploy SFN.
- **Synthetic test fixture** that fails staging verification and exercises the revert path end-to-end.

Phase 4 doesn't touch Phase 3's pipeline — it's a separate state machine with its own EventBridge entrypoint.
