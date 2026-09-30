"""Cross-bot presentation contracts: same input must render alike."""

from __future__ import annotations

import pytest

from envs_xmpp_core.presentation import (
    RoomListRequest,
    RoomView,
    filter_room_views,
    render_room_entry,
    room_lifecycle_summary,
    room_view_with_lifecycle,
)
from envs_xmpp_core.runtime.rooms import RoomLifecycleRegistry


@pytest.mark.parametrize(
    ("state", "icon"),
    [
        ("configured", "⚪"),
        ("joining", "🔄"),
        ("degraded", "🟠"),
        ("failed", "❌"),
        ("deferred", "🟠"),
        ("leaving", "⏹️"),
    ],
)
def test_unconfirmed_rooms_show_shared_lifecycle_without_faking_join(state, icon):
    registry = RoomLifecycleRegistry()
    room = "room@conference.example.test"
    registry.configure(room)
    if state == "joining":
        registry.begin_join(room)
    elif state == "degraded":
        registry.mark_degraded(room)
    elif state == "failed":
        registry.mark_failed(room, reason="timeout")
    elif state == "deferred":
        registry.mark_deferred(room)
    elif state == "leaving":
        registry.begin_leave(room)
    view = room_view_with_lifecycle(
        RoomView(jid=room, joined=False, unavailable=True), registry.get(room)
    )
    assert view.joined is False
    assert view.state == state
    assert render_room_entry(view).startswith(icon)
    assert f"lifecycle={state}" in view.details
    issues = filter_room_views([view], RoomListRequest(filter="problems"))
    assert bool(issues) is (state != "leaving")


def test_stale_join_snapshot_cannot_claim_verified_presence():
    registry = RoomLifecycleRegistry()
    registry.confirm_self_presence("room@conference.example.test", "Bot")
    observation = registry.get("room@conference.example.test")
    view = room_view_with_lifecycle(
        RoomView("ROOM@conference.example.test", joined=False), observation
    )
    assert not view.joined
    assert view.needs_attention
    assert view.state == "attention"
    assert "self-presence unconfirmed" in view.details


def test_verified_presence_and_missing_snapshot_remain_authoritative():
    registry = RoomLifecycleRegistry()
    registry.mark_failed("room@conference.example.test")
    view = room_view_with_lifecycle(
        RoomView("room@conference.example.test", joined=True),
        registry.get("room@conference.example.test"),
    )
    assert view.joined and view.state == "joined"
    assert room_view_with_lifecycle(view, None) == view
    assert room_view_with_lifecycle(view, registry.get("different@test")) == view


def test_lifecycle_summary_count_contract():
    registry = RoomLifecycleRegistry()
    registry.confirm_self_presence("joined@test", "Bot")
    registry.begin_join("joining@test")
    registry.mark_degraded("degraded@test")
    registry.mark_failed("failed@test")
    registry.mark_deferred("deferred@test")
    registry.begin_leave("leaving@test")
    assert room_lifecycle_summary(registry.snapshot()) == (
        "Room lifecycle: 6 tracked · 1 joined · 1 joining · "
        "1 degraded · 1 failed · 1 deferred · 1 leaving"
    )


def test_failed_manual_join_is_a_problem_even_without_autojoin():
    registry = RoomLifecycleRegistry()
    registry.mark_failed("manual@conference.example.test")
    view = room_view_with_lifecycle(
        RoomView("manual@conference.example.test", joined=False, expected_joined=False),
        registry.get("manual@conference.example.test"),
    )
    assert view.needs_attention
    assert view.state == "failed"
