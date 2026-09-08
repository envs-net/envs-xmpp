from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest

from envs_xmpp_core.storage.outbox import OutboxStore, retry_delay_seconds


class _Cursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    async def fetchone(self) -> sqlite3.Row | None:
        return self._cursor.fetchone()

    async def fetchall(self) -> list[sqlite3.Row]:
        return self._cursor.fetchall()


class _Connection:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> _Cursor:
        return _Cursor(self._connection.execute(sql, tuple(params)))


class _Database:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.conn = _Connection(self.connection)

    @asynccontextmanager
    async def transaction(self, *, label: str = "transaction") -> AsyncIterator[_Connection]:
        del label
        try:
            yield self.conn
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.connection.execute(sql, tuple(params)).fetchone()

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, tuple(params)).fetchall()


@pytest.mark.asyncio
async def test_outbox_store_round_trip() -> None:
    store = OutboxStore(_Database())
    await store.init()
    message_id = await store.enqueue(
        destination="admin@example.test",
        body="hello",
        category="alert",
        dedupe_key="alert:test",
    )
    claimed = await store.claim_due()
    assert len(claimed) == 1
    assert claimed[0].id == message_id
    assert claimed[0].body == "hello"
    await store.mark_sent(message_id)
    assert (await store.counts())["total"] == 0


@pytest.mark.asyncio
async def test_outbox_dedupe_updates_existing_message() -> None:
    store = OutboxStore(_Database())
    await store.init()
    first = await store.enqueue(destination="a", body="one", dedupe_key="same")
    second = await store.enqueue(destination="a", body="two", dedupe_key="same")
    assert first == second
    claimed = await store.claim_due()
    assert claimed[0].body == "two"


def test_retry_delay_is_bounded_exponential() -> None:
    assert retry_delay_seconds(0, initial=5, maximum=20) == 5
    assert retry_delay_seconds(1, initial=5, maximum=20) == 10
    assert retry_delay_seconds(10, initial=5, maximum=20) == 20
