"""Persistent outbound message queue for reliable XMPP delivery."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from envs_xmpp_core.security.redaction import redact_text


def retry_delay_seconds(
    attempts: int,
    *,
    initial: int = 30,
    maximum: int = 1800,
) -> int:
    """Return bounded exponential retry delay for an outbox attempt."""
    initial_delay = max(1, int(initial))
    maximum_delay = max(initial_delay, int(maximum))
    return min(maximum_delay, initial_delay * (2 ** max(0, int(attempts))))


class OutboxCapacityError(RuntimeError):
    """Raised when a configured durable queue capacity would be exceeded."""


@dataclass(frozen=True)
class OutboxMessage:
    """One queued outbound stanza."""

    id: int
    destination: str
    body: str
    message_type: str
    category: str
    dedupe_key: str | None
    origin_id: str
    attempts: int
    max_attempts: int
    created_at: int
    available_at: int
    last_error: str | None


class AsyncConnectionOutboxDatabase:
    """Adapt one async SQLite-style connection to :class:`OutboxStore`.

    The connection should be dedicated to the outbox.  A task-reentrant lock
    protects savepoint transactions while allowing store methods to issue the
    nested reads used for capacity checks.
    """

    def __init__(self, connection: Any):
        self.connection = connection
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0
        self._savepoint_counter = 0

    async def _acquire(self) -> bool:
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            self._depth += 1
            return False
        await self._lock.acquire()
        self._owner = task
        self._depth = 1
        return True

    def _release(self, acquired: bool) -> None:
        self._depth -= 1
        if acquired:
            self._owner = None
            self._depth = 0
            self._lock.release()

    @asynccontextmanager
    async def transaction(
        self,
        *,
        label: str = "outbox",
    ) -> AsyncIterator[Any]:
        del label
        acquired = await self._acquire()
        self._savepoint_counter += 1
        savepoint = f"envs_xmpp_outbox_{self._savepoint_counter}"
        await self.connection.execute(f"SAVEPOINT {savepoint}")
        try:
            yield self.connection
        except BaseException:
            await self.connection.execute(f"ROLLBACK TO {savepoint}")
            await self.connection.execute(f"RELEASE {savepoint}")
            raise
        else:
            await self.connection.execute(f"RELEASE {savepoint}")
        finally:
            self._release(acquired)

    async def fetch_one(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> Any | None:
        acquired = await self._acquire()
        try:
            cursor = await self.connection.execute(sql, tuple(params))
            return await cursor.fetchone()
        finally:
            self._release(acquired)

    async def fetch_all(
        self,
        sql: str,
        params: Sequence[Any] = (),
    ) -> list[Any]:
        acquired = await self._acquire()
        try:
            cursor = await self.connection.execute(sql, tuple(params))
            return list(await cursor.fetchall())
        finally:
            self._release(acquired)


class OutboxStore:
    """SQLite persistence for pending and failed outbound messages."""

    def __init__(self, db):
        self.db = db

    async def init(self, *, commit: bool = True) -> None:
        del commit
        async with self.db.transaction(label="outbox_init") as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    destination TEXT NOT NULL,
                    body TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'message',
                    dedupe_key TEXT UNIQUE,
                    origin_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 12,
                    created_at INTEGER NOT NULL,
                    available_at INTEGER NOT NULL,
                    locked_at INTEGER,
                    last_error TEXT,
                    dead_at INTEGER
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_due "
                "ON outbox_messages(status, available_at, id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_category "
                "ON outbox_messages(category, status)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbox_destination "
                "ON outbox_messages(destination, status, available_at, id)"
            )
            await conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_outbox_origin_id "
                "ON outbox_messages(origin_id)"
            )

    @staticmethod
    def _payload_bytes(destination: str, body: str, message_type: str, category: str) -> int:
        return len(
            (str(destination) + str(body) + str(message_type) + str(category)).encode(
                "utf-8"
            )
        )

    async def _capacity_snapshot(self, *, exclude_id: int | None = None) -> dict[str, Any]:
        where = "status IN ('pending', 'inflight')"
        params: list[Any] = []
        if exclude_id is not None:
            where += " AND id != ?"
            params.append(int(exclude_id))
        row = await self.db.fetch_one(
            f"""
            SELECT COUNT(*) AS pending,
                   COALESCE(SUM(
                       LENGTH(CAST(destination AS BLOB)) +
                       LENGTH(CAST(body AS BLOB)) +
                       LENGTH(CAST(message_type AS BLOB)) +
                       LENGTH(CAST(category AS BLOB))
                   ), 0) AS bytes
              FROM outbox_messages
             WHERE {where}
            """,
            tuple(params),
        )
        return {
            "pending": int(row["pending"] if row else 0),
            "bytes": int(row["bytes"] if row else 0),
        }

    async def _scope_count(
        self,
        column: str,
        value: str,
        *,
        exclude_id: int | None = None,
    ) -> int:
        if column not in {"destination", "category"}:
            raise ValueError("unsupported outbox scope")
        sql = (
            f"SELECT COUNT(*) AS count FROM outbox_messages "
            f"WHERE status IN ('pending', 'inflight') AND {column}=?"
        )
        params: list[Any] = [str(value)]
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(int(exclude_id))
        row = await self.db.fetch_one(sql, tuple(params))
        return int(row["count"] if row else 0)

    async def recover_inflight(self, *, older_than_seconds: int = 300) -> int:
        cutoff = int(time.time()) - max(0, int(older_than_seconds))
        async with self.db.transaction(label="outbox") as conn:
            cursor = await conn.execute(
                """
                UPDATE outbox_messages
                   SET status='pending', locked_at=NULL
                 WHERE status='inflight'
                   AND COALESCE(locked_at, 0) <= ?
                """,
                (cutoff,),
            )
            return max(0, int(cursor.rowcount or 0))

    async def enqueue(
        self,
        *,
        destination: str,
        body: str,
        message_type: str = "chat",
        category: str = "message",
        dedupe_key: str | None = None,
        origin_id: str | None = None,
        available_at: int | None = None,
        max_attempts: int = 12,
        max_pending: int = 10000,
        max_bytes: int = 50 * 1024 * 1024,
        max_per_destination: int = 1000,
        max_per_category: int = 5000,
    ) -> int:
        now = int(time.time())
        available = now if available_at is None else int(available_at)
        key = str(dedupe_key).strip() if dedupe_key else None
        stable_origin_id = str(origin_id or "").strip() or uuid.uuid4().hex
        destination = str(destination)
        body = str(body)
        message_type = str(message_type or "chat")
        category = str(category or "message")
        max_pending = max(1, int(max_pending))
        max_bytes = max(1, int(max_bytes))
        max_per_destination = max(1, int(max_per_destination))
        max_per_category = max(1, int(max_per_category))
        payload_bytes = self._payload_bytes(destination, body, message_type, category)

        async with self.db.transaction(label="outbox") as conn:
            existing = None
            if key:
                existing = await (
                    await conn.execute(
                        "SELECT id FROM outbox_messages WHERE dedupe_key=?",
                        (key,),
                    )
                ).fetchone()
            existing_id = int(existing["id"]) if existing else None
            snapshot = await self._capacity_snapshot(exclude_id=existing_id)
            if snapshot["pending"] + 1 > max_pending:
                raise OutboxCapacityError(
                    f"pending message limit reached ({max_pending})"
                )
            if snapshot["bytes"] + payload_bytes > max_bytes:
                raise OutboxCapacityError(
                    f"queue byte limit reached ({max_bytes} bytes)"
                )
            destination_count = await self._scope_count(
                "destination", destination, exclude_id=existing_id
            )
            if destination_count + 1 > max_per_destination:
                raise OutboxCapacityError(
                    f"destination limit reached for {destination} ({max_per_destination})"
                )
            category_count = await self._scope_count(
                "category", category, exclude_id=existing_id
            )
            if category_count + 1 > max_per_category:
                raise OutboxCapacityError(
                    f"category limit reached for {category} ({max_per_category})"
                )

            params = (
                destination,
                body,
                message_type,
                category,
                key,
                stable_origin_id,
                max(1, int(max_attempts)),
                now,
                available,
            )
            cursor = await conn.execute(
                """
                INSERT INTO outbox_messages (
                    destination, body, message_type, category, dedupe_key,
                    origin_id, max_attempts, created_at, available_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    destination=excluded.destination,
                    body=excluded.body,
                    message_type=excluded.message_type,
                    category=excluded.category,
                    max_attempts=excluded.max_attempts,
                    available_at=MIN(outbox_messages.available_at, excluded.available_at),
                    status=CASE
                        WHEN outbox_messages.status='dead' THEN 'pending'
                        ELSE outbox_messages.status
                    END,
                    attempts=CASE
                        WHEN outbox_messages.status='dead' THEN 0
                        ELSE outbox_messages.attempts
                    END,
                    locked_at=CASE
                        WHEN outbox_messages.status='dead' THEN NULL
                        ELSE outbox_messages.locked_at
                    END,
                    last_error=CASE
                        WHEN outbox_messages.status='dead' THEN NULL
                        ELSE outbox_messages.last_error
                    END,
                    dead_at=CASE
                        WHEN outbox_messages.status='dead' THEN NULL
                        ELSE outbox_messages.dead_at
                    END
                RETURNING id
                """,
                params,
            )
            row = await cursor.fetchone()
            return int(row["id"])

    async def claim_due(self, *, limit: int = 20) -> list[OutboxMessage]:
        """Claim due rows fairly across destinations for the delivery worker."""
        now = int(time.time())
        limit = max(1, min(200, int(limit)))
        async with self.db.transaction(label="outbox") as conn:
            cursor = await conn.execute(
                """
                WITH ranked AS (
                    SELECT id, available_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY destination
                               ORDER BY available_at, id
                           ) AS destination_rank
                      FROM outbox_messages
                     WHERE status='pending' AND available_at <= ?
                ), selected AS (
                    SELECT id
                      FROM ranked
                     ORDER BY destination_rank, available_at, id
                     LIMIT ?
                )
                UPDATE outbox_messages
                   SET status='inflight', locked_at=?
                 WHERE id IN (SELECT id FROM selected)
                   AND status='pending'
                RETURNING id, destination, body, message_type, category,
                          dedupe_key, origin_id, attempts, max_attempts, created_at,
                          available_at, last_error
                """,
                (now, limit, now),
            )
            rows = await cursor.fetchall()
        rows = sorted(rows, key=lambda row: (int(row["available_at"]), int(row["id"])))
        return [
            OutboxMessage(
                id=int(row["id"]),
                destination=str(row["destination"]),
                body=str(row["body"]),
                message_type=str(row["message_type"]),
                category=str(row["category"]),
                dedupe_key=row["dedupe_key"],
                origin_id=str(row["origin_id"]),
                attempts=int(row["attempts"]),
                max_attempts=int(row["max_attempts"]),
                created_at=int(row["created_at"]),
                available_at=int(row["available_at"]),
                last_error=row["last_error"],
            )
            for row in rows
        ]

    async def defer(
        self,
        message_id: int,
        *,
        retry_delay_seconds: int,
        reason: str | None = None,
    ) -> None:
        async with self.db.transaction(label="outbox") as conn:
            await conn.execute(
                """
                UPDATE outbox_messages
                   SET status='pending', available_at=?, locked_at=NULL,
                       last_error=?
                 WHERE id=?
                """,
                (
                    int(time.time()) + max(1, int(retry_delay_seconds)),
                    redact_text(reason, max_length=1000) if reason else None,
                    int(message_id),
                ),
            )

    async def mark_sent(self, message_id: int) -> None:
        async with self.db.transaction(label="outbox") as conn:
            await conn.execute(
                "DELETE FROM outbox_messages WHERE id=?", (int(message_id),)
            )

    async def mark_failed(
        self,
        message: OutboxMessage,
        error: object,
        *,
        retry_delay_seconds: int,
    ) -> bool:
        attempts = int(message.attempts) + 1
        dead = attempts >= int(message.max_attempts)
        async with self.db.transaction(label="outbox") as conn:
            await conn.execute(
                """
                UPDATE outbox_messages
                   SET status=?, attempts=?, available_at=?, locked_at=NULL,
                       last_error=?, dead_at=?
                 WHERE id=?
                """,
                (
                    "dead" if dead else "pending",
                    attempts,
                    int(time.time()) + max(1, int(retry_delay_seconds)),
                    f"{type(error).__name__}: {redact_text(error, max_length=960)}"[:1000],
                    int(time.time()) if dead else None,
                    int(message.id),
                ),
            )
        return dead

    async def retry_dead(
        self,
        *,
        category: str | None = None,
        message_id: int | None = None,
    ) -> int:
        clauses = ["status='dead'"]
        params: list[Any] = [int(time.time())]
        if category:
            clauses.append("category=?")
            params.append(str(category))
        if message_id is not None:
            clauses.append("id=?")
            params.append(int(message_id))
        async with self.db.transaction(label="outbox") as conn:
            cursor = await conn.execute(
                f"""
                UPDATE outbox_messages
                   SET status='pending', attempts=0, available_at=?,
                       locked_at=NULL, last_error=NULL, dead_at=NULL
                 WHERE {' AND '.join(clauses)}
                """,
                tuple(params),
            )
            return max(0, int(cursor.rowcount or 0))

    async def delete(self, message_id: int) -> int:
        async with self.db.transaction(label="outbox") as conn:
            cursor = await conn.execute(
                "DELETE FROM outbox_messages WHERE id=?", (int(message_id),)
            )
            return max(0, int(cursor.rowcount or 0))

    async def delete_dead(self) -> int:
        async with self.db.transaction(label="outbox") as conn:
            cursor = await conn.execute(
                "DELETE FROM outbox_messages WHERE status='dead'"
            )
            return max(0, int(cursor.rowcount or 0))

    async def prune_dead(self, *, retention_days: int) -> int:
        days = max(0, int(retention_days))
        if days <= 0:
            return 0
        cutoff = int(time.time()) - days * 86400
        async with self.db.transaction(label="outbox") as conn:
            cursor = await conn.execute(
                "DELETE FROM outbox_messages "
                "WHERE status='dead' AND COALESCE(dead_at, created_at) < ?",
                (cutoff,),
            )
            return max(0, int(cursor.rowcount or 0))

    async def counts(self) -> dict[str, int]:
        rows = await self.db.fetch_all(
            "SELECT status, COUNT(*) AS count FROM outbox_messages GROUP BY status"
        )
        result = {"pending": 0, "inflight": 0, "dead": 0, "total": 0}
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            result[status] = count
            result["total"] += count
        return result

    async def queue_usage(self) -> dict[str, Any]:
        row = await self.db.fetch_one(
            """
            SELECT COUNT(*) AS queued,
                   COALESCE(SUM(
                       LENGTH(CAST(destination AS BLOB)) +
                       LENGTH(CAST(body AS BLOB)) +
                       LENGTH(CAST(message_type AS BLOB)) +
                       LENGTH(CAST(category AS BLOB))
                   ), 0) AS bytes
              FROM outbox_messages
             WHERE status IN ('pending', 'inflight')
            """
        )
        destination = await self.db.fetch_one(
            """
            SELECT destination, COUNT(*) AS count
              FROM outbox_messages
             WHERE status IN ('pending', 'inflight')
             GROUP BY destination
             ORDER BY count DESC, destination
             LIMIT 1
            """
        )
        category = await self.db.fetch_one(
            """
            SELECT category, COUNT(*) AS count
              FROM outbox_messages
             WHERE status IN ('pending', 'inflight')
             GROUP BY category
             ORDER BY count DESC, category
             LIMIT 1
            """
        )
        return {
            "queued": int(row["queued"] if row else 0),
            "bytes": int(row["bytes"] if row else 0),
            "largest_destination": str(destination["destination"]) if destination else "",
            "largest_destination_count": int(destination["count"] if destination else 0),
            "largest_category": str(category["category"]) if category else "",
            "largest_category_count": int(category["count"] if category else 0),
        }

    async def oldest_pending_age(self) -> int:
        row = await self.db.fetch_one(
            "SELECT MIN(created_at) AS oldest FROM outbox_messages "
            "WHERE status IN ('pending', 'inflight')"
        )
        if row is None or row["oldest"] is None:
            return 0
        return max(0, int(time.time()) - int(row["oldest"]))

    async def dead_letters(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self.db.fetch_all(
            """
            SELECT id, destination, category, attempts, max_attempts,
                   created_at, dead_at, last_error
              FROM outbox_messages
             WHERE status='dead'
             ORDER BY id DESC
             LIMIT ?
            """,
            (max(1, min(200, int(limit))),),
        )
        return [dict(row) for row in rows]
