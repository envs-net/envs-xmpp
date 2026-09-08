"""Tracked MUC join, self-presence confirmation, and cleanup helpers."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MucJoinResult:
    """Outcome of a confirmed MUC join operation.

    ``joined`` means the caller-provided self-presence predicate became true.
    A Slixmpp join waiter is deliberately not authoritative because
    ``join_muc_wait()`` may continue waiting for a room subject after the
    client's own presence already confirms membership.
    """

    joined: bool
    api_name: str
    attempts: int
    error: BaseException | None = None
    waiter_error: Exception | None = None


def _timeout_seconds(timeout: float) -> float:
    return max(float(timeout), 0.1)


def _retry_delay(delays: Sequence[float] | Callable[[int], float] | None, attempt: int) -> float:
    if delays is None:
        return min(2.0 * attempt, 5.0)
    if callable(delays):
        return max(0.0, float(delays(attempt)))
    if not delays:
        return 0.0
    index = min(max(1, int(attempt)) - 1, len(delays) - 1)
    return max(0.0, float(delays[index]))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def start_muc_join_task(
    muc_plugin: Any,
    room: str,
    nick: str,
    *,
    timeout: float,
    join_kwargs: dict[str, Any] | None = None,
) -> tuple[asyncio.Future[Any] | asyncio.Task[Any] | None, str]:
    """Start the best available Slixmpp MUC join API as a tracked task."""
    join_wait = getattr(muc_plugin, "join_muc_wait", None)
    kwargs = dict(join_kwargs or {})
    if callable(join_wait):
        kwargs.setdefault("maxstanzas", 0)
        kwargs.setdefault("timeout", _timeout_seconds(timeout))
        try:
            result = join_wait(room, nick, **kwargs)
        except TypeError:
            # Older/test-double implementations may only accept room+nick.
            result = join_wait(room, nick)
        api_name = "join_muc_wait"
    else:
        result = muc_plugin.join_muc(room, nick, **(join_kwargs or {}))
        api_name = "join_muc"
    if asyncio.isfuture(result):
        return result, api_name
    if inspect.isawaitable(result):
        return asyncio.ensure_future(result), api_name
    return None, api_name


async def drain_task(
    task: asyncio.Future[Any] | asyncio.Task[Any] | None,
    *,
    cancel: bool = False,
) -> Exception | None:
    """Cancel/consume a join task and return a non-cancellation exception."""
    if task is None:
        return None
    if cancel and not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return None
    except Exception as exc:  # noqa: BLE001 - Slixmpp/plugin failures are returned to callers
        return exc
    return None


async def wait_for_muc_self_presence(
    is_joined: Callable[[], bool],
    *,
    timeout: float,
    event: asyncio.Event | None = None,
    poll_interval: float = 0.1,
) -> bool:
    """Wait until *is_joined* confirms the client's own MUC presence.

    The predicate remains authoritative even when an event is supplied.  This
    avoids treating a stale or accidentally-set event as proof of membership.
    Polling also supports bots that keep occupant state but do not expose an
    event from their presence handler.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(float(timeout), 0.0)
    interval = max(0.01, float(poll_interval))

    while True:
        if bool(is_joined()):
            if event is not None:
                event.set()
            return True

        remaining = deadline - loop.time()
        if remaining <= 0:
            return False

        if event is None:
            await asyncio.sleep(min(interval, remaining))
            continue

        try:
            await asyncio.wait_for(event.wait(), timeout=min(interval, remaining))
        except TimeoutError:
            continue
        if bool(is_joined()):
            return True
        # The event can be shared with a stale presence transition. Clear it so
        # subsequent iterations block instead of spinning until the deadline.
        event.clear()


async def _best_effort_leave(
    muc_plugin: Any,
    room: str,
    nick: str,
    *,
    on_cleanup_error: Callable[[Exception], Any] | None = None,
) -> Exception | None:
    leave_muc = getattr(muc_plugin, "leave_muc", None)
    if not callable(leave_muc):
        return None
    try:
        await _maybe_await(leave_muc(room, nick))
    except Exception as exc:  # noqa: BLE001 - cleanup is intentionally best-effort
        if callable(on_cleanup_error):
            on_cleanup_error(exc)
        return exc
    return None


async def join_muc_confirmed(
    muc_plugin: Any,
    room: str,
    nick: str,
    *,
    is_joined: Callable[[], bool],
    timeout: float,
    retries: int = 1,
    join_kwargs: dict[str, Any] | None = None,
    event: asyncio.Event | None = None,
    force: bool = False,
    clear_state: Callable[[], Any] | None = None,
    retry_delays: Sequence[float] | Callable[[int], float] | None = None,
    leave_delay: float = 0.0,
    cleanup_on_failure: bool = True,
    accept_legacy_completion: bool = True,
    on_cleanup_error: Callable[[Exception], Any] | None = None,
) -> MucJoinResult:
    """Join a MUC and require actual self-presence confirmation.

    This is the high-level compatibility primitive used by both envs.net bots.
    It prefers ``join_muc_wait()`` when available, races the Slixmpp waiter
    against the caller's authoritative self-presence state, consumes every
    waiter task, retries in a bounded way, and cleans partial memberships before
    a retry/final failure.

    ``clear_state`` is called immediately before every real attempt so callers
    can discard stale occupant/runtime mirrors without coupling the core to a
    particular state representation.
    """
    if not force and bool(is_joined()):
        return MucJoinResult(joined=True, api_name="already_joined", attempts=0)

    attempts = max(1, int(retries))
    timeout_s = _timeout_seconds(timeout)
    last_error: BaseException | None = None
    last_waiter_error: Exception | None = None
    last_api = "unknown"

    for attempt in range(1, attempts + 1):
        if (force and attempt == 1) or (attempt > 1 and not cleanup_on_failure):
            await _best_effort_leave(
                muc_plugin,
                room,
                nick,
                on_cleanup_error=on_cleanup_error,
            )
            if leave_delay > 0:
                await asyncio.sleep(float(leave_delay))

        if clear_state is not None:
            await _maybe_await(clear_state())
        if event is not None:
            event.clear()

        join_task: asyncio.Future[Any] | asyncio.Task[Any] | None = None
        presence_task: asyncio.Task[bool] | None = None
        last_error = None
        last_waiter_error = None

        try:
            join_task, last_api = start_muc_join_task(
                muc_plugin,
                room,
                nick,
                timeout=timeout_s,
                join_kwargs=join_kwargs,
            )
            presence_task = asyncio.create_task(
                wait_for_muc_self_presence(
                    is_joined,
                    timeout=timeout_s,
                    event=event,
                )
            )

            if join_task is None:
                joined = await presence_task
            else:
                done, _pending = await asyncio.wait(
                    {join_task, presence_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if presence_task in done:
                    joined = presence_task.result()
                else:
                    try:
                        join_task.result()
                    except asyncio.CancelledError as exc:
                        last_error = exc
                        joined = False
                    except Exception as exc:  # noqa: BLE001 - arbitrary plugin failure
                        last_error = exc
                        joined = bool(is_joined())
                    else:
                        if last_api == "join_muc" and accept_legacy_completion:
                            # Old Slixmpp versions expose only join_muc(). Its
                            # completed awaitable was historically the strongest
                            # available membership signal. Modern join_muc_wait()
                            # still requires authoritative self-presence.
                            joined = True
                        else:
                            # A successful modern waiter does not replace our
                            # self-presence predicate. Give the presence handler
                            # the remainder of the same bounded timeout.
                            joined = await presence_task
        except asyncio.CancelledError:
            if presence_task is not None and not presence_task.done():
                presence_task.cancel()
                with suppress(asyncio.CancelledError):
                    await presence_task
            await drain_task(join_task, cancel=True)
            raise
        except Exception as exc:  # noqa: BLE001 - caller receives the failure
            last_error = exc
            joined = False

        if presence_task is not None and not presence_task.done():
            presence_task.cancel()
            with suppress(asyncio.CancelledError):
                await presence_task

        if joined:
            last_waiter_error = await drain_task(join_task, cancel=True)
            return MucJoinResult(
                joined=True,
                api_name=last_api,
                attempts=attempt,
                error=None,
                waiter_error=last_waiter_error,
            )

        last_waiter_error = await drain_task(join_task, cancel=True)
        if last_error is None:
            last_error = last_waiter_error
        if last_error is None:
            last_error = TimeoutError(f"No self-presence received within {timeout_s:g}s")

        if cleanup_on_failure:
            await _best_effort_leave(
                muc_plugin,
                room,
                nick,
                on_cleanup_error=on_cleanup_error,
            )

        if attempt < attempts:
            delay = _retry_delay(retry_delays, attempt)
            if delay > 0:
                await asyncio.sleep(delay)

    return MucJoinResult(
        joined=False,
        api_name=last_api,
        attempts=attempts,
        error=last_error,
        waiter_error=last_waiter_error,
    )


async def await_muc_join_compat(
    muc_plugin: Any,
    room: str,
    nick: str,
    *,
    timeout: float,
) -> tuple[bool, str, Exception | None]:
    """Compatibility helper for callers that only care about the waiter."""
    try:
        task, api_name = start_muc_join_task(muc_plugin, room, nick, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - plugin API failures are part of the compatibility result
        return False, "unknown", exc
    if task is None:
        return True, api_name, None
    try:
        await asyncio.wait_for(task, timeout=_timeout_seconds(timeout))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - preserve arbitrary join failures for bot-specific handling
        if not task.done():
            task.cancel()
        await drain_task(task)
        return False, api_name, exc
    return True, api_name, None


async def join_muc_with_timeout(
    muc_plugin: Any,
    room: str,
    nick: str,
    *,
    timeout: float,
    join_kwargs: dict[str, Any] | None = None,
    cleanup_on_timeout: bool = True,
    on_cleanup_error: Any | None = None,
) -> None:
    """Join a MUC with a hard timeout and optional ghost-membership cleanup.

    Kept as a compatibility primitive for consumers that intentionally do not
    have a self-presence predicate. New bot code should prefer
    :func:`join_muc_confirmed`.
    """
    result = muc_plugin.join_muc(room, nick, **dict(join_kwargs or {}))
    try:
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=_timeout_seconds(timeout))
    except TimeoutError:
        if cleanup_on_timeout:
            await _best_effort_leave(
                muc_plugin,
                room,
                nick,
                on_cleanup_error=on_cleanup_error,
            )
        raise
