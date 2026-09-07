"""Shared high-level deployment path calculations."""

from __future__ import annotations

import filecmp
import shutil
import sys
import tempfile
from collections.abc import Callable
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
class ReleaseUpdateResult:
    """Outcome of the shared release-update transaction."""

    remote: str
    target: str
    changed: bool
    stopped: bool


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


def run_release_update_transaction(
    *,
    root: Path,
    prepare_target: Callable[[], tuple[str, str]],
    approve_target: Callable[[str], bool],
    protected_paths: Callable[[], dict[str, Path]],
    stop_service: Callable[[], bool],
    checkout_target: Callable[[str], None],
    apply_target: Callable[[str], None],
    ask_start: Callable[[], None],
    before_checkout: Callable[[], None] | None = None,
    temp_prefix: str = "envs-xmpp-deploy-",
    announce_protected: bool = False,
    failure_message: str | None = None,
    print_func: Callable[[str], None] = print,
) -> ReleaseUpdateResult:
    """Run the shared mutable part of a stable-release deployment.

    Frontends keep preflight, plan rendering, confirmation and application-
    specific validation.  This helper owns the common release selection,
    service-stop boundary, checkout-file preservation, checkout, post-checkout
    application hook, restart prompt and failure-state handling.

    Protected checkout files are restored in a ``finally`` block even when
    ``git checkout`` fails.  The helper deliberately does not roll Git or a
    database back after an application hook fails; callers keep the service
    stopped so an operator can inspect the partially updated deployment.
    """
    remote, target = prepare_target()
    print_func(f"Selected release: {target} (remote: {remote})")
    if not approve_target(target):
        return ReleaseUpdateResult(
            remote=remote,
            target=target,
            changed=False,
            stopped=False,
        )

    protected = protected_paths()
    if announce_protected:
        print_func("\nProtected operator files:")
        for label, path in protected.items():
            state = "exists" if path.exists() else "missing"
            print_func(f"  {label}: {path} ({state})")

    stopped = stop_service()
    try:
        if before_checkout is not None:
            before_checkout()
        with tempfile.TemporaryDirectory(prefix=temp_prefix) as temporary:
            backups = backup_checkout_files(
                protected,
                root=root,
                backup_dir=Path(temporary),
                print_func=print_func,
            )
            try:
                checkout_target(target)
            finally:
                restore_checkout_files(backups, print_func=print_func)
        apply_target(target)
    except BaseException:
        if stopped and failure_message:
            print(f"\n{failure_message}", file=sys.stderr)
        raise

    ask_start()
    print_func(f"Update to {target} completed.")
    return ReleaseUpdateResult(
        remote=remote,
        target=target,
        changed=True,
        stopped=stopped,
    )
