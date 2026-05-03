"""Minimal Anthropic Messages API client (raw HTTP).

Avoids the `anthropic` SDK to keep the Lambda zip small. Supports system +
single user message. Returns text + token counts. Phase 3 will extend with
prompt caching by adding a `cache_control` block on the system message.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.request import urlopen  # patched in tests

from common.secrets import get_secret

ANTHROPIC_VERSION = "2023-06-01"
API_URL = "https://api.anthropic.com/v1/messages"


def messages_create(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout: int = 90,
) -> dict:
    """One-shot Messages API call.

    Returns:
        {"text": "<concatenated text content>", "input_tokens": int, "output_tokens": int}

    Raises RuntimeError on empty content array.
    """
    api_key = get_secret("nova/factory/anthropic-api-key")
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        API_URL,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    with urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())

    content = payload.get("content") or []
    if not content:
        raise RuntimeError("Anthropic returned no content blocks")

    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    usage = payload.get("usage", {})
    return {
        "text": text,
        "input_tokens":  int(usage.get("input_tokens", 0)),
        "output_tokens": int(usage.get("output_tokens", 0)),
    }
