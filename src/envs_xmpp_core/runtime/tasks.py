"""Neutral background task supervision primitives."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

log = logging.getLogger(__name__)
_COMPLETED_ONE_SHOT_HISTORY_LIMIT = 50
type CircuitCallback = Callable[[str, str, str], Awaitable[None] | None]
type HeartbeatCallback = Callable[[], Any]
type SleepCallback = Callable[[float], Awaitable[Any]]
type WaitForCallback = Callable[..., Awaitable[Any]]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _datetime_from_timestamp(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def _asyncio_create_task_supports_name() -> bool:
    try:
        return "name" in inspect.signature(asyncio.create_task).parameters
    except (TypeError, ValueError):
        return True


@dataclass(frozen=True)
class SupervisorOptions:
    max_restarts: int = 5
    initial_backoff: float = 5.0
    max_backoff: float = 300.0
    reset_after: float = 900.0
    stale_after: float = 3600.0
    yield_before_start: bool = True
    terminal_error_style: str = "circuit"


class ExpectedTaskExit(Exception):
    """Signal an intentional service-task exit outside process shutdown."""


def runtime_is_ready(owner: Any, *, attribute: str = "runtime_ready") -> bool:
    """Return whether an optional runtime-readiness gate is open.

    Objects without such a gate retain historical immediate behavior, which is
    useful for lightweight test doubles and applications that do not need a
    separate startup barrier.
    """
    runtime_ready = getattr(owner, attribute, None)
    if runtime_ready is None:
        return True
    is_set = getattr(runtime_ready, "is_set", None)
    return bool(is_set()) if callable(is_set) else True


async def wait_for_runtime_ready(
    owner: Any,
    *,
    heartbeat: HeartbeatCallback | None = None,
    attribute: str = "runtime_ready",
) -> None:
    """Wait for an optional runtime gate and emit one progress heartbeat."""
    if not runtime_is_ready(owner, attribute=attribute):
        runtime_ready = getattr(owner, attribute, None)
        wait = getattr(runtime_ready, "wait", None)
        if callable(wait):
            await wait()
    if heartbeat is not None:
        heartbeat()


def task_heartbeat_interval(
    stale_after: float | str | None,
    *,
    maximum: float = 30.0,
    default_stale_after: float = 3600.0,
) -> float:
    """Return a cadence that remains safely below a task stale threshold."""
    try:
        configured = float(stale_after or default_stale_after)
    except (TypeError, ValueError):
        configured = float(default_stale_after)
    safe_maximum = max(0.05, float(maximum))
    return max(0.05, min(safe_maximum, max(0.05, configured / 2.0)))


def _emit_heartbeat(heartbeat: HeartbeatCallback | None) -> None:
    if heartbeat is not None:
        heartbeat()


async def sleep_with_heartbeat(
    delay: float,
    *,
    heartbeat: HeartbeatCallback | None = None,
    stale_after: float | str | None = 3600.0,
    interval: float = 30.0,
    sleep_func: SleepCallback | None = None,
) -> None:
    """Sleep for ``delay`` seconds while periodically signaling progress."""
    remaining = max(0.0, float(delay))
    cadence = task_heartbeat_interval(stale_after, maximum=interval)
    sleeper = sleep_func or asyncio.sleep
    while remaining > 0:
        _emit_heartbeat(heartbeat)
        step = min(remaining, cadence)
        await sleeper(step)
        remaining -= step


async def wait_for_event_with_heartbeat(
    event: asyncio.Event,
    delay: float,
    *,
    heartbeat: HeartbeatCallback | None = None,
    stale_after: float | str | None = 3600.0,
    interval: float = 30.0,
    wait_for_func: WaitForCallback | None = None,
) -> bool:
    """Wait up to ``delay`` seconds for an event while signaling progress."""
    remaining = max(0.0, float(delay))
    cadence = task_heartbeat_interval(stale_after, maximum=interval)
    wait_for = wait_for_func or asyncio.wait_for
    while remaining > 0 and not event.is_set():
        _emit_heartbeat(heartbeat)
        step = min(remaining, cadence)
        try:
            await wait_for(event.wait(), timeout=step)
            return True
        except TimeoutError:
            remaining -= step
    return event.is_set()


@dataclass(frozen=True)
class TaskInfo:
    scope: str
    name: str
    status: str
    created_at: str
    done_at: str | None
    cancelled: bool
    last_error: str | None
    heartbeat_at: str | None = None
    restart_count: int = 0
    circuit_state: str = "closed"
    next_restart_at: str | None = None
    kind: str = "one-shot"


class TaskSupervisor:
    """Track scope background tasks and cancel them on unload/shutdown."""

    def __init__(
        self,
        options: SupervisorOptions | None = None,
        *,
        on_circuit_open: CircuitCallback | None = None,
    ):
        self.options = options or SupervisorOptions()
        self.on_circuit_open = on_circuit_open
        self._tasks: dict[asyncio.Task[Any], dict[str, Any]] = {}
        self._by_scope: dict[str, set[asyncio.Task[Any]]] = {}

    def create(
        self,
        scope: str,
        coro: Awaitable[Any],
        *,
        name: str | None = None,
        kind: str = "one-shot",
    ) -> asyncio.Task[Any]:
        """Create and track a task for a scope."""
        task_name = name or f"{scope}-task"
        task_coro = cast(Coroutine[Any, Any, Any], coro)
        task: asyncio.Task[Any]
        if _asyncio_create_task_supports_name():
            try:
                task = asyncio.create_task(task_coro, name=task_name)
            except TypeError as exc:
                if "name" not in str(exc):
                    raise
                # Some tests monkeypatch asyncio.create_task with a reduced callable.
                task = asyncio.create_task(task_coro)
        else:
            task = asyncio.create_task(task_coro)
        meta = {
            "scope": scope,
            "name": task_name,
            "created_at": _now(),
            "done_at": None,
            "last_error": None,
            # Keep explicit heartbeat state separate from creation time. Stale
            # detection uses ``created_at`` only as the initial service progress
            # marker; one-shot tasks without a heartbeat remain exempt.
            "heartbeat_at": None,
            "restart_count": 0,
            "circuit_state": "closed",
            "next_restart_at": None,
            "kind": kind,
            "expected_exit": False,
        }
        self._tasks[task] = meta
        self._by_scope.setdefault(scope, set()).add(task)
        add_done_callback = getattr(task, "add_done_callback", None)
        if callable(add_done_callback):
            add_done_callback(self._on_task_done)
        return task

    def create_resilient(
        self,
        scope: str,
        factory: Callable[[], Awaitable[Any]],
        *,
        name: str | None = None,
        max_restarts: int | None = None,
        initial_backoff: float | None = None,
        max_backoff: float | None = None,
        reset_after: float | None = None,
        service: bool = True,
    ) -> asyncio.Task[Any]:
        """Create a worker protected by restart backoff and a circuit breaker."""
        restart_limit = max(0, int(self.options.max_restarts if max_restarts is None else max_restarts))
        initial = max(0.0, float(self.options.initial_backoff if initial_backoff is None else initial_backoff))
        maximum = max(initial, float(self.options.max_backoff if max_backoff is None else max_backoff))
        reset = max(0.0, float(self.options.reset_after if reset_after is None else reset_after))
        task_name = name or f"{scope}-task"
        return self.create(
            scope,
            self._resilient_runner(
                scope,
                task_name,
                factory,
                restart_limit=restart_limit,
                initial_backoff=initial,
                max_backoff=maximum,
                reset_after=reset,
                service=service,
            ),
            name=task_name,
            kind="service" if service else "one-shot",
        )

    async def _notify_circuit_open(self, scope: str, name: str, error: str) -> None:
        callback = self.on_circuit_open
        if callback is None:
            return
        try:
            result = callback(scope, name, error)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("[TASKS] Failed to run circuit-open callback")

    async def _sleep_with_heartbeat(self, scope: str, name: str, delay: float) -> None:
        await sleep_with_heartbeat(
            delay,
            heartbeat=lambda: self.heartbeat(scope, name),
            stale_after=self.options.stale_after,
            interval=30.0,
        )

    async def _resilient_runner(
        self,
        scope: str,
        name: str,
        factory: Callable[[], Awaitable[Any]],
        *,
        restart_limit: int,
        initial_backoff: float,
        max_backoff: float,
        reset_after: float,
        service: bool,
    ) -> Any:
        if self.options.yield_before_start:
            await asyncio.sleep(0)
        consecutive = 0
        while True:
            started = asyncio.get_running_loop().time()
            try:
                result = await factory()
                if service:
                    raise RuntimeError("service task exited unexpectedly")
            except asyncio.CancelledError:
                raise
            except ExpectedTaskExit:
                task = asyncio.current_task()
                if task is not None:
                    self._tasks.get(task, {})["expected_exit"] = True
                return None
            except Exception as exc:
                run_seconds = asyncio.get_running_loop().time() - started
                if reset_after and run_seconds >= reset_after:
                    consecutive = 0
                consecutive += 1
                task = asyncio.current_task()
                meta = self._tasks.get(task, {}) if task is not None else {}
                meta["restart_count"] = int(meta.get("restart_count") or 0) + 1
                meta["last_error"] = f"{type(exc).__name__}: {exc}"
                if consecutive > restart_limit:
                    meta["circuit_state"] = "open"
                    meta["next_restart_at"] = None
                    error = str(meta["last_error"] or "unknown error")
                    await self._notify_circuit_open(scope, name, error)
                    if self.options.terminal_error_style == "restart_limit":
                        raise RuntimeError(f"background service {name} exceeded restart limit: {error}") from exc
                    raise RuntimeError(f"task circuit open after {restart_limit} restart(s): {error}") from exc
                delay = min(
                    max_backoff,
                    initial_backoff * (2 ** max(0, consecutive - 1)),
                )
                next_at = datetime.now(UTC).timestamp() + delay
                meta["circuit_state"] = "half-open"
                meta["next_restart_at"] = _datetime_from_timestamp(next_at).isoformat(timespec="seconds")
                log.warning(
                    "[TASKS] Restarting %s/%s in %.1fs after failure %d/%d: %s",
                    scope,
                    name,
                    delay,
                    consecutive,
                    restart_limit,
                    exc,
                )
                await self._sleep_with_heartbeat(scope, name, delay)
                meta["circuit_state"] = "closed"
                meta["next_restart_at"] = None
                continue
            else:
                task = asyncio.current_task()
                meta = self._tasks.get(task, {}) if task is not None else {}
                meta["circuit_state"] = "closed"
                meta["next_restart_at"] = None
                meta["last_error"] = None
                return result

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        meta = self._tasks.get(task)
        if not meta:
            log.debug(
                "[TASKS] Done callback for untracked task; metadata missing: %r",
                task,
            )
            return
        meta["done_at"] = _now()
        scope = meta["scope"]
        self._by_scope.get(scope, set()).discard(task)
        if task.cancelled():
            return

        try:
            exc = task.exception()
        except asyncio.InvalidStateError:
            log.debug(
                "[TASKS] Task exception unavailable due to invalid state: %r",
                task,
            )
            return

        if exc is not None:
            meta["last_error"] = f"{type(exc).__name__}: {exc}"
            log.error(
                "[TASKS] Background task failed: %s.%s",
                scope,
                meta["name"],
                exc_info=exc,
            )
        elif meta.get("kind") == "service" and meta.get("expected_exit"):
            self._forget_task(task)
        elif meta.get("kind") != "service":
            self._prune_completed_one_shot_history()

    def _prune_completed_one_shot_history(self) -> None:
        """Keep recent successful one-shots for UX without leaking task metadata."""
        completed = [
            task
            for task, meta in self._tasks.items()
            if task.done() and not task.cancelled() and meta.get("kind") != "service" and meta.get("last_error") is None
        ]
        excess = len(completed) - _COMPLETED_ONE_SHOT_HISTORY_LIMIT
        for task in completed[: max(0, excess)]:
            self._forget_task(task)

    def _forget_task(self, task: asyncio.Task[Any]) -> None:
        """Remove a task from supervisor indexes."""
        meta = self._tasks.pop(task, None)
        if not meta:
            return
        scope_tasks = self._by_scope.get(meta["scope"])
        if scope_tasks is not None:
            scope_tasks.discard(task)
            if not scope_tasks:
                self._by_scope.pop(meta["scope"], None)

    def _prune_task_unless_failed(self, task: asyncio.Task[Any]) -> None:
        """Remove task metadata unless it should be kept for failure diagnostics."""
        meta = self._tasks.get(task, {})
        has_error = meta.get("last_error") is not None
        keep_for_diagnostics = has_error and task.done() and not task.cancelled()
        if not keep_for_diagnostics:
            self._forget_task(task)

    def heartbeat(self, scope: str, name: str | None = None) -> bool:
        """Update heartbeat timestamp for a running task by scope/name."""
        for task, meta in tuple(self._tasks.items()):
            if task.done():
                continue
            if meta.get("scope") != scope:
                continue
            if name is not None and meta.get("name") != name:
                continue
            meta["heartbeat_at"] = _now()
            return True
        return False

    def touch(self, task: asyncio.Task[Any]) -> bool:
        """Update heartbeat timestamp for a specific supervised task."""
        meta = self._tasks.get(task)
        if meta is None or task.done():
            return False
        meta["heartbeat_at"] = _now()
        return True

    def stale_tasks(self, *, max_age_seconds: float = 3600.0) -> list[TaskInfo]:
        """Return running tasks whose progress signal is too old.

        A service that hangs before its first explicit heartbeat used to be
        invisible forever.  For services only, creation time is therefore the
        initial progress timestamp until the first heartbeat arrives.  One-shot
        tasks keep the historical behavior because they are not required to
        implement a heartbeat contract.
        """
        now = datetime.now(UTC)
        stale: list[TaskInfo] = []
        # Use the neutral snapshot contract even when a compatibility subclass
        # overrides snapshot() with application-specific datatypes.
        for info in TaskSupervisor.snapshot(self, include_done=False):
            if info.status != "running":
                continue
            progress_at = info.heartbeat_at
            if not progress_at and info.kind == "service":
                progress_at = info.created_at
            if not progress_at:
                continue
            try:
                heartbeat = datetime.fromisoformat(progress_at)
                if heartbeat.tzinfo is None:
                    heartbeat = heartbeat.replace(tzinfo=UTC)
                age = (now - heartbeat.astimezone(UTC)).total_seconds()
            except ValueError:
                age = max_age_seconds + 1
            if age > max_age_seconds:
                stale.append(info)
        return stale

    def owns(self, task: object | None) -> bool:
        if task is None:
            return False
        try:
            return task in self._tasks
        except TypeError:
            return False

    async def cancel_task(
        self,
        task: asyncio.Task[Any],
        *,
        timeout: float = 5.0,
    ) -> bool:
        """Cancel one supervised task and remove normal cancellation noise.

        This is useful for scopes that restart one worker without unloading the
        whole scope. Failed tasks remain visible for diagnostics, while
        successful or cancelled tasks are pruned from task status output.

        Returns:
            Whether a running task was requested to cancel.
        """
        was_running = not task.done()
        if was_running:
            task.cancel()
            done, pending = await asyncio.wait({task}, timeout=timeout)
            if pending:
                log.warning(
                    "[TASKS] Scope task did not stop in time: %s",
                    task.get_name(),
                )
                return True

            for done_task in done:
                if done_task.cancelled():
                    continue
                error = done_task.exception()
                if error is not None:
                    log.debug(
                        "[TASKS] Task raised during cancellation",
                        exc_info=error,
                    )

        self._prune_task_unless_failed(task)
        return was_running

    async def cancel_scope(self, scope: str, *, timeout: float = 5.0) -> int:
        """Cancel all tasks owned by a scope and prune finished noise.

        Scopes often cancel their own workers in ``on_unload`` before the
        manager calls into the supervisor.  Those tasks are already done by the
        time we get here, so looking only at running tasks leaves stale
        ``cancelled`` entries in ``tasks all``.  Snapshot all tasks for the
        scope, cancel only the running ones, then prune every non-failed task.

        Returns:
            Number of running tasks that were requested to cancel.
        """
        scope_tasks = [task for task, meta in tuple(self._tasks.items()) if meta.get("scope") == scope]
        running_tasks = [task for task in scope_tasks if not task.done()]
        for task in running_tasks:
            task.cancel()
        pending: set[asyncio.Task[Any]] = set()
        if running_tasks:
            done, pending = await asyncio.wait(running_tasks, timeout=timeout)
            for task in pending:
                log.warning(
                    "[TASKS] Scope task did not stop in time: %s",
                    task.get_name(),
                )

            for done_task in done:
                if done_task.cancelled():
                    continue
                error = done_task.exception()
                if error is not None:
                    log.debug(
                        "[TASKS] Task raised during cancellation",
                        exc_info=error,
                    )

        for task in scope_tasks:
            if task not in pending:
                self._prune_task_unless_failed(task)
        return len(running_tasks)

    def clear_scope_failures(self, scope: str) -> int:
        """Forget completed failure and open-circuit diagnostics for a scope.

        A successful manual task restart is an explicit circuit reset. Keeping
        the old failed runner afterward would make ``tasks`` and ``doctor``
        continue to report an open circuit even though a replacement worker is
        running.
        """
        failed_tasks = [
            task
            for task, meta in tuple(self._tasks.items())
            if meta.get("scope") == scope and task.done() and meta.get("last_error") is not None
        ]
        for task in failed_tasks:
            self._forget_task(task)
        return len(failed_tasks)

    async def cancel_all(self, *, timeout: float = 5.0) -> int:
        """Cancel all running supervised tasks.

        Returns:
            Total number of running tasks cancelled across all scopes.
        """
        scopes = list(self._by_scope)
        total = 0
        for scope in scopes:
            total += await self.cancel_scope(scope, timeout=timeout)
        return total

    def snapshot(self, *, include_done: bool = True) -> list[TaskInfo]:
        """Return a stable snapshot of supervised task states."""
        items = []
        for task, meta in tuple(self._tasks.items()):
            if task.done():
                cancelled = task.cancelled()
                last_error = meta.get("last_error")

                if not include_done and (cancelled or last_error is None):
                    continue

                if cancelled:
                    status = "cancelled"
                elif last_error:
                    status = "failed"
                else:
                    status = "done"
            else:
                cancelled = False
                last_error = meta.get("last_error")
                status = "running"
            items.append(
                TaskInfo(
                    scope=meta["scope"],
                    name=meta["name"],
                    status=status,
                    created_at=meta["created_at"],
                    done_at=meta.get("done_at"),
                    cancelled=cancelled,
                    last_error=last_error,
                    heartbeat_at=meta.get("heartbeat_at"),
                    restart_count=int(meta.get("restart_count") or 0),
                    circuit_state=str(meta.get("circuit_state") or "closed"),
                    next_restart_at=meta.get("next_restart_at"),
                    kind=str(meta.get("kind") or "one-shot"),
                )
            )
        return sorted(items, key=lambda item: (item.scope, item.name))

    def summary_by_kind(self) -> dict[str, int]:
        """Return operator-friendly task counts split by lifecycle kind."""
        counts = {
            "services_running": 0,
            "one_shots_running": 0,
            "one_shots_completed": 0,
            "services_finished": 0,
            "failed": 0,
            "cancelled": 0,
        }
        for info in self.snapshot(include_done=True):
            if info.status == "failed":
                counts["failed"] += 1
            elif info.status == "cancelled":
                counts["cancelled"] += 1
            elif info.status == "running":
                key = "services_running" if info.kind == "service" else "one_shots_running"
                counts[key] += 1
            elif info.kind == "service":
                counts["services_finished"] += 1
            else:
                counts["one_shots_completed"] += 1
        return counts

    def summary(self) -> tuple[int, int, int]:
        """Return (running, failed, done_or_cancelled) counts."""
        running = failed = finished = 0
        for info in self.snapshot(include_done=True):
            if info.status == "running":
                running += 1
            elif info.status == "failed":
                failed += 1
            else:
                finished += 1
        return running, failed, finished
