from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from envs_xmpp_core.release.state import ReleaseState, ReleaseStateSqlRepository


class SQLiteBackend:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)

    def available(self) -> bool:
        return True

    async def execute(self, query, params=(), *, label="release_state") -> int:
        del label
        cursor = self.connection.execute(query, tuple(params))
        self.connection.commit()
        return max(cursor.rowcount, 0)

    async def fetch_one(self, query, params=()):
        return self.connection.execute(query, tuple(params)).fetchone()


@pytest.mark.asyncio
async def test_release_state_repository_round_trip_and_conditional_clear(tmp_path):
    backend = SQLiteBackend(tmp_path / "state.sqlite")
    repo = ReleaseStateSqlRepository(backend)
    await repo.setup()
    await repo.save(
        ReleaseState(
            version="v1.8.2",
            pending_from="v1.8.1",
            pending_to="v1.8.2",
        )
    )

    assert await repo.load() == ReleaseState(
        version="1.8.2",
        pending_from="1.8.1",
        pending_to="1.8.2",
    )
    assert await repo.clear_pending_if_matches("1.7.9", "1.8.2") is False
    assert (await repo.load()).pending_announcement == {"from": "1.8.1", "to": "1.8.2"}
    assert await repo.clear_pending_if_matches("1.8.1", "1.8.2") is True
    assert await repo.load() == ReleaseState(version="1.8.2")


def test_release_state_mapping_normalizes_invalid_pending_values():
    state = ReleaseState.from_mapping(
        {
            "version": "v2.6.1",
            "pending_announcement": {"from": "v2.5.9", "to": "v2.6.1"},
        }
    )
    assert state.as_mapping() == {
        "version": "2.6.1",
        "pending_announcement": {"from": "2.5.9", "to": "2.6.1"},
    }
    assert ReleaseState(pending_from="2.6.1").pending_announcement is None
