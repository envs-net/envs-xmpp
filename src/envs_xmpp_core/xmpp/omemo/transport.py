"""Bot-neutral OMEMO stanza inspection, decrypt and encrypt helpers."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from typing import Any

from ..jid import bare_jid
from ..outbound import ensure_message_origin_id

OMEMO_NAMESPACES = (
    "eu.siacs.conversations.axolotl",
    "urn:xmpp:omemo:2",
)


def normalize_bare_jid(value: object) -> str | None:
    try:
        normalized = bare_jid(value)
    except Exception:  # noqa: BLE001 - JID-like compatibility objects may raise arbitrary errors
        return None
    if not normalized:
        return None
    normalized = normalized.strip().lower()
    if not normalized or any(char.isspace() for char in normalized):
        return None
    if "@" in normalized:
        node, domain = normalized.split("@", 1)
        if not node or not domain:
            return None
    return normalized


def require_omemo_bare_jid(value: object) -> str:
    """Normalize an OMEMO recipient, rejecting missing/invalid identities.

    Both bots must fail closed rather than silently treating an invalid sender
    as a bare JID or an acceptable OMEMO recipient.
    """
    normalized = normalize_bare_jid(value)
    if not normalized:
        raise ValueError("OMEMO recipient does not contain a valid bare JID")
    return normalized


def message_has_omemo_payload(msg: Any) -> bool:
    """Return True only for a stanza containing an actual encrypted payload."""
    try:
        xml = msg.xml
    except Exception:  # noqa: BLE001 - stanza compatibility objects vary
        return False
    return any(xml.find(f".//{{{namespace}}}encrypted") is not None for namespace in OMEMO_NAMESPACES)


def expected_device_info_error(exc: Exception) -> bool:
    text = str(exc)
    return any(
        marker in text
        for marker in (
            "Couldn't find public information about the device",
            "device either does not appear in the device list",
            "bundle of the sending device could not be downloaded",
            "Bundle download failed",
            "Bundle not available",
            "could not be downloaded",
        )
    )


def extract_unusable_recipients(exc: Exception) -> set[str]:
    matches = re.findall(r"['\"]([^'\"]+@[^'\"]+)['\"]", str(exc))
    return {bare for value in matches if (bare := normalize_bare_jid(value))}


def recipient_bare_jids(values: AbstractSet[object], *, own_jid: object | None = None) -> set[str]:
    """Normalize visible recipient JIDs and optionally include the bot's own JID."""
    own_bare = normalize_bare_jid(own_jid) if own_jid else None
    recipients = {
        bare
        for value in values
        if (bare := normalize_bare_jid(value)) and bare != own_bare
    }
    if recipients and own_bare:
        recipients.add(own_bare)
    return recipients


async def wait_for_omemo_ready(
    ready_event: asyncio.Event,
    *,
    enabled: bool,
    timeout: float = 15,
    reset_pending: bool = False,
) -> bool:
    if reset_pending or not enabled:
        return False
    if ready_event.is_set():
        return True
    try:
        await asyncio.wait_for(ready_event.wait(), timeout=max(0.0, float(timeout)))
        return True
    except TimeoutError:
        return False


async def decrypt_incoming_message(
    msg: Any,
    *,
    enabled: bool,
    plugin_map: Mapping[str, Any],
    ready_event: asyncio.Event,
    timeout: float = 15,
    reset_pending: bool = False,
) -> tuple[Any | None, bool, str | None]:
    """Decrypt an incoming stanza and return ``(message, encrypted, reason)``.

    ``reason`` is a compact diagnostic string when encrypted input is rejected.
    The function is deliberately fail-closed: a visible OMEMO payload is never
    reinterpreted as plaintext merely because inspection/decryption failed.
    """
    has_payload = message_has_omemo_payload(msg)
    if reset_pending:
        return (None, True, "reset-pending") if has_payload else (msg, False, None)
    if not has_payload:
        return msg, False, None
    if not enabled:
        return None, True, "disabled"
    omemo = plugin_map.get("xep_0384")
    if omemo is None:
        return None, True, "plugin-unavailable"
    try:
        namespace = omemo.is_encrypted(msg)
    except Exception:  # noqa: BLE001 - OMEMO plugin implementations vary
        return None, True, "inspection-failed"
    if not namespace:
        return None, True, "unrecognized-payload"
    if not await wait_for_omemo_ready(ready_event, enabled=enabled, timeout=timeout):
        return None, True, "not-ready"
    try:
        result = await omemo.decrypt_message(msg)
    except Exception as exc:  # noqa: BLE001 - backend errors are normalized for callers
        reason = "device-info-unavailable" if expected_device_info_error(exc) else "decrypt-failed"
        return None, True, reason
    return (result[0] if isinstance(result, tuple) else result), True, None


async def encrypt_and_send(
    plugin: Any,
    msg: Any,
    recipients: set[Any] | Any,
    *,
    mto: str,
    origin_id: str | None = None,
) -> Any:
    """Encrypt and send, reusing a durable origin-id on actual wire stanzas."""
    if not isinstance(recipients, set):
        return await _encrypt_and_send_once(plugin, msg, recipients, mto=mto, origin_id=origin_id)

    current = set(recipients)
    skipped: set[str] = set()
    for _attempt in range(max(1, len(current) + 1)):
        if not current:
            raise RuntimeError(f"No usable OMEMO recipients left for {mto}")
        try:
            return await _encrypt_and_send_once(plugin, msg, current, mto=mto, origin_id=origin_id)
        except Exception as exc:
            missing = extract_unusable_recipients(exc)
            if not missing:
                raise
            before = set(current)
            current = {
                jid for jid in current if normalize_bare_jid(jid) not in missing
            }
            removed = {
                normalize_bare_jid(jid)
                for jid in before
                if normalize_bare_jid(jid) in missing
            }
            removed.discard(None)
            if not removed:
                raise
            skipped.update(str(item) for item in removed)
            if not current:
                raise RuntimeError(
                    f"No usable OMEMO recipients left for {mto}; skipped {len(skipped)} recipient(s)"
                ) from exc
    raise RuntimeError(f"Could not encrypt OMEMO message for {mto}; skipped {len(skipped)} recipient(s)")


async def _encrypt_and_send_once(
    plugin: Any, msg: Any, recipients: set[Any] | Any, *,
    mto: str, origin_id: str | None = None,
) -> Any:
    result = await plugin.encrypt_message(msg, recipients)
    encrypted_messages, errors = result if isinstance(result, tuple) and len(result) == 2 else (result, None)
    if not encrypted_messages:
        raise RuntimeError(f"OMEMO produced no encrypted messages for {mto}")
    # Errors are intentionally non-fatal when usable encrypted stanzas exist.
    _ = errors
    echo = None
    if isinstance(encrypted_messages, Mapping):
        for encrypted_msg in encrypted_messages.values():
            echo = encrypted_msg
            if origin_id is not None:
                ensure_message_origin_id(encrypted_msg, origin_id, require_stanza_id=True)
            encrypted_msg.send()
    else:
        echo = encrypted_messages
        if origin_id is not None:
            ensure_message_origin_id(echo, origin_id, require_stanza_id=True)
        echo.send()
    return echo


__all__ = [
    "OMEMO_NAMESPACES",
    "decrypt_incoming_message",
    "encrypt_and_send",
    "expected_device_info_error",
    "extract_unusable_recipients",
    "message_has_omemo_payload",
    "normalize_bare_jid",
    "recipient_bare_jids",
    "wait_for_omemo_ready",
]
