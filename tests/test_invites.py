from __future__ import annotations

from types import SimpleNamespace
from xml.etree import ElementTree as ET

from envs_xmpp_core.xmpp.invites import (
    RoomInvite,
    extract_room_invite,
    invite_is_expired,
    inviter_from_attr,
    reason_from_invite_element,
)


class Stanza(dict):
    def __init__(self, from_jid: str, *, xml=None, plugins=None):
        super().__init__()
        self["from"] = SimpleNamespace(bare=from_jid.split("/", 1)[0])
        self.xml = xml
        self._plugins = plugins or {}

    def get_plugin(self, name, check=True):
        return self._plugins.get(name)


def test_direct_xml_invite_is_normalized() -> None:
    xml = ET.fromstring(
        "<message><x xmlns='jabber:x:conference' "
        "jid='Room@Conference.Example' reason=' join '/></message>"
    )
    invite = extract_room_invite(Stanza("Alice@Example.Org/Phone", xml=xml))
    assert invite == RoomInvite(
        room_jid="room@conference.example",
        inviter="alice@example.org",
        reason="join",
    )
    assert invite.as_dict() == {
        "room_jid": "room@conference.example",
        "inviter": "alice@example.org",
        "reason": "join",
    }


def test_mediated_xml_invite_preserves_occupant_identity() -> None:
    xml = ET.Element("message")
    x_el = ET.SubElement(xml, "{http://jabber.org/protocol/muc#user}x")
    invite_el = ET.SubElement(
        x_el,
        "{http://jabber.org/protocol/muc#user}invite",
        {"from": "Room@Conference.Example/Alice"},
    )
    ET.SubElement(invite_el, "{http://jabber.org/protocol/muc#user}reason").text = " hello "
    invite = extract_room_invite(Stanza("Room@Conference.Example/Bot", xml=xml))
    assert invite == RoomInvite(
        room_jid="room@conference.example",
        inviter="room@conference.example/alice",
        reason="hello",
    )


def test_plugin_fallback_supports_mediated_and_direct_invites() -> None:
    mediated = Stanza(
        "Room@Conference.Example/Bot",
        plugins={
            "muc": Stanza(
                "ignored@example.org",
                plugins={"invite": {"from": "Alice@Example.Org/Phone", "reason": "mediated"}},
            )
        },
    )
    assert extract_room_invite(mediated) == RoomInvite(
        "room@conference.example", "alice@example.org", "mediated"
    )

    direct = Stanza(
        "Alice@Example.Org/Phone",
        plugins={"groupchat_invite": {"jid": "Direct@Conference.Example", "reason": "direct"}},
    )
    assert extract_room_invite(direct) == RoomInvite(
        "direct@conference.example", "alice@example.org", "direct"
    )


def test_inviter_reason_and_expiry_helpers() -> None:
    assert inviter_from_attr("room@conference/Alice", "room@conference") == "room@conference/alice"
    assert inviter_from_attr("Alice@Example.Org/Phone", "room@conference") == "alice@example.org"
    assert inviter_from_attr(None) == ""

    element = ET.fromstring(
        "<invite xmlns='http://jabber.org/protocol/muc#user'><reason> hello </reason></invite>"
    )
    assert reason_from_invite_element(element) == "hello"
    assert invite_is_expired(100, 1, now=100 + 86400 + 1) is True
    assert invite_is_expired(100, 0, now=999999) is False
    assert invite_is_expired("bad", 1, now=999999) is False
    assert invite_is_expired(100, "bad", now=999999) is False
