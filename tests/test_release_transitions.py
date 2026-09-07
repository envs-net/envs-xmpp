from __future__ import annotations

import pytest

from envs_xmpp_core.release.checks import (
    ReleaseCheckDecision,
    ReleaseCheckResult,
    evaluate_release_check,
)
from envs_xmpp_core.release.transitions import (
    VersionTransition,
    merge_pending_version_transition,
    version_transition,
)


def test_version_transition_classifies_upgrade_downgrade_same_and_unknown() -> None:
    assert version_transition("v1.2.3", "1.3.0") == VersionTransition("1.2.3", "1.3.0", "upgrade")
    assert version_transition("1.3.0", "1.2.3") == VersionTransition("1.3.0", "1.2.3", "downgrade")
    assert version_transition("1.2.3", "v1.2.3") == VersionTransition("1.2.3", "1.2.3", "same")
    assert version_transition("unknown", "1.2.3").direction == "unknown"
    assert version_transition("", "1.2.3").direction == "unknown"


def test_merge_pending_version_transition_extends_keeps_clears_and_restarts() -> None:
    assert merge_pending_version_transition(
        "1.8.3", "1.8.4", {"from": "1.8.2", "to": "1.8.3"}
    ) == {"from": "1.8.2", "to": "1.8.4"}
    assert merge_pending_version_transition(
        "1.8.3", "1.8.3", {"from": "1.8.2", "to": "1.8.3"}
    ) == {"from": "1.8.2", "to": "1.8.3"}
    assert merge_pending_version_transition(
        "1.8.3", "1.8.2", {"from": "1.8.2", "to": "1.8.3"}
    ) is None
    assert merge_pending_version_transition(
        "1.8.3", "1.8.4", {"from": "1.7.9", "to": "1.8.1"}
    ) == {"from": "1.8.3", "to": "1.8.4"}
    assert merge_pending_version_transition("unknown", "1.8.4", None) is None


@pytest.mark.asyncio
async def test_evaluate_release_check_normalizes_notification_deduplication() -> None:
    due = await evaluate_release_check(
        "1.2.3",
        lambda: "v1.3.0",
        announce=True,
        last_notified_version="1.2.9",
    )
    assert due == ReleaseCheckDecision(ReleaseCheckResult(True, "1.3.0", None), "1.3.0")
    assert due.as_tuple() == (True, "1.3.0", None)

    duplicate = await evaluate_release_check(
        "1.2.3",
        lambda: "v1.3.0",
        announce=True,
        last_notified_version="v1.3.0",
    )
    assert duplicate.notification_version is None

    quiet = await evaluate_release_check("1.2.3", lambda: "1.3.0", announce=False)
    assert quiet.notification_version is None

    same = await evaluate_release_check("1.2.3", lambda: "1.2.3", announce=True)
    assert same.notification_version is None
