"""Shared pytest frontend for envs.net XMPP projects."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PytestConfig:
    marker: str | None
    coverage_source: str
    coverage_report: str
    coverage_fail_under: int


def _tool_config(root: Path) -> dict[str, Any]:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    tool = data.get("tool", {})
    envs_xmpp = tool.get("envs-xmpp", {})
    if not isinstance(envs_xmpp, dict):
        raise TypeError("[tool.envs-xmpp] must be a table")
    return envs_xmpp


def load_test_config(root: Path = Path(".")) -> PytestConfig:
    raw = _tool_config(root).get("testing")
    if not isinstance(raw, dict):
        raise TypeError("missing [tool.envs-xmpp.testing] configuration")
    marker_value = raw.get("marker")
    marker = None if marker_value is None else str(marker_value).strip() or None
    return PytestConfig(
        marker=marker,
        coverage_source=str(raw.get("coverage-source", ".")),
        coverage_report=str(raw.get("coverage-report", "term")),
        coverage_fail_under=int(raw.get("coverage-fail-under", 0)),
    )


def pytest_command(
    config: PytestConfig,
    *,
    coverage: bool,
    last_failed: bool,
    durations: int | None,
    targets: list[str],
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "-q",
        "-W",
        "error::RuntimeWarning",
        "-W",
        "error::DeprecationWarning",
    ]
    if config.marker:
        command.extend(["-m", config.marker])
    if last_failed:
        command.append("--lf")
    if durations is not None:
        command.extend([f"--durations={durations}", "--durations-min=0.1"])
    if coverage:
        command.extend(
            [
                f"--cov={config.coverage_source}",
                f"--cov-report={config.coverage_report}",
                f"--cov-fail-under={config.coverage_fail_under}",
            ]
        )
    command.extend(targets)
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", action="store_true", help="enable configured coverage gate")
    parser.add_argument("--last-failed", action="store_true", help="re-run previous failures")
    parser.add_argument("--durations", type=int, metavar="N", help="show the N slowest tests")
    args, pytest_args = parser.parse_known_args(argv)

    if args.durations is not None and args.durations <= 0:
        parser.error("--durations requires a positive integer")

    config = load_test_config()
    return subprocess.run(
        pytest_command(
            config,
            coverage=args.coverage,
            last_failed=args.last_failed,
            durations=args.durations,
            targets=pytest_args,
        ),
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
