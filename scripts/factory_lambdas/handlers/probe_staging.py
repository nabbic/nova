"""ProbeStaging Lambda — verifies the deployed feature is actually serving by
running HTTP probes derived from the PRD's acceptance criteria.

Spec §2.7. Triggered by the postdeploy state machine after deploy.yml's
workflow_run completion event.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from urllib.request import urlopen

from common.probe import extract_probes
from common.secrets import get_secret

GH_OWNER = os.environ.get("GITHUB_OWNER", "nabbic")
GH_REPO  = os.environ.get("GITHUB_REPO",  "nova")
STAGING_URL = os.environ["STAGING_URL"].rstrip("/")
PROBE_TIMEOUT = 10


def _fetch_prd_from_github(merge_sha: str) -> dict:
    """Read .factory/last-run/prd.json from the merged commit via the GitHub
    REST contents API."""
    gh_token = get_secret("nova/factory/github-token")
    url = f"https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/.factory/last-run/prd.json?ref={merge_sha}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3.raw",
    })
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _get_token() -> str:
    return get_secret("nova/factory/staging-verifier-token")


def _probe(method: str, path: str, expected: int, auth: bool, token: str) -> dict:
    url = STAGING_URL + path
    headers = {}
    if auth:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers)
    actual_status = None
    error = None
    try:
        with urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            actual_status = resp.status
    except urllib.error.HTTPError as e:
        actual_status = e.code
    except Exception as e:
        error = str(e)[:200]

    return {
        "method": method,
        "path": path,
        "expected_status": expected,
        "actual_status":   actual_status,
        "passed":          (actual_status == expected) and (error is None),
        "error":           error,
    }


def handler(event, _ctx):
    feature_id = event["feature_id"]
    merge_sha  = event["merge_sha"]

    prd = _fetch_prd_from_github(merge_sha)
    criteria = []
    for s in prd.get("stories", []):
        criteria.extend(s.get("acceptance_criteria", []))
    probes_def = extract_probes(criteria)
    if not probes_def:
        return {"feature_id": feature_id, "merge_sha": merge_sha, "passed": True, "probes": [], "failures": [], "reason": "no_http_probes"}

    token = _get_token()
    results = [_probe(p["method"], p["path"], p["expected_status"], p["auth"], token) for p in probes_def]
    failures = [r for r in results if not r["passed"]]

    return {
        "feature_id": feature_id,
        "merge_sha":  merge_sha,
        "passed":     len(failures) == 0,
        "probes":     results,
        "failures":   failures,
    }
