"""Filesystem/path helpers shared by deployment frontends."""

from __future__ import annotations

from pathlib import Path


def relative_to_root(path: Path | None, root: Path) -> bool:
    """Return whether *path* resolves below *root*."""
    if path is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
