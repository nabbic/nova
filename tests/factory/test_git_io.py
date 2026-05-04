"""Tests for git tarball pack/unpack."""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "factory_lambdas" / "containers" / "ralph_turn"))

from git_io import pack_git, unpack_git  # noqa: E402


def test_pack_then_unpack_preserves_git_state(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "x.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
    sha_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True).stdout.strip()

    tarball = tmp_path / "git.tar.gz"
    pack_git(repo, tarball)
    assert tarball.exists() and tarball.stat().st_size > 0

    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    (repo2 / "x.txt").write_text("hello\n")
    unpack_git(tarball, repo2)
    sha_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo2, check=True, capture_output=True).stdout.strip()

    assert sha_after == sha_before


def test_pack_only_includes_git_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "junk.txt").write_text("not a git file")

    tarball = tmp_path / "git.tar.gz"
    pack_git(repo, tarball)

    with tarfile.open(tarball, "r:gz") as tf:
        names = tf.getnames()
    assert all(n == ".git" or n.startswith(".git/") for n in names), names
