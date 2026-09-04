"""Neutral XMPP room-invite parsing primitives.

Only stanza parsing and value normalization live here. Persistence, policy,
notifications, commands, and room-join decisions remain bot-specific.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

from .jid import bare_jid
from .stanza import safe_get_plugin, safe_plugin_value

DIRECT_INVITE_NS = "jabber:x:conference"
MUC_USER_NS = "http://jabber.org/protocol/muc#user"

BareJidResolver = Callable[[Any], str]
PluginGetter = Callable[[Any, str], Any | None]
PluginValueGetter = Callable[[Any, str], str]


@dataclass(frozen=True, slots=True)
class RoomInvite:
    """Normalized incoming MUC invite data."""

    room_jid: str
    inviter: str
    reason: str = ""

    def as_dict(self) -> dict[str, str]:
        """Return the legacy mapping shape used by both bots."""
        return {
            "room_jid": self.room_jid,
            "inviter": self.inviter,
            "reason": self.reason,
        }


def stanza_bare_jid(value: Any) -> str:
    """Return a best-effort lower-case bare JID from stanza values."""
    if value is None:
        return ""
    bare = getattr(value, "bare", None)
    if bare:
        return str(bare).lower()
    return bare_jid(value) or ""


def inviter_from_attr(
    value: str | None,
    room_jid: str = "",
    *,
    jid_bare: BareJidResolver = stanza_bare_jid,
) -> str:
    """Return the best available inviter identity from an invite attribute."""
    raw = str(value or "").strip()
    if not raw:
        return ""

    bare = jid_bare(raw)
    # Some servers only expose a MUC occupant JID. Preserve room/nick in that
    # case instead of collapsing it to the room's bare JID.
    if room_jid and bare == room_jid and "/" in raw:
        return raw.lower()
    return bare or raw.lower()


def reason_from_invite_element(invite_el: ET.Element) -> str:
    """Extract the optional XEP-0045 mediated invite reason."""
    reason_el = invite_el.find(f"{{{MUC_USER_NS}}}reason")
    if reason_el is not None and reason_el.text:
        return reason_el.text.strip()
    return ""


def room_invite_from_muc_plugin(
    msg: Any,
    *,
    jid_bare: BareJidResolver = stanza_bare_jid,
    get_plugin: PluginGetter = safe_get_plugin,
    plugin_value: PluginValueGetter = safe_plugin_value,
) -> RoomInvite | None:
    """Extract a mediated MUC invite from registered Slixmpp plugins."""
    muc = get_plugin(msg, "muc")
    if muc is None:
        return None
    invite = get_plugin(muc, "invite")
    if invite is None:
        return None

    room_jid = jid_bare(msg["from"])
    if not room_jid:
        return None

    inviter = inviter_from_attr(
        plugin_value(invite, "from"),
        room_jid,
        jid_bare=jid_bare,
    )
    return RoomInvite(
        room_jid=room_jid,
        inviter=inviter or "unknown",
        reason=plugin_value(invite, "reason"),
    )


def room_invite_from_direct_plugin(
    msg: Any,
    *,
    jid_bare: BareJidResolver = stanza_bare_jid,
    get_plugin: PluginGetter = safe_get_plugin,
    plugin_value: PluginValueGetter = safe_plugin_value,
) -> RoomInvite | None:
    """Extract a XEP-0249 direct invite from registered Slixmpp plugins."""
    direct = get_plugin(msg, "groupchat_invite")
    if direct is None:
        direct = get_plugin(msg, "conference")
    if direct is None:
        return None

    room_jid = (
        plugin_value(direct, "jid")
        or plugin_value(direct, "room")
        or plugin_value(direct, "to")
    ).lower()
    if not room_jid:
        return None

    return RoomInvite(
        room_jid=room_jid,
        inviter=jid_bare(msg["from"]) or "unknown",
        reason=plugin_value(direct, "reason"),
    )


def extract_room_invite(
    msg: Any,
    *,
    jid_bare: BareJidResolver = stanza_bare_jid,
    get_plugin: PluginGetter = safe_get_plugin,
    plugin_value: PluginValueGetter = safe_plugin_value,
) -> RoomInvite | None:
    """Extract a direct or mediated room invite from XML or stanza plugins."""
    xml = getattr(msg, "xml", None)
    if xml is None:
        return room_invite_from_muc_plugin(
            msg,
            jid_bare=jid_bare,
            get_plugin=get_plugin,
            plugin_value=plugin_value,
        ) or room_invite_from_direct_plugin(
            msg,
            jid_bare=jid_bare,
            get_plugin=get_plugin,
            plugin_value=plugin_value,
        )

    # XEP-0249 direct invite:
    # <x xmlns='jabber:x:conference' jid='room@conference'>
    for direct in xml.findall(f".//{{{DIRECT_INVITE_NS}}}x"):
        room_jid = (direct.attrib.get("jid") or "").strip().lower()
        if not room_jid:
            continue
        return RoomInvite(
            room_jid=room_jid,
            inviter=jid_bare(msg["from"]) or "unknown",
            reason=(direct.attrib.get("reason") or "").strip(),
        )

    # XEP-0045 mediated invite:
    # <x xmlns='http://jabber.org/protocol/muc#user'>
    #   <invite from='user@example.org'/>
    # </x>
    for invite in xml.findall(f".//{{{MUC_USER_NS}}}invite"):
        room_jid = jid_bare(msg["from"])
        if not room_jid:
            continue
        inviter = inviter_from_attr(
            invite.attrib.get("from"),
            room_jid,
            jid_bare=jid_bare,
        )
        return RoomInvite(
            room_jid=room_jid,
            inviter=inviter or "unknown",
            reason=reason_from_invite_element(invite),
        )

    return room_invite_from_muc_plugin(
        msg,
        jid_bare=jid_bare,
        get_plugin=get_plugin,
        plugin_value=plugin_value,
    ) or room_invite_from_direct_plugin(
        msg,
        jid_bare=jid_bare,
        get_plugin=get_plugin,
        plugin_value=plugin_value,
    )


def invite_is_expired(
    created_at: Any,
    max_age_days: Any,
    *,
    now: int | None = None,
) -> bool:
    """Return whether a pending invite exceeded a positive age limit."""
    try:
        days = int(max_age_days)
    except (TypeError, ValueError):
        return False
    if days <= 0:
        return False

    try:
        created = int(created_at or 0)
    except (TypeError, ValueError):
        return False
    if created <= 0:
        return False

    current = int(time.time()) if now is None else int(now)
    return created < current - (days * 86400)
