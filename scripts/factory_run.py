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
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agents import run_agent, run_orchestrator, check_security_review
from github_client import create_branch, commit_all, push_branch, create_pr, approve_and_merge_pr, trigger_repository_dispatch
from notion_client import get_page, update_page, create_page, query_database

ROOT = Path(__file__).parent.parent
WORKSPACE = ROOT / ".factory-workspace"
RUNS_DB = os.environ["NOTION_RUNS_DB_ID"]
FEATURES_DB = os.environ["NOTION_FEATURES_DB_ID"]

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

def _rich_text(props: dict, key: str) -> str:
    items = props.get(key, {}).get("rich_text", [])
    return "".join(i["plain_text"] for i in items)


def _title_text(props: dict) -> str:
    items = props.get("Title", {}).get("title", [])
    return "".join(i["plain_text"] for i in items)


def _multi_select(props: dict, key: str) -> list[str]:
    return [i["name"] for i in props.get(key, {}).get("multi_select", [])]


def _url_field(props: dict, key: str) -> str:
    return props.get(key, {}).get("url") or ""


def _page_status(props: dict) -> str:
    status_prop = props.get("Status", {})
    return (
        (status_prop.get("status") or {}).get("name") or
        (status_prop.get("select") or {}).get("name") or
        "Unknown"
    )


def load_spec(feature_id: str) -> dict:
    page = get_page(feature_id)
    props = page["properties"]

    description = _rich_text(props, "Description")
    tech_notes = _rich_text(props, "Tech Notes")

    # Fetch dependency context so orchestrator and agents can build on prior work
    dep_relations = props.get("Depends On", {}).get("relation", [])
    dependencies = []
    for dep in dep_relations:
        dep_page = get_page(dep["id"])
        dp = dep_page["properties"]
        dep_desc = _rich_text(dp, "Description") or _rich_text(dp, "Tech Notes")
        dependencies.append({
            "id": dep["id"],
            "title": _title_text(dp),
            "status": _page_status(dp),
            "description": dep_desc,
        })

    return {
        "feature_id": feature_id,
        "title": _title_text(props),
        "description": description or tech_notes,
        "tech_notes": tech_notes,
        "acceptance_criteria": _rich_text(props, "Acceptance Criteria"),
        "out_of_scope": _rich_text(props, "Out of Scope"),
        "affected_roles": _multi_select(props, "Affected Roles"),
        "design_url": _url_field(props, "Design URL"),
        "feature_flag": _rich_text(props, "Feature Flag"),
        "dependencies": dependencies,
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


def get_unblocked_queued_features() -> list[str]:
    """Returns IDs of Queued features whose dependencies are all Done."""
    queued_pages = query_database(FEATURES_DB, filter_obj={
        "property": "Status",
        "select": {"equals": "Queued"},
    })
    unblocked = []
    for page in queued_pages:
        deps = page["properties"].get("Depends On", {}).get("relation", [])
        if not deps:
            continue
        all_done = all(
            _page_status(get_page(dep["id"])["properties"]) == "Done"
            for dep in deps
        )
        if all_done:
            unblocked.append(page["id"])
    return unblocked


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

        # Strip every character that git disallows in branch names; collapse hyphens
        slug = re.sub(r"[^a-z0-9]+", "-", spec["title"].lower()).strip("-")[:50]
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
        try:
            log_run(feature_id, agents_fired, "Failed", duration, error=error_msg)
        except Exception as e2:
            print(f"WARNING: log_run failed: {e2}", file=sys.stderr)
        try:
            set_status(feature_id, "Failed", {
                "Error Log": {"rich_text": [{"text": {"content": error_msg[:2000]}}]},
            })
        except Exception as e2:
            print(f"WARNING: set_status failed: {e2}", file=sys.stderr)
        if branch_name:
            try:
                delete_remote_branch(branch_name)
            except Exception as e2:
                print(f"WARNING: delete_remote_branch failed: {e2}", file=sys.stderr)
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

        # Auto-trigger any Queued features that are now unblocked
        try:
            unblocked = get_unblocked_queued_features()
            for unblocked_id in unblocked:
                print(f"Auto-triggering newly unblocked feature: {unblocked_id}")
                trigger_repository_dispatch(unblocked_id)
        except Exception as e:
            print(f"WARNING: auto-trigger check failed: {e}", file=sys.stderr)

    except Exception as exc:
        error_msg = str(exc)
        print(f"Merge FAILED: {error_msg}", file=sys.stderr)
        try:
            log_run(feature_id, agents_fired, "Failed", duration, error=error_msg)
        except Exception as e2:
            print(f"WARNING: log_run failed: {e2}", file=sys.stderr)
        try:
            set_status(feature_id, "Failed", {
                "Error Log": {"rich_text": [{"text": {"content": error_msg[:2000]}}]},
            })
        except Exception as e2:
            print(f"WARNING: set_status failed: {e2}", file=sys.stderr)
        try:
            delete_remote_branch(branch_name)
        except Exception as e2:
            print(f"WARNING: delete_remote_branch failed: {e2}", file=sys.stderr)
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
    try:
        log_run(feature_id, agents_fired, "Failed", duration, error=error_msg)
    except Exception as e:
        print(f"WARNING: log_run failed: {e}", file=sys.stderr)
    try:
        set_status(feature_id, "Failed", {
            "Error Log": {"rich_text": [{"text": {"content": error_msg[:2000]}}]},
        })
    except Exception as e:
        print(f"WARNING: set_status failed: {e}", file=sys.stderr)
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
