"""Shared release-state audit for envs-xmpp consumer repositories."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from envs_xmpp_core import __version__ as envs_xmpp_version

from .release import read_python_assignment

_DEPENDENCY_NAME = "envs-xmpp"


@dataclass(frozen=True)
class SharedCoreReleaseAudit:
    """Observed envs-xmpp dependency state for one consumer checkout."""

    expected_version: str
    pyproject_requirement: str | None
    requirements_requirement: str | None
    constraint_pins: tuple[tuple[str, str | None], ...]
    bootstrap_version: str | None
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _pyproject_requirement(path: Path) -> str | None:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    dependencies = data.get("project", {}).get("dependencies", ())
    for value in dependencies:
        text = str(value).strip()
        if text.lower().startswith(_DEPENDENCY_NAME):
            return text
    return None


def _requirements_requirement(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#") and text.lower().startswith(_DEPENDENCY_NAME):
            return text
    return None


def _constraint_pin(path: Path) -> str | None:
    if not path.is_file():
        return None
    prefix = f"{_DEPENDENCY_NAME}=="
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text.lower().startswith(prefix):
            return text[len(prefix) :].strip()
    return None


def _requirement_has_version(requirement: str | None, expected: str) -> bool:
    if not requirement:
        return False
    normalized = re.sub(r"\s+", "", requirement).lower()
    return normalized.startswith(f"{_DEPENDENCY_NAME}>={expected},") and "<2.0" in normalized


def audit_shared_core_release_state(
    root: str | Path = ".",
    *,
    expected_version: str | None = None,
    constraint_paths: tuple[str, ...] = (
        "constraints/python312.txt",
        "constraints/python313.txt",
    ),
    bootstrap_path: str = "scripts/_envs_xmpp_bootstrap.py",
) -> SharedCoreReleaseAudit:
    """Verify that a consumer checkout agrees on one envs-xmpp version."""
    project_root = Path(root).resolve()
    expected = str(expected_version or envs_xmpp_version)
    pyproject = _pyproject_requirement(project_root / "pyproject.toml")
    requirements = _requirements_requirement(project_root / "requirements.txt")
    pins = tuple(
        (relative, _constraint_pin(project_root / relative))
        for relative in constraint_paths
    )
    bootstrap_file = project_root / bootstrap_path
    bootstrap: str | None = None
    if bootstrap_file.is_file():
        try:
            bootstrap = read_python_assignment(bootstrap_file, "_REQUIRED_VERSION")
        except RuntimeError:
            bootstrap = None

    errors: list[str] = []
    if not _requirement_has_version(pyproject, expected):
        errors.append(
            f"pyproject.toml envs-xmpp requirement must start at {expected} and stay below 2.0; got {pyproject!r}"
        )
    if requirements != pyproject:
        errors.append(
            f"requirements.txt and pyproject.toml envs-xmpp requirements differ: {requirements!r} != {pyproject!r}"
        )
    for relative, pin in pins:
        if pin != expected:
            errors.append(f"{relative} must pin envs-xmpp=={expected}; got {pin!r}")
    if bootstrap != expected:
        errors.append(
            f"{bootstrap_path} must use _REQUIRED_VERSION={expected!r}; got {bootstrap!r}"
        )

    return SharedCoreReleaseAudit(
        expected_version=expected,
        pyproject_requirement=pyproject,
        requirements_requirement=requirements,
        constraint_pins=pins,
        bootstrap_version=bootstrap,
        errors=tuple(errors),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify envs-xmpp dependency, constraint and deploy-bootstrap alignment."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--expected-version", default=envs_xmpp_version)
    options = parser.parse_args(argv)

    result = audit_shared_core_release_state(
        options.root,
        expected_version=options.expected_version,
    )
    if result.errors:
        for error in result.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "shared-core release audit passed: "
        f"envs-xmpp {result.expected_version} dependency/pins/bootstrap agree"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
