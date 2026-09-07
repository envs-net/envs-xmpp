"""Neutral ordered lifecycle phase orchestration primitives."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter

type LifecyclePhaseOutcome = tuple[str, Mapping[str, object]] | None
type LifecyclePhaseOperation = Callable[[], Awaitable[LifecyclePhaseOutcome]]
type LifecyclePhaseObserver = Callable[["LifecyclePhaseResult", Exception | None], None]


@dataclass(frozen=True, slots=True)
class LifecyclePhaseResult:
    """Result of one startup/shutdown lifecycle phase."""

    name: str
    status: str
    duration_seconds: float
    details: dict[str, object] = field(default_factory=dict)

    @property
    def healthy(self) -> bool:
        """Return whether the phase completed cleanly or was not applicable."""
        return self.status in {"ok", "skipped"}


class LifecyclePhaseRunner:
    """Run ordered async lifecycle phases while retaining structured results.

    The runner deliberately does not log. Applications can provide an observer
    to preserve their own logging vocabulary and policy. Ordinary exceptions
    are recorded as failed phases before being re-raised, unless
    ``continue_on_error`` is requested. Cancellation always propagates.
    """

    def __init__(self, *, observer: LifecyclePhaseObserver | None = None) -> None:
        self._results: list[LifecyclePhaseResult] = []
        self._observer = observer

    @property
    def results(self) -> tuple[LifecyclePhaseResult, ...]:
        """Return an immutable snapshot of all completed/failed phases."""
        return tuple(self._results)

    def _record(self, result: LifecyclePhaseResult, error: Exception | None) -> None:
        self._results.append(result)
        if self._observer is not None:
            self._observer(result, error)

    async def run(
        self,
        name: str,
        operation: LifecyclePhaseOperation,
        *,
        continue_on_error: bool = False,
        default_status: str = "ok",
    ) -> LifecyclePhaseResult:
        """Run one phase, record timing/status and optionally continue on error."""
        started = perf_counter()
        try:
            outcome = await operation()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = LifecyclePhaseResult(
                name=name,
                status="failed",
                duration_seconds=perf_counter() - started,
            )
            self._record(result, exc)
            if continue_on_error:
                return result
            raise

        if outcome is None:
            status = default_status
            details: dict[str, object] = {}
        else:
            status, raw_details = outcome
            details = dict(raw_details)

        result = LifecyclePhaseResult(
            name=name,
            status=str(status),
            duration_seconds=perf_counter() - started,
            details=details,
        )
        self._record(result, None)
        return result

    async def run_all(
        self,
        phases: Sequence[tuple[str, LifecyclePhaseOperation]],
        *,
        continue_on_error: bool = False,
    ) -> tuple[LifecyclePhaseResult, ...]:
        """Run phases in order and return the complete result snapshot."""
        for name, operation in phases:
            await self.run(name, operation, continue_on_error=continue_on_error)
        return self.results
