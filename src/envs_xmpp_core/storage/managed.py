"""Managed runtime-file catalog, resolution, and retention primitives."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class ManagedFile:
    """Metadata for one managed file."""

    path: Path
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def mtime_text(self) -> str:
        return datetime.fromtimestamp(self.mtime, tz=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def is_relative_to(path: Path, directory: Path) -> bool:
    """Return whether ``path`` is contained by ``directory``."""
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def list_managed_files(
    directory: Path,
    pattern: str,
    *,
    exclude_suffixes: Iterable[str] = (),
    predicate: Callable[[Path], bool] | None = None,
) -> list[ManagedFile]:
    """List matching regular files sorted newest first."""
    if not directory.exists():
        return []

    excluded = tuple(exclude_suffixes)
    files: list[ManagedFile] = []
    for path in directory.glob(pattern):
        if not path.is_file():
            continue
        if excluded and path.name.endswith(excluded):
            continue
        if predicate is not None and not predicate(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append(ManagedFile(path=path, size=stat.st_size, mtime=stat.st_mtime))

    files.sort(key=lambda item: (item.mtime, item.name), reverse=True)
    return files


def resolve_managed_file(
    directory: Path,
    query: str,
    files: list[ManagedFile],
    *,
    predicate: Callable[[Path], bool] | None = None,
    latest_aliases: Iterable[str] = ("latest",),
) -> Path | None:
    """Resolve a managed file by alias, basename, or contained path.

    Paths outside ``directory`` are rejected even when they point at an
    existing file. ``latest_aliases`` lets applications preserve command
    vocabulary such as ``latest`` or ``last`` without duplicating resolution
    logic.
    """
    value = str(query).strip()
    if not value or not files:
        return None

    aliases = {str(alias).strip().lower() for alias in latest_aliases if str(alias).strip()}
    if value.lower() in aliases:
        return files[0].path

    for managed_file in files:
        if value == managed_file.name or value == str(managed_file.path):
            return managed_file.path

    base_dir = directory.resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = directory / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None

    if not is_relative_to(resolved, base_dir):
        return None
    if not resolved.is_file():
        return None
    if predicate is not None and not predicate(resolved):
        return None
    return resolved


def select_managed_files_for_prune(
    files: Iterable[ManagedFile],
    *,
    keep: int,
    preserve: Path | None = None,
    max_age_seconds: float | None = None,
    now: float | None = None,
) -> list[ManagedFile]:
    """Return files selected by count and optional age retention.

    ``files`` are expected newest first, matching :func:`list_managed_files`.
    A preserved file counts toward the keep budget but is never selected for
    deletion. Age retention is additive: an old file may be selected even when
    it is otherwise within the count budget.
    """
    materialized = list(files)
    keep = max(0, int(keep))
    preserve_resolved: Path | None = None
    if preserve is not None:
        try:
            preserve_resolved = preserve.resolve()
        except OSError:
            preserve_resolved = preserve

    selected: set[Path] = set()
    kept = 0
    for managed_file in materialized:
        try:
            managed_resolved = managed_file.path.resolve()
        except OSError:
            managed_resolved = managed_file.path

        if preserve_resolved is not None and managed_resolved == preserve_resolved:
            kept += 1
            continue
        if kept < keep:
            kept += 1
            continue
        selected.add(managed_file.path)

    if max_age_seconds is not None:
        max_age = max(0.0, float(max_age_seconds))
        if now is None:
            now = datetime.now(UTC).timestamp()
        cutoff = float(now) - max_age
        for managed_file in materialized:
            if managed_file.mtime >= cutoff:
                continue
            try:
                managed_resolved = managed_file.path.resolve()
            except OSError:
                managed_resolved = managed_file.path
            if preserve_resolved is not None and managed_resolved == preserve_resolved:
                continue
            selected.add(managed_file.path)

    return [managed_file for managed_file in materialized if managed_file.path in selected]


async def prune_managed_files(
    files: list[ManagedFile],
    *,
    keep: int,
    preserve: Path | None = None,
    delete_companions: Callable[[Path], list[Path]] | None = None,
    max_age_seconds: float | None = None,
    now: float | None = None,
) -> list[Path]:
    """Delete managed files selected by retention and return removed paths."""
    planned = select_managed_files_for_prune(
        files,
        keep=keep,
        preserve=preserve,
        max_age_seconds=max_age_seconds,
        now=now,
    )
    removed: list[Path] = []
    for managed_file in planned:
        managed_file.path.unlink()
        removed.append(managed_file.path)
        if delete_companions is not None:
            for companion in delete_companions(managed_file.path):
                if companion.exists():
                    companion.unlink()
                    removed.append(companion)
    return removed
