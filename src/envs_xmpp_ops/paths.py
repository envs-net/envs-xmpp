"""Filesystem/path helpers shared by deployment frontends."""

from __future__ import annotations

from collections.abc import Callable, Sequence
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


def require_source_tree(
    root: Path,
    required: Sequence[str],
    *,
    project_name: str,
    error_factory: Callable[[str], Exception] = RuntimeError,
) -> None:
    """Require marker files that identify an expected deployment checkout."""
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise error_factory(f"not a {project_name} source checkout: {root} (missing: {', '.join(missing)})")
