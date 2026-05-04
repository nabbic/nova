"""RalphTurn — one Claude Code turn against a feature workspace.

Spec §2.3.2. Per-turn flow:
1. Download S3 workspace tree to /tmp/ws. Restore .git from .git.tar.gz if present.
   First-turn seed: if S3 workspace is empty, clone the repo from GitHub.
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
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import boto3

# Lambda task root holds the system prompt files we ship in the image
TASK_ROOT = Path(os.environ.get("LAMBDA_TASK_ROOT", "/var/task"))
sys.path.insert(0, str(TASK_ROOT))

from allowlist import partition  # noqa: E402
from git_io import pack_git, unpack_git  # noqa: E402

BUCKET   = os.environ["WORKSPACE_BUCKET"]
WS_ROOT  = Path("/tmp/ws")
GIT_TGZ_KEY_SUFFIX = "workspace/.git.tar.gz"
RALPH_MODEL = os.environ.get("RALPH_MODEL", "claude-sonnet-4-6")
RALPH_MAX_INNER_TURNS = os.environ.get("RALPH_MAX_INNER_TURNS", "30")
SYSTEM_PROMPT_PATH = TASK_ROOT / ".factory" / "implementer-system.md"
GH_OWNER = os.environ.get("GITHUB_OWNER", "nabbic")
GH_REPO  = os.environ.get("GITHUB_REPO",  "nova")

_s3 = boto3.client("s3")
_sm = boto3.client("secretsmanager")


def _list_s3_keys(prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def _seed_workspace_from_github() -> None:
    """First-turn seed: shallow clone main into WS_ROOT."""
    token = _sm.get_secret_value(SecretId="nova/factory/github-token")["SecretString"]
    clone_url = f"https://x-access-token:{token}@github.com/{GH_OWNER}/{GH_REPO}.git"
    if WS_ROOT.exists():
        shutil.rmtree(WS_ROOT)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", "main", clone_url, str(WS_ROOT)],
        check=True, capture_output=True,
    )
    subprocess.run(["git", "config", "user.email", "factory@nova"], cwd=WS_ROOT, check=True)
    subprocess.run(["git", "config", "user.name", "Nova Factory"], cwd=WS_ROOT, check=True)


def _download_workspace(execution_id: str) -> None:
    """Mirror s3://<bucket>/<execution_id>/workspace/ → /tmp/ws.

    If S3 has no workspace contents, seed from GitHub instead (first turn).
    """
    prefix = f"{execution_id}/workspace/"
    keys = _list_s3_keys(prefix)
    non_git_keys = [k for k in keys if not k.endswith(".git.tar.gz")]

    if not non_git_keys:
        _seed_workspace_from_github()
        return

    if WS_ROOT.exists():
        shutil.rmtree(WS_ROOT)
    WS_ROOT.mkdir(parents=True)
    for key in non_git_keys:
        rel = key[len(prefix):]
        if not rel or rel.endswith("/"):
            continue
        dest = WS_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        _s3.download_file(BUCKET, key, str(dest))

    # Restore .git from tarball
    git_tgz_key = f"{execution_id}/{GIT_TGZ_KEY_SUFFIX}"
    git_tarball = Path("/tmp/.git.tar.gz")
    try:
        _s3.download_file(BUCKET, git_tgz_key, str(git_tarball))
        unpack_git(git_tarball, WS_ROOT)
    except _s3.exceptions.ClientError:
        # No tarball yet — initialize fresh git
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=WS_ROOT, check=True)
        subprocess.run(["git", "config", "user.email", "factory@nova"], cwd=WS_ROOT, check=True)
        subprocess.run(["git", "config", "user.name", "Nova Factory"], cwd=WS_ROOT, check=True)
        subprocess.run(["git", "add", "-A"], cwd=WS_ROOT, check=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "factory: initial workspace state"], cwd=WS_ROOT, check=True)


def _ensure_prd_in_workspace(execution_id: str) -> dict:
    """The Plan stage wrote prd.json to <exec>/plan/prd.json. Copy it to
    /tmp/ws/prd.json (where the implementer reads it from). Also returns
    the parsed PRD."""
    plan_key = f"{execution_id}/plan/prd.json"
    ws_path = WS_ROOT / "prd.json"
    if not ws_path.exists():
        local = Path("/tmp/_plan_prd.json")
        _s3.download_file(BUCKET, plan_key, str(local))
        ws_path.write_bytes(local.read_bytes())
    return json.loads(ws_path.read_text(encoding="utf-8"))


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
        parts += ["", "# repair_context.md (issues from last cycle — address first)", "", repair]
    return "\n".join(parts)


def _system_prompt() -> str:
    impl = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    repo_claude = WS_ROOT / "CLAUDE.md"
    if repo_claude.is_file():
        return f"{impl}\n\n# REPO CLAUDE.md\n\n{repo_claude.read_text(encoding='utf-8')}"
    return impl


def _get_anthropic_key() -> str:
    return _sm.get_secret_value(SecretId="nova/factory/anthropic-api-key")["SecretString"]


def _run_claude(user_prompt: str) -> dict:
    """Invoke claude -p and return the parsed JSON output.

    The Claude Code CLI (--output-format json) emits a JSON object on stdout.
    """
    env = {**os.environ, "ANTHROPIC_API_KEY": _get_anthropic_key(), "HOME": "/tmp"}
    # Pass user prompt via stdin to avoid ARG_MAX (Linux default ~128KB) when
    # the repair_context.md grows large after Validate failures.
    sys_prompt = _system_prompt()
    cmd = [
        "claude",
        "-p",
        "--model", RALPH_MODEL,
        "--max-turns", str(RALPH_MAX_INNER_TURNS),
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--append-system-prompt", sys_prompt,
    ]
    print(f"[ralph] invoking claude (prompt {len(user_prompt)} chars, system {len(sys_prompt)} chars)", flush=True)
    started = time.time()
    proc = subprocess.run(cmd, cwd=WS_ROOT, env=env, capture_output=True, text=True,
                          input=user_prompt, timeout=780)
    elapsed = time.time() - started
    print(f"[ralph] claude exit={proc.returncode} elapsed={elapsed:.0f}s stdout_len={len(proc.stdout)} stderr_len={len(proc.stderr)}", flush=True)
    if proc.stderr:
        print(f"[ralph] claude stderr (last 1000 chars):\n{proc.stderr[-1000:]}", flush=True)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exit {proc.returncode}: stderr=\n{proc.stderr[-4000:]}\nstdout=\n{proc.stdout[-2000:]}")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude returned non-JSON: {proc.stdout[-2000:]}")
    # Log the result summary
    result_text = (out.get("result") or "")[:1500]
    print(f"[ralph] claude result (first 1500 chars):\n{result_text}", flush=True)
    out["_elapsed_s"] = elapsed
    return out


def _current_head_sha() -> str:
    """HEAD sha, or empty string if no commits yet."""
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WS_ROOT, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def _scan_changed_paths(pre_turn_sha: str) -> list[str]:
    """All paths changed during this turn — both uncommitted (status) and
    committed by claude (diff vs pre-turn HEAD)."""
    paths: set[str] = set()

    # Uncommitted: working tree + index vs HEAD
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z"],
        cwd=WS_ROOT, capture_output=True, text=True, check=True,
    )
    for entry in out.stdout.split("\0"):
        if not entry:
            continue
        # Format is "XY <path>" — at least 4 chars before the path
        path = entry[3:].strip() if len(entry) >= 4 else entry.strip()
        if path:
            paths.add(path)

    # Claude may have committed via its bash tool — capture commits since pre-turn HEAD
    if pre_turn_sha:
        out2 = subprocess.run(
            ["git", "diff", "--name-only", "-z", f"{pre_turn_sha}..HEAD"],
            cwd=WS_ROOT, capture_output=True, text=True, check=False,
        )
        if out2.returncode == 0:
            for path in out2.stdout.split("\0"):
                path = path.strip()
                if path:
                    paths.add(path)

    return sorted(paths)


def _enforce_allowlist(changed: list[str], repair_context_path: Path) -> tuple[list[str], list[str]]:
    allowed, denied = partition(changed)
    if denied:
        for p in denied:
            full = WS_ROOT / p
            if full.is_file():
                full.unlink()
            subprocess.run(["git", "checkout", "--", p], cwd=WS_ROOT, capture_output=True)

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
    """Two-of-two completion signal:
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
    _s3.upload_file(str(tarball), BUCKET, f"{execution_id}/{GIT_TGZ_KEY_SUFFIX}")

    # Use git to enumerate paths — tracked + untracked-but-not-ignored.
    # This respects .gitignore so we don't upload vendored deps, build
    # artifacts, __pycache__, etc.
    p = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=WS_ROOT, capture_output=True, text=True, check=True,
    )
    rels = [r for r in p.stdout.split("\0") if r]
    print(f"[ralph] uploading {len(rels)} files (gitignore-respecting)", flush=True)

    for rel in rels:
        if rel.startswith(".git/") or rel == ".git":
            continue
        local = WS_ROOT / rel
        if not local.is_file():
            continue
        _s3.upload_file(str(local), BUCKET, f"{prefix}{rel}")


def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]
    iter_num     = int(event.get("iter", 0))

    _download_workspace(execution_id)
    prd = _ensure_prd_in_workspace(execution_id)

    progress_path = WS_ROOT / "progress.txt"
    repair_path   = WS_ROOT / "repair_context.md"
    progress = _read_optional(progress_path)
    repair   = _read_optional(repair_path)

    pre_turn_sha = _current_head_sha()
    user_prompt = _build_user_prompt(prd, progress, repair)
    claude_out  = _run_claude(user_prompt)

    changed = _scan_changed_paths(pre_turn_sha)
    allowed, denied = _enforce_allowlist(changed, repair_path)

    new_progress = progress.rstrip()
    new_progress += f"\n\n## Turn {iter_num + 1}\n"
    new_progress += f"- elapsed: {claude_out.get('_elapsed_s', 0):.0f}s\n"
    new_progress += f"- changed (allowed): {sorted(allowed)}\n"
    if denied:
        new_progress += f"- changed (DENIED, surfaced as repair): {sorted(denied)}\n"
    progress_path.write_text(new_progress.lstrip() + "\n", encoding="utf-8")

    _commit_intra_turn()
    _upload_workspace(execution_id)

    # Clear the repair context if it had been present going INTO the turn
    # (next stage's Validate/Review writes a new one if issues persist).
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
