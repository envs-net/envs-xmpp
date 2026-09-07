"""Shared passive runtime-health snapshot primitives."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
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
        return tuple(
            key for key, check in self.checks.items() if check.needs_attention
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
                raise TypeError(
                    f"{key} collector returned {type(result).__name__}"
                )
            if result.key != key:
                raise ValueError(
                    f"{key} collector returned mismatched key {result.key!r}"
                )
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
