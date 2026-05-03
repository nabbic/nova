import os
import urllib.request
from common.workspace import write_json
from common.secrets import get_secret

GH_OWNER = os.environ["GITHUB_OWNER"]
GH_REPO = os.environ["GITHUB_REPO"]


def handler(event, _ctx):
    execution_id = event["execution_id"]

    token = get_secret("nova/factory/github-token")
    url = f"https://raw.githubusercontent.com/{GH_OWNER}/{GH_REPO}/main/CLAUDE.md"
    req = urllib.request.Request(url, headers={"Authorization": f"token {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        claude_md = resp.read().decode("utf-8")

    write_json(execution_id, "project_context.json", {"claude_md": claude_md})
    return {"loaded": True}
