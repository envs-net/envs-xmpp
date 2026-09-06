"""Persistent pending-room-invite state shared by envs.net XMPP bots.

The core owns the normalized model, cache/index bookkeeping, expiry handling,
deduplication, store orchestration and the SQLite-style repository. Each
application only adapts its own database API through a tiny SQL backend.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .invites import invite_is_expired

_INVITE_KEYS = ("id", "room_jid", "inviter", "reason", "created_at")


@dataclass(frozen=True, slots=True, eq=False)
class PendingRoomInvite(Mapping[str, object]):
    """Normalized persistent pending room invite.

    ``Mapping`` compatibility intentionally keeps existing bot code such as
    ``invite["room_jid"]`` and ``invite.get("reason")`` working while moving
    runtime state to a typed immutable model.
    """

    id: int
    room_jid: str
    inviter: str
    reason: str = ""
    created_at: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", int(self.id))
        object.__setattr__(self, "room_jid", str(self.room_jid or "").strip().lower())
        object.__setattr__(self, "inviter", str(self.inviter or "unknown").strip().lower() or "unknown")
        object.__setattr__(self, "reason", str(self.reason or ""))
        object.__setattr__(self, "created_at", int(self.created_at or 0))

    @property
    def key(self) -> tuple[str, str]:
        """Return the uniqueness key used by the persistent table."""
        return self.room_jid, self.inviter

    def __getitem__(self, key: str) -> object:
        if key not in _INVITE_KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(_INVITE_KEYS)

    def __len__(self) -> int:
        return len(_INVITE_KEYS)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, PendingRoomInvite):
            return (
                self.id == other.id
                and self.room_jid == other.room_jid
                and self.inviter == other.inviter
                and self.reason == other.reason
                and self.created_at == other.created_at
            )
        if isinstance(other, Mapping):
            return self.as_dict() == dict(other)
        return NotImplemented

    def as_dict(self) -> dict[str, object]:
        """Return the historical mapping representation."""
        return {
            "id": self.id,
            "room_jid": self.room_jid,
            "inviter": self.inviter,
            "reason": self.reason,
            "created_at": self.created_at,
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        fallback_id: int | None = None,
    ) -> PendingRoomInvite:
        """Normalize a historical mapping into the typed model."""
        invite_id = value.get("id", fallback_id)
        if invite_id is None:
            raise ValueError("pending room invite is missing id")
        return cls(
            id=int(invite_id),
            room_jid=str(value.get("room_jid") or ""),
            inviter=str(value.get("inviter") or "unknown"),
            reason=str(value.get("reason") or ""),
            created_at=int(value.get("created_at") or 0),
        )

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> PendingRoomInvite:
        """Build an invite from ``id, room_jid, inviter, reason, created_at``."""
        if len(row) < 5:
            raise ValueError("pending room invite row must contain five columns")
        return cls(
            id=int(row[0]),
            room_jid=str(row[1] or ""),
            inviter=str(row[2] or "unknown"),
            reason=str(row[3] or ""),
            created_at=int(row[4] or 0),
        )


@dataclass(frozen=True, slots=True)
class PendingRoomInviteStoreResult:
    """Result of storing one pending invite.

    ``created`` is false when the same active ``(room_jid, inviter)`` invite
    already existed. Duplicate delivery therefore does not refresh its reason or
    lifetime.
    """

    invite: PendingRoomInvite
    created: bool


_CREATE_PENDING_INVITES_TABLE = """
CREATE TABLE IF NOT EXISTS room_invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_jid TEXT NOT NULL,
    inviter TEXT NOT NULL,
    reason TEXT,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
    UNIQUE(room_jid, inviter)
)
"""
_CREATE_PENDING_INVITES_CREATED_AT_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_room_invites_created_at "
    "ON room_invites(created_at)"
)
_SELECT_PENDING_INVITES = """
SELECT id, room_jid, inviter, reason, created_at
FROM room_invites
ORDER BY id ASC
"""
_SELECT_PENDING_INVITE_BY_KEY = """
SELECT id, room_jid, inviter, reason, created_at
FROM room_invites
WHERE room_jid = ? AND inviter = ?
"""
_SELECT_PENDING_INVITE_BY_ID = """
SELECT id, room_jid, inviter, reason, created_at
FROM room_invites
WHERE id = ?
"""
_INSERT_PENDING_INVITE = """
INSERT INTO room_invites (room_jid, inviter, reason, created_at)
VALUES (?, ?, ?, ?)
ON CONFLICT(room_jid, inviter) DO NOTHING
"""


class PendingRoomInviteSqlBackend(Protocol):
    """Minimal async SQL backend needed by the shared invite repository."""

    def available(self) -> bool:
        """Return whether database access is currently usable."""
        ...

    async def execute(
        self,
        query: str,
        params: Sequence[Any] = (),
        *,
        label: str = "room_invites",
    ) -> int:
        """Execute a write/DDL statement and return affected rows when known."""
        ...

    async def fetch_one(
        self,
        query: str,
        params: Sequence[Any] = (),
    ) -> Sequence[Any] | None:
        """Fetch one row or ``None``."""
        ...

    async def fetch_all(
        self,
        query: str,
        params: Sequence[Any] = (),
    ) -> Sequence[Sequence[Any]]:
        """Fetch every matching row."""
        ...


class PendingRoomInviteSqlRepository:
    """Shared SQLite-style repository for pending room invites.

    Applications only adapt their database API to
    :class:`PendingRoomInviteSqlBackend`; schema and CRUD SQL stay centralized
    here so both bots use exactly the same persistence semantics.
    """

    def __init__(self, backend: PendingRoomInviteSqlBackend) -> None:
        self.backend = backend

    def available(self) -> bool:
        return self.backend.available()

    async def setup(self) -> None:
        if not self.available():
            return
        await self.backend.execute(
            _CREATE_PENDING_INVITES_TABLE,
            label="room_invites_init",
        )
        await self.backend.execute(
            _CREATE_PENDING_INVITES_CREATED_AT_INDEX,
            label="room_invites_init",
        )

    async def load_all(self) -> list[PendingRoomInvite]:
        if not self.available():
            return []
        rows = await self.backend.fetch_all(_SELECT_PENDING_INVITES)
        return [PendingRoomInvite.from_row(row) for row in rows]

    async def insert_if_absent(
        self,
        room_jid: str,
        inviter: str,
        reason: str,
        created_at: int,
    ) -> PendingRoomInviteStoreResult:
        if not self.available():
            raise RuntimeError("room invite database is unavailable")
        affected = await self.backend.execute(
            _INSERT_PENDING_INVITE,
            (room_jid, inviter, reason, created_at),
            label="room_invite_store",
        )
        row = await self.backend.fetch_one(
            _SELECT_PENDING_INVITE_BY_KEY,
            (room_jid, inviter),
        )
        if row is None:
            raise RuntimeError(
                f"could not reload stored room invite for {room_jid} from {inviter}"
            )
        return PendingRoomInviteStoreResult(
            PendingRoomInvite.from_row(row),
            created=affected == 1,
        )

    async def get(self, invite_id: int) -> PendingRoomInvite | None:
        if not self.available():
            return None
        row = await self.backend.fetch_one(
            _SELECT_PENDING_INVITE_BY_ID,
            (int(invite_id),),
        )
        return PendingRoomInvite.from_row(row) if row is not None else None

    async def delete(self, invite_id: int) -> int:
        if not self.available():
            return 0
        return await self.backend.execute(
            "DELETE FROM room_invites WHERE id = ?",
            (int(invite_id),),
            label="room_invite_delete",
        )

    async def delete_many(self, invite_ids: Sequence[int]) -> int:
        ids = [int(invite_id) for invite_id in invite_ids]
        if not ids or not self.available():
            return 0
        placeholders = ",".join("?" for _ in ids)
        return await self.backend.execute(
            f"DELETE FROM room_invites WHERE id IN ({placeholders})",
            ids,
            label="room_invites_expire",
        )

    async def clear(self) -> int:
        if not self.available():
            return 0
        return await self.backend.execute(
            "DELETE FROM room_invites",
            label="room_invites_clear",
        )


class PendingRoomInviteRepository(Protocol):
    """Database adapter contract used by :class:`PendingRoomInviteStore`."""

    def available(self) -> bool:
        """Return whether persistence is currently usable."""
        ...

    async def setup(self) -> None:
        """Create/verify the persistent schema."""
        ...

    async def load_all(self) -> list[PendingRoomInvite]:
        """Return all persisted invites ordered by id."""
        ...

    async def insert_if_absent(
        self,
        room_jid: str,
        inviter: str,
        reason: str,
        created_at: int,
    ) -> PendingRoomInviteStoreResult:
        """Insert unless the uniqueness key exists and return the resulting row.

        Existing rows must be returned unchanged with ``created=False``.
        """
        ...

    async def get(self, invite_id: int) -> PendingRoomInvite | None:
        """Return one persisted invite by id."""
        ...

    async def delete(self, invite_id: int) -> int:
        """Delete one persisted invite and return the affected row count."""
        ...

    async def delete_many(self, invite_ids: Sequence[int]) -> int:
        """Delete several persisted invites and return the affected row count."""
        ...

    async def clear(self) -> int:
        """Delete all persisted invites and return the affected row count."""
        ...


@dataclass(frozen=True, slots=True)
class PendingRoomInviteLoadResult:
    """Result of loading persistent invite state."""

    active_count: int
    expired_count: int


class PendingRoomInviteStore:
    """Shared pending-invite cache and persistence orchestration."""

    def __init__(self, repository: PendingRoomInviteRepository | None = None) -> None:
        self.repository = repository
        self.pending: dict[int, PendingRoomInvite] = {}
        self.index: dict[tuple[str, str], int] = {}
        self.next_id = 1
        self._lock = asyncio.Lock()

    def _repository_available(self) -> bool:
        return self.repository is not None and self.repository.available()

    def adopt(self, pending: Mapping[int, Mapping[str, Any] | PendingRoomInvite]) -> None:
        """Adopt historical/injected runtime state into the typed cache."""
        normalized: list[PendingRoomInvite] = []
        for invite_id, value in pending.items():
            if isinstance(value, PendingRoomInvite):
                invite = value
            elif isinstance(value, Mapping):
                invite = PendingRoomInvite.from_mapping(value, fallback_id=int(invite_id))
            else:
                continue
            normalized.append(invite)
        self._replace_cache(normalized)

    def _replace_cache(self, invites: Sequence[PendingRoomInvite]) -> None:
        self.pending.clear()
        self.index.clear()
        max_id = 0
        for invite in sorted(invites, key=lambda item: item.id):
            max_id = max(max_id, invite.id)
            if invite.key in self.index:
                continue
            self.pending[invite.id] = invite
            self.index[invite.key] = invite.id
        self.next_id = max_id + 1

    def _cache(self, invite: PendingRoomInvite) -> PendingRoomInvite:
        previous_id = self.index.get(invite.key)
        if previous_id is not None and previous_id != invite.id:
            self.pending.pop(previous_id, None)
        self.pending[invite.id] = invite
        self.index[invite.key] = invite.id
        self.next_id = max(self.next_id, invite.id + 1)
        return invite

    async def setup(self) -> None:
        """Create persistent state when a repository is available."""
        if self._repository_available():
            assert self.repository is not None
            await self.repository.setup()

    async def load(
        self,
        *,
        max_age_days: int = 0,
        now: int | None = None,
    ) -> PendingRoomInviteLoadResult:
        """Load state, remove expired records and rebuild indexes."""
        async with self._lock:
            return await self._load_unlocked(max_age_days=max_age_days, now=now)

    async def _load_unlocked(
        self,
        *,
        max_age_days: int = 0,
        now: int | None = None,
    ) -> PendingRoomInviteLoadResult:
        if self._repository_available():
            assert self.repository is not None
            await self.repository.setup()
            source = await self.repository.load_all()
        else:
            source = list(self.pending.values())

        current = int(time.time()) if now is None else int(now)
        active: list[PendingRoomInvite] = []
        expired_ids: list[int] = []
        for invite in source:
            if invite_is_expired(invite.created_at, max_age_days, now=current):
                expired_ids.append(invite.id)
            else:
                active.append(invite)

        if expired_ids and self._repository_available():
            assert self.repository is not None
            await self.repository.delete_many(expired_ids)

        self._replace_cache(active)
        return PendingRoomInviteLoadResult(
            active_count=len(active),
            expired_count=len(expired_ids),
        )

    async def store(
        self,
        room_jid: str,
        inviter: str,
        reason: str = "",
        *,
        max_age_days: int = 0,
        now: int | None = None,
    ) -> PendingRoomInviteStoreResult:
        """Store one invite and deduplicate active deliveries by room/inviter.

        A duplicate does not update ``reason`` or ``created_at``. Expired entries
        are removed first, so the next delivery becomes a fresh invite with a
        fresh lifetime and, where persistence is used, a new row id.
        """
        async with self._lock:
            return await self._store_unlocked(
                room_jid,
                inviter,
                reason,
                max_age_days=max_age_days,
                now=now,
            )

    async def _store_unlocked(
        self,
        room_jid: str,
        inviter: str,
        reason: str = "",
        *,
        max_age_days: int = 0,
        now: int | None = None,
    ) -> PendingRoomInviteStoreResult:
        normalized_room = str(room_jid or "").strip().lower()
        normalized_inviter = str(inviter or "unknown").strip().lower() or "unknown"
        normalized_reason = str(reason or "")
        key = (normalized_room, normalized_inviter)
        current = int(time.time()) if now is None else int(now)

        existing_id = self.index.get(key)
        existing = self.pending.get(existing_id) if existing_id is not None else None
        if existing is not None:
            if invite_is_expired(existing.created_at, max_age_days, now=current):
                await self._delete_unlocked(existing.id)
            else:
                return PendingRoomInviteStoreResult(existing, created=False)

        if self._repository_available():
            assert self.repository is not None
            await self.repository.setup()
            result = await self.repository.insert_if_absent(
                normalized_room,
                normalized_inviter,
                normalized_reason,
                current,
            )
            invite = result.invite
            if not result.created and invite_is_expired(
                invite.created_at,
                max_age_days,
                now=current,
            ):
                await self.repository.delete(invite.id)
                self.pending.pop(invite.id, None)
                self.index.pop(invite.key, None)
                result = await self.repository.insert_if_absent(
                    normalized_room,
                    normalized_inviter,
                    normalized_reason,
                    current,
                )
                invite = result.invite
            self._cache(invite)
            return PendingRoomInviteStoreResult(invite, created=result.created)

        invite = PendingRoomInvite(
            id=self.next_id,
            room_jid=normalized_room,
            inviter=normalized_inviter,
            reason=normalized_reason,
            created_at=current,
        )
        self._cache(invite)
        return PendingRoomInviteStoreResult(invite, created=True)

    async def delete(self, invite_id: int) -> PendingRoomInvite | None:
        """Delete and return one invite from persistence/cache."""
        async with self._lock:
            return await self._delete_unlocked(invite_id)

    async def _delete_unlocked(self, invite_id: int) -> PendingRoomInvite | None:
        invite_id = int(invite_id)
        invite = self.pending.get(invite_id)
        if self._repository_available():
            assert self.repository is not None
            await self.repository.setup()
            if invite is None:
                invite = await self.repository.get(invite_id)
            await self.repository.delete(invite_id)

        if invite is not None:
            self.pending.pop(invite_id, None)
            self.index.pop(invite.key, None)
        return invite

    async def cleanup_expired(
        self,
        *,
        max_age_days: int,
        now: int | None = None,
    ) -> int:
        """Remove expired invites and return the actual number removed."""
        if int(max_age_days) <= 0:
            return 0
        async with self._lock:
            result = await self._load_unlocked(max_age_days=max_age_days, now=now)
        return result.expired_count

    async def clear(self) -> int:
        """Delete every pending invite and reset runtime state."""
        async with self._lock:
            count = len(self.pending)
            if self._repository_available():
                assert self.repository is not None
                await self.repository.setup()
                persisted = await self.repository.clear()
                count = max(count, persisted)
            self.pending.clear()
            self.index.clear()
            self.next_id = 1
            return count
