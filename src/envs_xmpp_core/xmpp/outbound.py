"""Shared outbound routing, reply encryption and durable stanza identities.

This module makes no transport or persistence decision for an application.
A bot still chooses its OMEMO recipients, fallback policy and outbox strategy.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from .messaging import ReplyRoute, normalize_message_type, target_text

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OutboundMessagePlan:
    """Resolved delivery metadata, without a decrypted body or OMEMO keys."""

    route: ReplyRoute
    encrypted: bool | None
    durable: bool

    @property
    def can_persist_without_encryption_context(self) -> bool:
        """An explicitly encrypted reply must never become a plaintext row."""
        return can_persist_without_encryption_context(self.encrypted)


def resolve_reply_encryption(
    encrypted: bool | None, inherited_encryption: bool | None
) -> bool | None:
    """Preserve explicit caller choice over task-local OMEMO preference."""
    return inherited_encryption if encrypted is None else encrypted


def can_persist_without_encryption_context(encrypted: bool | None) -> bool:
    """Do not enqueue plaintext for an explicitly encrypted reply."""
    return encrypted is not True


def plan_outbound_message(
    *,
    target: object,
    message_type: object,
    reply_route: ReplyRoute | None = None,
    encrypted: bool | None = None,
    inherited_encryption: bool | None = None,
    durable: bool = False,
) -> OutboundMessagePlan:
    """Apply task-local reply routing and encryption in one deterministic order.

    Explicit encryption wins over task-local context; no implicit encryption
    downgrade is performed. A queue-first caller must independently reject
    ``durable and encrypted is True`` or persist an authenticated crypto policy.
    """
    route = (
        ReplyRoute(target_text(reply_route.target), normalize_message_type(reply_route.message_type))
        if reply_route is not None
        else ReplyRoute(target_text(target), normalize_message_type(message_type))
    )
    effective_encryption = resolve_reply_encryption(encrypted, inherited_encryption)
    return OutboundMessagePlan(route=route, encrypted=effective_encryption, durable=bool(durable))


def transport_accepted(value: object) -> bool:
    """Slixmpp sends may return ``None``; only explicit ``False`` rejects."""
    return value is not False


def ensure_message_origin_id(
    message: Any,
    origin_id: str | None = None,
    *,
    require_stanza_id: bool = False,
) -> str:
    """Stamp a stable XEP-0359 identity on the *outbound* stanza.

    Queues must persist the returned ID and reuse it for all attempts. The
    origin-id plugin is best-effort for older stanza doubles. Durable transport
    callers can require the ordinary stanza id to be set successfully, so
    replay safety is not silently lost when a stanza interface is missing.
    """
    stable = str(origin_id or "").strip() or uuid.uuid4().hex
    try:
        message["id"] = stable
    except Exception:
        if require_stanza_id:
            raise RuntimeError("Cannot apply stable id to an outbound stanza") from None
        log.debug("Could not assign outbound stanza id", exc_info=True)
    try:
        message["origin_id"]["id"] = stable
    except Exception:
        log.debug("Could not attach XEP-0359 origin-id", exc_info=True)
    return stable


__all__ = [
    "OutboundMessagePlan", "can_persist_without_encryption_context",
    "ensure_message_origin_id", "plan_outbound_message", "resolve_reply_encryption",
    "transport_accepted",
]
