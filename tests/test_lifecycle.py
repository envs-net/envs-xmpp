from __future__ import annotations

import asyncio

import pytest

from envs_xmpp_core.runtime.lifecycle import LifecyclePhaseResult, LifecyclePhaseRunner


@pytest.mark.asyncio
async def test_runner_records_success_and_structured_outcome() -> None:
    runner = LifecyclePhaseRunner()

    async def ready():
        return "ok", {"rooms": 3}

    result = await runner.run("ready", ready)

    assert result.name == "ready"
    assert result.status == "ok"
    assert result.details == {"rooms": 3}
    assert result.duration_seconds >= 0
    assert result.healthy is True
    assert runner.results == (result,)


@pytest.mark.asyncio
async def test_runner_records_failure_before_reraising() -> None:
    observed = []
    runner = LifecyclePhaseRunner(observer=lambda result, error: observed.append((result, error)))

    async def broken():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await runner.run("storage", broken)

    assert len(runner.results) == 1
    assert runner.results[0].status == "failed"
    assert runner.results[0].healthy is False
    assert observed[0][0] == runner.results[0]
    assert isinstance(observed[0][1], RuntimeError)


@pytest.mark.asyncio
async def test_runner_can_continue_after_failed_phase() -> None:
    events: list[str] = []
    runner = LifecyclePhaseRunner()

    async def broken():
        events.append("broken")
        raise ValueError("nope")

    async def later():
        events.append("later")
        return "skipped", {}

    results = await runner.run_all(
        (("broken", broken), ("later", later)),
        continue_on_error=True,
    )

    assert events == ["broken", "later"]
    assert [result.status for result in results] == ["failed", "skipped"]
    assert results[1].healthy is True


@pytest.mark.asyncio
async def test_runner_does_not_convert_cancellation_to_failure() -> None:
    runner = LifecyclePhaseRunner()

    async def cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await runner.run("cancelled", cancelled, continue_on_error=True)

    assert runner.results == ()


def test_lifecycle_phase_health_contract() -> None:
    assert LifecyclePhaseResult("a", "ok", 0).healthy is True
    assert LifecyclePhaseResult("b", "skipped", 0).healthy is True
    assert LifecyclePhaseResult("c", "partial", 0).healthy is False
    assert LifecyclePhaseResult("d", "failed", 0).healthy is False
