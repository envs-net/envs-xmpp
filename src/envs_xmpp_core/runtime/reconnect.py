"""Bot-neutral reconnect orchestration for Slixmpp-style clients."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable

type ConnectResult = bool | None
type ConnectCallback = Callable[[], ConnectResult | Awaitable[ConnectResult]]
type AsyncReasonCallback = Callable[[str], Awaitable[None]]
type BoolCallback = Callable[[], bool]


async def _maybe_await(value: ConnectResult | Awaitable[ConnectResult]) -> ConnectResult:
    if inspect.isawaitable(value):
        return await value
    return value


async def run_reconnect_loop(
    *,
    connect: ConnectCallback,
    disconnect_partial: AsyncReasonCallback,
    ready_event: asyncio.Event,
    session_started: BoolCallback,
    shutdown_requested: BoolCallback,
    startup_completed: BoolCallback,
    logger: logging.Logger | None = None,
    initial_delay: float = 5.0,
    max_delay: float = 60.0,
    startup_timeout: float = 120.0,
) -> None:
    """Reconnect until a complete session-start lifecycle reports readiness.

    The caller owns application state, room reconciliation, and policy. This
    helper owns only the retry/backoff transaction:

    * wait before each transport attempt;
    * avoid opening a second connection if ``session_start`` raced the backoff;
    * wait for full application readiness rather than raw TCP connection;
    * disconnect partial sessions that never become ready;
    * stop promptly when process shutdown begins.
    """

    log = logger or logging.getLogger(__name__)
    had_completed_startup = bool(startup_completed())
    delay = max(0.0, float(initial_delay))
    maximum = max(delay, float(max_delay))
    timeout = max(0.001, float(startup_timeout))

    while True:
        if shutdown_requested():
            log.debug("Reconnect loop stopped because shutdown is in progress")
            return

        log.info("🔄 Attempting reconnect in %gs...", delay)
        await asyncio.sleep(delay)
        if shutdown_requested():
            log.debug("Reconnect attempt suppressed because shutdown is in progress")
            return

        # A session_start can race the delay after a pre-session disconnect.
        # In that case, wait for the already-running startup lifecycle instead
        # of opening a second transport connection.
        if session_started():
            try:
                await asyncio.wait_for(ready_event.wait(), timeout=timeout)
                if had_completed_startup:
                    log.info("🔄 Reconnect completed during backoff")
                else:
                    log.info("✅ Initial XMPP startup completed during reconnect backoff")
                return
            except TimeoutError:
                log.warning(
                    "Session startup did not complete within %gs; "
                    "disconnecting partial session before retry",
                    timeout,
                )
                await disconnect_partial("session startup timeout")
                delay = min(maximum, max(delay * 2, 1.0))
                continue

        ready_event.clear()
        try:
            connected = await _maybe_await(connect())
            if connected is False:
                raise ConnectionError("Reconnect initiation returned False")
            log.info("🔌 Reconnect initiated")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - reconnect boundary
            log.error("Reconnect error: %s", exc)
            delay = min(maximum, max(delay * 2, 1.0))
            continue

        try:
            await asyncio.wait_for(ready_event.wait(), timeout=timeout)
            if had_completed_startup:
                log.info("🔄 Reconnect completed")
            else:
                log.info("✅ Initial XMPP startup completed after retry")
            return
        except TimeoutError:
            log.warning(
                "Reconnect startup did not complete within %gs; "
                "disconnecting partial session before retry",
                timeout,
            )
            await disconnect_partial("startup timeout")
            delay = min(maximum, max(delay * 2, 1.0))
