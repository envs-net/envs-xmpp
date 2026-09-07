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


def require_confirmation(
    prompt: str,
    *,
    confirm_func: Callable[[str], bool],
    error_factory: Callable[[str], Exception] = RuntimeError,
) -> None:
    """Require explicit operator confirmation or raise a caller-defined error."""
    if not confirm_func(prompt):
        raise error_factory("cancelled by operator")
