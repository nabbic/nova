"""RevertMerge Lambda — reverts the merge commit on main and re-files Notion.

Spec §2.7. Idempotent: if main's HEAD is already a revert of the offending
sha, skip the revert step and just update Notion.

Uses the GitHub Tree API directly (no `gh` CLI). Strategy:
- Get HEAD on main.
- Get HEAD's first parent's tree (the state before the merge).
- Create a revert commit with parent's tree, parented at HEAD.
- Open a revert PR; quality-gates auto-merges.
"""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.request import urlopen

from common.secrets import get_secret

GH_OWNER = os.environ["GITHUB_OWNER"]
GH_REPO  = os.environ["GITHUB_REPO"]
GH_API   = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"
NOTION_VERSION = "2022-06-28"


def _gh(method: str, path: str, body: dict | None = None) -> dict:
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


def handler(event, _ctx):
    feature_id = event["feature_id"]
    merge_sha  = event["merge_sha"]
    failures   = event.get("failures", [])

    # Get HEAD on main and inspect its commit message
    main_ref     = _gh("GET", "/git/ref/heads/main")
    head_sha     = main_ref["object"]["sha"]
    head_commit  = _gh("GET", f"/git/commits/{head_sha}")
    head_message = head_commit.get("message", "")

    if f"This reverts commit {merge_sha}" in head_message or merge_sha[:7] in head_message and "Revert" in head_message:
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

    # Build a revert commit using parent's tree
    parent_sha   = head_commit["parents"][0]["sha"]
    parent_commit = _gh("GET", f"/git/commits/{parent_sha}")
    parent_tree  = parent_commit["tree"]["sha"]

    revert_msg = (
        f"Revert: deploy verification failed for {merge_sha[:8]}\n\n"
        f"This reverts commit {merge_sha}\n\n"
        f"Failures:\n{json.dumps(failures, indent=2)[:2000]}\n"
    )
    revert_commit = _gh("POST", "/git/commits", {
        "message": revert_msg,
        "tree":    parent_tree,
        "parents": [head_sha],
    })

    revert_branch = f"revert/{merge_sha[:8]}"
    _gh("POST", "/git/refs", {
        "ref": f"refs/heads/{revert_branch}",
        "sha": revert_commit["sha"],
    })

    pr = _gh("POST", "/pulls", {
        "title": f"Revert: deploy verification failed for {merge_sha[:8]}",
        "body":  f"Auto-revert: deploy verification failed for merge {merge_sha}.\n\n```json\n{json.dumps(failures, indent=2)[:2000]}\n```",
        "head":  revert_branch,
        "base":  "main",
    })

    _notion_request(
        f"/pages/{feature_id}",
        method="PATCH",
        body={
            "properties": {
                "Status":    {"select": {"name": "Failed"}},
                "Error Log": {"rich_text": [{"text": {"content": f"deploy_verification_failed; revert PR #{pr['number']} opened for {merge_sha}"[:2000]}}]},
            }
        },
    )

    return {
        "feature_id":    feature_id,
        "reverted":      True,
        "already_reverted": False,
        "revert_pr_url": pr.get("html_url", ""),
        "revert_pr_number": pr.get("number"),
    }
