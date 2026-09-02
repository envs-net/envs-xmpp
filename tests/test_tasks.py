import asyncio
import pytest
from envs_xmpp_core.runtime.tasks import SupervisorOptions, TaskSupervisor

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
