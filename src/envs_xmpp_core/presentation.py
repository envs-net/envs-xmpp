"""Shared operator-facing presentation models and renderers.

Applications keep ownership of runtime data collection and policy. This module
only normalizes and renders common task, status, and room inventory state so
operator commands can present the same concepts consistently.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .formatting import format_absolute_time, format_duration, format_relative_time
from .pagination import PageRequest
from .runtime.session import SessionLifecycleSnapshot

_STATUS_ICONS = {
    "ok": "✅",
    "success": "✅",
    "healthy": "✅",
    "running": "✅",
    "enabled": "✅",
    "joined": "🟢",
    "done": "☑️",
    "completed": "☑️",
    "info": "ℹ️",
    "disabled": "⚪",
    "not-joined": "⚪",
    "warning": "⚠️",
    "attention": "🟠",
    "stale": "⚠️",
    "cancelled": "⏹️",
    "canceled": "⏹️",
    "restarting": "🔄",
    "error": "❌",
    "failed": "❌",
    "unavailable": "🔴",
}

_TASK_MODE_ALIASES = {
    "run": "running",
    "running": "running",
    "failed": "failed",
    "fail": "failed",
    "error": "failed",
    "errors": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "done": "done",
    "finished": "done",
    "restarting": "restarting",
    "restarted": "restarted",
    "stale": "stale",
    "problems": "problems",
    "problem": "problems",
}


@dataclass(frozen=True)
class StatusField:
    """One label/value row inside an operator status section."""

    label: str
    value: str

    def render(self) -> str:
        return f"{self.label}: {self.value}" if self.label else self.value


@dataclass(frozen=True)
class StatusSection:
    """One titled group in a structured status response."""

    title: str
    fields: tuple[StatusField, ...]
    icon: str = "•"

    @classmethod
    def from_lines(
        cls,
        title: str,
        lines: Iterable[str],
        *,
        icon: str = "•",
    ) -> StatusSection:
        return cls(
            title=title,
            fields=tuple(StatusField("", str(line)) for line in lines),
            icon=icon,
        )


@dataclass(frozen=True)
class TaskView:
    """Normalized operator view of one supervised background task."""

    scope: str
    name: str
    status: str
    kind: str
    created_at: Any = None
    done_at: Any = None
    heartbeat_at: Any = None
    restart_count: int = 0
    circuit_state: str = "closed"
    next_restart_at: Any = None
    last_error: str | None = None
    cancelled: bool = False
    stale: bool = False

    @property
    def label(self) -> str:
        return f"{self.scope}/{self.name}" if self.scope else self.name

    @property
    def needs_attention(self) -> bool:
        return self.stale or self.status in {"failed", "restarting"} or self.circuit_state == "open"


@dataclass(frozen=True)
class TaskListRequest:
    """Common operator grammar for task inventory commands."""

    mode: str = "overview"
    full: bool = False
    scope: str | None = None
    page: PageRequest = field(default_factory=PageRequest)
    show: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class RoomView:
    """Normalized operator-facing room inventory row."""

    jid: str
    joined: bool
    details: tuple[str, ...] = ()
    attention: bool = False
    unavailable: bool = False
    expected_joined: bool = True
    configured: bool = True

    @property
    def state(self) -> str:
        if self.unavailable:
            return "unavailable"
        if self.attention:
            return "attention"
        return "joined" if self.joined else "not-joined"

    @property
    def needs_attention(self) -> bool:
        return self.attention or self.unavailable or (self.expected_joined and not self.joined)


@dataclass(frozen=True)
class RoomListRequest:
    """Common operator grammar for room inventory commands."""

    filter: str = "all"
    page: PageRequest = field(default_factory=PageRequest)
    error: str | None = None


@dataclass(frozen=True)
class TaskSummary:
    """Aggregate task counts used by both task and status commands."""

    services_running: int
    one_shots_running: int
    one_shots_completed: int
    services_finished: int
    restarting: int
    failed: int
    stale: int
    restarted: int
    open_circuits: int
    cancelled: int

    @property
    def healthy(self) -> bool:
        return not any((self.failed, self.restarting, self.stale, self.open_circuits, self.services_finished))


def status_icon(status: str | None) -> str:
    """Return the common operator icon for a status value."""
    return _STATUS_ICONS.get(str(status or "").strip().lower(), "ℹ️")


def render_status_section(section: StatusSection) -> list[str]:
    """Render one tree-shaped status section, including multiline fields."""
    lines = [f"{section.icon} {section.title}:"]
    rendered = [field.render() for field in section.fields] or ["—"]
    for index, value in enumerate(rendered):
        parts = str(value).splitlines() or [""]
        is_last = index == len(rendered) - 1
        marker = "└─" if is_last else "├─"
        lines.append(f"{marker} {parts[0]}")
        continuation = "   " if is_last else "│  "
        lines.extend(f"{continuation}{part}" for part in parts[1:])
    lines.append("")
    return lines


def render_status_sections(
    title: str,
    sections: Sequence[StatusSection],
    *,
    preamble: Sequence[str] | Iterable[str] = (),
) -> list[str]:
    """Render a complete status response from application-owned sections."""
    preamble_rows = list(preamble)
    lines = [title, *preamble_rows, ""] if preamble_rows else [title, ""]
    for section in sections:
        lines.extend(render_status_section(section))
    return lines[:-1] if lines and lines[-1] == "" else lines


def _value(item: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = getattr(item, name, None)
        if value is not None:
            return value
    return default


def _time_detail(value: Any, *, now: float | None) -> str:
    if value in (None, ""):
        return "-"
    relative = format_relative_time(value, now=now)
    absolute = format_absolute_time(value)
    return relative if absolute == "-" else f"{relative} ({absolute})"


def task_view(
    item: Any,
    *,
    stale: bool = False,
) -> TaskView:
    """Normalize either bot's task facade into one shared presentation view."""
    status = str(_value(item, "status", default="unknown") or "unknown").lower()
    kind = str(_value(item, "kind", default="one-shot") or "one-shot")
    circuit = str(_value(item, "circuit_state", default="closed") or "closed").lower()
    if status == "running" and circuit == "half-open":
        status = "restarting"
    elif status == "restarting" and circuit == "closed":
        circuit = "half-open"

    raw_error = _value(item, "last_error")
    return TaskView(
        scope=str(_value(item, "scope", "plugin", "group", default="") or ""),
        name=str(_value(item, "name", default="?") or "?"),
        status=status,
        kind=kind,
        created_at=_value(item, "created_at"),
        done_at=_value(item, "done_at"),
        heartbeat_at=_value(item, "heartbeat_at"),
        restart_count=max(0, int(_value(item, "restart_count", default=0) or 0)),
        circuit_state=circuit,
        next_restart_at=_value(item, "next_restart_at", "restart_at"),
        last_error=(str(raw_error) if raw_error not in (None, "") else None),
        cancelled=bool(_value(item, "cancelled", default=(status == "cancelled"))),
        stale=bool(stale),
    )


def normalize_tasks(
    items: Iterable[Any],
    *,
    stale_ids: set[tuple[str, str]] | None = None,
) -> list[TaskView]:
    """Normalize and deterministically sort a task snapshot."""
    stale_ids = stale_ids or set()
    views = []
    for item in items:
        scope = str(_value(item, "scope", "plugin", "group", default="") or "")
        name = str(_value(item, "name", default="?") or "?")
        views.append(task_view(item, stale=(scope, name) in stale_ids))
    order = {"failed": 0, "restarting": 1, "running": 2, "cancelled": 3, "done": 4}
    return sorted(
        views,
        key=lambda view: (
            0 if view.stale else 1,
            order.get(view.status, 99),
            view.scope.casefold(),
            view.name.casefold(),
        ),
    )


def summarize_tasks(tasks: Iterable[TaskView]) -> TaskSummary:
    """Return lifecycle-aware task counts."""
    views = list(tasks)
    return TaskSummary(
        services_running=sum(view.kind == "service" and view.status == "running" for view in views),
        one_shots_running=sum(view.kind != "service" and view.status == "running" for view in views),
        one_shots_completed=sum(view.kind != "service" and view.status == "done" for view in views),
        services_finished=sum(view.kind == "service" and view.status == "done" for view in views),
        restarting=sum(view.status == "restarting" for view in views),
        failed=sum(view.status == "failed" for view in views),
        stale=sum(view.stale for view in views),
        restarted=sum(view.restart_count > 0 and view.status != "restarting" for view in views),
        open_circuits=sum(view.circuit_state == "open" for view in views),
        cancelled=sum(view.status == "cancelled" or view.cancelled for view in views),
    )


def task_scope_counts(tasks: Iterable[TaskView]) -> list[tuple[str, int]]:
    """Return sorted active task counts grouped by scope."""
    counts: Counter[str] = Counter()
    for view in tasks:
        if view.status in {"running", "restarting"}:
            counts[view.scope or "default"] += 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))


def render_task_summary(
    tasks: Iterable[TaskView],
    *,
    tree: bool = True,
    include_scopes: bool = True,
) -> list[str]:
    """Render a compact task-health overview."""
    views = list(tasks)
    summary = summarize_tasks(views)
    overall = "healthy" if summary.healthy else "attention needed"
    overall_icon = "✅" if summary.healthy else "⚠️"
    values = [
        f"{overall_icon} Overall: {overall}",
        f"Services: {summary.services_running} running",
        f"One-shots: {summary.one_shots_running} running · {summary.one_shots_completed} completed",
        f"Restarting: {summary.restarting}",
        f"Failed: {summary.failed}",
        f"Stale: {summary.stale}",
        f"Open circuits: {summary.open_circuits}",
    ]
    if tree:
        lines = [values[0]]
        for index, value in enumerate(values[1:]):
            marker = "└─" if index == len(values[1:]) - 1 else "├─"
            lines.append(f"{marker} {value}")
    else:
        lines = values

    if summary.services_finished or summary.cancelled or summary.restarted:
        extras: list[str] = []
        if summary.services_finished:
            extras.append(f"services finished={summary.services_finished}")
        if summary.cancelled:
            extras.append(f"cancelled={summary.cancelled}")
        if summary.restarted:
            extras.append(f"restarted={summary.restarted}")
        lines.append("ℹ️ History: " + " · ".join(extras))

    scopes = task_scope_counts(views)
    if scopes and include_scopes:
        lines.extend(["", "📦 Scopes"])
        if tree:
            for index, (scope, count) in enumerate(scopes):
                marker = "└─" if index == len(scopes) - 1 else "├─"
                lines.append(f"{marker} {scope}: {count} active")
        else:
            lines.extend(f"{scope}: {count} active" for scope, count in scopes)
    return lines


def render_task_entry(view: TaskView, *, full: bool = False, now: float | None = None) -> str:
    """Render one task as a compact or diagnostic multi-line block."""
    state = "stale" if view.stale else view.status
    icon = status_icon(state)

    if not full:
        details = [view.kind]
        progress = view.heartbeat_at if view.heartbeat_at not in (None, "") else view.created_at
        if progress and view.status in {"running", "restarting"}:
            label = "heartbeat" if view.heartbeat_at not in (None, "") else "started"
            details.append(f"{label} {format_relative_time(progress, now=now)}")
        details.append(f"restarts {view.restart_count}")
        if view.status == "restarting" and view.next_restart_at is not None:
            details.append(f"retry {format_relative_time(view.next_restart_at, now=now)}")
        if view.circuit_state != "closed":
            details.append(f"circuit {view.circuit_state}")
        result = f"{icon} {view.label}\n   {state} · " + " · ".join(details)
        if view.last_error:
            result += f"\n   last error: {view.last_error}"
        return result

    details = [
        f"status: {state}",
        f"kind: {view.kind}",
        f"created: {_time_detail(view.created_at, now=now)}",
        f"heartbeat: {_time_detail(view.heartbeat_at, now=now) if view.heartbeat_at else 'not reported'}",
        f"restarts: {view.restart_count}",
        f"circuit: {view.circuit_state}",
    ]
    if view.done_at is not None:
        details.append(f"done: {_time_detail(view.done_at, now=now)}")
    if view.next_restart_at is not None:
        details.append(f"next restart: {_time_detail(view.next_restart_at, now=now)}")
    if view.last_error:
        details.append(f"last error: {view.last_error}")
    return f"{icon} {view.label}\n   " + "\n   ".join(details)


def task_problem_views(tasks: Iterable[TaskView]) -> list[TaskView]:
    """Return only tasks that currently need operator attention."""
    return [view for view in tasks if view.needs_attention]


def parse_task_list_request(args: Sequence[str]) -> TaskListRequest:
    """Parse the shared task-command grammar in any sensible modifier order."""
    tokens = [str(value).strip() for value in args if str(value).strip()]
    if not tokens:
        return TaskListRequest()

    full = False
    scope: str | None = None
    mode: str | None = None
    show: str | None = None
    page = PageRequest()
    paging_seen = False
    index = 0

    def fail(reason: str) -> TaskListRequest:
        return TaskListRequest(full=full, scope=scope, page=page, show=show, error=reason)

    while index < len(tokens):
        token = tokens[index]
        lowered = token.lower()
        if lowered in {"full", "details", "all-details"}:
            if full:
                return fail("duplicate full modifier")
            full = True
            index += 1
            continue
        if lowered in {"scope", "group", "plugin"}:
            if scope is not None:
                return fail("duplicate scope filter")
            if index + 1 >= len(tokens):
                return fail("missing scope name")
            scope = tokens[index + 1]
            index += 2
            continue
        if lowered == "show":
            if show is not None or mode not in (None, "show"):
                return fail("conflicting task view")
            if index + 1 >= len(tokens):
                return fail("missing task label")
            show = tokens[index + 1]
            mode = "show"
            full = True
            index += 2
            continue
        if lowered == "list":
            if mode not in (None, "inventory"):
                return fail("conflicting task view")
            mode = "inventory"
            index += 1
            continue
        if lowered in _TASK_MODE_ALIASES:
            parsed_mode = _TASK_MODE_ALIASES[lowered]
            if mode not in (None, parsed_mode):
                return fail("conflicting task filters")
            mode = parsed_mode
            index += 1
            continue
        if lowered == "all" or lowered == "last" or lowered.isdigit():
            if paging_seen:
                return fail("duplicate page selector")
            paging_seen = True
            if lowered == "all":
                page = PageRequest(all=True)
            elif lowered == "last":
                page = PageRequest(page=-1)
            else:
                page = PageRequest(page=max(1, int(lowered)))
            index += 1
            continue
        return fail(f"unknown argument: {token}")

    if show is not None and paging_seen:
        return fail("task detail view cannot be paged")
    if mode is None:
        mode = "inventory" if full or scope is not None or paging_seen else "overview"
    return TaskListRequest(mode=mode, full=full, scope=scope, page=page, show=show)


def filter_task_views(tasks: Iterable[TaskView], request: TaskListRequest) -> list[TaskView]:
    """Apply a parsed task request to normalized task views."""
    views = list(tasks)
    if request.scope:
        needle = request.scope.casefold()
        views = [view for view in views if view.scope.casefold() == needle]

    if request.mode == "failed":
        return [view for view in views if view.status == "failed"]
    if request.mode == "stale":
        return [view for view in views if view.stale]
    if request.mode == "restarting":
        return [view for view in views if view.status == "restarting"]
    if request.mode == "restarted":
        return [view for view in views if view.restart_count > 0 and view.status != "restarting"]
    if request.mode == "problems":
        return task_problem_views(views)
    if request.mode in {"running", "cancelled", "done"}:
        return [view for view in views if view.status == request.mode]
    if request.mode == "show":
        needle = str(request.show or "").casefold()
        return [view for view in views if view.label.casefold() == needle or view.name.casefold() == needle]
    return views


def render_session_lifecycle_lines(
    snapshot: SessionLifecycleSnapshot | None,
    *,
    full: bool = False,
) -> list[str]:
    """Render shared XMPP-session telemetry for operator status output."""
    if snapshot is None:
        return ["Session: unavailable"]

    lines = [
        (
            f"Session: {snapshot.state} · generation {snapshot.generation} · "
            f"reconnects {snapshot.reconnect_count}"
        )
    ]
    if snapshot.state in {"starting", "reconnecting", "failed"} and snapshot.phase:
        age = (
            format_duration(snapshot.phase_age_seconds)
            if snapshot.phase_age_seconds is not None
            else "unknown"
        )
        lines.append(f"Session phase: {snapshot.phase} · age {age}")
    if snapshot.startup_duration_seconds is not None:
        lines.append(
            "Session startup: "
            + format_duration(snapshot.startup_duration_seconds, zero_label="<1s")
        )
    if snapshot.last_error:
        lines.append(f"Session error: {snapshot.last_error}")

    if full:
        if snapshot.session_started_at:
            lines.append(
                f"Session started: {format_relative_time(snapshot.session_started_at)} "
                f"({snapshot.session_started_at})"
            )
        if snapshot.last_ready_at:
            lines.append(
                f"Last ready: {format_relative_time(snapshot.last_ready_at)} "
                f"({snapshot.last_ready_at})"
            )
        if snapshot.last_disconnect_at:
            reason = snapshot.last_disconnect_reason or "unknown reason"
            lines.append(
                f"Last disconnect: {reason} · "
                f"{format_relative_time(snapshot.last_disconnect_at)} "
                f"({snapshot.last_disconnect_at})"
            )
    return lines


def render_watchdog_lines(state: Mapping[str, Any] | None) -> list[str]:
    """Render either bot's watchdog runtime-state mapping."""
    if not state:
        return ["ℹ️ Status: unavailable"]
    enabled = bool(state.get("enabled", True))
    worker_running = bool(state.get("worker_running", True))
    suppressed = int(state.get("heartbeat_suppressed", 0) or 0)
    last_error = state.get("last_error")
    if not enabled:
        status = "disabled"
        icon = "⏹️"
    elif not worker_running or last_error:
        status = "unhealthy"
        icon = "❌"
    elif suppressed:
        status = "degraded"
        icon = "⚠️"
    else:
        status = "healthy"
        icon = "✅"
    lines = [
        f"{icon} Status: {status}",
        f"├─ systemd watchdog: {'active' if state.get('systemd_active') else 'inactive'}",
        (
            "├─ event-loop lag: "
            f"{float(state.get('last_lag_seconds', 0.0) or 0.0):.3f}s current · "
            f"{float(state.get('max_lag_seconds', 0.0) or 0.0):.3f}s max"
        ),
        (
            "└─ heartbeats: "
            f"{int(state.get('heartbeats', 0) or 0)} · suppressed: {suppressed}"
        ),
    ]
    if last_error:
        lines.append(f"❌ last error: {last_error}")
    return lines


def render_room_entry(room: RoomView) -> str:
    """Render one room inventory entry."""
    icon = status_icon(room.state)
    details = " · ".join(room.details)
    return f"{icon} {room.jid}" + (f"\n   {details}" if details else "")


def room_summary(rooms: Iterable[RoomView]) -> str:
    """Return a compact room inventory summary."""
    views = list(rooms)
    configured = sum(room.configured for room in views)
    joined = sum(room.joined for room in views)
    problems = sum(room.needs_attention for room in views)
    values = [f"{configured} configured"]
    if len(views) != configured:
        values.append(f"{len(views)} known")
    values.extend([f"{joined} joined", f"{problems} issue{'s' if problems != 1 else ''}"])
    return "Summary: " + " · ".join(values)


def room_problem_views(rooms: Iterable[RoomView]) -> list[RoomView]:
    """Return room entries that need attention."""
    return [room for room in rooms if room.needs_attention]


def parse_room_list_request(args: Sequence[str]) -> RoomListRequest:
    """Parse ``joined|offline|problems`` plus one page selector in any order."""
    tokens = [str(value).strip() for value in args if str(value).strip()]
    room_filter = "all"
    page = PageRequest()
    filter_seen = False
    paging_seen = False
    for token in tokens:
        lowered = token.lower()
        if lowered in {"joined", "offline", "problems"}:
            if filter_seen:
                return RoomListRequest(filter=room_filter, page=page, error="duplicate room filter")
            room_filter = lowered
            filter_seen = True
            continue
        if lowered == "all" or lowered == "last" or lowered.isdigit():
            if paging_seen:
                return RoomListRequest(filter=room_filter, page=page, error="duplicate page selector")
            paging_seen = True
            if lowered == "all":
                page = PageRequest(all=True)
            elif lowered == "last":
                page = PageRequest(page=-1)
            else:
                page = PageRequest(page=max(1, int(lowered)))
            continue
        return RoomListRequest(filter=room_filter, page=page, error=f"unknown argument: {token}")
    return RoomListRequest(filter=room_filter, page=page)


def filter_room_views(rooms: Iterable[RoomView], request: RoomListRequest) -> list[RoomView]:
    """Apply a parsed room filter to a normalized room inventory."""
    views = list(rooms)
    if request.filter == "joined":
        return [room for room in views if room.joined]
    if request.filter == "offline":
        return [room for room in views if not room.joined]
    if request.filter == "problems":
        return room_problem_views(views)
    return views


def fields_from_mapping(values: Mapping[str, Any]) -> tuple[StatusField, ...]:
    """Convenience helper for deterministic label/value section construction."""
    return tuple(StatusField(str(key), str(value)) for key, value in values.items())
