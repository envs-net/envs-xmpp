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
