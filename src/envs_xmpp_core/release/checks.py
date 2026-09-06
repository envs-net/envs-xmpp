"""Application-neutral asynchronous release-check primitives."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from .versions import is_remote_version_newer, normalize_version


@dataclass(frozen=True)
class ReleaseCheckResult:
    """Result of comparing one fetched release with a local version."""

    update_available: bool
    remote_version: str | None
    error: str | None = None

    def as_tuple(self) -> tuple[bool, str | None, str | None]:
        """Return the legacy tuple shape used by both bots."""
        return self.update_available, self.remote_version, self.error


async def check_latest_release(
    local_version: str,
    fetch_latest: Callable[[], str],
) -> ReleaseCheckResult:
    """Fetch the latest release off-thread and compare it with ``local_version``.

    Transport selection, configuration policy and user-facing notifications are
    deliberately left to the caller. Any fetch/comparison error is converted to
    a result so periodic workers can report it without duplicating try/except
    scaffolding.
    """
    try:
        remote_version = normalize_version(await asyncio.to_thread(fetch_latest))
        return ReleaseCheckResult(
            update_available=is_remote_version_newer(remote_version, normalize_version(local_version)),
            remote_version=remote_version,
        )
    except Exception as exc:  # noqa: BLE001 - transport/comparison errors are result data
        return ReleaseCheckResult(False, None, str(exc))
