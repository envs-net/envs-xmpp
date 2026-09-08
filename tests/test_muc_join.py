from __future__ import annotations

import asyncio

import pytest

from envs_xmpp_core.xmpp.muc_join import (
    MucJoinResult,
    drain_task,
    join_muc_confirmed,
    start_muc_join_task,
    wait_for_muc_self_presence,
)


@pytest.mark.asyncio
async def test_wait_for_self_presence_requires_predicate_even_when_event_is_set() -> None:
    event = asyncio.Event()
    event.set()
    joined = False

    async def mark_joined() -> None:
        nonlocal joined
        await asyncio.sleep(0.02)
        joined = True
        event.set()

    task = asyncio.create_task(mark_joined())
    assert await wait_for_muc_self_presence(lambda: joined, timeout=0.2, event=event)
    await task


@pytest.mark.asyncio
async def test_join_muc_confirmed_prefers_waiter_but_self_presence_is_authoritative() -> None:
    event = asyncio.Event()
    joined = False
    cancelled = asyncio.Event()

    class Muc:
        async def join_muc_wait(self, room: str, nick: str, **kwargs) -> None:
            assert room == "room@example.org"
            assert nick == "bot"
            assert kwargs["maxstanzas"] == 0
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        def leave_muc(self, room: str, nick: str) -> None:
            raise AssertionError("successful join must not be left")

    async def set_presence() -> None:
        nonlocal joined
        await asyncio.sleep(0.02)
        joined = True
        event.set()

    marker = asyncio.create_task(set_presence())
    result = await join_muc_confirmed(
        Muc(),
        "room@example.org",
        "bot",
        is_joined=lambda: joined,
        timeout=0.2,
        event=event,
    )
    await marker

    assert result == MucJoinResult(
        joined=True,
        api_name="join_muc_wait",
        attempts=1,
        error=None,
        waiter_error=None,
    )
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_join_muc_confirmed_consumes_waiter_failure_after_presence() -> None:
    joined = True

    class Muc:
        async def join_muc_wait(self, room: str, nick: str, **kwargs) -> None:
            raise RuntimeError("subject waiter failed")

    result = await join_muc_confirmed(
        Muc(),
        "room@example.org",
        "bot",
        is_joined=lambda: joined,
        timeout=0.2,
        force=True,
        cleanup_on_failure=False,
    )

    assert result.joined is True
    assert result.attempts == 1
    assert isinstance(result.waiter_error, RuntimeError)


@pytest.mark.asyncio
async def test_join_muc_confirmed_retries_and_cleans_partial_join() -> None:
    joined = False
    calls: list[tuple[str, int | str]] = []

    class Muc:
        def join_muc(self, room: str, nick: str) -> None:
            calls.append(("join", len([c for c in calls if c[0] == "join"]) + 1))

        def leave_muc(self, room: str, nick: str) -> None:
            calls.append(("leave", nick))

    attempts = 0

    def clear_state() -> None:
        nonlocal attempts, joined
        attempts += 1
        joined = attempts >= 2
        calls.append(("clear", attempts))

    result = await join_muc_confirmed(
        Muc(),
        "room@example.org",
        "bot",
        is_joined=lambda: joined,
        timeout=0.02,
        retries=2,
        clear_state=clear_state,
        retry_delays=(),
    )

    assert result.joined is True
    assert result.attempts == 2
    assert calls.count(("leave", "bot")) >= 1


def test_start_muc_join_task_falls_back_to_join_muc() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class Muc:
        def join_muc(self, room: str, nick: str, **kwargs):
            calls.append((room, nick, kwargs))

    task, api = start_muc_join_task(
        Muc(),
        "room@example.org",
        "bot",
        timeout=1,
        join_kwargs={"pshow": "away"},
    )
    assert task is None
    assert api == "join_muc"
    assert calls == [("room@example.org", "bot", {"pshow": "away"})]


@pytest.mark.asyncio
async def test_drain_task_returns_failure() -> None:
    async def fail() -> None:
        raise RuntimeError("boom")

    exc = await drain_task(asyncio.create_task(fail()))
    assert isinstance(exc, RuntimeError)
    assert str(exc) == "boom"
