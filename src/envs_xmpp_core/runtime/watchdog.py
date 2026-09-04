"""Generic event-loop/systemd watchdog."""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable

from .systemd import sd_notify, systemd_watchdog_interval
from .tasks import TaskSupervisor

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchdogOptions:
    enabled: bool = True
    interval_seconds: float = 20.0
    lag_warning_seconds: float = 2.0
    lag_failure_seconds: float = 30.0
    defer_ready_notification: bool = False


@dataclass
class WatchdogState:
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


class RuntimeWatchdog:
    """Monitor event-loop responsiveness and optionally feed systemd."""

    def __init__(
        self,
        *,
        service_name: str,
        options: WatchdogOptions | None = None,
        supervisor: TaskSupervisor | None = None,
        ready_event: Any | None = None,
        on_lag: Callable[[float, float], Awaitable[None] | None] | None = None,
        ready_predicate: Callable[[], bool] | None = None,
        notifier: Callable[[str], bool] = sd_notify,
        on_ready: Callable[[], Any] | None = None,
        options_provider: Callable[[], WatchdogOptions] | None = None,
    ) -> None:
        self.service_name = service_name
        self.options = options or WatchdogOptions()
        self.supervisor = supervisor
        self.ready_event = ready_event
        self.on_lag = on_lag
        self.ready_predicate = ready_predicate
        self.notifier = notifier
        self.on_ready = on_ready
        self.options_provider = options_provider
        self.task: asyncio.Task[Any] | None = None
        self._lag_alert_task: asyncio.Task[Any] | None = None
        self.stop_event = asyncio.Event()
        self.state = WatchdogState()
        self._ready_notification_pending = False
        self._ready_sent = False

    def _current_options(self) -> WatchdogOptions:
        provider = self.options_provider
        if provider is None:
            return self.options
        try:
            return provider()
        except Exception:
            log.exception("[WATCHDOG] Failed to refresh runtime options")
            return self.options

    async def start(self) -> None:
        options = self._current_options()
        self.state.systemd_active = bool(os.environ.get("NOTIFY_SOCKET") and os.environ.get("WATCHDOG_USEC"))
        self.state.enabled = bool(options.enabled) or self.state.systemd_active
        if not self.state.enabled or (self.task is not None and not self.task.done()):
            return
        self.stop_event = asyncio.Event()
        if self.supervisor is not None:
            self.task = self.supervisor.create_resilient("_runtime", self._run, name="runtime-watchdog", service=True)
        else:
            self.task = asyncio.create_task(self._run(), name="runtime-watchdog")
        self.state.worker_running = True

    @property
    def ready_sent(self) -> bool:
        """Return whether READY=1 has been accepted by the notifier."""
        return self._ready_sent

    def _send_ready(self) -> bool:
        status = (
            f"{self.service_name} started and monitoring event-loop health"
            if self.state.enabled
            else f"{self.service_name} startup complete"
        )
        sent = self.notifier(f"READY=1\nSTATUS={status}")
        if sent:
            self._ready_sent = True
            callback = self.on_ready
            if callback is not None:
                try:
                    callback()
                except Exception:
                    log.exception("[WATCHDOG] Failed to run ready callback")
        return sent

    def _notify_ready_if_complete(self) -> None:
        self._ready_notification_pending = False
        if self.ready_predicate is None or self.ready_predicate():
            self._send_ready()

    def notify_ready(self) -> bool:
        if self.ready_predicate is None or self.ready_predicate():
            return self._send_ready()
        if not self.options.defer_ready_notification or self._ready_notification_pending:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        self._ready_notification_pending = True
        loop.call_soon(self._notify_ready_if_complete)
        return False

    async def stop(self) -> None:
        self.stop_event.set()
        task, alert_task = self.task, self._lag_alert_task
        self.task = None
        self._lag_alert_task = None

        supervisor = self.supervisor
        owns = getattr(supervisor, "owns", None) if supervisor is not None else None
        cancel_scope = getattr(supervisor, "cancel_scope", None) if supervisor is not None else None
        if not callable(cancel_scope) and supervisor is not None:
            cancel_scope = getattr(supervisor, "cancel_group", None)

        if (
            task is not None
            and callable(owns)
            and owns(task)
            and callable(cancel_scope)
        ):
            await cancel_scope("_runtime", timeout=5.0)
        else:
            for running in (task, alert_task):
                if running is not None and not running.done():
                    running.cancel()
            awaitables = [
                running
                for running in (task, alert_task)
                if running is not None and inspect.isawaitable(running)
            ]
            if awaitables:
                await asyncio.gather(*awaitables, return_exceptions=True)

        self.state.worker_running = False
        self.notifier(f"STOPPING=1\nSTATUS={self.service_name} shutting down")

    async def _wait_ready(self) -> None:
        event = self.ready_event
        if event is None:
            return
        is_set = getattr(event, "is_set", None)
        wait = getattr(event, "wait", None)
        if callable(is_set) and is_set():
            return
        if callable(wait):
            result = wait()
            if inspect.isawaitable(result):
                await result

    async def _wait_interval(self, delay: float) -> bool:
        remaining = max(0.0, delay)
        heartbeat_interval = max(0.05, min(30.0, remaining / 2.0 if remaining else 0.05))
        while remaining > 0 and not self.stop_event.is_set():
            if self.supervisor is not None:
                self.supervisor.heartbeat("_runtime", "runtime-watchdog")
            step = min(remaining, heartbeat_interval)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=step)
                return True
            except TimeoutError:
                remaining -= step
        return self.stop_event.is_set()

    async def _report_lag(self, lag: float, threshold: float) -> None:
        callback = self.on_lag
        if callback is None:
            return
        try:
            result = callback(lag, threshold)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[WATCHDOG] Failed to report event-loop lag")

    def _schedule_lag_report(self, lag: float, threshold: float) -> None:
        if self.on_lag is None:
            return
        current = self._lag_alert_task
        if current is not None and not current.done():
            return
        coro = self._report_lag(lag, threshold)
        if self.supervisor is not None:
            self._lag_alert_task = self.supervisor.create("_runtime", coro, name="runtime-watchdog-lag-alert")
        else:
            self._lag_alert_task = asyncio.create_task(coro, name="runtime-watchdog-lag-alert")

    def _publish_heartbeat(self, lag: float, failure_threshold: float) -> None:
        if self.supervisor is not None:
            self.supervisor.heartbeat("_runtime", "runtime-watchdog")
        if lag >= failure_threshold:
            self.state.heartbeat_suppressed += 1
            self.notifier(f"STATUS={self.service_name} unhealthy: event-loop lag {lag:.3f}s; watchdog heartbeat suppressed")
            return
        payload = f"WATCHDOG=1\nSTATUS={self.service_name} healthy; event-loop lag {lag:.3f}s"
        if self.notifier(payload):
            self.state.heartbeats += 1
            self.state.last_heartbeat_at = int(time.time())

    async def _run(self) -> None:
        await self._wait_ready()
        options = self._current_options()
        interval = systemd_watchdog_interval(max(1.0, float(options.interval_seconds)))
        warning_threshold = max(0.1, float(options.lag_warning_seconds))
        failure_threshold = max(warning_threshold, float(options.lag_failure_seconds))
        loop = asyncio.get_running_loop()
        expected = loop.time() + interval
        self.state.worker_running = True
        try:
            while not self.stop_event.is_set():
                if await self._wait_interval(interval):
                    break
                now = loop.time()
                lag = max(0.0, now - expected)
                expected = now + interval
                self.state.last_lag_seconds = lag
                self.state.max_lag_seconds = max(self.state.max_lag_seconds, lag)
                if lag >= warning_threshold:
                    self.state.lag_warnings += 1
                    log.warning("[WATCHDOG] Event-loop lag %.3fs exceeds %.3fs", lag, warning_threshold)
                self._publish_heartbeat(lag, failure_threshold)
                if lag >= warning_threshold:
                    self._schedule_lag_report(lag, warning_threshold)
                self.state.last_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.last_error = f"{type(exc).__name__}: {exc}"
            log.exception("[WATCHDOG] Runtime watchdog failed")
            raise
        finally:
            self.state.worker_running = False

    def runtime_state(self) -> dict[str, Any]:
        return asdict(self.state)
