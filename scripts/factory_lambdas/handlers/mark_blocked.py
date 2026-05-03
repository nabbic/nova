"""MarkBlocked Lambda — when Plan rejects a feature for sizing, post a
structured Notion comment with the breach + suggested split, and flip the
Notion status to Failed.

Spec §2.2.1.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.request import urlopen

from common.secrets import get_secret

NOTION_VERSION = "2022-06-28"


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
        data=json.dumps(body).encode("utf-8") if body is not None else None,
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _format_comment(hard_blockers: list[dict], suggested_split: list[str]) -> str:
    blocker_lines = []
    for b in hard_blockers:
        line = f"- **{b['reason']}**"
        if b.get("details"):
            line += f": {b['details']}"
        blocker_lines.append(line)

    split_lines = [f"  {i+1}. {s}" for i, s in enumerate(suggested_split)] if suggested_split else []

    parts = [
        "🛑 Factory cannot run this feature in one pass — sizing rubric breached.",
        "",
        "**Detected:**",
        *blocker_lines,
    ]
    if split_lines:
        parts += [
            "",
            "**Suggested decomposition** (paste each as a separate Ready-to-Build feature):",
            *split_lines,
        ]
    parts += [
        "",
        "See `.factory/feature-sizing-rubric.md` in the repo for the rubric this enforces.",
    ]
    return "\n".join(parts)


def handler(event, _ctx):
    feature_id      = event["feature_id"]
    hard_blockers   = event.get("hard_blockers", [])
    suggested_split = event.get("suggested_split", [])

    # 1. Update status to Failed with the first blocker reason
    first = hard_blockers[0] if hard_blockers else {"reason": "unknown"}
    _notion_request(
        f"/pages/{feature_id}",
        method="PATCH",
        body={
            "properties": {
                "Status":    {"select": {"name": "Failed"}},
                "Error Log": {"rich_text": [{"text": {"content": f"Blocked at Plan: {first.get('reason')} — {first.get('details', '')}"[:2000]}}]},
            }
        },
    )

    # 2. Post a structured comment
    comment = _format_comment(hard_blockers, suggested_split)
    _notion_request(
        "/comments",
        method="POST",
        body={
            "parent":    {"page_id": feature_id},
            "rich_text": [{"text": {"content": comment[:2000]}}],
        },
    )

    return {"blocked": True, "reason": first.get("reason")}
