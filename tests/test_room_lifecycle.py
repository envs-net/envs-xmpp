"""Cross-bot contracts for session-scoped MUC membership observations."""

from __future__ import annotations

import pytest

from envs_xmpp_core.runtime import RoomLifecycleRegistry, room_key


def test_all_room_states_and_backoff_are_policy_neutral() -> None:
    rooms = RoomLifecycleRegistry()
    initial = rooms.configure("Room@Conference.Example/Bot")
    assert initial.room == "room@conference.example"
    assert initial.state == "configured"
    assert not initial.joined

    assert rooms.begin_join(initial.room).attempts == 1
    failed = rooms.mark_failed(initial.room, reason="timeout", retry_at=135.5)
    assert (failed.state, failed.failures, failed.retry_at) == ("failed", 1, 135.5)
    deferred = rooms.mark_deferred(initial.room, retry_at=135.5, reason="backoff")
    assert deferred.state == "deferred" and deferred.needs_attention

    assert rooms.begin_join(initial.room).attempts == 2
    joined = rooms.confirm_self_presence(initial.room, "BotRenamed")
    assert joined is not None and joined.joined and joined.nick == "BotRenamed"
    assert joined.failures == 0 and joined.retry_at is None
    degraded = rooms.mark_degraded(initial.room, reason="self presence lost")
    assert degraded.state == "degraded" and not degraded.joined
    assert rooms.begin_leave(initial.room).state == "leaving"
    assert rooms.confirm_self_presence(initial.room, "stale") is None
    assert rooms.mark_failed(initial.room).state == "leaving"


def test_reconnect_invalidates_joined_but_keeps_intentional_leave() -> None:
    rooms = RoomLifecycleRegistry()
    room_a = "a@conference.example"
    room_b = "b@conference.example"
    old_generation = rooms.generation
    rooms.confirm_self_presence(room_a, "Bot")
    rooms.begin_leave(room_b)
    assert rooms.new_session() == old_generation + 1
    assert rooms.get(room_a).state == "configured"
    assert rooms.get(room_a).nick is None
    assert rooms.get(room_b).state == "leaving"
    assert rooms.confirm_self_presence(room_a, "late", generation=old_generation) is None
    assert rooms.get(room_a).state == "configured"
    rooms.begin_join(room_a)
    assert rooms.confirm_self_presence(room_a, "fresh", generation=rooms.generation).joined
    rooms.forget(room_a)
    assert rooms.get(room_a) is None
    rooms.clear()
    assert not rooms.snapshot()


def test_state_snapshots_are_deterministic_and_isolated() -> None:
    rooms = RoomLifecycleRegistry()
    rooms.configure("B@Conf.Test")
    rooms.configure("a@conf.test")
    assert tuple(item.room for item in rooms.snapshot()) == ("a@conf.test", "b@conf.test")
    old = rooms.get("B@Conf.Test")
    rooms.begin_join("b@conf.test")
    assert old.state == "configured"
    assert room_key("ROOM@CONFERENCE/Nick") == "room@conference"
    with pytest.raises(ValueError, match="empty"):
        rooms.configure(" ")
    with pytest.raises(ValueError, match="nonempty"):
        rooms.confirm_self_presence("a@conf.test", " ")
    assert rooms.get("a@conf.test").state == "configured"
