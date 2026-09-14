"""Neutral human-readable formatting helpers."""

from __future__ import annotations

from datetime import UTC, datetime

_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def format_duration(seconds: float, *, zero_label: str = "0s") -> str:
    """Render a duration using compact day/hour/minute/second units.

    ``seconds <= 0`` is rendered as ``zero_label`` so applications can retain
    domain-specific wording such as ``"permanent"`` without duplicating the
    positive-duration formatter.
    """
    value = int(seconds)
    if value <= 0:
        return zero_label

    minutes, remainder_seconds = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if remainder_seconds:
        parts.append(f"{remainder_seconds}s")
    return " ".join(parts)


def format_bytes(
    size_bytes: float,
    *,
    negative_label: str | None = "unknown",
    max_unit: str = "TiB",
    bytes_decimals: int = 0,
) -> str:
    """Render a byte count using binary units.

    ``max_unit`` caps scaling so callers can preserve an existing display
    contract (for example a formatter that historically stopped at MiB).
    When ``negative_label`` is ``None``, negative values are rendered as raw
    bytes instead of being replaced with a sentinel string.
    """
    raw = int(size_bytes)
    if raw < 0:
        if negative_label is not None:
            return negative_label
        return f"{raw} B"

    try:
        max_index = _UNITS.index(max_unit)
    except ValueError as exc:
        raise ValueError(f"Unsupported max_unit: {max_unit}") from exc

    size = float(raw)
    for index, unit in enumerate(_UNITS[: max_index + 1]):
        if size < 1024 or index == max_index:
            if unit == "B":
                if bytes_decimals > 0:
                    return f"{size:.{bytes_decimals}f} B"
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024

    raise AssertionError("unreachable byte formatter state")


def _as_datetime(value: object | None) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_absolute_time(value: object | None, *, missing: str = "-") -> str:
    """Render supported timestamps as normalized UTC ISO-8601 text."""
    parsed = _as_datetime(value)
    if parsed is None:
        return missing
    return parsed.isoformat(timespec="seconds")


def format_relative_time(
    value: object | None,
    *,
    now: datetime | float | None = None,
    missing: str = "-",
) -> str:
    """Render ISO/datetime/epoch values relative to ``now``."""
    parsed = _as_datetime(value)
    if parsed is None:
        return missing
    if isinstance(now, (int, float)):
        current = datetime.fromtimestamp(float(now), tz=UTC)
    elif isinstance(now, datetime):
        current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
    else:
        current = datetime.now(UTC)
    delta = (parsed - current).total_seconds()
    label = format_duration(abs(delta), zero_label="now")
    if label == "now":
        return label
    return f"in {label}" if delta > 0 else f"{label} ago"
