#!/usr/bin/env python3
"""
Factory entry point. Three commands, called by GitHub Actions steps.

  build  — Run agents, write files, commit to feature branch, push.
            Writes .factory-workspace/build-state.json for subsequent steps.
  merge  — Create PR, merge, log run to Notion, set status Done.
  fail   — Set Notion status to Failed and clean up (called on CI quality gate failure).

Usage:
  PYTHONPATH=scripts python scripts/factory_run.py build <feature_id>
  PYTHONPATH=scripts python scripts/factory_run.py merge <feature_id>
  PYTHONPATH=scripts python scripts/factory_run.py fail <feature_id> "<error>"
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agents import run_agent, run_orchestrator, check_security_review
from github_client import create_branch, commit_all, push_branch, create_pr, approve_and_merge_pr
from notion_client import get_page, update_page, create_page

ROOT = Path(__file__).parent.parent
WORKSPACE = ROOT / ".factory-workspace"
RUNS_DB = os.environ["NOTION_RUNS_DB_ID"]

AGENT_SEQUENCE = [
    "spec-analyst",
    "architect",
    "database",
    "backend",
    "frontend",
    "infrastructure",
    "test",
    "security-reviewer",
]


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def load_spec(feature_id: str) -> dict:
    page = get_page(feature_id)
    props = page["properties"]

    def rich_text(key: str) -> str:
        items = props.get(key, {}).get("rich_text", [])
        return "".join(i["plain_text"] for i in items)

    def title_text() -> str:
        items = props.get("Title", {}).get("title", [])
        return "".join(i["plain_text"] for i in items)

    def multi_select(key: str) -> list[str]:
        return [i["name"] for i in props.get(key, {}).get("multi_select", [])]

    def url_field(key: str) -> str:
        return props.get(key, {}).get("url") or ""

    return {
        "feature_id": feature_id,
        "title": title_text(),
        "description": rich_text("Description") or rich_text("Tech Notes"),
        "tech_notes": rich_text("Tech Notes"),
        "acceptance_criteria": rich_text("Acceptance Criteria"),
        "out_of_scope": rich_text("Out of Scope"),
        "affected_roles": multi_select("Affected Roles"),
        "design_url": url_field("Design URL"),
        "feature_flag": rich_text("Feature Flag"),
    }


def set_status(feature_id: str, status: str, extra_props: dict = None) -> None:
    props = {"Status": {"select": {"name": status}}}
    if extra_props:
        props.update(extra_props)
    update_page(feature_id, props)


def log_run(feature_id: str, agents_fired: list, outcome: str, duration: float, error: str = "") -> None:
    create_page(
        parent_id=RUNS_DB,
        parent_type="database",
        properties={
            "Run ID": {"title": [{"text": {"content": f"run-{int(time.time())}"}}]},
            "Feature": {"rich_text": [{"text": {"content": feature_id}}]},
            "Agents Fired": {"rich_text": [{"text": {"content": ", ".join(agents_fired)}}]},
            "Outcome": {"select": {"name": outcome}},
            "Duration (s)": {"number": round(duration, 1)},
            "Error": {"rich_text": [{"text": {"content": error[:2000]}}]},
            "Started": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        },
    )


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def delete_remote_branch(branch_name: str) -> None:
    try:
        subprocess.run(["git", "push", "origin", "--delete", branch_name], check=True, capture_output=True)
        print(f"Cleaned up remote branch: {branch_name}")
    except subprocess.CalledProcessError:
        pass


# ---------------------------------------------------------------------------
# Phase: build
# ---------------------------------------------------------------------------

def cmd_build(feature_id: str) -> None:
    start = time.time()
    agents_fired: list[str] = []
    branch_name: str | None = None

    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    WORKSPACE.mkdir()

    try:
        set_status(feature_id, "In Progress")
        spec = load_spec(feature_id)

        slug = spec["title"].lower().replace(" ", "-")[:50]
        branch_name = f"feature/{slug}-{int(time.time())}"
        create_branch(branch_name)

        plan = run_orchestrator(spec)
        agents_fired.append("orchestrator")

        skipped = set(plan.get("skip_reason", {}).keys())
        for agent_name in AGENT_SEQUENCE:
            if agent_name in skipped:
                continue
            print(f"Running {agent_name}...")
            run_agent(agent_name, plan)
            agents_fired.append(agent_name)

            if agent_name == "spec-analyst":
                reqs_path = WORKSPACE / "requirements.json"
                if reqs_path.exists():
                    reqs = json.loads(reqs_path.read_text())
                    if reqs.get("blockers"):
                        # Only hard blockers halt the build — things like "no idea what to build".
                        # Assumption-level questions are logged as warnings and the build continues.
                        hard = [b for b in reqs["blockers"] if b.upper().startswith("HARD:")]
                        soft = [b for b in reqs["blockers"] if not b.upper().startswith("HARD:")]
                        if soft:
                            print(f"WARNING — spec assumptions (non-blocking): {'; '.join(soft)}")
                        if hard:
                            raise RuntimeError(f"Spec blocked: {'; '.join(hard)}")

        review = check_security_review()
        if not review["passed"]:
            raise RuntimeError(f"Security review failed:\n{json.dumps(review['issues'], indent=2)}")

        commit_all(f"feat: {spec['title']} (factory build)")
        push_branch(branch_name)

        # Persist state for the merge phase
        (WORKSPACE / "build-state.json").write_text(json.dumps({
            "feature_id": feature_id,
            "branch_name": branch_name,
            "feature_title": spec["title"],
            "agents_fired": agents_fired,
            "start_time": start,
        }))

        # Emit branch name for GitHub Actions
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a") as f:
                f.write(f"branch_name={branch_name}\n")
                f.write(f"feature_title={spec['title']}\n")

        print(f"Build phase complete. Branch: {branch_name}")

    except Exception as exc:
        error_msg = str(exc)
        duration = time.time() - start
        print(f"Build FAILED: {error_msg}", file=sys.stderr)
        log_run(feature_id, agents_fired, "Failed", duration, error=error_msg)
        set_status(feature_id, "Failed", {
            "Error Log": {"rich_text": [{"text": {"content": error_msg[:2000]}}]},
        })
        if branch_name:
            delete_remote_branch(branch_name)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Phase: merge
# ---------------------------------------------------------------------------

def cmd_merge(feature_id: str) -> None:
    state_path = WORKSPACE / "build-state.json"
    if not state_path.exists():
        print("No build-state.json — build phase must have failed.", file=sys.stderr)
        sys.exit(1)

    state = json.loads(state_path.read_text())
    branch_name = state["branch_name"]
    feature_title = state["feature_title"]
    agents_fired = state["agents_fired"]
    duration = time.time() - state["start_time"]

    try:
        pr_body = (
            f"## {feature_title}\n\n"
            f"Built by Nova Software Factory.\n\n"
            f"**Agents:** {', '.join(agents_fired)}\n\n"
            f"**Feature ID:** {feature_id}"
        )
        pr_url = create_pr(feature_title, pr_body, branch_name)
        approve_and_merge_pr(pr_url)

        log_run(feature_id, agents_fired, "Success", duration)
        set_status(feature_id, "Done", {"PR Link": {"url": pr_url}})
        print(f"Factory run complete in {duration:.1f}s. PR: {pr_url}")

    except Exception as exc:
        error_msg = str(exc)
        print(f"Merge FAILED: {error_msg}", file=sys.stderr)
        log_run(feature_id, agents_fired, "Failed", duration, error=error_msg)
        set_status(feature_id, "Failed", {
            "Error Log": {"rich_text": [{"text": {"content": error_msg[:2000]}}]},
        })
        delete_remote_branch(branch_name)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Phase: fail  (called by CI on quality gate failure)
# ---------------------------------------------------------------------------

def cmd_fail(feature_id: str, error_msg: str) -> None:
    state_path = WORKSPACE / "build-state.json"
    agents_fired: list[str] = []
    branch_name: str | None = None
    start = time.time()

    if state_path.exists():
        state = json.loads(state_path.read_text())
        agents_fired = state.get("agents_fired", [])
        branch_name = state.get("branch_name")
        start = state.get("start_time", start)

    duration = time.time() - start
    log_run(feature_id, agents_fired, "Failed", duration, error=error_msg)
    set_status(feature_id, "Failed", {
        "Error Log": {"rich_text": [{"text": {"content": error_msg[:2000]}}]},
    })
    if branch_name:
        delete_remote_branch(branch_name)
    print(f"Marked {feature_id} as Failed: {error_msg}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

COMMANDS = {"build": cmd_build, "merge": cmd_merge, "fail": cmd_fail}

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in COMMANDS:
        print("Usage: factory_run.py <build|merge|fail> <feature_id> [error_msg]")
        sys.exit(1)

    cmd = sys.argv[1]
    fid = sys.argv[2]

    if cmd == "build":
        cmd_build(fid)
    elif cmd == "merge":
        cmd_merge(fid)
    elif cmd == "fail":
        error = sys.argv[3] if len(sys.argv) > 3 else "Quality gate failure"
        cmd_fail(fid, error)
