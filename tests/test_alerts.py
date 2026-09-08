from envs_xmpp_core.runtime.alerts import AlertTracker, TransitionAlertState


def test_transition_alert_state_defaults() -> None:
    state = TransitionAlertState()
    assert not state.active
    assert state.since == 0
    assert state.fingerprint == ""


def test_alert_tracker_deduplicates_and_can_release_reservation() -> None:
    tracker = AlertTracker(dedup_window_seconds=60)
    assert tracker.should_emit("db", now=100.0)
    assert not tracker.should_emit("db", now=120.0)
    tracker.forget_emission("db")
    assert tracker.should_emit("db", now=121.0)


def test_alert_tracker_counts_consecutive_failures() -> None:
    tracker = AlertTracker()
    assert tracker.record_failure("rtbl") == 1
    assert tracker.record_failure("rtbl") == 2
    tracker.record_success("rtbl")
    assert "rtbl" not in tracker.counters
