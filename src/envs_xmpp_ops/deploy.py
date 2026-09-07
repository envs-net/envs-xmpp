"""Shared high-level deployment path calculations."""

from __future__ import annotations

import filecmp
import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import relative_to_root
from .profile import DeploymentProfile


@dataclass(frozen=True)
class DeploymentPaths:
    root: Path
    venv: Path
    config: Path
    data: Path


@dataclass(frozen=True)
class ProtectedFileBackup:
    """One temporary backup of an operator-owned file inside a checkout."""

    label: str
    path: Path
    backup: Path


def resolve_paths(root: str | Path, profile: DeploymentProfile) -> DeploymentPaths:
    app_root = Path(root).resolve()
    return DeploymentPaths(
        root=app_root,
        venv=app_root / profile.venv_name,
        config=Path(profile.default_config),
        data=Path(profile.default_data),
    )


def backup_checkout_files(
    protected: dict[str, Path],
    *,
    root: Path,
    backup_dir: Path,
    print_func=print,
) -> list[ProtectedFileBackup]:
    """Temporarily preserve existing regular files that live inside *root*.

    External runtime paths are intentionally ignored: a Git checkout cannot
    overwrite them, so copying them during a code update only adds risk and
    work without protecting anything.
    """
    backups: list[ProtectedFileBackup] = []
    for label, path in protected.items():
        if not path.is_file() or not relative_to_root(path, root):
            continue
        target = backup_dir / f"{len(backups):02d}-{path.name}"
        shutil.copy2(path, target)
        backups.append(ProtectedFileBackup(label=label, path=path, backup=target))
        print_func(f"PROTECT {label}: {path}")
    return backups


def restore_checkout_files(
    backups: list[ProtectedFileBackup],
    *,
    print_func=print,
) -> None:
    """Restore checkout files whose content changed while switching revisions."""
    for item in backups:
        unchanged = item.path.is_file() and filecmp.cmp(
            item.path,
            item.backup,
            shallow=False,
        )
        if unchanged:
            continue
        item.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.backup, item.path)
        print_func(f"RESTORE protected {item.label}: {item.path}")
