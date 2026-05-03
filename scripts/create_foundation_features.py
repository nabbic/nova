#!/usr/bin/env python3
"""
Template for creating factory feature pages in Notion.
Each feature gets discrete fields: Description, Tech Notes, Acceptance Criteria,
Out of Scope, Affected Roles, Design URL.

Run: PYTHONPATH=scripts /c/Python314/python scripts/create_foundation_features.py
"""
import os
from notion_client import create_page

FEATURES_DB = os.environ["NOTION_FEATURES_DB_ID"]
CHUNK = 1900  # Notion rich_text block limit is 2000; stay safely under


def rich_blocks(text: str) -> list:
    blocks = []
    while text:
        blocks.append({"type": "text", "text": {"content": text[:CHUNK]}})
        text = text[CHUNK:]
    return blocks or [{"type": "text", "text": {"content": ""}}]


def create_feature(
    title: str,
    description: str,
    tech_notes: str,
    acceptance_criteria: str,
    out_of_scope: str,
    affected_roles: list[str],
    design_url: str = "",
    feature_flag: str = "",
) -> dict:
    props = {
        "Title": {"title": [{"type": "text", "text": {"content": title}}]},
        "Description": {"rich_text": rich_blocks(description)},
        "Tech Notes": {"rich_text": rich_blocks(tech_notes)},
        "Acceptance Criteria": {"rich_text": rich_blocks(acceptance_criteria)},
        "Out of Scope": {"rich_text": rich_blocks(out_of_scope)},
        "Affected Roles": {"multi_select": [{"name": r} for r in affected_roles]},
        "Status": {"select": {"name": "Spec Ready"}},
    }
    if design_url:
        props["Design URL"] = {"url": design_url}
    if feature_flag:
        props["Feature Flag"] = {"rich_text": rich_blocks(feature_flag)}
    return create_page(parent_id=FEATURES_DB, parent_type="database", properties=props)


# ---------------------------------------------------------------------------
# Platform Foundation features (already created — kept here as reference)
# To create new sub-project features, add entries to FEATURES below.
# ---------------------------------------------------------------------------

FEATURES: list[dict] = [
    # Add new features here following the same structure.
    # Example:
    # {
    #     "title": "Sub-project 2: Cloud Connector Framework",
    #     "description": "...",
    #     "tech_notes": "...",
    #     "acceptance_criteria": "...",
    #     "out_of_scope": "...",
    #     "affected_roles": ["backend", "infrastructure"],
    #     "design_url": "https://github.com/nabbic/nova/blob/main/docs/...",
    # },
]


if __name__ == "__main__":
    if not FEATURES:
        print("No features defined in FEATURES list. Add entries and re-run.")
    for f in FEATURES:
        result = create_feature(**f)
        print(f"Created: {f['title']}")
        print(f"  Page ID: {result['id']}")
        print(f"  URL:     {result.get('url', 'N/A')}")
        print()
    print(f"Done. {len(FEATURES)} feature(s) created with status 'Spec Ready'.")
    print("Flip each to 'Ready to Build' in Notion to trigger the factory.")
