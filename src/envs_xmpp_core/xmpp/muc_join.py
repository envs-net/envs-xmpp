"""Tracked MUC join compatibility and timeout cleanup helpers."""
from __future__ import annotations
import asyncio
import inspect
from typing import Any


def start_muc_join_task(muc_plugin: Any, room: str, nick: str, *, timeout: float, join_kwargs: dict[str, Any] | None = None) -> tuple[asyncio.Future[Any] | asyncio.Task[Any] | None, str]:
    join_wait = getattr(muc_plugin, "join_muc_wait", None)
    kwargs = dict(join_kwargs or {})
    if callable(join_wait):
        kwargs.setdefault("maxstanzas", 0)
        kwargs.setdefault("timeout", max(float(timeout), 0.1))
        try:
            result = join_wait(room, nick, **kwargs)
        except TypeError:
            result = join_wait(room, nick)
        api_name = "join_muc_wait"
    else:
        result = muc_plugin.join_muc(room, nick, **(join_kwargs or {}))
        api_name = "join_muc"
    if asyncio.isfuture(result):
        return result, api_name
    if inspect.isawaitable(result):
        return asyncio.create_task(result), api_name
    return None, api_name


async def drain_task(task: asyncio.Future[Any] | asyncio.Task[Any] | None, *, cancel: bool = False) -> Exception | None:
    if task is None:
        return None
    if cancel and not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return None
    except Exception as exc:
        return exc
    return None


async def await_muc_join_compat(muc_plugin: Any, room: str, nick: str, *, timeout: float) -> tuple[bool, str, Exception | None]:
    try:
        task, api_name = start_muc_join_task(muc_plugin, room, nick, timeout=timeout)
    except Exception as exc:
        return False, "unknown", exc
    if task is None:
        return True, api_name, None
    try:
        await asyncio.wait_for(task, timeout=max(float(timeout), 0.1))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        if not task.done():
            task.cancel()
        await drain_task(task)
        return False, api_name, exc
    return True, api_name, None
