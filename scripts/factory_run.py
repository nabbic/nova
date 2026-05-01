#!/usr/bin/env python3
"""
Main factory entry point. Called by GitHub Actions with a Notion feature ID.
Usage: PYTHONPATH=scripts python scripts/factory_run.py <feature_id>
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
FEATURES_DB = os.environ["NOTION_FEATURES_DB_ID"]
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
        items = props.get(key, {}).get("multi_select", [])
        return [i["name"] for i in items]

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


def log_run(
    feature_id: str,
    agents_fired: list[str],
    outcome: str,
    duration: float,
    error: str = "",
) -> None:
    run_id = f"run-{int(time.time())}"
    create_page(
        parent_id=RUNS_DB,
        parent_type="database",
        properties={
            "Run ID": {"title": [{"text": {"content": run_id}}]},
            "Feature": {"rich_text": [{"text": {"content": feature_id}}]},
            "Agents Fired": {"rich_text": [{"text": {"content": ", ".join(agents_fired)}}]},
            "Outcome": {"select": {"name": outcome}},
            "Duration (s)": {"number": round(duration, 1)},
            "Error": {"rich_text": [{"text": {"content": error}}]},
            "Started": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
        },
    )


def delete_remote_branch(branch_name: str) -> None:
    try:
        subprocess.run(
            ["git", "push", "origin", "--delete", branch_name],
            check=True,
            capture_output=True,
        )
        print(f"Cleaned up remote branch: {branch_name}")
    except subprocess.CalledProcessError:
        pass  # Branch may not have been pushed yet — that's fine


def main(feature_id: str) -> None:
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
        agents_to_run = [a for a in AGENT_SEQUENCE if a not in skipped]

        for agent_name in agents_to_run:
            print(f"Running {agent_name}...")
            run_agent(agent_name, plan)
            agents_fired.append(agent_name)

            if agent_name == "spec-analyst":
                reqs_path = WORKSPACE / "requirements.json"
                if reqs_path.exists():
                    reqs = json.loads(reqs_path.read_text())
                    if reqs.get("blockers"):
                        blockers = "; ".join(reqs["blockers"])
                        raise RuntimeError(f"Spec blocked: {blockers}")

        review = check_security_review()
        if not review["passed"]:
            issues_text = json.dumps(review["issues"], indent=2)
            raise RuntimeError(f"Security review failed:\n{issues_text}")

        commit_all(f"feat: {spec['title']} (factory build)")
        push_branch(branch_name)

        pr_body = (
            f"## {spec['title']}\n\n"
            f"Built by Nova Software Factory.\n\n"
            f"**Agents:** {', '.join(agents_fired)}\n\n"
            f"**Feature ID:** {feature_id}"
        )
        pr_url = create_pr(spec["title"], pr_body, branch_name)
        approve_and_merge_pr(pr_url)

        duration = time.time() - start
        log_run(feature_id, agents_fired, "Success", duration)
        set_status(feature_id, "Done", {"PR Link": {"url": pr_url}})
        print(f"Factory run complete in {duration:.1f}s. PR: {pr_url}")

    except Exception as exc:
        duration = time.time() - start
        error_msg = str(exc)
        print(f"Factory run FAILED: {error_msg}", file=sys.stderr)
        log_run(feature_id, agents_fired, "Failed", duration, error=error_msg)
        set_status(feature_id, "Failed", {
            "Error Log": {"rich_text": [{"text": {"content": error_msg[:2000]}}]},
        })
        if branch_name:
            delete_remote_branch(branch_name)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: PYTHONPATH=scripts python scripts/factory_run.py <feature_id>")
        sys.exit(1)
    main(sys.argv[1])
