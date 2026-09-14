from envs_xmpp_core.runtime.session import SessionLifecycleState


def test_session_lifecycle_tracks_generations_reconnects_and_readiness(monkeypatch):
    wall = iter([100.0, 110.0, 120.0, 130.0])
    mono = iter([10.0, 11.0, 14.0, 15.0, 20.0, 21.0, 22.0, 23.0, 24.0])
    monkeypatch.setattr("envs_xmpp_core.runtime.session.time.time", lambda: next(wall))
    monkeypatch.setattr("envs_xmpp_core.runtime.session.time.monotonic", lambda: next(mono))

    state = SessionLifecycleState()
    first = state.begin()
    assert first == 1
    assert state.begin_phase(first, "rooms") is True
    assert state.mark_ready(first) is True
    ready = state.snapshot()
    assert ready.state == "ready"
    assert ready.phase == "ready"
    assert ready.reconnect_count == 0
    assert ready.startup_duration_seconds == 4.0

    state.mark_disconnected("transport lost")
    assert state.snapshot().last_disconnect_reason == "transport lost"
    second = state.begin()
    assert second == 2
    assert state.snapshot().reconnect_count == 1
    assert state.is_current(first) is False
    assert state.begin_phase(first, "stale") is False
    assert state.begin_phase(second, "synchronization") is True


def test_session_failure_only_applies_to_current_generation():
    state = SessionLifecycleState()
    first = state.begin()
    state.mark_disconnected("lost")
    second = state.begin()
    assert state.mark_failed(first, "old") is False
    assert state.mark_failed(second, RuntimeError("boom")) is True
    snapshot = state.snapshot()
    assert snapshot.state == "failed"
    assert snapshot.last_error == "boom"


def test_reconnecting_invalidates_the_ended_generation():
    state = SessionLifecycleState()
    generation = state.begin()
    assert state.is_current(generation) is True
    state.mark_reconnecting("connection lost")
    assert state.is_current(generation) is False
    snapshot = state.snapshot()
    assert snapshot.state == "reconnecting"
    assert snapshot.session_age_seconds is None
    assert snapshot.last_disconnect_reason == "connection lost"
