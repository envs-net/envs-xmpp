"""JID normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# U+200B ZERO WIDTH SPACE and U+FEFF ZERO WIDTH NO-BREAK SPACE/BOM can
# leak into copied/pasted JIDs even though they are presentation artifacts.
# Keep this intentionally narrow: stripping arbitrary Unicode format characters
# could change meaningful internationalized identifiers.
_JID_PRESENTATION_TRANSLATION = str.maketrans({"\u200b": None, "\ufeff": None})


def normalize_jid_text(value: object | None) -> str | None:
    """Return JID text with known presentation artifacts removed.

    The helper performs only transport-neutral text cleanup. It deliberately
    does not lowercase, validate, or strip a resource so callers can layer
    their own JID/domain semantics on top.
    """
    if value is None:
        return None
    normalized = str(value).translate(_JID_PRESENTATION_TRANSLATION).strip()
    return normalized or None


def bare_jid(jid: object | None) -> str | None:
    value = normalize_jid_text(jid)
    return value.split("/", 1)[0].lower() if value else None


def build_client_jid(jid: object, resource: object | None = None) -> str:
    value = str(jid)
    if resource is None or not str(resource).strip():
        return value
    return f"{value.split('/', 1)[0]}/{str(resource).strip()}"


def configured_jid_domain(config: Mapping[str, Any], key: str = "jid") -> str | None:
    value = normalize_jid_text(config.get(key)) or ""
    if "@" not in value:
        return None
    domain = value.split("@", 1)[1].split("/", 1)[0].strip()
    return domain or None


def boundjid_domain(xmpp: Any) -> str | None:
    boundjid = getattr(xmpp, "boundjid", None)
    if boundjid is None:
        return None
    for attribute in ("domain", "host"):
        value = getattr(boundjid, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
