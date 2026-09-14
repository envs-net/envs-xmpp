from __future__ import annotations

from dataclasses import dataclass

from envs_xmpp_core.pagination import PageRequest
from envs_xmpp_core.presentation import (
    RoomListRequest,
    RoomView,
    StatusField,
    StatusSection,
    filter_room_views,
    filter_task_views,
    normalize_tasks,
    parse_room_list_request,
    parse_task_list_request,
    render_room_entry,
    render_session_lifecycle_lines,
    render_status_sections,
    render_task_entry,
    render_task_summary,
    room_problem_views,
    room_summary,
    summarize_tasks,
)
from envs_xmpp_core.runtime import SessionLifecycleSnapshot


@dataclass
class Task:
    plugin: str
    name: str
    status: str
    kind: str = "service"
    created_at: str = "2026-09-11T00:00:00+00:00"
    heartbeat_at: str | None = "2026-09-11T00:01:30+00:00"
    done_at: str | None = None
    restart_count: int = 0
    circuit_state: str = "closed"
    next_restart_at: str | None = None
    last_error: str | None = None
    cancelled: bool = False


def test_status_sections_use_tree_layout_and_indent_multiline_values() -> None:
    lines = render_status_sections(
        "🤖 Bot Status",
        [
            StatusSection(
                "Core",
                (
                    StatusField("Version", "1.2.3"),
                    StatusField("State", "ready\nextra detail"),
                ),
                "⚙️",
            )
        ],
    )
    assert lines == [
        "🤖 Bot Status",
        "",
        "⚙️ Core:",
        "├─ Version: 1.2.3",
        "└─ State: ready",
        "   extra detail",
    ]


def test_task_normalization_summary_and_compact_rendering() -> None:
    tasks = normalize_tasks(
        [
            Task("rss", "feed-loop", "running"),
            Task("core", "worker", "failed", last_error="boom"),
        ]
    )
    summary = summarize_tasks(tasks)
    assert summary.failed == 1
    assert summary.services_running == 1
    text = "\n".join(render_task_summary(tasks))
    assert "Services: 1 running" in text
    assert "Failed: 1" in text
    failed = next(view for view in tasks if view.status == "failed")
    rendered = render_task_entry(failed, now=1789084920.0)
    assert "core/worker" in rendered
    assert "last error: boom" in rendered


def test_task_full_render_includes_relative_and_absolute_timestamps() -> None:
    task = Task("core", "worker", "running")
    view = normalize_tasks([task])[0]
    rendered = render_task_entry(view, full=True, now=1789084920.0)
    assert "created:" in rendered
    assert "(2026-09-11T00:00:00+00:00)" in rendered


def test_parse_task_list_request_accepts_common_modifiers_in_either_order() -> None:
    first = parse_task_list_request(["failed", "scope", "rss", "all", "full"])
    second = parse_task_list_request(["full", "scope", "rss", "failed", "all"])
    assert first.error is None
    assert second.error is None
    assert first == second
    assert first.mode == "failed"
    assert first.scope == "rss"
    assert first.full is True
    assert first.page == PageRequest(all=True)


def test_parse_and_filter_task_detail_request() -> None:
    request = parse_task_list_request(["scope", "rss", "show", "feed-loop"])
    assert request.error is None
    views = normalize_tasks([Task("rss", "feed-loop", "running"), Task("core", "worker", "running")])
    assert [view.label for view in filter_task_views(views, request)] == ["rss/feed-loop"]


def test_task_request_rejects_conflicting_filters() -> None:
    request = parse_task_list_request(["failed", "running"])
    assert request.error == "conflicting task filters"


def test_room_rendering_summary_and_problem_filter() -> None:
    rooms = [
        RoomView("good@example.org", True, ("affiliation=owner",)),
        RoomView("bad@example.org", True, ("affiliation=member", "no admin rights"), attention=True),
        RoomView("offline@example.org", False, ("protected",), expected_joined=True),
        RoomView("runtime@example.org", True, ("stored=no",), configured=False),
    ]
    assert room_summary(rooms) == "Summary: 3 configured · 4 known · 3 joined · 2 issues"
    assert "🟠 bad@example.org" in render_room_entry(rooms[1])
    assert [room.jid for room in room_problem_views(rooms)] == ["bad@example.org", "offline@example.org"]


def test_parse_and_filter_room_request() -> None:
    request = parse_room_list_request(["all", "problems"])
    assert request == RoomListRequest(filter="problems", page=PageRequest(all=True))
    rooms = [RoomView("ok@example.org", True), RoomView("bad@example.org", False)]
    assert [room.jid for room in filter_room_views(rooms, request)] == ["bad@example.org"]


def test_room_request_rejects_duplicate_filters() -> None:
    request = parse_room_list_request(["joined", "offline"])
    assert request.error == "duplicate room filter"


def test_session_lifecycle_renderer_is_compact_and_expands_history():
    snapshot = SessionLifecycleSnapshot(
        generation=4,
        reconnect_count=3,
        state="ready",
        phase="ready",
        session_started_at="2026-09-14T06:00:00+00:00",
        last_ready_at="2026-09-14T06:00:05+00:00",
        last_disconnect_at="2026-09-14T05:59:50+00:00",
        last_disconnect_reason="transport lost",
        last_error=None,
        startup_duration_seconds=5.2,
        phase_age_seconds=10.0,
        session_age_seconds=20.0,
    )
    compact = render_session_lifecycle_lines(snapshot)
    assert compact == [
        "Session: ready · generation 4 · reconnects 3",
        "Session startup: 5s",
    ]
    full = render_session_lifecycle_lines(snapshot, full=True)
    assert any(line.startswith("Session started:") for line in full)
    assert any("Last disconnect: transport lost" in line for line in full)


def test_session_lifecycle_renderer_shows_active_phase_and_error():
    snapshot = SessionLifecycleSnapshot(
        generation=2,
        reconnect_count=1,
        state="failed",
        phase="synchronization",
        session_started_at=None,
        last_ready_at=None,
        last_disconnect_at=None,
        last_disconnect_reason=None,
        last_error="owner affiliation IQ timeout",
        startup_duration_seconds=None,
        phase_age_seconds=8.8,
        session_age_seconds=9.0,
    )
    lines = render_session_lifecycle_lines(snapshot)
    assert "Session: failed · generation 2 · reconnects 1" in lines
    assert "Session phase: synchronization · age 8s" in lines
    assert "Session error: owner affiliation IQ timeout" in lines
