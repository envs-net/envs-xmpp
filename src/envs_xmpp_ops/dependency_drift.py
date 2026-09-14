"""Detect runtime-package drift from a project's reviewed constraint snapshot."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

_NAME_NORMALIZER = re.compile(r"[-_.]+")
_DEPENDENCY_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXACT_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;]+)")


def normalize_package_name(name: str) -> str:
    """Return a PEP 503-style normalized package name."""
    return _NAME_NORMALIZER.sub("-", str(name).strip()).lower()


@dataclass(frozen=True, slots=True)
class DependencyVersion:
    """Expected and observed version for one runtime dependency."""

    package: str
    expected: str | None
    installed: str | None

    @property
    def ok(self) -> bool:
        return self.expected is not None and self.installed == self.expected


@dataclass(frozen=True, slots=True)
class DependencyDriftReport:
    """Runtime dependency comparison against one exact constraint snapshot."""

    constraint_file: Path
    dependencies: tuple[DependencyVersion, ...]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.dependencies)

    @property
    def mismatches(self) -> tuple[DependencyVersion, ...]:
        return tuple(item for item in self.dependencies if not item.ok)

    def summary(self) -> str:
        if self.ok:
            return f"clean ({len(self.dependencies)} runtime dependencies match constraints)"
        return f"DRIFT ({len(self.mismatches)}/{len(self.dependencies)} runtime dependencies differ)"

    def details(self) -> tuple[str, ...]:
        lines: list[str] = []
        for item in self.mismatches:
            if item.expected is None:
                lines.append(f"{item.package}: no exact pin in {self.constraint_file.name}")
            elif item.installed is None:
                lines.append(f"{item.package}: missing (expected {item.expected})")
            else:
                lines.append(
                    f"{item.package}: installed {item.installed}, expected {item.expected}"
                )
        return tuple(lines)


def project_runtime_dependencies(project_root: Path) -> tuple[str, ...]:
    """Return normalized package names from ``project.dependencies``."""
    data = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    raw = data.get("project", {}).get("dependencies", [])
    names: set[str] = set()
    for dependency in raw:
        match = _DEPENDENCY_NAME.match(str(dependency))
        if match:
            names.add(normalize_package_name(match.group(1)))
    return tuple(sorted(names))


def exact_constraint_pins(path: Path) -> dict[str, str]:
    """Read simple exact ``name==version`` pins from a constraint file."""
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        match = _EXACT_PIN.match(text)
        if match:
            pins[normalize_package_name(match.group(1))] = match.group(2)
    return pins


def installed_versions(
    python: Path,
    packages: Sequence[str],
    *,
    run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str | None]:
    """Query installed versions from a specific Python environment."""
    requested = [normalize_package_name(name) for name in packages]
    probe = (
        "import importlib.metadata as m, json, sys; "
        "names=json.loads(sys.argv[1]); out={}; "
        "exec(\"for n in names:\\n"
        " try: out[n]=m.version(n)\\n"
        " except m.PackageNotFoundError: out[n]=None\"); "
        "print(json.dumps(out, sort_keys=True))"
    )
    result = run_process(
        [str(python), "-c", probe, json.dumps(requested)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "version probe failed").strip()
        raise RuntimeError(f"could not inspect {python}: {message}")
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid dependency-version probe output from {python}") from exc
    return {normalize_package_name(name): value for name, value in raw.items()}


def inspect_dependency_drift(
    project_root: Path,
    python: Path,
    constraint_file: Path,
    *,
    run_process: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DependencyDriftReport:
    """Compare installed runtime dependencies with exact reviewed pins."""
    dependencies = project_runtime_dependencies(project_root)
    pins = exact_constraint_pins(constraint_file)
    observed = installed_versions(python, dependencies, run_process=run_process)
    rows = tuple(
        DependencyVersion(
            package=name,
            expected=pins.get(name),
            installed=observed.get(name),
        )
        for name in dependencies
    )
    return DependencyDriftReport(constraint_file=constraint_file, dependencies=rows)
