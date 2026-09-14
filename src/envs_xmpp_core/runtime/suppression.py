"""Bounded cooldown state for repetitive runtime events.

The helper intentionally knows nothing about logging or XMPP.  Callers can use
it to reduce repeated operator-visible messages while still executing the
underlying action every time.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CooldownDecision:
    """Result of one keyed cooldown check."""

    allowed: bool
    suppressed: int = 0


@dataclass
class KeyedCooldown:
    """Bounded per-key cooldown with repeat accounting.

    ``check()`` reserves a key when it is outside the cooldown window. Calls
    inside the window are denied and counted.  The next allowed call reports
    how many repetitions were suppressed since the previous emission.
    """

    cooldown_seconds: float = 300.0
    max_keys: int = 1024
    _state: OrderedDict[str, tuple[float, int]] = field(
        default_factory=OrderedDict,
        init=False,
        repr=False,
    )

    def _trim(self) -> None:
        limit = max(1, int(self.max_keys))
        while len(self._state) > limit:
            self._state.popitem(last=False)

    def check(
        self,
        key: str,
        *,
        now: float | None = None,
        cooldown_seconds: float | None = None,
    ) -> CooldownDecision:
        """Reserve ``key`` if its cooldown has elapsed."""
        timestamp = time.monotonic() if now is None else float(now)
        window = self.cooldown_seconds if cooldown_seconds is None else cooldown_seconds
        window = max(0.0, float(window or 0.0))
        normalized = str(key)
        previous = self._state.get(normalized)

        if previous is not None:
            last_allowed, suppressed = previous
            if window and timestamp - last_allowed < window:
                suppressed += 1
                self._state[normalized] = (last_allowed, suppressed)
                self._state.move_to_end(normalized)
                return CooldownDecision(False, suppressed)
        else:
            suppressed = 0

        previous_suppressed = suppressed
        self._state[normalized] = (timestamp, 0)
        self._state.move_to_end(normalized)
        self._trim()
        return CooldownDecision(True, previous_suppressed)

    def forget(self, key: str) -> None:
        """Forget all cooldown/repeat state for one key."""
        self._state.pop(str(key), None)

    def clear(self) -> None:
        """Clear all cooldown/repeat state."""
        self._state.clear()

    def __len__(self) -> int:
        return len(self._state)
