"""LoadFeature Lambda — fetches a Notion page and writes intake artifacts to S3.

Spec §2.1. Inputs: feature_id (Notion page UUID), execution_id (SFN execution).
Outputs (to S3 under <execution_id>/intake/):
  - spec_raw.md       — concatenated Title + Description + Tech Notes + Acceptance Criteria as markdown
  - feature_meta.json — title, status, feature_id, raw properties dict
"""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.request import urlopen

import boto3

from common.secrets import get_secret

NOTION_VERSION = "2022-06-28"
BUCKET = os.environ["WORKSPACE_BUCKET"]
_s3 = boto3.client("s3")


def _notion_get(path: str) -> dict:
    api_key = get_secret("nova/factory/notion-api-key")
    req = urllib.request.Request(
        f"https://api.notion.com/v1{path}",
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _rich(props: dict, key: str) -> str:
    return "".join(t.get("plain_text", "") for t in props.get(key, {}).get("rich_text", []))


def _title(props: dict) -> str:
    return "".join(t.get("plain_text", "") for t in props.get("Title", {}).get("title", []))


def _status(props: dict) -> str:
    s = props.get("Status", {})
    return (s.get("status") or {}).get("name") or (s.get("select") or {}).get("name") or "Unknown"


def _build_spec_md(props: dict) -> str:
    title       = _title(props)
    description = _rich(props, "Description")
    tech_notes  = _rich(props, "Tech Notes")
    accept      = _rich(props, "Acceptance Criteria")
    out_of_scope = _rich(props, "Out of Scope")

    parts = [f"# {title}", ""]
    if description:
        parts += ["## Description", "", description, ""]
    if tech_notes:
        parts += ["## Tech Notes", "", tech_notes, ""]
    if accept:
        parts += ["## Acceptance Criteria", "", accept, ""]
    if out_of_scope:
        parts += ["## Out of Scope", "", out_of_scope, ""]
    return "\n".join(parts).rstrip() + "\n"


def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]

    page  = _notion_get(f"/pages/{feature_id}")
    props = page["properties"]

    spec_md = _build_spec_md(props)
    meta = {
        "feature_id":   feature_id,
        "title":        _title(props),
        "status":       _status(props),
        "url":          page.get("url"),
        "last_edited":  page.get("last_edited_time"),
    }

    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/intake/spec_raw.md",
        Body=spec_md.encode("utf-8"),
        ContentType="text/markdown",
    )
    _s3.put_object(
        Bucket=BUCKET,
        Key=f"{execution_id}/intake/feature_meta.json",
        Body=json.dumps(meta, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return {"feature_id": feature_id, "title": meta["title"], "status": meta["status"]}
