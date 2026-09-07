from __future__ import annotations

import asyncio

import pytest

from envs_xmpp_core.runtime.health import (
    HealthCheck,
    HealthSnapshot,
    collect_health_snapshot,
)


def test_health_snapshot_reports_attention_and_unknown_checks() -> None:
    snapshot = HealthSnapshot(
        checked_at="2026-09-07T10:00:00+00:00",
        checks={
            "database": HealthCheck("database", "ok", "connected"),
            "rooms": HealthCheck("rooms", "warning", "one room missing"),
            "optional": HealthCheck("optional", "unknown", "not configured"),
        },
    )

    assert snapshot.needs_attention is True
    assert snapshot.problem_keys == ("rooms",)
    assert snapshot.check("database").needs_attention is False
    assert snapshot.check("missing") == HealthCheck(
        "missing", "unknown", "unavailable"
    )


@pytest.mark.asyncio
async def test_collect_health_snapshot_isolates_failures_and_preserves_order() -> None:
    async def async_ok() -> HealthCheck:
        return HealthCheck("async", "ok", "ready")

    def sync_ok() -> HealthCheck:
        return HealthCheck("sync", "warning", "degraded")

    def broken() -> HealthCheck:
        raise RuntimeError("boom")

    snapshot = await collect_health_snapshot(
        [
            ("async", async_ok),
            ("sync", sync_ok),
            ("broken", broken),
        ],
        checked_at="fixed",
    )

    assert snapshot.checked_at == "fixed"
    assert tuple(snapshot.checks) == ("async", "sync", "broken")
    assert snapshot.check("async").status == "ok"
    assert snapshot.check("sync").status == "warning"
    assert snapshot.check("broken").status == "error"
    assert snapshot.check("broken").error == "RuntimeError: boom"


@pytest.mark.asyncio
async def test_collect_health_snapshot_rejects_wrong_result_and_key() -> None:
    snapshot = await collect_health_snapshot(
        [
            ("wrong-type", lambda: object()),  # type: ignore[arg-type]
            (
                "expected-key",
                lambda: HealthCheck("other-key", "ok", "ready"),
            ),
        ]
    )

    assert snapshot.check("wrong-type").status == "error"
    assert "returned object" in (snapshot.check("wrong-type").error or "")
    assert snapshot.check("expected-key").status == "error"
    assert "mismatched key" in (snapshot.check("expected-key").error or "")


@pytest.mark.asyncio
async def test_collect_health_snapshot_propagates_cancellation() -> None:
    async def cancelled() -> HealthCheck:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await collect_health_snapshot([("cancelled", cancelled)])
