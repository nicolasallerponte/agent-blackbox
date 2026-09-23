"""Fixtures for integration tests against real git repositories."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

if sys.platform == "win32":  # pragma: no cover - POSIX only (ADR-0006)
    collect_ignore_glob = ["*"]


@pytest.fixture(autouse=True)
def isolated_git_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep the host's git configuration and environment out of every test."""
    home = tmp_path_factory.mktemp("home")
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Test User\n\temail = test@example.invalid\n"
        "[init]\n\tdefaultBranch = main\n",
        encoding="utf-8",
    )
    saved = dict(os.environ)
    for key in list(os.environ):
        if key.startswith("GIT_"):
            del os.environ[key]
    os.environ["HOME"] = str(home)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def git(cwd: Path, *args: str) -> str:
    """Run git in a user repository (not the shadow) and return stdout."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A git repository with one commit, plus an uncommitted change."""
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (root / ".gitignore").write_text("node_modules/\n*.log\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    (root / "app.py").write_text("print('hello')\n", encoding="utf-8")  # uncommitted
    return root


def snapshot_files(tree_listing: str) -> list[str]:
    """Paths from ``git ls-tree -r --name-only`` output."""
    return sorted(line for line in tree_listing.splitlines() if line)
