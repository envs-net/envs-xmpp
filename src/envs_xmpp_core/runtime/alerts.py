"""Shared operational-alert state primitives."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TransitionAlertState:
    """State for an alert that opens, repeats and eventually resolves."""

    active: bool = False
    since: int = 0
    last_notified_at: int = 0
    summary: str = ""
    fingerprint: str = ""


@dataclass
class AlertTracker:
    """Track deduplication windows and consecutive failures by alert key."""

    dedup_window_seconds: int = 300
    last_sent: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def should_emit(
        self,
        key: str,
        *,
        now: float | None = None,
        dedup_window_seconds: int | None = None,
    ) -> bool:
        """Reserve an alert key when it is outside its deduplication window."""
        timestamp = time.time() if now is None else float(now)
        window = self.dedup_window_seconds if dedup_window_seconds is None else dedup_window_seconds
        window = max(0, int(window or 0))
        last = self.last_sent.get(str(key), 0.0)
        if window and timestamp - last < window:
            return False
        self.last_sent[str(key)] = timestamp
        return True

    def forget_emission(self, key: str) -> None:
        """Release a reserved emission after delivery could not be accepted."""
        self.last_sent.pop(str(key), None)

    def record_success(self, key: str) -> None:
        """Reset a consecutive-failure counter."""
        self.counters.pop(str(key), None)

    def record_failure(self, key: str) -> int:
        """Increment and return a consecutive-failure counter."""
        normalized = str(key)
        count = self.counters.get(normalized, 0) + 1
        self.counters[normalized] = count
        return count
