"""Filesystem allowlist for the RalphTurn post-execution upload.

Spec §4.3 sandbox boundary 4. Pure string-classification — no I/O.

A path is DENIED if any of:
- Contains '..' anywhere
- Starts with '/'
- Is under .github/workflows/
- Is under infra/factory/
- Is under .factory/ AND is not exactly '.factory/_DONE_'

Otherwise it is ALLOWED.
"""

from __future__ import annotations

from typing import Iterable

ALLOWED = "ALLOWED"
DENIED  = "DENIED"

_DENIED_PREFIXES = (
    ".github/workflows/",
    "infra/factory/",
)
_FACTORY_DONE_SENTINEL = ".factory/_DONE_"


def classify(path: str) -> str:
    if path.startswith("/"):
        return DENIED
    if ".." in path.split("/"):
        return DENIED
    if path.startswith(".factory/"):
        return ALLOWED if path == _FACTORY_DONE_SENTINEL else DENIED
    for prefix in _DENIED_PREFIXES:
        if path.startswith(prefix):
            return DENIED
    return ALLOWED


def partition(paths: Iterable[str]) -> tuple[list[str], list[str]]:
    allowed: list[str] = []
    denied:  list[str] = []
    for p in paths:
        (allowed if classify(p) is ALLOWED else denied).append(p)
    return allowed, denied
