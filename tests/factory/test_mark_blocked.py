"""Tests for the MarkBlocked Lambda."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

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

    methods = sorted(c["method"] for c in calls)
    assert methods == ["PATCH", "POST"]

    patch_call = next(c for c in calls if c["method"] == "PATCH")
    assert "00000000-0000-0000-0000-000000000002" in patch_call["path"]
    assert patch_call["body"]["properties"]["Status"]["select"]["name"] == "Failed"

    post_call = next(c for c in calls if c["method"] == "POST")
    body_text = json.dumps(post_call["body"])
    assert "feature_too_large" in body_text
    assert "Seller invitation flow" in body_text
