from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import pytest

from envs_xmpp_core.xmpp.pending_invites import (
    PendingRoomInvite,
    PendingRoomInviteSqlRepository,
    PendingRoomInviteStore,
    PendingRoomInviteStoreResult,
)


class FakeRepository:
    def __init__(self) -> None:
        self.enabled = True
        self.rows: dict[int, PendingRoomInvite] = {}
        self.next_id = 1
        self.setup_calls = 0

    def available(self) -> bool:
        return self.enabled

    async def setup(self) -> None:
        self.setup_calls += 1

    async def load_all(self) -> list[PendingRoomInvite]:
        return [self.rows[key] for key in sorted(self.rows)]

    async def insert_if_absent(
        self,
        room_jid: str,
        inviter: str,
        reason: str,
        created_at: int,
    ) -> PendingRoomInviteStoreResult:
        for invite in self.rows.values():
            if invite.key == (room_jid, inviter):
                return PendingRoomInviteStoreResult(invite, created=False)
        invite = PendingRoomInvite(
            id=self.next_id,
            room_jid=room_jid,
            inviter=inviter,
            reason=reason,
            created_at=created_at,
        )
        self.rows[invite.id] = invite
        self.next_id += 1
        return PendingRoomInviteStoreResult(invite, created=True)

    async def get(self, invite_id: int) -> PendingRoomInvite | None:
        return self.rows.get(invite_id)

    async def delete(self, invite_id: int) -> int:
        return int(self.rows.pop(invite_id, None) is not None)

    async def delete_many(self, invite_ids: Sequence[int]) -> int:
        deleted = 0
        for invite_id in invite_ids:
            deleted += await self.delete(invite_id)
        return deleted

    async def clear(self) -> int:
        count = len(self.rows)
        self.rows.clear()
        return count


def test_pending_invite_is_mapping_compatible_and_normalized() -> None:
    invite = PendingRoomInvite(
        id=7,
        room_jid=" Room@Conference.Example ",
        inviter="Alice@Example.Org",
        reason="hello",
        created_at=123,
    )

    assert invite.room_jid == "room@conference.example"
    assert invite.inviter == "alice@example.org"
    assert invite["id"] == 7
    assert invite.get("reason") == "hello"
    assert invite == {
        "id": 7,
        "room_jid": "room@conference.example",
        "inviter": "alice@example.org",
        "reason": "hello",
        "created_at": 123,
    }
    assert PendingRoomInvite.from_mapping(invite.as_dict()) == invite
    assert PendingRoomInvite.from_row((7, "ROOM@CONF", "A@EXAMPLE", None, 9)).reason == ""


def test_adopt_deduplicates_historical_runtime_state() -> None:
    store = PendingRoomInviteStore()
    store.adopt(
        {
            9: PendingRoomInvite(9, "room@conf", "alice@example.org", "later", 200),
            4: PendingRoomInvite(4, "room@conf", "alice@example.org", "first", 100),
            12: PendingRoomInvite(12, "other@conf", "bob@example.org", "other", 300),
        }
    )

    assert list(store.pending) == [4, 12]
    assert store.pending[4].reason == "first"
    assert store.index[("room@conf", "alice@example.org")] == 4
    assert store.next_id == 13


@pytest.mark.asyncio
async def test_memory_store_deduplicates_without_refreshing() -> None:
    store = PendingRoomInviteStore()
    store.adopt(
        {
            4: {
                "id": 4,
                "room_jid": "room@conf",
                "inviter": "alice@example.org",
                "reason": "old",
                "created_at": 100,
            }
        }
    )

    duplicate = await store.store(
        "room@conf",
        "alice@example.org",
        "ignored",
        max_age_days=30,
        now=200,
    )
    assert duplicate.created is False
    assert duplicate.invite.id == 4
    assert duplicate.invite.reason == "old"
    assert duplicate.invite.created_at == 100
    assert store.next_id == 5


@pytest.mark.asyncio
async def test_memory_store_replaces_expired_invite() -> None:
    store = PendingRoomInviteStore()
    store.adopt(
        {
            4: PendingRoomInvite(4, "room@conf", "alice@example.org", "old", 1),
        }
    )

    replacement = await store.store(
        "room@conf",
        "alice@example.org",
        "new",
        max_age_days=1,
        now=200_000,
    )
    assert replacement.created is True
    assert replacement.invite.id == 5
    assert replacement.invite.reason == "new"
    assert replacement.invite.created_at == 200_000


@pytest.mark.asyncio
async def test_memory_store_serializes_concurrent_duplicates() -> None:
    import asyncio

    store = PendingRoomInviteStore()
    first, second = await asyncio.gather(
        store.store("room@conf", "alice@example.org", "first", now=100),
        store.store("room@conf", "alice@example.org", "second", now=101),
    )

    assert first.created is True
    assert second.created is False
    assert first.invite == second.invite
    assert len(store.pending) == 1


@pytest.mark.asyncio
async def test_persistent_store_loads_expires_inserts_deletes_and_clears() -> None:
    repo = FakeRepository()
    repo.rows = {
        1: PendingRoomInvite(1, "active@conf", "a@example.org", "", 200_000),
        2: PendingRoomInvite(2, "old@conf", "b@example.org", "", 1),
    }
    repo.next_id = 3
    store = PendingRoomInviteStore(repo)

    result = await store.load(max_age_days=1, now=200_100)
    assert result.active_count == 1
    assert result.expired_count == 1
    assert list(store.pending) == [1]
    assert 2 not in repo.rows

    duplicate = await store.store(
        "active@conf",
        "a@example.org",
        "ignored",
        max_age_days=1,
        now=200_100,
    )
    assert duplicate.created is False
    assert duplicate.invite.reason == ""
    assert duplicate.invite.created_at == 200_000

    created = await store.store(
        "new@conf",
        "c@example.org",
        "reason",
        max_age_days=30,
        now=200_200,
    )
    assert created.created is True
    assert created.invite.id == 3
    assert store.index[created.invite.key] == 3

    deleted = await store.delete(3)
    assert deleted == created.invite
    assert 3 not in store.pending

    assert await store.clear() == 1
    assert store.pending == {}
    assert store.index == {}
    assert store.next_id == 1


@pytest.mark.asyncio
async def test_persistent_store_replaces_expired_row_not_loaded_in_cache() -> None:
    repo = FakeRepository()
    repo.rows = {
        1: PendingRoomInvite(1, "room@conf", "alice@example.org", "old", 1),
    }
    repo.next_id = 2
    store = PendingRoomInviteStore(repo)

    replacement = await store.store(
        "room@conf",
        "alice@example.org",
        "new",
        max_age_days=1,
        now=200_000,
    )

    assert replacement.created is True
    assert replacement.invite.id == 2
    assert replacement.invite.reason == "new"
    assert 1 not in repo.rows
    assert list(store.pending) == [2]


@pytest.mark.asyncio
async def test_cleanup_expired_uses_memory_state_without_repository() -> None:
    store = PendingRoomInviteStore()
    store.adopt(
        {
            1: PendingRoomInvite(1, "old@conf", "a@example.org", "", 1),
            2: PendingRoomInvite(2, "new@conf", "b@example.org", "", 100_000),
        }
    )

    removed = await store.cleanup_expired(max_age_days=1, now=100_100)
    assert removed == 1
    assert list(store.pending) == [2]


class FakeSqlBackend:
    def __init__(self) -> None:
        self.enabled = True
        self.connection = sqlite3.connect(":memory:")
        self.labels: list[str] = []

    def available(self) -> bool:
        return self.enabled

    async def execute(self, query, params=(), *, label: str = "room_invites") -> int:
        self.labels.append(label)
        cursor = self.connection.execute(query, tuple(params))
        self.connection.commit()
        rowcount = cursor.rowcount
        return rowcount if rowcount is not None and rowcount >= 0 else 0

    async def fetch_one(self, query, params=()):
        return self.connection.execute(query, tuple(params)).fetchone()

    async def fetch_all(self, query, params=()):
        return self.connection.execute(query, tuple(params)).fetchall()


@pytest.mark.asyncio
async def test_shared_sql_repository_owns_schema_and_crud() -> None:
    backend = FakeSqlBackend()
    repository = PendingRoomInviteSqlRepository(backend)

    await repository.setup()
    first = await repository.insert_if_absent(
        "Room@Conf",
        "Alice@Example.Org",
        "first",
        100,
    )
    duplicate = await repository.insert_if_absent(
        "Room@Conf",
        "Alice@Example.Org",
        "ignored",
        200,
    )

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.invite == first.invite
    assert duplicate.invite.reason == "first"
    assert duplicate.invite.created_at == 100
    assert await repository.get(first.invite.id) == first.invite
    assert await repository.load_all() == [first.invite]
    assert "room_invites_init" in backend.labels
    assert "room_invite_store" in backend.labels

    assert await repository.delete_many([first.invite.id]) == 1
    assert await repository.load_all() == []

    second = await repository.insert_if_absent("second@conf", "bob@example.org", "", 300)
    assert second.created is True
    assert await repository.clear() == 1
    assert await repository.load_all() == []


@pytest.mark.asyncio
async def test_shared_sql_repository_respects_unavailable_backend() -> None:
    backend = FakeSqlBackend()
    backend.enabled = False
    repository = PendingRoomInviteSqlRepository(backend)

    await repository.setup()
    assert await repository.load_all() == []
    assert await repository.get(1) is None
    assert await repository.delete(1) == 0
    assert await repository.delete_many([1]) == 0
    assert await repository.clear() == 0
    with pytest.raises(RuntimeError, match="database is unavailable"):
        await repository.insert_if_absent("room@conf", "a@example.org", "", 1)
