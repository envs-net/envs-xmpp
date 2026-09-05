"""Interactive deployment primitives with injectable I/O."""

from __future__ import annotations

from collections.abc import Callable


def confirm(
    prompt: str,
    *,
    input_func: Callable[[str], str] = input,
) -> bool:
    """Return whether an operator explicitly confirmed a destructive action."""
    try:
        answer = input_func(f"{prompt} [y/N] ").strip().casefold()
    except EOFError:
        return False
    return answer in {"y", "yes"}
