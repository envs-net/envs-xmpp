"""Small git helpers used by deployment frontends."""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(root: str | Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=Path(root),
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def worktree_is_clean(root: str | Path) -> bool:
    return not run_git(root, "status", "--porcelain")


def current_revision(root: str | Path) -> str:
    return run_git(root, "rev-parse", "HEAD")
