import asyncio

import pytest

from envs_xmpp_core.xmpp.messaging import (
    MessageTargetKind,
    TaskLocalReplyRoute,
    classify_message_target,
    disco_muc_status,
    is_muc_private_message,
    target_is_muc_room,
)


class Disco:
    def __init__(self, payload):
        self.payload = payload

    async def get_info(self, *, jid):
        assert jid == "room@example.org"
        return self.payload


def test_classify_message_target() -> None:
    assert classify_message_target("user@example.org").kind is MessageTargetKind.CHAT
    assert classify_message_target("room@example.org", is_muc=True).message_type == "groupchat"
    assert classify_message_target("room@example.org/Nick", muc_private=True).kind is MessageTargetKind.MUC_PM


def test_muc_private_message_requires_joined_room_and_resource() -> None:
    assert is_muc_private_message("chat", "room@example.org", "Nick", {"room@example.org"})
    assert not is_muc_private_message("groupchat", "room@example.org", "Nick", {"room@example.org"})
    assert not is_muc_private_message("chat", "room@example.org", "", {"room@example.org"})


@pytest.mark.asyncio
async def test_task_local_route_does_not_leak_to_child_tasks() -> None:
    routes = TaskLocalReplyRoute("test_reply_route")
    token = routes.set("room@example.org", "groupchat")
    try:
        assert routes.get().target == "room@example.org"

        async def child():
            return routes.get()

        assert await asyncio.create_task(child()) is None
    finally:
        routes.reset(token)
    assert routes.get() is None


@pytest.mark.asyncio
async def test_disco_muc_detection_from_feature_and_identity() -> None:
    assert await disco_muc_status(
        Disco({"disco_info": {"features": ["http://jabber.org/protocol/muc"]}}),
        "room@example.org",
    )
    assert await disco_muc_status(
        Disco({"disco_info": {"identities": [("conference", "text")]}}),
        "room@example.org",
    )
    assert not await disco_muc_status(Disco({"disco_info": {"features": []}}), "room@example.org")


@pytest.mark.asyncio
async def test_target_is_muc_room_uses_state_disco_and_legacy_hint() -> None:
    assert await target_is_muc_room("room@example.org", joined=True)
    assert await target_is_muc_room("room@muc.example.org", disco=None)
    assert not await target_is_muc_room("user@example.org", disco=Disco({"disco_info": {"features": []}}))
    assert not await target_is_muc_room("room@example.org/resource", joined=True)


def test_incoming_message_context_captures_dm_without_guessing_real_jid() -> None:
    from envs_xmpp_core.xmpp.messaging import MessageContext, MessageTargetKind, message_context_from_stanza

    msg = {"from": "alice@example.org/Phone", "type": "normal", "body": "  hi  ", "id": "stanza-7"}
    ctx = message_context_from_stanza(msg, encrypted=True)
    assert isinstance(ctx, MessageContext)
    assert ctx.kind is MessageTargetKind.CHAT
    assert (ctx.sender, ctx.sender_bare, ctx.sender_resource) == (
        "alice@example.org/Phone", "alice@example.org", "Phone"
    )
    assert (ctx.message_type, ctx.body, ctx.encrypted) == ("normal", "  hi  ", True)
    assert ctx.reply_route.target == msg["from"]
    assert ctx.reply_route.message_type == "chat"
    assert ctx.message_id == "stanza-7"
    assert ctx.origin_id is None
    assert ctx.real_jid is None
    assert not ctx.is_muc_pm
    assert not ctx.is_room


def test_incoming_message_context_classifies_groupchat_and_muc_pm() -> None:
    from envs_xmpp_core.xmpp.messaging import MessageTargetKind, message_context_from_stanza

    room = "Room@conference.Example.org"
    group = message_context_from_stanza(
        {"from": room + "/Alice", "mucnick": "Alice", "type": "groupchat", "body": "hi"}
    )
    assert group.kind is MessageTargetKind.GROUPCHAT
    assert group.is_room and not group.is_muc_pm
    assert group.room == room
    assert group.nick == "Alice"
    assert (group.reply_route.target, group.reply_route.message_type) == (room, "groupchat")

    pm = message_context_from_stanza(
        {"from": room + "/Alice", "type": "chat", "body": "secret"},
        joined_rooms=["room@conference.example.org"], encrypted=True,
    )
    assert pm.kind is MessageTargetKind.MUC_PM
    assert pm.is_muc_pm and not pm.is_room
    assert pm.room == room
    assert pm.nick == "Alice"
    assert pm.encrypted
    assert pm.real_jid is None  # Never infer identity from a MUC occupant JID.
    assert (pm.reply_route.target, pm.reply_route.message_type) == (room + "/Alice", "chat")
    no_room = message_context_from_stanza(
        {"from": room + "/Alice", "type": "chat", "body": "secret"}, joined_rooms=[]
    )
    assert no_room.kind is MessageTargetKind.CHAT
    assert no_room.room is None


def test_incoming_message_context_origin_id_and_real_jid_are_explicit() -> None:
    from types import SimpleNamespace
    from xml.etree.ElementTree import Element, SubElement

    from envs_xmpp_core.xmpp.messaging import message_context_from_stanza

    xml = Element("message", {"id": "wire-id"})
    SubElement(xml, "{urn:xmpp:sid:0}origin-id", {"id": "origin-42"})

    class Stanza(dict):
        pass

    msg = Stanza({"from": SimpleNamespace(bare="room@example.org", resource="Bob"), "type": "groupchat"})
    msg.xml = xml
    ctx = message_context_from_stanza(msg, real_jid="bob@example.net/Desktop")
    assert ctx.origin_id == "origin-42"
    assert ctx.message_id is None
    assert ctx.real_jid == "bob@example.net"


def test_incoming_message_context_missing_type_is_not_assumed_chat() -> None:
    from envs_xmpp_core.xmpp.messaging import message_context_from_stanza

    ctx = message_context_from_stanza({"from": "alice@example.org", "body": "test"})
    assert ctx.message_type == ""
    assert ctx.reply_route.message_type == "chat"
