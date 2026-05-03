"""Tests for the LoadFeature Lambda."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("WORKSPACE_BUCKET", "test-bucket")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_feature_writes_spec_raw_and_meta():
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
    meta_body = body_meta_put["Body"]
    if isinstance(meta_body, bytes):
        meta_body = meta_body.decode("utf-8")
    meta = json.loads(meta_body)
    assert meta["title"] == "Add buyer engagement export endpoint"
    assert meta["feature_id"] == "00000000-0000-0000-0000-000000000001"

    body_spec_put = next(p for p in s3_puts if p["Key"].endswith("spec_raw.md"))
    spec_body = body_spec_put["Body"]
    if isinstance(spec_body, bytes):
        spec_body = spec_body.decode("utf-8")
    assert "Add buyer engagement export endpoint" in spec_body
    assert "200 with engagement data" in spec_body
