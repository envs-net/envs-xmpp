"""Shared passive runtime-health snapshot primitives."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

HealthStatus = Literal["ok", "warning", "error", "unknown"]


@dataclass(frozen=True)
class HealthCheck:
    """One detached health check with structured data for renderers."""

    key: str
    status: HealthStatus
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def needs_attention(self) -> bool:
        """Return whether this check represents an actionable problem."""
        return self.status in {"warning", "error"}


@dataclass(frozen=True)
class HealthSnapshot:
    """Detached point-in-time health view composed of named checks."""

    checked_at: str
    checks: dict[str, HealthCheck]

    def check(self, key: str) -> HealthCheck:
        """Return a named check or an explicit unknown placeholder."""
        return self.checks.get(
            key,
            HealthCheck(key=key, status="unknown", summary="unavailable"),
        )

    @property
    def needs_attention(self) -> bool:
        """Return whether any check is warning or error."""
        return any(check.needs_attention for check in self.checks.values())

    @property
    def problem_keys(self) -> tuple[str, ...]:
        """Return keys for checks that currently need attention."""
        return tuple(key for key, check in self.checks.items() if check.needs_attention)


@dataclass(frozen=True)
class TaskDiagnostic:
    """Normalized task state independent of application compatibility facades."""

    scope: str
    name: str
    status: str
    kind: str
    restart_count: int = 0
    circuit_state: str = "closed"
    last_error: str | None = None

    @property
    def label(self) -> str:
        """Return a stable operator-oriented scope/name label."""
        return f"{self.scope}/{self.name}" if self.scope else self.name


@dataclass(frozen=True)
class TaskHealthState:
    """Normalized passive diagnostics derived from a task-supervisor snapshot."""

    tasks: tuple[TaskDiagnostic, ...]
    services_running: int
    one_shots_running: int
    one_shots_completed: int
    services_finished: int
    failed: int
    cancelled: int
    failed_tasks: tuple[TaskDiagnostic, ...]
    restarting_tasks: tuple[TaskDiagnostic, ...]
    restarted_tasks: tuple[TaskDiagnostic, ...]
    open_circuits: tuple[TaskDiagnostic, ...]

    @property
    def counts(self) -> dict[str, int]:
        """Return the historical supervisor count mapping used by renderers."""
        return {
            "services_running": self.services_running,
            "one_shots_running": self.one_shots_running,
            "one_shots_completed": self.one_shots_completed,
            "services_finished": self.services_finished,
            "failed": self.failed,
            "cancelled": self.cancelled,
        }


def _task_scope(item: Any) -> str:
    for attribute in ("scope", "plugin", "group"):
        value = getattr(item, attribute, None)
        if value is not None:
            return str(value)
    return ""


def analyze_task_snapshot(items: Iterable[Any]) -> TaskHealthState:
    """Normalize task snapshots from either bot without imposing health policy."""
    tasks: list[TaskDiagnostic] = []
    for item in items:
        status = str(getattr(item, "status", "unknown") or "unknown")
        circuit_state = str(getattr(item, "circuit_state", "closed") or "closed")
        if status == "running" and circuit_state == "half-open":
            status = "restarting"
        elif status == "restarting" and circuit_state == "closed":
            circuit_state = "half-open"
        tasks.append(
            TaskDiagnostic(
                scope=_task_scope(item),
                name=str(getattr(item, "name", "?") or "?"),
                status=status,
                kind=str(getattr(item, "kind", "one-shot") or "one-shot"),
                restart_count=max(0, int(getattr(item, "restart_count", 0) or 0)),
                circuit_state=circuit_state,
                last_error=(str(item.last_error) if getattr(item, "last_error", None) is not None else None),
            )
        )

    services_running = one_shots_running = one_shots_completed = services_finished = 0
    failed = cancelled = 0
    for task in tasks:
        if task.status == "failed":
            failed += 1
        elif task.status == "cancelled":
            cancelled += 1
        elif task.status in {"running", "restarting"}:
            if task.kind == "service":
                services_running += 1
            else:
                one_shots_running += 1
        elif task.kind == "service":
            services_finished += 1
        else:
            one_shots_completed += 1

    return TaskHealthState(
        tasks=tuple(tasks),
        services_running=services_running,
        one_shots_running=one_shots_running,
        one_shots_completed=one_shots_completed,
        services_finished=services_finished,
        failed=failed,
        cancelled=cancelled,
        failed_tasks=tuple(task for task in tasks if task.status == "failed"),
        restarting_tasks=tuple(task for task in tasks if task.status == "restarting"),
        restarted_tasks=tuple(task for task in tasks if task.restart_count > 0 and task.status != "restarting"),
        open_circuits=tuple(task for task in tasks if task.circuit_state == "open"),
    )


@dataclass(frozen=True)
class WatchdogHealthState:
    """Normalized passive diagnostics for the shared runtime watchdog."""

    available: bool = False
    enabled: bool = False
    systemd_active: bool = False
    worker_running: bool = False
    heartbeats: int = 0
    last_heartbeat_at: int = 0
    last_lag_seconds: float = 0.0
    max_lag_seconds: float = 0.0
    lag_warnings: int = 0
    heartbeat_suppressed: int = 0
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a renderer-friendly mapping with stable primitive values."""
        return asdict(self)


def _watchdog_mapping(watchdog: Any) -> Mapping[str, Any] | None:
    if watchdog is None:
        return None
    runtime_state = getattr(watchdog, "runtime_state", None)
    if callable(runtime_state):
        value = runtime_state()
        if isinstance(value, Mapping):
            return value
    state = getattr(watchdog, "state", None)
    if state is None:
        return None
    if isinstance(state, Mapping):
        return state
    return {
        name: getattr(state, name, None)
        for name in (
            "enabled",
            "systemd_active",
            "worker_running",
            "heartbeats",
            "last_heartbeat_at",
            "last_lag_seconds",
            "max_lag_seconds",
            "lag_warnings",
            "heartbeat_suppressed",
            "last_error",
        )
    }


def watchdog_health_state(watchdog: Any) -> WatchdogHealthState:
    """Normalize watchdog runtime state while leaving severity policy to callers."""
    state = _watchdog_mapping(watchdog)
    if state is None:
        return WatchdogHealthState()
    error = str(state.get("last_error") or "").strip() or None
    return WatchdogHealthState(
        available=True,
        enabled=bool(state.get("enabled", False)),
        systemd_active=bool(state.get("systemd_active", False)),
        worker_running=bool(state.get("worker_running", False)),
        heartbeats=max(0, int(state.get("heartbeats", 0) or 0)),
        last_heartbeat_at=max(0, int(state.get("last_heartbeat_at", 0) or 0)),
        last_lag_seconds=max(0.0, float(state.get("last_lag_seconds", 0.0) or 0.0)),
        max_lag_seconds=max(0.0, float(state.get("max_lag_seconds", 0.0) or 0.0)),
        lag_warnings=max(0, int(state.get("lag_warnings", 0) or 0)),
        heartbeat_suppressed=max(0, int(state.get("heartbeat_suppressed", 0) or 0)),
        last_error=error,
    )


@dataclass(frozen=True)
class LifecycleHealthState:
    """Normalized startup/shutdown phase diagnostics shared by both bots."""

    startup: tuple[tuple[str, str], ...]
    shutdown: tuple[tuple[str, str], ...]

    @property
    def startup_attention(self) -> tuple[str, ...]:
        return tuple(name for name, status in self.startup if status not in {"ok", "skipped"})

    @property
    def shutdown_attention(self) -> tuple[str, ...]:
        return tuple(name for name, status in self.shutdown if status not in {"ok", "skipped"})


def lifecycle_health_state(owner: Any) -> LifecycleHealthState:
    """Read the shared lifecycle result convention without application policy."""

    def normalize(attribute: str) -> tuple[tuple[str, str], ...]:
        phases = tuple(getattr(owner, attribute, ()) or ())
        return tuple(
            (
                str(getattr(phase, "name", "?") or "?"),
                str(getattr(phase, "status", "unknown") or "unknown"),
            )
            for phase in phases
        )

    return LifecycleHealthState(
        startup=normalize("_last_startup_phases"),
        shutdown=normalize("_last_shutdown_phases"),
    )


type HealthCollector = Callable[[], HealthCheck | Awaitable[HealthCheck]]


def _checked_at_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def collect_health_snapshot(
    collectors: Iterable[tuple[str, HealthCollector]],
    *,
    checked_at: str | None = None,
) -> HealthSnapshot:
    """Collect independent checks without one failure aborting the snapshot.

    Cancellation remains cooperative and is always re-raised. Any other
    collector failure becomes an ``error`` check so callers can still render a
    complete diagnostic snapshot.
    """
    checks: dict[str, HealthCheck] = {}
    for key, collector in collectors:
        try:
            result = collector()
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, HealthCheck):
                raise TypeError(f"{key} collector returned {type(result).__name__}")
            if result.key != key:
                raise ValueError(f"{key} collector returned mismatched key {result.key!r}")
            checks[key] = result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - health isolation boundary
            checks[key] = HealthCheck(
                key,
                "error",
                f"health check failed: {type(exc).__name__}",
                {},
                f"{type(exc).__name__}: {exc}",
            )

    return HealthSnapshot(
        checked_at=checked_at or _checked_at_now(),
        checks=checks,
    )
