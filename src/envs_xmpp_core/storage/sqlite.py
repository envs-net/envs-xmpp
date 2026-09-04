"""Small, synchronous SQLite file verification primitives."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SQLiteIntegrityResult:
    """Detached result of read-only SQLite integrity checks."""

    path: Path
    integrity: tuple[str, ...] = ()
    foreign_key_violations: tuple[tuple[Any, ...], ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.integrity == ("ok",)
            and not self.foreign_key_violations
        )

    @property
    def message(self) -> str:
        """Return a concise human-readable result."""
        if self.error:
            return self.error
        if self.integrity != ("ok",):
            return ", ".join(self.integrity or ("no integrity_check result",))
        if self.foreign_key_violations:
            return f"foreign key check failed: {len(self.foreign_key_violations)} violation(s)"
        return "ok"


def check_sqlite_integrity(
    path: str | Path,
    *,
    check_foreign_keys: bool = False,
    require_nonempty_file: bool = False,
) -> SQLiteIntegrityResult:
    """Open a SQLite file read-only and run integrity checks.

    The function deliberately performs no logging, retries, async dispatch, or
    cleanup policy. Callers can adapt the structured result to their existing
    bot-specific messages and workflows.
    """
    resolved = Path(path).expanduser().resolve()
    if require_nonempty_file:
        if not resolved.exists():
            return SQLiteIntegrityResult(
                path=resolved,
                error=f"Database file does not exist: {resolved}",
            )
        if not resolved.is_file():
            return SQLiteIntegrityResult(
                path=resolved,
                error=f"Database path is not a regular file: {resolved}",
            )
        if resolved.stat().st_size <= 0:
            return SQLiteIntegrityResult(
                path=resolved,
                error=f"Database file is empty: {resolved}",
            )

    try:
        connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
        try:
            integrity = tuple(
                str(row[0])
                for row in connection.execute("PRAGMA integrity_check;").fetchall()
            )
            foreign_keys = (
                tuple(
                    tuple(row)
                    for row in connection.execute("PRAGMA foreign_key_check;").fetchall()
                )
                if check_foreign_keys
                else ()
            )
        finally:
            connection.close()
    except Exception as exc:
        return SQLiteIntegrityResult(path=resolved, error=str(exc))

    return SQLiteIntegrityResult(
        path=resolved,
        integrity=integrity,
        foreign_key_violations=foreign_keys,
    )
