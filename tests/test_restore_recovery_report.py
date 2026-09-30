from __future__ import annotations

import pytest

from envs_xmpp_core.storage.restore import (
    RestoreTransactionError,
    restore_recovery_report,
)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "not_attempted"),
        ({"rollback_attempted": True}, "rollback_complete"),
        ({"recovery_attempted": True}, "runtime_recovered"),
        ({"rollback_attempted": True, "recovery_errors": (RuntimeError("reopen"),)}, "rollback_incomplete"),
        ({"recovery_attempted": True, "recovery_errors": (RuntimeError("reopen"),)}, "runtime_recovery_failed"),
    ],
)
def test_restore_recovery_report_classifies_failure(kwargs: dict, expected: str) -> None:
    error = RestoreTransactionError("apply", RuntimeError("write"), **kwargs)
    report = restore_recovery_report(error)
    assert report.phase == "apply"
    assert report.outcome == expected
    assert report.errors == (*error.rollback_errors, *error.recovery_errors)
