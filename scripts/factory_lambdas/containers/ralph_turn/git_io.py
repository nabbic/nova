"""Pack and unpack the .git directory of a workspace as a tarball.

The RalphTurn Lambda preserves git history across turns by tarring up .git
into S3 between invocations. The full code tree is also re-materialized
each turn but its history-bearing state lives only in .git.
"""

from __future__ import annotations

import tarfile
from pathlib import Path


def pack_git(repo_root: Path, out_tarball: Path) -> None:
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        raise FileNotFoundError(f"{git_dir} is not a git directory")
    out_tarball.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_tarball, "w:gz") as tf:
        tf.add(git_dir, arcname=".git")


def unpack_git(tarball: Path, repo_root: Path) -> None:
    repo_root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tf:
        for member in tf.getmembers():
            # Reject paths attempting traversal
            if member.name.startswith("..") or "/.." in member.name or member.name.startswith("/"):
                raise RuntimeError(f"refusing to extract suspicious path: {member.name}")
        tf.extractall(repo_root)
