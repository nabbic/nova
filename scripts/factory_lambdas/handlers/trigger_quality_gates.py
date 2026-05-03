import json
import os
import urllib.request
from common.secrets import get_secret

GH_OWNER = os.environ["GITHUB_OWNER"]
GH_REPO  = os.environ["GITHUB_REPO"]


def handler(event, _ctx):
    branch     = event["branch"]
    pr_number  = event["pr_number"]
    task_token = event["task_token"]

    token = get_secret("nova/factory/github-token")
    body = {
        "ref": "main",
        "inputs": {
            "branch":     branch,
            "pr_number":  str(pr_number),
            "task_token": task_token,
        },
    }
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/actions/workflows/quality-gates.yml/dispatches",
        method="POST",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8"),
    )
    urllib.request.urlopen(req, timeout=15)
    return {"dispatched": True}
