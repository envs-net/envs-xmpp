"""JID normalization helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def bare_jid(jid: object | None) -> str | None:
    if jid is None:
        return None
    value = str(jid).strip()
    return value.split("/", 1)[0].lower() if value else None


def build_client_jid(jid: object, resource: object | None = None) -> str:
    value = str(jid)
    if resource is None or not str(resource).strip():
        return value
    return f"{value.split('/', 1)[0]}/{str(resource).strip()}"


def configured_jid_domain(config: Mapping[str, Any], key: str = "jid") -> str | None:
    value = str(config.get(key, ""))
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
