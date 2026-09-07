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
    assert snapshot.check("missing") == HealthCheck("missing", "unknown", "unavailable")


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


def test_analyze_task_snapshot_normalizes_both_compatibility_shapes() -> None:
    class EnvsTask:
        plugin = "rss"
        name = "feed-worker"
        status = "running"
        kind = "service"
        restart_count = 2
        circuit_state = "half-open"
        last_error = "boom"

    class BanTask:
        group = "_core"
        name = "unban-worker"
        status = "failed"
        kind = "service"
        restart_count = 1
        last_error = "bad"

    from envs_xmpp_core.runtime.health import analyze_task_snapshot

    state = analyze_task_snapshot([EnvsTask(), BanTask()])

    assert state.services_running == 1
    assert state.failed == 1
    assert state.restarting_tasks[0].label == "rss/feed-worker"
    assert state.restarting_tasks[0].circuit_state == "half-open"
    assert state.failed_tasks[0].label == "_core/unban-worker"
    assert state.restarted_tasks == (state.failed_tasks[0],)


def test_analyze_task_snapshot_keeps_open_circuits_and_counts_one_shots() -> None:
    from types import SimpleNamespace

    from envs_xmpp_core.runtime.health import analyze_task_snapshot

    state = analyze_task_snapshot(
        [
            SimpleNamespace(
                scope="plugin",
                name="broken",
                status="failed",
                kind="service",
                restart_count=3,
                circuit_state="open",
                last_error="boom",
            ),
            SimpleNamespace(
                scope="plugin",
                name="command",
                status="done",
                kind="one-shot",
                restart_count=0,
                circuit_state="closed",
                last_error=None,
            ),
        ]
    )

    assert state.counts["failed"] == 1
    assert state.counts["one_shots_completed"] == 1
    assert [item.label for item in state.open_circuits] == ["plugin/broken"]


def test_watchdog_health_state_supports_mapping_and_object_state() -> None:
    from types import SimpleNamespace

    from envs_xmpp_core.runtime.health import watchdog_health_state

    mapping = SimpleNamespace(
        runtime_state=lambda: {
            "enabled": True,
            "worker_running": True,
            "last_lag_seconds": 0.5,
            "max_lag_seconds": 1.25,
            "lag_warnings": 2,
            "heartbeat_suppressed": 1,
            "last_error": "",
        }
    )
    mapped = watchdog_health_state(mapping)
    assert mapped.available is True
    assert mapped.enabled is True
    assert mapped.worker_running is True
    assert mapped.max_lag_seconds == 1.25
    assert mapped.last_error is None

    object_state = SimpleNamespace(
        state=SimpleNamespace(
            enabled=True,
            worker_running=False,
            max_lag_seconds=3.0,
            heartbeat_suppressed=4,
        )
    )
    object_result = watchdog_health_state(object_state)
    assert object_result.available is True
    assert object_result.worker_running is False
    assert object_result.heartbeat_suppressed == 4
    assert watchdog_health_state(None).available is False


def test_lifecycle_health_state_normalizes_shared_phase_results() -> None:
    from types import SimpleNamespace

    from envs_xmpp_core.runtime.health import lifecycle_health_state

    owner = SimpleNamespace(
        _last_startup_phases=(
            SimpleNamespace(name="storage", status="ok"),
            SimpleNamespace(name="rooms", status="partial"),
        ),
        _last_shutdown_phases=(SimpleNamespace(name="database", status="failed"),),
    )

    state = lifecycle_health_state(owner)
    assert state.startup == (("storage", "ok"), ("rooms", "partial"))
    assert state.startup_attention == ("rooms",)
    assert state.shutdown_attention == ("database",)
