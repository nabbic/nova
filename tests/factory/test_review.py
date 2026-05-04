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
