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
    assert "suggested_split" in result
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
    assert len(written["suggested_split"]) == 5


def test_repairs_malformed_json_with_one_retry():
    from handlers import plan  # type: ignore

    fake = FakeS3()
    _seed_intake(fake, "exec-repair")
    valid = json.loads((FIXTURES / "haiku_response_valid_prd.json").read_text())

    # First call returns prose-wrapped JSON; the impl strips ```json fences.
    responses = [
        {"text": "Here is your PRD:\n```json\n" + json.dumps(valid) + "\n```", "input_tokens": 1, "output_tokens": 1},
    ]
    with patch.object(plan, "_s3", fake), \
         patch.object(plan, "messages_create", side_effect=responses):
        result = plan.handler(
            {"feature_id": "00000000-0000-0000-0000-000000000001",
             "execution_id": "exec-repair"},
            None,
        )

    assert result["hard_blockers"] == []


def test_raises_if_schema_validation_fails_after_retry():
    from handlers import plan  # type: ignore

    fake = FakeS3()
    _seed_intake(fake, "exec-bad")

    bad = {"title": "missing required fields"}
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
