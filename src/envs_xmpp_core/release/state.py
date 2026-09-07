"""Persistent release-state primitives shared by envs.net XMPP bots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .versions import normalize_version

RELEASE_STATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS release_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version TEXT,
    pending_from TEXT,
    pending_to TEXT,
    updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
)
"""

_SELECT_RELEASE_STATE = (
    "SELECT version, pending_from, pending_to FROM release_state WHERE id = 1"
)

_UPSERT_RELEASE_STATE = """
INSERT INTO release_state (id, version, pending_from, pending_to, updated_at)
VALUES (1, ?, ?, ?, strftime('%s','now'))
ON CONFLICT(id) DO UPDATE SET
    version = excluded.version,
    pending_from = excluded.pending_from,
    pending_to = excluded.pending_to,
    updated_at = excluded.updated_at
"""

_CLEAR_PENDING_IF_MATCHES = """
UPDATE release_state
SET pending_from = NULL,
    pending_to = NULL,
    updated_at = strftime('%s','now')
WHERE id = 1 AND pending_from = ? AND pending_to = ?
"""


def _known_version(value: object) -> str | None:
    normalized = normalize_version(str(value or "")).strip()
    if not normalized or normalized.lower() == "unknown":
        return None
    return normalized


@dataclass(frozen=True, slots=True)
class ReleaseState:
    """Last successfully started version plus one undelivered announcement."""

    version: str | None = None
    pending_from: str | None = None
    pending_to: str | None = None

    def __post_init__(self) -> None:
        version = _known_version(self.version)
        pending_from = _known_version(self.pending_from)
        pending_to = _known_version(self.pending_to)
        if pending_from == pending_to:
            pending_from = None
            pending_to = None
        if (pending_from is None) != (pending_to is None):
            pending_from = None
            pending_to = None
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "pending_from", pending_from)
        object.__setattr__(self, "pending_to", pending_to)

    @property
    def pending_announcement(self) -> dict[str, str] | None:
        if self.pending_from is None or self.pending_to is None:
            return None
        return {"from": self.pending_from, "to": self.pending_to}

    def as_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self.version is not None:
            result["version"] = self.version
        pending = self.pending_announcement
        if pending is not None:
            result["pending_announcement"] = pending
        return result

    @classmethod
    def from_mapping(cls, value: object) -> ReleaseState:
        if not isinstance(value, Mapping):
            return cls()
        pending = value.get("pending_announcement")
        pending_from: object = None
        pending_to: object = None
        if isinstance(pending, Mapping):
            pending_from = pending.get("from")
            pending_to = pending.get("to")
        return cls(
            version=_known_version(value.get("version")),
            pending_from=_known_version(pending_from),
            pending_to=_known_version(pending_to),
        )

    @classmethod
    def from_row(cls, row: Sequence[Any] | None) -> ReleaseState:
        if row is None:
            return cls()
        return cls(version=row[0], pending_from=row[1], pending_to=row[2])


class ReleaseStateSqlBackend(Protocol):
    """Small async SQL contract required by :class:`ReleaseStateSqlRepository`."""

    def available(self) -> bool: ...

    async def execute(
        self,
        query: str,
        params: Sequence[Any] = (),
        *,
        label: str = "release_state",
    ) -> int: ...

    async def fetch_one(
        self,
        query: str,
        params: Sequence[Any] = (),
    ) -> Sequence[Any] | None: ...


class ReleaseStateSqlRepository:
    """Shared SQLite-style persistence for successful startup release state."""

    def __init__(self, backend: ReleaseStateSqlBackend) -> None:
        self.backend = backend

    def available(self) -> bool:
        return self.backend.available()

    async def setup(self) -> None:
        if not self.available():
            return
        await self.backend.execute(RELEASE_STATE_TABLE_SQL, label="release_state_init")

    async def load(self) -> ReleaseState:
        if not self.available():
            return ReleaseState()
        row = await self.backend.fetch_one(_SELECT_RELEASE_STATE)
        return ReleaseState.from_row(row)

    async def save(self, state: ReleaseState) -> None:
        if not self.available():
            raise RuntimeError("release state database is unavailable")
        await self.backend.execute(
            _UPSERT_RELEASE_STATE,
            (state.version, state.pending_from, state.pending_to),
            label="release_state_save",
        )

    async def clear_pending_if_matches(self, previous_version: object, current_version: object) -> bool:
        if not self.available():
            return False
        previous = _known_version(previous_version)
        current = _known_version(current_version)
        if previous is None or current is None:
            return False
        affected = await self.backend.execute(
            _CLEAR_PENDING_IF_MATCHES,
            (previous, current),
            label="release_state_clear_pending",
        )
        return affected > 0
