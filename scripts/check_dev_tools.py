#!/usr/bin/env python3
"""Check that repository-only development tools are installed."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence

_TOOL_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "quality": (
        ("pytest", "pytest"),
        ("pytest_cov", "pytest-cov"),
        ("ruff", "ruff"),
        ("mypy", "mypy"),
        ("build", "build"),
        ("twine", "twine"),
    ),
    "mutation": (("mutmut", "mutmut"),),
}


def missing_tools(group: str) -> tuple[str, ...]:
    """Return distribution names missing from the selected development group."""
    try:
        tools = _TOOL_GROUPS[group]
    except KeyError as exc:
        raise ValueError(f"unknown development tool group: {group}") from exc
    return tuple(distribution for module, distribution in tools if importlib.util.find_spec(module) is None)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in _TOOL_GROUPS:
        print("Usage: check_dev_tools.py <quality|mutation>", file=sys.stderr)
        return 2

    missing = missing_tools(args[0])
    if not missing:
        return 0

    print(
        "Missing envs-xmpp development tools: " + ", ".join(missing),
        file=sys.stderr,
    )
    print(
        'Install the development extra with: python -m pip install -e ".[dev]"',
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
