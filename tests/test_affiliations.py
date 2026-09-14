from __future__ import annotations

import pytest

from envs_xmpp_core.xmpp.affiliations import AffiliationQueryOptions, query_muc_affiliation


@pytest.mark.asyncio
async def test_affiliation_query_passes_bounded_timeout():
    calls = []

    class Muc:
        async def get_affiliation_list(self, room, affiliation, *, timeout):
            calls.append((room, affiliation, timeout))
            return ["owner@example.org"]

    result = await query_muc_affiliation(
        Muc(),
        "room@example.org",
        "owner",
        options=AffiliationQueryOptions(timeout_seconds=7, attempts=1),
    )
    assert result.ok is True
    assert result.items == ("owner@example.org",)
    assert calls == [("room@example.org", "owner", 7.0)]


@pytest.mark.asyncio
async def test_affiliation_query_retries_iq_timeout_without_raw_stanza():
    sleeps = []

    class IqTimeout(Exception):
        pass

    class Muc:
        def __init__(self):
            self.calls = 0

        async def get_affiliation_list(self, room, affiliation, *, timeout):
            self.calls += 1
            if self.calls == 1:
                raise IqTimeout("<iq id='secret'/>")
            return ["admin@example.org"]

    muc = Muc()

    async def sleep(delay):
        sleeps.append(delay)

    result = await query_muc_affiliation(
        muc,
        "room@example.org",
        "admin",
        options=AffiliationQueryOptions(timeout_seconds=5, attempts=2, retry_delay_seconds=0.25),
        sleep=sleep,
    )
    assert result.ok is True
    assert result.attempts == 2
    assert muc.calls == 2
    assert sleeps == [0.25]


@pytest.mark.asyncio
async def test_affiliation_query_classifies_permanent_iq_error_without_retry():
    class IqError(Exception):
        condition = "forbidden"
        text = "denied"

    class Muc:
        async def get_affiliation_list(self, room, affiliation, *, timeout):
            raise IqError("<iq private='raw'/>")

    result = await query_muc_affiliation(Muc(), "room@example.org", "owner")
    assert result.ok is False
    assert result.attempts == 1
    assert result.error_kind == "iq-error"
    assert result.error_condition == "forbidden"
    assert result.summary == "IQ error forbidden: denied"
    assert "<iq" not in result.summary


@pytest.mark.asyncio
async def test_affiliation_query_bounds_legacy_signature_without_timeout_kwarg():
    class Muc:
        async def get_affiliation_list(self, room, affiliation):
            return ["owner@example.org"]

    result = await query_muc_affiliation(
        Muc(),
        "room@example.org",
        "owner",
        options=AffiliationQueryOptions(attempts=1),
    )
    assert result.ok is True
    assert result.items == ("owner@example.org",)


@pytest.mark.asyncio
async def test_affiliation_query_falls_back_to_legacy_getter():
    class Muc:
        async def get_users_by_affiliation(self, room, affiliation):
            return ["owner@example.org"]

    result = await query_muc_affiliation(
        Muc(),
        "room@example.org",
        "owner",
        options=AffiliationQueryOptions(attempts=1),
    )
    assert result.ok is True
    assert result.items == ("owner@example.org",)


@pytest.mark.asyncio
async def test_query_extracts_mucadmin_items_from_rich_result():
    items = [{"jid": "owner@example.org", "reason": "manual"}]

    class Plugin:
        async def get_affiliation_list(self, room, affiliation, **kwargs):
            return {"mucadmin_query": {"items": items}}

    result = await query_muc_affiliation(Plugin(), "room@example.org", "outcast")
    assert result.ok is True
    assert result.items == tuple(items)
