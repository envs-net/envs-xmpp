"""Service-account inspection helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def account_exists(
    user: str,
    *,
    getpwnam: Callable[[str], Any],
) -> bool:
    """Return whether *user* exists according to the supplied pwd lookup."""
    try:
        getpwnam(user)
    except KeyError:
        return False
    return True
