"""Session-scoped, bot-neutral MUC membership lifecycle snapshots.

This tracker is an observation/coordination primitive, not an authority for
identifying occupants or deciding whether a room should be joined. Callers
must only record ``confirm_self_presence`` after their own authoritative
self-presence / authenticated occupant checks succeed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

RoomLifecycleStatus = Literal[
    "configured", "joining", "joined", "degraded", "failed", "deferred", "leaving"
]


def room_key(value: object) -> str:
    """Normalize a bare room JID for lifecycle bookkeeping, never authentication."""
    bare = getattr(value, "bare", value)
    return str(bare or "").split("/", 1)[0].strip().casefold()


@dataclass(frozen=True, slots=True)
class RoomLifecycleSnapshot:
    """One immutable room observation in a particular XMPP session generation."""

    room: str
    state: RoomLifecycleStatus = "configured"
    generation: int = 0
    nick: str | None = None
    attempts: int = 0
    failures: int = 0
    retry_at: float | None = None
    reason: str | None = None

    @property
    def joined(self) -> bool:
        """Only confirmed self-presence counts as joined."""
        return self.state == "joined" and bool(self.nick)

    @property
    def needs_attention(self) -> bool:
        return self.state in {"degraded", "failed", "deferred"}


class RoomLifecycleRegistry:
    """Track MUC lifecycle without choosing retries, joins or privileges.

    Session invalidation always removes joined assertions. An intentional
    ``leaving`` marker survives reconnection until the caller explicitly
    starts a new join or removes that room.
    """

    def __init__(self) -> None:
        self._generation = 0
        self._rooms: dict[str, RoomLifecycleSnapshot] = {}

    @property
    def generation(self) -> int:
        return self._generation

    def configure(self, room: object) -> RoomLifecycleSnapshot:
        key = room_key(room)
        if not key:
            raise ValueError("room JID must not be empty")
        return self._rooms.setdefault(key, RoomLifecycleSnapshot(room=key, generation=self._generation))

    def get(self, room: object) -> RoomLifecycleSnapshot | None:
        return self._rooms.get(room_key(room))

    def snapshot(self) -> tuple[RoomLifecycleSnapshot, ...]:
        return tuple(self._rooms[key] for key in sorted(self._rooms))

    def _change(self, room: object, *, state: RoomLifecycleStatus, **updates: Any) -> RoomLifecycleSnapshot:
        previous = self.configure(room)
        current = replace(previous, state=state, generation=self._generation, **updates)
        self._rooms[current.room] = current
        return current

    def begin_join(self, room: object) -> RoomLifecycleSnapshot:
        previous = self.configure(room)
        return self._change(
            room, state="joining", nick=None, retry_at=None, reason=None,
            attempts=previous.attempts + 1,
        )

    def confirm_self_presence(
        self, room: object, nick: str, *, generation: int | None = None
    ) -> RoomLifecycleSnapshot | None:
        """Record a verified self-presence; refuse stale generations/leaving rooms.

        Checking the stanza belongs to the bot is the caller's responsibility.
        ``generation`` can reject results originating in a previous session.
        """
        if generation is not None and generation != self._generation:
            return None
        previous = self.configure(room)
        if previous.state == "leaving":
            return None
        if not str(nick).strip():
            raise ValueError("confirmed self-presence requires a nonempty nick")
        return self._change(
            room, state="joined", nick=str(nick), failures=0, retry_at=None, reason=None,
        )

    def mark_degraded(self, room: object, *, reason: str | None = None) -> RoomLifecycleSnapshot:
        previous = self.configure(room)
        if previous.state == "leaving":
            return previous
        return self._change(room, state="degraded", nick=None, reason=reason, retry_at=None)

    def mark_failed(
        self, room: object, *, reason: str | None = None, retry_at: float | None = None
    ) -> RoomLifecycleSnapshot:
        previous = self.configure(room)
        if previous.state == "leaving":
            return previous
        return self._change(
            room, state="failed", nick=None, reason=reason, retry_at=retry_at,
            failures=previous.failures + 1,
        )

    def mark_deferred(
        self, room: object, *, retry_at: float | None = None, reason: str | None = None
    ) -> RoomLifecycleSnapshot:
        previous = self.configure(room)
        if previous.state == "leaving":
            return previous
        return self._change(room, state="deferred", nick=None, retry_at=retry_at, reason=reason)

    def begin_leave(self, room: object) -> RoomLifecycleSnapshot:
        return self._change(room, state="leaving", nick=None, retry_at=None, reason=None)

    def forget(self, room: object) -> None:
        self._rooms.pop(room_key(room), None)

    def new_session(self) -> int:
        """Invalidate old self-presence without changing application leave intent."""
        self._generation += 1
        self._rooms = {
            room: replace(
                observation,
                state="leaving" if observation.state == "leaving" else "configured",
                generation=self._generation,
                nick=None,
                attempts=0,
                failures=0,
                retry_at=None,
                reason=None,
            )
            for room, observation in self._rooms.items()
        }
        return self._generation

    def clear(self) -> None:
        """Forget all rooms (e.g. application/plugin teardown)."""
        self._rooms.clear()
