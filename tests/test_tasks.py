import asyncio

import pytest

from envs_xmpp_core.runtime.tasks import (
    SupervisorOptions,
    TaskSupervisor,
    sleep_with_heartbeat,
    task_heartbeat_interval,
    wait_for_event_with_heartbeat,
    wait_for_runtime_ready,
)


@pytest.mark.asyncio
async def test_supervisor_create_cancel():
    supervisor = TaskSupervisor()

    async def sleeper():
        await asyncio.sleep(60)

    task = supervisor.create("scope", sleeper(), name="worker")
    assert supervisor.owns(task)
    assert supervisor.snapshot()[0].scope == "scope"
    assert await supervisor.cancel_scope("scope", timeout=1.0) == 1


@pytest.mark.asyncio
async def test_resilient_circuit_callback():
    calls = []

    async def callback(scope, name, error):
        calls.append((scope, name, error))

    supervisor = TaskSupervisor(
        SupervisorOptions(max_restarts=0, initial_backoff=0, max_backoff=0),
        on_circuit_open=callback,
    )

    async def fail():
        raise RuntimeError("boom")

    task = supervisor.create_resilient("runtime", fail, name="broken")
    with pytest.raises(RuntimeError, match="task circuit open"):
        await task
    assert calls and calls[0][:2] == ("runtime", "broken")


@pytest.mark.asyncio
async def test_create_accepts_task_like_without_done_callback(monkeypatch):
    class TaskLike:
        def done(self):
            return False

        def cancel(self):
            return None

    created = TaskLike()

    def fake_create_task(coro, **_kwargs):
        coro.close()
        return created

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)
    supervisor = TaskSupervisor()

    async def worker():
        return None

    assert supervisor.create("scope", worker(), name="worker") is created
    assert supervisor.owns(created)


def test_task_heartbeat_interval_is_bounded_by_stale_threshold():
    assert task_heartbeat_interval(120) == 30.0
    assert task_heartbeat_interval(120, maximum=100) == 60.0
    assert task_heartbeat_interval("invalid") == 30.0


@pytest.mark.asyncio
async def test_sleep_with_heartbeat_chunks_wait(monkeypatch):
    beats: list[str] = []
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await sleep_with_heartbeat(5, heartbeat=lambda: beats.append("beat"), stale_after=4, interval=30)
    assert sleeps == [2.0, 2.0, 1.0]
    assert beats == ["beat", "beat", "beat"]


@pytest.mark.asyncio
async def test_wait_for_event_with_heartbeat_and_runtime_gate(monkeypatch):
    beats: list[str] = []
    event = asyncio.Event()

    async def fake_wait_for(awaitable, *, timeout):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
    assert (
        await wait_for_event_with_heartbeat(event, 3, heartbeat=lambda: beats.append("event"), stale_after=2) is False
    )
    assert beats == ["event", "event", "event"]

    ready = asyncio.Event()
    owner = type("Owner", (), {"runtime_ready": ready})()
    waiter = asyncio.create_task(wait_for_runtime_ready(owner, heartbeat=lambda: beats.append("ready")))
    await asyncio.sleep(0)
    assert not waiter.done()
    ready.set()
    await waiter
    assert beats[-1] == "ready"


@pytest.mark.asyncio
async def test_stale_tasks_uses_neutral_snapshot_contract_in_subclasses():
    class CompatibilitySupervisor(TaskSupervisor):
        def snapshot(self, *, include_done=True):
            return ["application-specific snapshot"]

    supervisor = CompatibilitySupervisor()

    async def worker():
        await asyncio.Event().wait()

    task = supervisor.create("scope", worker(), name="silent", kind="service")
    supervisor._tasks[task]["created_at"] = "2000-01-01T00:00:00+00:00"

    stale = supervisor.stale_tasks(max_age_seconds=1)
    assert [item.name for item in stale] == ["silent"]
    await supervisor.cancel_task(task, timeout=1.0)
