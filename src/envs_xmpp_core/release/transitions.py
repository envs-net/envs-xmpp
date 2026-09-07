"""Application-neutral release transition helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .versions import compare_versions, normalize_version

ReleaseDirection = Literal["upgrade", "downgrade", "same", "unknown"]


def _known_version(value: object) -> str | None:
    normalized = normalize_version(str(value or "")).strip()
    if not normalized or normalized.lower() == "unknown":
        return None
    return normalized


@dataclass(frozen=True, slots=True)
class VersionTransition:
    """Normalized relationship between two application versions."""

    previous_version: str | None
    current_version: str | None
    direction: ReleaseDirection

    @property
    def changed(self) -> bool:
        """Return whether both versions are known and differ."""
        return self.direction in {"upgrade", "downgrade"}

    @property
    def is_upgrade(self) -> bool:
        return self.direction == "upgrade"

    @property
    def is_downgrade(self) -> bool:
        return self.direction == "downgrade"


def version_transition(previous_version: object, current_version: object) -> VersionTransition:
    """Classify a normalized version transition without application policy."""
    previous = _known_version(previous_version)
    current = _known_version(current_version)
    if previous is None or current is None:
        return VersionTransition(previous, current, "unknown")

    comparison = compare_versions(current, previous)
    if comparison > 0:
        direction: ReleaseDirection = "upgrade"
    elif comparison < 0:
        direction = "downgrade"
    else:
        direction = "same"
    return VersionTransition(previous, current, direction)


def merge_pending_version_transition(
    previous_version: object,
    current_version: object,
    pending: object,
) -> dict[str, str] | None:
    """Merge one successful transition with an optional undelivered chain.

    A pending transition is extended only when its ``to`` version matches the
    previous successful version. Returning to the original ``from`` version
    clears the pending transition. Unknown baselines are ignored.
    """
    transition = version_transition(previous_version, current_version)
    previous = transition.previous_version
    current = transition.current_version
    if previous is None or current is None:
        return None

    existing: dict[str, str] | None = None
    if isinstance(pending, Mapping):
        pending_from = _known_version(pending.get("from"))
        pending_to = _known_version(pending.get("to"))
        if (
            pending_from is not None
            and pending_to == previous
            and pending_from != pending_to
        ):
            existing = {"from": pending_from, "to": pending_to}

    if previous == current:
        return existing

    start = existing["from"] if existing is not None else previous
    if start == current:
        return None
    return {"from": start, "to": current}
