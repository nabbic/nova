import json
import time
import urllib.request
from common.workspace import write_json
from common.secrets import get_secret

NOTION_VERSION = "2022-06-28"


def _notion_request(path: str, method: str = "GET", body: dict | None = None) -> dict:
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
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _rich(props: dict, key: str) -> str:
    return "".join(t["plain_text"] for t in props.get(key, {}).get("rich_text", []))


def _title(props: dict) -> str:
    return "".join(t["plain_text"] for t in props.get("Title", {}).get("title", []))


def _multi(props: dict, key: str) -> list[str]:
    return [t["name"] for t in props.get(key, {}).get("multi_select", [])]


def _status(props: dict) -> str:
    s = props.get("Status", {})
    return (s.get("status") or {}).get("name") or (s.get("select") or {}).get("name") or "Unknown"


def handler(event, _ctx):
    feature_id   = event["feature_id"]
    execution_id = event["execution_id"]

    page = _notion_request(f"/pages/{feature_id}")
    props = page["properties"]

    deps = []
    for dep in props.get("Depends On", {}).get("relation", []):
        dp = _notion_request(f"/pages/{dep['id']}")["properties"]
        deps.append({
            "id": dep["id"],
            "title": _title(dp),
            "status": _status(dp),
            "description": _rich(dp, "Description") or _rich(dp, "Tech Notes"),
        })

    spec = {
        "feature_id": feature_id,
        "title": _title(props),
        "description": _rich(props, "Description") or _rich(props, "Tech Notes"),
        "tech_notes": _rich(props, "Tech Notes"),
        "acceptance_criteria": _rich(props, "Acceptance Criteria"),
        "out_of_scope": _rich(props, "Out of Scope"),
        "affected_roles": _multi(props, "Affected Roles"),
        "feature_flag": _rich(props, "Feature Flag"),
        "dependencies": deps,
    }

    write_json(execution_id, "spec.json", spec)
    return {"feature_id": feature_id, "title": spec["title"]}
