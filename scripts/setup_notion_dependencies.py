#!/usr/bin/env python3
"""
One-time setup: adds "Depends On" relation and "Queued" status to the Notion
Features DB, then wires dependencies for the four foundation features.

Run from repo root:
  PYTHONPATH=scripts python scripts/setup_notion_dependencies.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import requests

NOTION_API_KEY = os.environ["NOTION_API_KEY"]
FEATURES_DB_ID = os.environ["NOTION_FEATURES_DB_ID"]
NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def get_database() -> dict:
    resp = requests.get(f"{BASE_URL}/databases/{FEATURES_DB_ID}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def patch_database(properties: dict) -> dict:
    resp = requests.patch(
        f"{BASE_URL}/databases/{FEATURES_DB_ID}",
        headers=_headers(),
        json={"properties": properties},
    )
    resp.raise_for_status()
    return resp.json()


def query_database(filter_obj: dict = None) -> list[dict]:
    payload = {}
    if filter_obj:
        payload["filter"] = filter_obj
    resp = requests.post(
        f"{BASE_URL}/databases/{FEATURES_DB_ID}/query",
        headers=_headers(),
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["results"]


def update_page(page_id: str, properties: dict) -> dict:
    resp = requests.patch(
        f"{BASE_URL}/pages/{page_id}",
        headers=_headers(),
        json={"properties": properties},
    )
    resp.raise_for_status()
    return resp.json()


def add_depends_on_relation() -> None:
    """Adds a self-referencing 'Depends On' relation to the Features DB."""
    db = get_database()
    if "Depends On" in db.get("properties", {}):
        print("  'Depends On' property already exists -- skipping")
        return

    patch_database({
        "Depends On": {
            "type": "relation",
            "relation": {
                "database_id": FEATURES_DB_ID,
                "single_property": {},
            },
        }
    })
    print("  Added 'Depends On' relation property")


def add_queued_status() -> None:
    """Adds 'Queued' as a status option to the Status property."""
    db = get_database()
    status_prop = db.get("properties", {}).get("Status", {})
    prop_type = status_prop.get("type")

    if prop_type == "select":
        existing_options = status_prop.get("select", {}).get("options", [])
        if any(o["name"] == "Queued" for o in existing_options):
            print("  'Queued' select option already exists -- skipping")
            return
        patch_database({
            "Status": {
                "select": {
                    "options": existing_options + [{"name": "Queued", "color": "yellow"}],
                }
            }
        })
        print("  Added 'Queued' as a select option")
    elif prop_type == "status":
        existing_options = status_prop.get("status", {}).get("options", [])
        existing_groups = status_prop.get("status", {}).get("groups", [])
        if any(o["name"] == "Queued" for o in existing_options):
            print("  'Queued' status option already exists -- skipping")
            return
        patch_database({
            "Status": {
                "status": {
                    "options": existing_options + [{"name": "Queued", "color": "yellow"}],
                    "groups": existing_groups,
                }
            }
        })
        print("  Added 'Queued' as a status option")
    else:
        print(f"  WARNING: Status property type '{prop_type}' not handled -- skipping")


def find_feature_by_title(title: str) -> str | None:
    """Returns the page ID for a feature matching the given title, or None."""
    pages = query_database()
    for page in pages:
        title_items = page["properties"].get("Title", {}).get("title", [])
        page_title = "".join(i["plain_text"] for i in title_items)
        if page_title.strip() == title.strip():
            return page["id"]
    return None


def wire_dependencies() -> None:
    """Sets Depends On relations for the four foundation features.

    Dependency map:
      Core Backend Setup          -- no deps (base layer)
      Terraform - Cognito & RDS   -- no deps (infra can run in parallel)
      Org, Engagement & Invitation API  -- depends on Core Backend
      React Frontend Scaffold     -- depends on Core Backend
    """
    core_backend_title = "Foundation: Core Backend Setup"
    core_backend_id = find_feature_by_title(core_backend_title)
    if not core_backend_id:
        print(f"  WARNING: could not find '{core_backend_title}' -- skipping dependency wiring")
        return
    print(f"  Core Backend id: {core_backend_id}")

    dependents = [
        "Foundation: Org, Engagement & Invitation API",
        "Foundation: React Frontend Scaffold",
    ]

    for title in dependents:
        page_id = find_feature_by_title(title)
        if not page_id:
            print(f"  WARNING: could not find '{title}' -- skipping")
            continue
        update_page(page_id, {
            "Depends On": {
                "relation": [{"id": core_backend_id}]
            }
        })
        print(f"  Wired '{title}' -> depends on Core Backend")


def main() -> None:
    print("Setting up Notion dependency system...")

    print("\n1. Adding 'Depends On' relation property...")
    add_depends_on_relation()

    print("\n2. Adding 'Queued' status option...")
    add_queued_status()

    print("\n3. Wiring dependencies for foundation features...")
    wire_dependencies()

    print("\nDone.")


if __name__ == "__main__":
    main()
