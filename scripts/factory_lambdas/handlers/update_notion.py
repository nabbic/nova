import json
import urllib.request
from common.secrets import get_secret

NOTION_VERSION = "2022-06-28"


def handler(event, _ctx):
    feature_id = event["feature_id"]
    status     = event["status"]
    extras     = event.get("extras", {})

    props: dict = {"Status": {"select": {"name": status}}}
    if "pr_url" in extras:
        props["PR Link"] = {"url": extras["pr_url"]}
    if "error" in extras:
        props["Error Log"] = {"rich_text": [{"text": {"content": str(extras["error"])[:2000]}}]}

    api_key = get_secret("nova/factory/notion-api-key")
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{feature_id}",
        method="PATCH",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        data=json.dumps({"properties": props}).encode("utf-8"),
    )
    urllib.request.urlopen(req, timeout=15)
    return {"updated": True}
