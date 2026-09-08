"""Shared XMPP message-target classification and task-local reply routing."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Collection
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

MUC_FEATURE = "http://jabber.org/protocol/muc"


class MessageTargetKind(StrEnum):
    """Normalized transport kind for an XMPP message target."""

    CHAT = "chat"
    GROUPCHAT = "groupchat"
    MUC_PM = "muc-pm"


@dataclass(frozen=True)
class MessageTarget:
    """Normalized message target with the wire message type to use."""

    jid: str
    kind: MessageTargetKind

    @property
    def message_type(self) -> str:
        return "groupchat" if self.kind is MessageTargetKind.GROUPCHAT else "chat"


@dataclass(frozen=True)
class ReplyRoute:
    """Task-local reply destination."""

    target: str
    message_type: str


class TaskLocalReplyRoute:
    """Store a reply route without leaking it into child asyncio tasks.

    Context variables are inherited by newly-created asyncio tasks.  Associating
    a route with the task that created it prevents command reply routing from
    accidentally affecting background tasks spawned by that command.
    """

    def __init__(self, name: str = "xmpp_reply_route") -> None:
        self._context: ContextVar[tuple[object | None, ReplyRoute] | None] = ContextVar(
            name,
            default=None,
        )

    def set(self, target: object, message_type: object) -> Token[tuple[object | None, ReplyRoute] | None]:
        route = ReplyRoute(str(target), normalize_message_type(message_type))
        return self._context.set((asyncio.current_task(), route))

    def reset(self, token: Token[tuple[object | None, ReplyRoute] | None]) -> None:
        self._context.reset(token)

    def get(self) -> ReplyRoute | None:
        value = self._context.get()
        if value is None:
            return None
        owner_task, route = value
        if owner_task is not None and asyncio.current_task() is not owner_task:
            return None
        return route


def target_text(target: object | None) -> str:
    """Return a stripped XMPP target string."""
    return str(target or "").strip()


def normalize_message_type(value: object | None, *, default: str = "chat") -> str:
    """Normalize Slixmpp message type values used by the bots."""
    message_type = str(value or "").strip().lower()
    if message_type == "groupchat":
        return "groupchat"
    if message_type in {"chat", "normal"}:
        return "chat"
    return default


def looks_like_bare_room_jid(target: object | None) -> bool:
    """Return whether a value has the shape of a bare room JID."""
    value = target_text(target)
    if not value or "/" in value or "@" not in value:
        return False
    node, domain = value.split("@", 1)
    return bool(node and domain)


def legacy_muc_domain_hint(target: object | None) -> bool:
    """Recognize conventional MUC service domains when disco is unavailable."""
    value = target_text(target)
    if not looks_like_bare_room_jid(value):
        return False
    domain = value.split("@", 1)[1].strip().lower()
    return domain.startswith(("conference.", "muc."))


def is_muc_private_message(
    message_type: object,
    from_bare: object,
    from_resource: object | None,
    joined_rooms: Collection[str],
) -> bool:
    """Return True for a chat/normal stanza from a joined MUC occupant JID."""
    return (
        str(message_type or "chat").lower() in {"chat", "normal"}
        and bool(str(from_resource or ""))
        and str(from_bare) in joined_rooms
    )


def classify_message_target(
    target: object,
    *,
    is_muc: bool = False,
    muc_private: bool = False,
) -> MessageTarget:
    """Return a normalized target classification."""
    value = target_text(target)
    kind = (
        MessageTargetKind.MUC_PM
        if muc_private
        else MessageTargetKind.GROUPCHAT
        if is_muc
        else MessageTargetKind.CHAT
    )
    return MessageTarget(value, kind)


async def maybe_await(value: Any) -> Any:
    """Await a compatibility value when necessary."""
    if inspect.isawaitable(value):
        return await value
    return value


def _stanza_interfaces(value: Any) -> set[str] | None:
    interfaces = getattr(value, "interfaces", None)
    if interfaces is None:
        return None
    try:
        return {str(item) for item in interfaces}
    except TypeError:
        return set()


def _safe_get_stanza_plugin(stanza: Any, plugin_name: str) -> Any:
    get_plugin = getattr(stanza, "get_plugin", None)
    if not callable(get_plugin):
        return None
    try:
        return get_plugin(plugin_name, check=True)
    except TypeError:
        try:
            return get_plugin(plugin_name)
        except Exception:  # noqa: BLE001 - compatibility objects may raise arbitrary errors
            return None
    except Exception:  # noqa: BLE001 - stanza plugin implementations vary by Slixmpp version
        return None


def _disco_field(candidate: Any, key: str) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key)
    interfaces = _stanza_interfaces(candidate)
    if interfaces is not None:
        if key not in interfaces:
            return None
        try:
            return candidate[key]
        except Exception:  # noqa: BLE001 - compatibility stanzas may reject unsupported keys
            return None
    return getattr(candidate, key, None)


def _disco_payloads(info: Any):
    if isinstance(info, dict):
        nested = info.get("disco_info")
        if nested is not None:
            yield nested
        if "features" in info or "identities" in info:
            yield info
        return

    interfaces = _stanza_interfaces(info)
    if interfaces is not None:
        if {"features", "identities"} & interfaces:
            yield info
            return
        disco_info = _safe_get_stanza_plugin(info, "disco_info")
        if disco_info is not None:
            yield disco_info
        return

    nested = getattr(info, "disco_info", None)
    if nested is not None:
        yield nested
    if _disco_field(info, "features") or _disco_field(info, "identities"):
        yield info


def iter_disco_features(info: Any):
    """Yield disco features from mapping, stanza and compatibility shapes."""
    for candidate in _disco_payloads(info):
        features = _disco_field(candidate, "features")
        if features:
            for feature in features:
                yield str(feature)


def iter_disco_identities(info: Any):
    """Yield disco identities from mapping, stanza and compatibility shapes."""
    for candidate in _disco_payloads(info):
        identities = _disco_field(candidate, "identities")
        if identities:
            yield from identities


def identity_is_muc(identity: Any) -> bool:
    """Return whether a disco identity belongs to the conference category."""
    if isinstance(identity, dict):
        category = identity.get("category")
    elif isinstance(identity, (tuple, list)):
        category = identity[0] if identity else None
    else:
        category = getattr(identity, "category", None)
    return str(category or "").strip().lower() == "conference"


async def disco_muc_status(disco: Any, target: object) -> bool | None:
    """Return True/False from XEP-0030, or None when discovery is unavailable."""
    if disco is None or not callable(getattr(disco, "get_info", None)):
        return None
    try:
        info = await maybe_await(disco.get_info(jid=target_text(target)))
    except Exception:  # noqa: BLE001 - discovery failure is an expected classification fallback
        return None
    if any(feature == MUC_FEATURE for feature in iter_disco_features(info)):
        return True
    return any(identity_is_muc(identity) for identity in iter_disco_identities(info))


async def target_is_muc_room(
    target: object,
    *,
    joined: bool = False,
    stored: bool = False,
    disco: Any = None,
    allow_legacy_domain_hint: bool = True,
) -> bool:
    """Classify a bare JID as a MUC from runtime state, storage, or disco."""
    value = target_text(target)
    if not looks_like_bare_room_jid(value):
        return False
    if joined or stored:
        return True
    discovered = await disco_muc_status(disco, value)
    if discovered is not None:
        return discovered
    return allow_legacy_domain_hint and legacy_muc_domain_hint(value)


__all__ = [
    "MUC_FEATURE",
    "MessageTarget",
    "MessageTargetKind",
    "ReplyRoute",
    "TaskLocalReplyRoute",
    "classify_message_target",
    "disco_muc_status",
    "identity_is_muc",
    "is_muc_private_message",
    "iter_disco_features",
    "iter_disco_identities",
    "legacy_muc_domain_hint",
    "looks_like_bare_room_jid",
    "maybe_await",
    "normalize_message_type",
    "target_is_muc_room",
    "target_text",
]
