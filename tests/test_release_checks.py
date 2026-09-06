from __future__ import annotations

import pytest

from envs_xmpp_core.release.checks import ReleaseCheckResult, check_latest_release


@pytest.mark.asyncio
async def test_check_latest_release_reports_newer_same_and_error():
    newer = await check_latest_release("1.2.3", lambda: "v1.3.0")
    assert newer == ReleaseCheckResult(True, "1.3.0", None)
    assert newer.as_tuple() == (True, "1.3.0", None)

    same = await check_latest_release("1.2.3", lambda: "1.2.3")
    assert same == ReleaseCheckResult(False, "1.2.3", None)

    def broken() -> str:
        raise RuntimeError("network down")

    failed = await check_latest_release("1.2.3", broken)
    assert failed == ReleaseCheckResult(False, None, "network down")
