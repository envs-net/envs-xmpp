"""Stable bot-neutral runtime helpers."""

from .alerts import AlertTracker, TransitionAlertState
from .diagnostics import DiagnosticError, diagnostic_error, diagnostic_payload, exception_summary
from .health import (
    HealthCheck,
    HealthSnapshot,
    RoomJoinHealthState,
    TaskHealthState,
    WatchdogHealthState,
    analyze_room_join_state,
    health_check_from_messages,
    health_snapshot_messages,
    supervisor_task_health_state,
    watchdog_health_state,
)
from .reconnect import run_reconnect_loop
from .session import SessionLifecycleSnapshot, SessionLifecycleState
from .suppression import CooldownDecision, KeyedCooldown

__all__ = [
    "AlertTracker",
    "CooldownDecision",
    "DiagnosticError",
    "HealthCheck",
    "HealthSnapshot",
    "KeyedCooldown",
    "RoomJoinHealthState",
    "SessionLifecycleSnapshot",
    "SessionLifecycleState",
    "TaskHealthState",
    "TransitionAlertState",
    "WatchdogHealthState",
    "analyze_room_join_state",
    "diagnostic_error",
    "diagnostic_payload",
    "exception_summary",
    "health_check_from_messages",
    "health_snapshot_messages",
    "run_reconnect_loop",
    "supervisor_task_health_state",
    "watchdog_health_state",
]
