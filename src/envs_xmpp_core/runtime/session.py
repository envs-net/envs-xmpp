"""Bot-neutral XMPP session lifecycle state and generation guards."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class SessionLifecycleSnapshot:
    """Immutable operator/health snapshot for one process' XMPP sessions."""

    generation: int
    reconnect_count: int
    state: str
    phase: str | None
    session_started_at: str | None
    last_ready_at: str | None
    last_disconnect_at: str | None
    last_disconnect_reason: str | None
    last_error: str | None
    startup_duration_seconds: float | None
    phase_age_seconds: float | None
    session_age_seconds: float | None

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def as_dict(self) -> dict[str, object]:
        """Return a serialization-friendly mapping for status/health layers."""
        return {
            "generation": self.generation,
            "reconnect_count": self.reconnect_count,
            "state": self.state,
            "phase": self.phase,
            "session_started_at": self.session_started_at,
            "last_ready_at": self.last_ready_at,
            "last_disconnect_at": self.last_disconnect_at,
            "last_disconnect_reason": self.last_disconnect_reason,
            "last_error": self.last_error,
            "startup_duration_seconds": self.startup_duration_seconds,
            "phase_age_seconds": self.phase_age_seconds,
            "session_age_seconds": self.session_age_seconds,
        }


class SessionLifecycleState:
    """Track session generations without owning application reconnect policy.

    Every ``session_start`` gets a monotonically increasing generation. Async
    work can retain that generation and use :meth:`is_current` before mutating
    session-scoped state, which makes late callbacks from an older stream easy
    to reject deterministically.
    """

    def __init__(self) -> None:
        self._generation = 0
        self._reconnect_count = 0
        self._state = "idle"
        self._phase: str | None = None
        self._session_started_wall: float | None = None
        self._session_started_monotonic: float | None = None
        self._phase_started_monotonic: float | None = None
        self._last_ready_wall: float | None = None
        self._last_disconnect_wall: float | None = None
        self._last_disconnect_reason: str | None = None
        self._last_error: str | None = None
        self._startup_duration_seconds: float | None = None

    @staticmethod
    def _iso(value: float | None) -> str | None:
        if value is None:
            return None
        return datetime.fromtimestamp(value, tz=UTC).isoformat(timespec="seconds")

    @property
    def generation(self) -> int:
        return self._generation

    def is_current(self, generation: int) -> bool:
        """Return whether ``generation`` still names the active session."""
        return int(generation) == self._generation and self._state in {"starting", "ready"}

    def begin(self) -> int:
        """Start a new XMPP session generation and return its identifier."""
        if self._generation:
            self._reconnect_count += 1
        self._generation += 1
        self._state = "starting"
        self._phase = "session"
        self._session_started_wall = time.time()
        self._session_started_monotonic = time.monotonic()
        self._phase_started_monotonic = self._session_started_monotonic
        self._last_error = None
        self._startup_duration_seconds = None
        return self._generation

    def begin_phase(self, generation: int, phase: str) -> bool:
        """Mark a startup phase if the caller still belongs to this session."""
        if not self.is_current(generation):
            return False
        self._state = "starting"
        self._phase = str(phase)
        self._phase_started_monotonic = time.monotonic()
        return True

    def mark_ready(self, generation: int) -> bool:
        """Mark the current session ready and retain startup duration."""
        if not self.is_current(generation):
            return False
        now_mono = time.monotonic()
        self._state = "ready"
        self._phase = "ready"
        self._phase_started_monotonic = now_mono
        self._last_ready_wall = time.time()
        if self._session_started_monotonic is not None:
            self._startup_duration_seconds = max(0.0, now_mono - self._session_started_monotonic)
        self._last_error = None
        return True

    def mark_failed(self, generation: int, error: object) -> bool:
        """Record failure for the current session without changing generations."""
        if not self.is_current(generation):
            return False
        self._state = "failed"
        self._last_error = str(error) or type(error).__name__
        return True

    def mark_reconnecting(self, reason: str | None = None) -> None:
        """Record reconnect backoff between an ended and the next session."""
        self._state = "reconnecting"
        self._phase = "backoff"
        self._phase_started_monotonic = time.monotonic()
        self._last_disconnect_wall = time.time()
        if reason:
            self._last_disconnect_reason = str(reason).strip()

    def mark_disconnected(self, reason: str | None = None) -> None:
        """Record transport loss for the current generation."""
        self._state = "disconnected"
        self._phase = None
        self._phase_started_monotonic = None
        self._last_disconnect_wall = time.time()
        self._last_disconnect_reason = str(reason).strip() if reason else None

    def snapshot(self) -> SessionLifecycleSnapshot:
        """Return current session telemetry with live age calculations."""
        now_mono = time.monotonic()
        phase_age = None
        if self._phase_started_monotonic is not None:
            phase_age = max(0.0, now_mono - self._phase_started_monotonic)
        session_age = None
        if self._session_started_monotonic is not None and self._state in {"starting", "ready", "failed"}:
            session_age = max(0.0, now_mono - self._session_started_monotonic)
        return SessionLifecycleSnapshot(
            generation=self._generation,
            reconnect_count=self._reconnect_count,
            state=self._state,
            phase=self._phase,
            session_started_at=self._iso(self._session_started_wall),
            last_ready_at=self._iso(self._last_ready_wall),
            last_disconnect_at=self._iso(self._last_disconnect_wall),
            last_disconnect_reason=self._last_disconnect_reason,
            last_error=self._last_error,
            startup_duration_seconds=self._startup_duration_seconds,
            phase_age_seconds=phase_age,
            session_age_seconds=session_age,
        )
