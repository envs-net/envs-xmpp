from envs_xmpp_core.runtime import KeyedCooldown


def test_keyed_cooldown_suppresses_repeats_and_reports_them() -> None:
    gate = KeyedCooldown(cooldown_seconds=10)

    assert gate.check("room/user", now=100).allowed is True
    second = gate.check("room/user", now=105)
    third = gate.check("room/user", now=109)
    assert second.allowed is False
    assert second.suppressed == 1
    assert third.allowed is False
    assert third.suppressed == 2

    resumed = gate.check("room/user", now=110)
    assert resumed.allowed is True
    assert resumed.suppressed == 2

    # The repeat count belongs to the previous cooldown window only.
    assert gate.check("room/user", now=121).suppressed == 0


def test_keyed_cooldown_can_forget_and_disable_window() -> None:
    gate = KeyedCooldown(cooldown_seconds=10)
    gate.check("one", now=1)
    assert gate.check("one", now=2).allowed is False
    gate.forget("one")
    assert gate.check("one", now=2).allowed is True
    assert gate.check("one", now=2, cooldown_seconds=0).allowed is True


def test_keyed_cooldown_bounds_state_by_lru_key() -> None:
    gate = KeyedCooldown(cooldown_seconds=60, max_keys=2)
    gate.check("one", now=1)
    gate.check("two", now=2)
    gate.check("one", now=3)  # touch one; two is now the oldest
    gate.check("three", now=4)

    assert len(gate) == 2
    # "two" was evicted and therefore starts a new cooldown window.
    assert gate.check("two", now=5).allowed is True
