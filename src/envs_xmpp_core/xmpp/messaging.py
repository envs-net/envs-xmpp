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


@dataclass(frozen=True, slots=True)
class MessageContext:
    """Immutable, bot-neutral snapshot of an incoming message after decryption.

    ``sender`` remains the full wire JID. ``real_jid`` is only populated from
    application-supplied occupant knowledge, never inferred from a MUC nick.
    A missing real JID must *not* be treated as an authorized user identity.
    No decrypted body is stored in a global/task-local context.
    """

    sender: str
    sender_bare: str
    sender_resource: str
    message_type: str
    kind: MessageTargetKind
    body: str
    nick: str
    room: str | None
    encrypted: bool
    message_id: str | None
    origin_id: str | None
    real_jid: str | None

    @property
    def is_room(self) -> bool:
        return self.kind is MessageTargetKind.GROUPCHAT

    @property
    def is_muc_pm(self) -> bool:
        return self.kind is MessageTargetKind.MUC_PM

    @property
    def reply_route(self) -> ReplyRoute:
        """Return a wire-compatible route, *not* an OMEMO recipient identity."""
        if self.is_room:
            return ReplyRoute(self.sender_bare, "groupchat")
        return ReplyRoute(self.sender, "chat")


def _incoming_field(stanza: Any, key: str) -> Any:
    """Read Slixmpp or mapping-style fields without mutating a stanza."""
    try:
        return stanza[key]
    except (KeyError, TypeError, AttributeError):
        return None


def message_context_from_stanza(
    stanza: Any,
    *,
    encrypted: bool = False,
    joined_rooms: Collection[str] = (),
    real_jid: object | None = None,
) -> MessageContext:
    """Snapshot routing metadata for DM, MUC and MUC-PM messages.

    Call this *after* OMEMO decryption for command bodies. Applications still
    own decryption, authentication, cache exclusion, policy and send decisions.
    ``joined_rooms`` is matched case-insensitively to classify MUC-PMs.
    """
    sender_jid = _incoming_field(stanza, "from")
    sender = str(sender_jid or "").strip()
    raw_bare = getattr(sender_jid, "bare", None)
    raw_resource = getattr(sender_jid, "resource", None)
    sender_bare = str(raw_bare or sender.split("/", 1)[0]).strip()
    sender_resource = str(
        raw_resource if raw_resource is not None else sender.partition("/")[2]
    ).strip()
    message_type = str(_incoming_field(stanza, "type") or "").strip().lower()
    body = str(_incoming_field(stanza, "body") or "")
    mucnick = str(_incoming_field(stanza, "mucnick") or "").strip()

    if message_type == "groupchat":
        kind = MessageTargetKind.GROUPCHAT
        room: str | None = sender_bare or None
    elif (
        message_type in {"chat", "normal"}
        and sender_resource
        and sender_bare.casefold() in {str(room).casefold() for room in joined_rooms}
    ):
        kind = MessageTargetKind.MUC_PM
        room = sender_bare
    else:
        kind = MessageTargetKind.CHAT
        room = None

    stanza_id = _incoming_field(stanza, "id")
    message_id = str(stanza_id).strip() if stanza_id else None
    # XEP-0359 origin-id and the stanza id are distinct identifiers.
    origin_id = None
    xml = getattr(stanza, "xml", None)
    if xml is not None and callable(getattr(xml, "find", None)):
        element = xml.find("{urn:xmpp:sid:0}origin-id")
        if element is not None:
            candidate = str(element.get("id") or "").strip()
            origin_id = candidate or None

    resolved = str(real_jid or "").strip() or None
    if resolved is not None:
        # An explicit real-JID hint may include a resource; never allow that to
        # become the OMEMO recipient's identity.
        resolved = resolved.split("/", 1)[0]

    return MessageContext(
        sender=sender,
        sender_bare=sender_bare,
        sender_resource=sender_resource,
        message_type=message_type,
        kind=kind,
        body=body,
        nick=mucnick or sender_resource if room is not None else mucnick,
        room=room,
        encrypted=bool(encrypted),
        message_id=message_id,
        origin_id=origin_id,
        real_jid=resolved,
    )


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
    "MessageContext",
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
    "message_context_from_stanza",
    "normalize_message_type",
    "target_is_muc_room",
    "target_text",
]
