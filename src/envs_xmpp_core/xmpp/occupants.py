"""Neutral MUC occupant identity and role/affiliation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .jid import bare_jid

_UNKNOWN = "unknown"
_ADMIN_AFFILIATIONS = frozenset({"admin", "owner"})
_MODERATOR_ROLES = frozenset({"moderator"})


@dataclass(frozen=True)
class MucOccupant:
    """Normalized view of one live MUC occupant."""

    room: str
    nick: str
    jid: str | None
    affiliation: str
    role: str
    is_self: bool = False

    @property
    def is_admin_or_owner(self) -> bool:
        return self.affiliation in _ADMIN_AFFILIATIONS

    @property
    def is_moderator(self) -> bool:
        return self.role in _MODERATOR_ROLES


@dataclass(frozen=True)
class MucOccupantSnapshot:
    """Immutable normalized snapshot of one room's occupants."""

    room: str
    occupants: tuple[MucOccupant, ...]

    def by_nick(self, nick: object) -> MucOccupant | None:
        return find_occupant_by_nick(self.occupants, nick)

    def by_jid(self, jid: object) -> MucOccupant | None:
        return find_occupant_by_jid(self.occupants, jid)

    def self_occupant(self) -> MucOccupant | None:
        return next((occupant for occupant in self.occupants if occupant.is_self), None)


def normalize_affiliation(value: object | None, *, default: str = _UNKNOWN) -> str:
    """Return a stable lower-case XMPP affiliation value."""
    text = str(value or "").strip().lower()
    return text or default


def normalize_role(value: object | None, *, default: str = _UNKNOWN) -> str:
    """Return a stable lower-case XMPP role value."""
    text = str(value or "").strip().lower()
    return text or default


def occupant_is_admin_or_owner(value: MucOccupant | Mapping[str, Any] | object) -> bool:
    """Return whether an occupant carries admin/owner affiliation."""
    if isinstance(value, MucOccupant):
        affiliation = value.affiliation
    elif isinstance(value, Mapping):
        affiliation = normalize_affiliation(value.get("affiliation"))
    else:
        affiliation = normalize_affiliation(getattr(value, "affiliation", None))
    return affiliation in _ADMIN_AFFILIATIONS


def occupant_is_moderator(value: MucOccupant | Mapping[str, Any] | object) -> bool:
    """Return whether an occupant currently has moderator role."""
    if isinstance(value, MucOccupant):
        role = value.role
    elif isinstance(value, Mapping):
        role = normalize_role(value.get("role"))
    else:
        role = normalize_role(getattr(value, "role", None))
    return role in _MODERATOR_ROLES


def occupant_from_mapping(
    room: object,
    nick: object,
    info: Mapping[str, Any] | None,
    *,
    self_bare_jid: object | None = None,
) -> MucOccupant:
    """Normalize a legacy ``nick -> mapping`` occupant entry."""
    values = info or {}
    jid = bare_jid(values.get("jid"))
    self_jid = bare_jid(self_bare_jid)
    return MucOccupant(
        room=str(room or ""),
        nick=str(nick or ""),
        jid=jid,
        affiliation=normalize_affiliation(values.get("affiliation")),
        role=normalize_role(values.get("role")),
        is_self=bool(jid and self_jid and jid == self_jid),
    )


def occupant_snapshot(
    room: object,
    occupants: Mapping[object, Mapping[str, Any]] | None,
    *,
    self_bare_jid: object | None = None,
) -> MucOccupantSnapshot:
    """Return a normalized immutable occupant snapshot."""
    normalized = tuple(
        occupant_from_mapping(room, nick, info, self_bare_jid=self_bare_jid)
        for nick, info in (occupants or {}).items()
        if isinstance(info, Mapping)
    )
    return MucOccupantSnapshot(room=str(room or ""), occupants=normalized)


def find_occupant_by_nick(
    occupants: Mapping[object, Mapping[str, Any]] | tuple[MucOccupant, ...] | list[MucOccupant],
    nick: object,
    *,
    room: object = "",
    self_bare_jid: object | None = None,
) -> MucOccupant | None:
    """Find an occupant by nickname with a case-insensitive fallback."""
    target = str(nick or "")
    target_folded = target.casefold()
    if isinstance(occupants, Mapping):
        direct = occupants.get(target)
        if isinstance(direct, Mapping):
            return occupant_from_mapping(room, target, direct, self_bare_jid=self_bare_jid)
        for candidate_nick, info in occupants.items():
            if str(candidate_nick).casefold() == target_folded and isinstance(info, Mapping):
                return occupant_from_mapping(room, candidate_nick, info, self_bare_jid=self_bare_jid)
        return None
    for occupant in occupants:
        if occupant.nick == target or occupant.nick.casefold() == target_folded:
            return occupant
    return None


def find_occupant_by_jid(
    occupants: Mapping[object, Mapping[str, Any]] | tuple[MucOccupant, ...] | list[MucOccupant],
    jid: object,
    *,
    room: object = "",
    self_bare_jid: object | None = None,
) -> MucOccupant | None:
    """Find an occupant by normalized bare JID."""
    target = bare_jid(jid)
    if not target:
        return None
    iterable: Iterable[MucOccupant]
    if isinstance(occupants, Mapping):
        iterable = (
            occupant_from_mapping(room, nick, info, self_bare_jid=self_bare_jid)
            for nick, info in occupants.items()
            if isinstance(info, Mapping)
        )
    else:
        iterable = iter(occupants)
    return next((occupant for occupant in iterable if occupant.jid == target), None)


def find_self_occupant(
    room: object,
    occupants: Mapping[object, Mapping[str, Any]] | None,
    *,
    self_bare_jid: object | None,
    preferred_nick: object | None = None,
    fallback_nick: object | None = None,
) -> MucOccupant | None:
    """Return the authoritative live occupant representing the bot itself.

    A nick learned from an actual self-presence may be supplied as
    ``preferred_nick`` and is checked first. Otherwise the authenticated bare
    JID is authoritative. ``fallback_nick`` is intentionally last and should
    only be used by lightweight callers that cannot track self-presence.
    """
    room_occupants = occupants or {}
    if preferred_nick:
        preferred = find_occupant_by_nick(
            room_occupants,
            preferred_nick,
            room=room,
            self_bare_jid=self_bare_jid,
        )
        if preferred is not None:
            return MucOccupant(**{**preferred.__dict__, "is_self": True})

    by_jid = find_occupant_by_jid(
        room_occupants,
        self_bare_jid,
        room=room,
        self_bare_jid=self_bare_jid,
    )
    if by_jid is not None:
        return MucOccupant(**{**by_jid.__dict__, "is_self": True})

    if fallback_nick:
        fallback = find_occupant_by_nick(
            room_occupants,
            fallback_nick,
            room=room,
            self_bare_jid=self_bare_jid,
        )
        if fallback is not None:
            return MucOccupant(**{**fallback.__dict__, "is_self": True})
    return None


def occupant_to_mapping(occupant: MucOccupant) -> dict[str, str | None]:
    """Return the legacy mutable mapping shape used by both bots."""
    return {
        "jid": occupant.jid,
        "affiliation": occupant.affiliation,
        "role": occupant.role,
    }


__all__ = [
    "MucOccupant",
    "MucOccupantSnapshot",
    "find_occupant_by_jid",
    "find_occupant_by_nick",
    "find_self_occupant",
    "normalize_affiliation",
    "normalize_role",
    "occupant_from_mapping",
    "occupant_is_admin_or_owner",
    "occupant_is_moderator",
    "occupant_snapshot",
    "occupant_to_mapping",
]
