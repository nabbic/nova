#!/usr/bin/env python3
"""
One-time script to bootstrap the Nova Notion workspace.
Run once with: python scripts/setup_notion.py <parent-page-id>

The parent page must already exist in your Notion workspace.
After running, copy the printed database IDs to GitHub Secrets.
"""
import sys
import json
from notion_client import create_database, create_page


def create_features_db(parent_page_id: str) -> str:
    db = create_database(
        parent_page_id=parent_page_id,
        title="Features",
        properties={
            "Title": {"title": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Idea", "color": "gray"},
                        {"name": "Spec Draft", "color": "blue"},
                        {"name": "Ready to Build", "color": "yellow"},
                        {"name": "In Progress", "color": "orange"},
                        {"name": "Done", "color": "green"},
                        {"name": "Failed", "color": "red"},
                    ]
                }
            },
            "Priority": {
                "select": {
                    "options": [
                        {"name": "High", "color": "red"},
                        {"name": "Medium", "color": "yellow"},
                        {"name": "Low", "color": "gray"},
                    ]
                }
            },
            "Tech Notes": {"rich_text": {}},
            "PR Link": {"url": {}},
            "Deploy URL": {"url": {}},
            "Agent Run ID": {"rich_text": {}},
            "Error Log": {"rich_text": {}},
        },
    )
    return db["id"]


def create_decisions_db(parent_page_id: str) -> str:
    db = create_database(
        parent_page_id=parent_page_id,
        title="Decisions Log",
        properties={
            "Decision": {"title": {}},
            "Area": {
                "select": {
                    "options": [
                        {"name": "Frontend", "color": "blue"},
                        {"name": "Backend", "color": "green"},
                        {"name": "Database", "color": "orange"},
                        {"name": "Infrastructure", "color": "purple"},
                        {"name": "Auth", "color": "red"},
                    ]
                }
            },
            "Choice": {"rich_text": {}},
            "Rationale": {"rich_text": {}},
            "Feature": {"rich_text": {}},
            "Date": {"date": {}},
        },
    )
    return db["id"]


def create_runs_db(parent_page_id: str) -> str:
    db = create_database(
        parent_page_id=parent_page_id,
        title="Agent Runs",
        properties={
            "Run ID": {"title": {}},
            "Feature": {"rich_text": {}},
            "Agents Fired": {"rich_text": {}},
            "Outcome": {
                "select": {
                    "options": [
                        {"name": "Success", "color": "green"},
                        {"name": "Failed", "color": "red"},
                        {"name": "Blocked", "color": "yellow"},
                    ]
                }
            },
            "Duration (s)": {"number": {}},
            "Error": {"rich_text": {}},
            "Started": {"date": {}},
        },
    )
    return db["id"]


def create_project_brief_page(parent_page_id: str) -> str:
    page = create_page(
        parent_id=parent_page_id,
        parent_type="page",
        properties={"title": {"title": [{"text": {"content": "Project Brief"}}]}},
        content=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Nova — Product Overview"}}]},
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": "TBD — update as product vision evolves."}}]},
            },
        ],
    )
    return page["id"]


def create_tech_stack_page(parent_page_id: str) -> str:
    page = create_page(
        parent_id=parent_page_id,
        parent_type="page",
        properties={"title": {"title": [{"text": {"content": "Tech Stack"}}]}},
        content=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Tech Stack Decisions"}}]},
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": "Maintained by the Architect agent. Updated automatically on each factory run."}}]
                },
            },
        ],
    )
    return page["id"]


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python setup_notion.py <parent-page-id>")
        sys.exit(1)

    parent_page_id = sys.argv[1]
    print("Setting up Nova Notion workspace...")

    features_db_id = create_features_db(parent_page_id)
    print(f"Features DB: {features_db_id}")

    decisions_db_id = create_decisions_db(parent_page_id)
    print(f"Decisions Log DB: {decisions_db_id}")

    runs_db_id = create_runs_db(parent_page_id)
    print(f"Agent Runs DB: {runs_db_id}")

    brief_page_id = create_project_brief_page(parent_page_id)
    print(f"Project Brief page: {brief_page_id}")

    tech_stack_page_id = create_tech_stack_page(parent_page_id)
    print(f"Tech Stack page: {tech_stack_page_id}")

    print("\n--- Copy these to GitHub Secrets ---")
    print(json.dumps({
        "NOTION_FEATURES_DB_ID": features_db_id,
        "NOTION_DECISIONS_DB_ID": decisions_db_id,
        "NOTION_RUNS_DB_ID": runs_db_id,
    }, indent=2))


if __name__ == "__main__":
    main()
