"""Tests for the raw-HTTP Anthropic Messages client used by Plan and Review."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas"))

from common.anthropic import messages_create  # noqa: E402


def _fake_resp(payload: dict) -> MagicMock:
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda self, *a: None
    return resp


def test_returns_text_and_token_counts():
    payload = {
        "id": "msg_1",
        "content": [{"type": "text", "text": "hello world"}],
        "usage": {"input_tokens": 12, "output_tokens": 5},
    }
    with patch("common.anthropic.urlopen", return_value=_fake_resp(payload)) as mock_open, \
         patch("common.anthropic.get_secret", return_value="sk-ant-test"):
        result = messages_create(
            model="claude-haiku-4-5",
            system="You are a tester.",
            user="say hello",
            max_tokens=64,
        )
    assert result["text"] == "hello world"
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 5
    request = mock_open.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 64
    assert body["system"] == "You are a tester."
    assert body["messages"] == [{"role": "user", "content": "say hello"}]


def test_passes_api_key_header():
    payload = {"content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    with patch("common.anthropic.urlopen", return_value=_fake_resp(payload)), \
         patch("common.anthropic.get_secret", return_value="sk-ant-secret"):
        messages_create(model="claude-haiku-4-5", system="s", user="u", max_tokens=10)


def test_raises_on_empty_content():
    payload = {"content": [], "usage": {"input_tokens": 1, "output_tokens": 0}}
    with patch("common.anthropic.urlopen", return_value=_fake_resp(payload)), \
         patch("common.anthropic.get_secret", return_value="sk-ant-test"):
        try:
            messages_create(model="claude-haiku-4-5", system="s", user="u", max_tokens=10)
        except RuntimeError as e:
            assert "no content" in str(e).lower()
            return
    raise AssertionError("expected RuntimeError on empty content")
