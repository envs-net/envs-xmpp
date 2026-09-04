#!/usr/bin/env python3
"""Require a release tag to match the PEP 621 project version exactly."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} vX.Y.Z", file=sys.stderr)
        return 2

    tag = sys.argv[1].strip()
    with Path("pyproject.toml").open("rb") as handle:
        version = str(tomllib.load(handle)["project"]["version"])

    expected = f"v{version}"
    if tag != expected:
        print(
            f"release tag/version mismatch: tag={tag!r}, expected={expected!r}",
            file=sys.stderr,
        )
        return 1

    print(f"release tag matches project version: {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
