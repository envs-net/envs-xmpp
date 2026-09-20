#!/usr/bin/env python3
"""Require a release tag to match the envs-xmpp package version exactly."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from envs_xmpp_ops.release import ReleaseTagSpec, release_tag_main

    return release_tag_main(
        root=ROOT,
        spec=ReleaseTagSpec("pyproject.toml", source_kind="pyproject"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
