import base64
import json
import os
import time
import urllib.request
import urllib.error
from common.workspace import list_code_files, read_code_file, read_json
from common.secrets import get_secret
from common.runs import record_step

GH_OWNER = os.environ["GITHUB_OWNER"]
GH_REPO  = os.environ["GITHUB_REPO"]
GH_API   = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}"


def _gh(method: str, path: str, body=None) -> dict:
    token = get_secret("nova/factory/github-token")
    req = urllib.request.Request(
        f"{GH_API}{path}",
        method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode("utf-8") if body else None,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def handler(event, _ctx):
    execution_id = event["execution_id"]
    feature_id   = event["feature_id"]
    spec = read_json(execution_id, "spec.json")

    title = spec["title"]
    slug  = "".join(c if c.isalnum() else "-" for c in title.lower()).strip("-")[:50]
    branch = f"feature/{slug}-{int(time.time())}"

    main_ref    = _gh("GET", "/git/ref/heads/main")
    main_sha    = main_ref["object"]["sha"]
    main_commit = _gh("GET", f"/git/commits/{main_sha}")
    base_tree   = main_commit["tree"]["sha"]

    tree_items = []
    for rel in list_code_files(execution_id):
        content = read_code_file(execution_id, rel)
        blob = _gh("POST", "/git/blobs", {
            "content":  base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
        })
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    if not tree_items:
        raise RuntimeError("No files produced by agents — refusing to commit empty change")

    new_tree = _gh("POST", "/git/trees", {"base_tree": base_tree, "tree": tree_items})
    new_commit = _gh("POST", "/git/commits", {
        "message": f"feat: {title} (factory build)\n\nFeature ID: {feature_id}\nExecution: {execution_id}",
        "tree":    new_tree["sha"],
        "parents": [main_sha],
    })
    _gh("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]})
    pr = _gh("POST", "/pulls", {
        "title": title,
        "body":  (
            f"Built by Nova Software Factory (Step Functions backend).\n\n"
            f"Feature ID: `{feature_id}`\nExecution: `{execution_id}`"
        ),
        "head": branch,
        "base": "main",
    })

    record_step(execution_id, feature_id, "commit_and_push", "success", 0,
                metadata={"branch": branch, "pr_number": pr["number"]})
    return {
        "branch":     branch,
        "pr_number":  pr["number"],
        "pr_url":     pr["html_url"],
        "commit_sha": new_commit["sha"],
    }
