"""Tests for shared reconnect retry/backoff orchestration."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

from envs_xmpp_core.runtime.reconnect import run_reconnect_loop


@pytest.mark.asyncio
async def test_reconnect_connects_and_waits_for_full_readiness(monkeypatch) -> None:
    ready = asyncio.Event()
    connects = Mock()

    async def no_sleep(_delay: float) -> None:
        return None

    def connect() -> bool:
        connects()
        ready.set()
        return True

    monkeypatch.setattr("envs_xmpp_core.runtime.reconnect.asyncio.sleep", no_sleep)

    await run_reconnect_loop(
        connect=connect,
        disconnect_partial=lambda reason: asyncio.sleep(0),
        ready_event=ready,
        session_started=lambda: False,
        shutdown_requested=lambda: False,
        startup_completed=lambda: True,
    )

    connects.assert_called_once_with()


@pytest.mark.asyncio
async def test_reconnect_does_not_double_connect_when_session_starts_during_backoff(
    monkeypatch,
) -> None:
    ready = asyncio.Event()
    started = False
    connects = Mock(return_value=True)

    async def session_starts(_delay: float) -> None:
        nonlocal started
        started = True
        ready.set()

    monkeypatch.setattr(
        "envs_xmpp_core.runtime.reconnect.asyncio.sleep",
        session_starts,
    )

    await run_reconnect_loop(
        connect=connects,
        disconnect_partial=lambda reason: asyncio.sleep(0),
        ready_event=ready,
        session_started=lambda: started,
        shutdown_requested=lambda: False,
        startup_completed=lambda: True,
    )

    connects.assert_not_called()


@pytest.mark.asyncio
async def test_reconnect_retries_false_connect_result(monkeypatch) -> None:
    ready = asyncio.Event()
    calls = 0

    async def no_sleep(_delay: float) -> None:
        return None

    def connect() -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            return False
        ready.set()
        return True

    monkeypatch.setattr("envs_xmpp_core.runtime.reconnect.asyncio.sleep", no_sleep)

    await run_reconnect_loop(
        connect=connect,
        disconnect_partial=lambda reason: asyncio.sleep(0),
        ready_event=ready,
        session_started=lambda: False,
        shutdown_requested=lambda: False,
        startup_completed=lambda: True,
    )

    assert calls == 2


@pytest.mark.asyncio
async def test_reconnect_disconnects_partial_session_after_timeout(monkeypatch) -> None:
    ready = asyncio.Event()
    connects = 0
    partial_reasons: list[str] = []

    async def no_sleep(_delay: float) -> None:
        return None

    async def immediate_wait_for(awaitable, timeout: float):
        nonlocal connects
        if connects == 1:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise TimeoutError
        ready.set()
        return await awaitable

    def connect() -> bool:
        nonlocal connects
        connects += 1
        if connects >= 2:
            ready.set()
        return True

    async def disconnect_partial(reason: str) -> None:
        partial_reasons.append(reason)

    monkeypatch.setattr("envs_xmpp_core.runtime.reconnect.asyncio.sleep", no_sleep)
    monkeypatch.setattr(
        "envs_xmpp_core.runtime.reconnect.asyncio.wait_for",
        immediate_wait_for,
    )

    await run_reconnect_loop(
        connect=connect,
        disconnect_partial=disconnect_partial,
        ready_event=ready,
        session_started=lambda: False,
        shutdown_requested=lambda: False,
        startup_completed=lambda: True,
        startup_timeout=1,
    )

    assert connects == 2
    assert partial_reasons == ["startup timeout"]


@pytest.mark.asyncio
async def test_reconnect_stops_before_connect_when_shutdown_begins(monkeypatch) -> None:
    ready = asyncio.Event()
    shutdown = False
    connects = Mock(return_value=True)

    async def begin_shutdown(_delay: float) -> None:
        nonlocal shutdown
        shutdown = True

    monkeypatch.setattr(
        "envs_xmpp_core.runtime.reconnect.asyncio.sleep",
        begin_shutdown,
    )

    await run_reconnect_loop(
        connect=connects,
        disconnect_partial=lambda reason: asyncio.sleep(0),
        ready_event=ready,
        session_started=lambda: False,
        shutdown_requested=lambda: shutdown,
        startup_completed=lambda: True,
    )

    connects.assert_not_called()
