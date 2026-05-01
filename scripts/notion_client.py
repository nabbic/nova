import os
import requests
from typing import Any

NOTION_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def create_database(parent_page_id: str, title: str, properties: dict) -> dict:
    resp = requests.post(
        f"{BASE_URL}/databases",
        headers=_headers(),
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        },
    )
    resp.raise_for_status()
    return resp.json()


def create_page(parent_id: str, parent_type: str, properties: dict, content: list = None) -> dict:
    payload: dict[str, Any] = {
        "parent": {"type": f"{parent_type}_id", f"{parent_type}_id": parent_id},
        "properties": properties,
    }
    if content:
        payload["children"] = content
    resp = requests.post(f"{BASE_URL}/pages", headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()


def update_page(page_id: str, properties: dict) -> dict:
    resp = requests.patch(
        f"{BASE_URL}/pages/{page_id}",
        headers=_headers(),
        json={"properties": properties},
    )
    resp.raise_for_status()
    return resp.json()


def get_page(page_id: str) -> dict:
    resp = requests.get(f"{BASE_URL}/pages/{page_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def query_database(database_id: str, filter_obj: dict = None) -> list[dict]:
    payload = {}
    if filter_obj:
        payload["filter"] = filter_obj
    resp = requests.post(
        f"{BASE_URL}/databases/{database_id}/query",
        headers=_headers(),
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["results"]


def append_block(page_id: str, children: list) -> dict:
    resp = requests.patch(
        f"{BASE_URL}/blocks/{page_id}/children",
        headers=_headers(),
        json={"children": children},
    )
    resp.raise_for_status()
    return resp.json()
