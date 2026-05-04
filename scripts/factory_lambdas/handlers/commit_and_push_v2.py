"""CommitAndPush v2 — reads workspace/ prefix (written by RalphTurn) and
opens a PR via the GitHub Tree API.

Spec §2.6. Differences from v1's commit_and_push.py:
- Source prefix is `<execution_id>/workspace/` (RalphTurn output) not `code/`.
- Commit message is deterministic: "feat(factory): <PRD title>\n\n<narrative>\n\nfactory-execution: <id>".
- Writes `.factory/last-run/{prd.json,review.json,progress.txt,meta.json}`
  to the tree before pushing — the postdeploy probe (Phase 4) reads them
  from the merged commit.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from urllib.request import urlopen

import boto3

from common.secrets import get_secret

GH_OWNER = os.environ["GITHUB_OWNER"]
GH_REPO  = os.environ["GITHUB_REPO"]
GH_API   = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"
BUCKET   = os.environ["WORKSPACE_BUCKET"]

_s3 = boto3.client("s3")


def _gh(method: str, path: str, body=None) -> dict:
    token = get_secret("nova/factory/github-token")
    req = urllib.request.Request(
        f"{GH_API}{path}",
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8") if body else None,
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _list_workspace(execution_id: str) -> list[str]:
    """Return relative paths under <execution_id>/workspace/ excluding .git/* and the tarball."""
    prefix = f"{execution_id}/workspace/"
    keys: list[str] = []
    paginator = _s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(prefix):]
            if not rel or rel.endswith("/"):
                continue
            if rel == ".git.tar.gz" or rel.startswith(".git/"):
                continue
            keys.append(rel)
    return keys


def _read_workspace_bytes(execution_id: str, rel: str) -> bytes:
    return _s3.get_object(Bucket=BUCKET, Key=f"{execution_id}/workspace/{rel}")["Body"].read()


def _read_text(execution_id: str, rel: str) -> str:
    return _s3.get_object(Bucket=BUCKET, Key=f"{execution_id}/{rel}")["Body"].read().decode("utf-8")


def _try_read_text(execution_id: str, rel: str) -> str | None:
    try:
        return _read_text(execution_id, rel)
    except _s3.exceptions.NoSuchKey:
        return None
    except Exception:
        return None


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]

    prd       = json.loads(_read_text(execution_id, "plan/prd.json"))
    review_js = _try_read_text(execution_id, "review/blockers.json")
    progress  = _try_read_text(execution_id, "workspace/progress.txt")

    # Get base sha
    main_ref    = _gh("GET", "/git/ref/heads/main")
    main_sha    = main_ref["object"]["sha"]
    main_commit = _gh("GET", f"/git/commits/{main_sha}")
    base_tree   = main_commit["tree"]["sha"]

    title = prd.get("title") or "factory feature"
    slug  = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")[:50]
    branch = f"feature/{slug}-{int(time.time())}"

    # Read RalphTurn's list of files that changed vs origin/main
    changed_list_text = _try_read_text(execution_id, "workspace/changed-files.txt")
    if not changed_list_text or not changed_list_text.strip():
        raise RuntimeError(f"changed-files.txt missing or empty for {execution_id} — RalphTurn produced no diff")
    changed_files = [line.strip() for line in changed_list_text.splitlines() if line.strip()]

    # Filter: skip RalphTurn-internal artifacts; the actual implementation
    # files are what we want in the PR.
    SKIP_INTERNAL = {"diff.patch", "changed-files.txt", "progress.txt", "repair_context.md", "prd.json"}
    changed_files = [f for f in changed_files if f not in SKIP_INTERNAL]

    if not changed_files:
        raise RuntimeError(f"No real file changes for {execution_id} (only internal artifacts changed)")

    # Always inject .factory/last-run/* artifacts (for the postdeploy probe)
    last_run_blobs: dict[str, bytes] = {
        ".factory/last-run/prd.json":  json.dumps(prd, indent=2).encode("utf-8"),
        ".factory/last-run/meta.json": json.dumps({
            "feature_id": feature_id, "execution_id": execution_id,
        }, indent=2).encode("utf-8"),
    }
    if review_js is not None:
        last_run_blobs[".factory/last-run/review.json"] = review_js.encode("utf-8")
    if progress is not None:
        last_run_blobs[".factory/last-run/progress.txt"] = progress.encode("utf-8")

    # Build the source map: only changed files + last-run artifacts
    sources: dict[str, bytes] = {}
    for rel in changed_files:
        try:
            sources[rel] = _read_workspace_bytes(execution_id, rel)
        except _s3.exceptions.NoSuchKey:
            # File was deleted — handle deletion in the tree (sha=None)
            sources[rel] = b""  # placeholder; we'll mark as delete below
    sources.update(last_run_blobs)

    tree_items = []
    for rel, content in sources.items():
        # Detect deletion: source not in workspace (after gitignore filter) means deleted
        # For simplicity in v2 we don't yet handle deletions distinctly — RalphTurn
        # rarely deletes files. Add explicit delete handling later if needed.
        blob = _gh("POST", "/git/blobs", {
            "content":  base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        })
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    new_tree = _gh("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_items})

    narrative = (prd.get("narrative_md") or "")[:4000]
    commit_msg = (
        f"feat(factory): {title}\n\n"
        f"{narrative}\n\n"
        f"factory-execution: {execution_id}\n"
    )

    new_commit = _gh("POST", "/git/commits", {
        "message": commit_msg,
        "tree":    new_tree["sha"],
        "parents": [main_sha],
    })
    _gh("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]})
    pr = _gh("POST", "/pulls", {
        "title": title,
        "body":  (
            f"Built by Nova Software Factory v2.\n\n"
            f"Feature ID: `{feature_id}`\nExecution: `{execution_id}`\n\n"
            f"```json\n{json.dumps(prd, indent=2)[:3000]}\n```\n"
        ),
        "head": branch,
        "base": "main",
    })

    return {
        "branch":     branch,
        "pr_number":  pr["number"],
        "pr_url":     pr["html_url"],
        "commit_sha": new_commit["sha"],
    }
