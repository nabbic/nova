"""Tests for RevertMerge — exercises GitHub Tree API and Notion update mocks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")
os.environ.setdefault("GITHUB_OWNER", "nabbic")
os.environ.setdefault("GITHUB_REPO", "nova")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))


def test_reverts_when_head_is_not_already_revert():
    from handlers import revert_merge  # type: ignore

    notion_calls: list[dict] = []
    gh_calls: list[dict] = []

    def fake_notion(path, *, method, body=None):
        notion_calls.append({"path": path, "method": method, "body": body})
        return {}

    def fake_gh(method, path, body=None):
        gh_calls.append({"method": method, "path": path, "body": body})
        # GET main ref
        if path == "/git/ref/heads/main" and method == "GET":
            return {"object": {"sha": "headsha"}}
        # GET HEAD commit
        if path == "/git/commits/headsha" and method == "GET":
            return {"sha": "headsha", "message": "feat: something\n\nfactory-execution: x", "parents": [{"sha": "parentsha"}], "tree": {"sha": "headtree"}}
        # GET parent commit (for tree)
        if path == "/git/commits/parentsha" and method == "GET":
            return {"sha": "parentsha", "tree": {"sha": "parenttree"}}
        # POST new commit
        if path == "/git/commits" and method == "POST":
            return {"sha": "revertsha"}
        # POST new ref (branch)
        if path == "/git/refs" and method == "POST":
            return {"ref": body["ref"]}
        # POST PR
        if path == "/pulls" and method == "POST":
            return {"number": 99, "html_url": "https://github.com/nabbic/nova/pull/99"}
        return {}

    with patch.object(revert_merge, "_notion_request", side_effect=fake_notion), \
         patch.object(revert_merge, "_gh", side_effect=fake_gh):
        result = revert_merge.handler({"feature_id": "x", "merge_sha": "abc123", "failures": []}, None)

    assert result["reverted"] is True
    assert result["already_reverted"] is False
    assert any(c["path"] == "/pulls" for c in gh_calls)
    assert any(c["method"] == "PATCH" for c in notion_calls)


def test_skips_revert_if_head_already_reverts():
    from handlers import revert_merge  # type: ignore

    notion_calls: list[dict] = []
    def fake_notion(path, *, method, body=None):
        notion_calls.append({"path": path, "method": method, "body": body})
        return {}

    def fake_gh(method, path, body=None):
        if path == "/git/ref/heads/main" and method == "GET":
            return {"object": {"sha": "headsha"}}
        if path == "/git/commits/headsha" and method == "GET":
            return {"sha": "headsha", "message": "Revert \"feat: stuff\"\n\nThis reverts commit abc123def...\n", "parents": [{"sha": "parentsha"}], "tree": {"sha": "headtree"}}
        return {}

    with patch.object(revert_merge, "_notion_request", side_effect=fake_notion), \
         patch.object(revert_merge, "_gh", side_effect=fake_gh):
        result = revert_merge.handler({"feature_id": "x", "merge_sha": "abc123", "failures": []}, None)

    assert result["reverted"] is False
    assert result["already_reverted"] is True
    # Notion was still updated with the failure note
    assert any(c["method"] == "PATCH" for c in notion_calls)
