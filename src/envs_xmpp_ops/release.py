"""Shared release verification for envs.net XMPP repositories.

The helpers in this module deliberately contain no bot policy.  Consumer
repositories provide a small declarative specification describing their
version source, wheel name, console entry point and packaged runtime assets.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import venv
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReleaseTagSpec:
    """Declarative version/tag contract for one repository."""

    version_file: str
    source_kind: str = "python"
    assignment: str = "__version__"
    tag_prefix: str = "v"


@dataclass(frozen=True)
class ReleaseTagCheck:
    """Result of comparing a requested release tag with source metadata."""

    tag: str
    project_version: str
    expected_tag: str

    @property
    def ok(self) -> bool:
        return self.tag == self.expected_tag


@dataclass(frozen=True)
class WheelAsset:
    """One canonical source asset that must be present unchanged in a wheel.

    ``resolver`` optionally names a ``module:function`` pair that resolves the
    installed asset at runtime.  This preserves the old consumer smoke tests
    without embedding consumer-specific Python code in the shared checker.
    """

    source: str
    member: str
    resolver: str | None = None
    resolver_argument: str | None = None
    expected_runtime_fragment: str | None = None


@dataclass(frozen=True)
class WheelCheckSpec:
    """Declarative contract for an isolated wheel smoke test."""

    distribution: str
    wheel_glob: str
    console_script: str
    entry_point: str
    version_prefix: str
    assets: tuple[WheelAsset, ...] = ()
    required_members: tuple[str, ...] = ()
    version_contains: tuple[str, ...] = ()


@dataclass(frozen=True)
class WheelInspection:
    """Static wheel inspection result."""

    wheel: Path
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def read_python_assignment(path: str | Path, assignment: str = "__version__") -> str:
    """Read a non-empty string assignment from a Python source file."""
    source = Path(path)
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == assignment for target in targets):
            continue
        if node.value is None:
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RuntimeError(f"could not read {assignment} from {source}")


def _release_version(project_root: Path, spec: ReleaseTagSpec) -> str:
    source = project_root / spec.version_file
    if spec.source_kind == "python":
        return read_python_assignment(source, spec.assignment)
    if spec.source_kind == "pyproject":
        with source.open("rb") as handle:
            value = tomllib.load(handle).get("project", {}).get("version")
        version = str(value).strip() if value is not None else ""
        if version:
            return version
        raise RuntimeError(f"could not read project.version from {source}")
    raise ValueError(f"unsupported release version source kind: {spec.source_kind!r}")


def check_release_tag(
    tag: str,
    *,
    root: str | Path = ".",
    spec: ReleaseTagSpec,
) -> ReleaseTagCheck:
    """Compare ``tag`` with the version declared by ``spec``."""
    project_root = Path(root).resolve()
    version = _release_version(project_root, spec)
    normalized_tag = str(tag).strip()
    return ReleaseTagCheck(
        tag=normalized_tag,
        project_version=version,
        expected_tag=f"{spec.tag_prefix}{version}",
    )


def release_tag_main(
    argv: Sequence[str] | None = None,
    *,
    root: str | Path = ".",
    spec: ReleaseTagSpec,
) -> int:
    """CLI adapter for :func:`check_release_tag`."""
    parser = argparse.ArgumentParser(description="Verify that a release tag matches the project version.")
    parser.add_argument("tag", metavar="vX.Y.Z")
    options = parser.parse_args(list(argv) if argv is not None else None)

    result = check_release_tag(options.tag, root=root, spec=spec)
    if not result.ok:
        print(
            f"release tag/version mismatch: tag={result.tag!r}, expected={result.expected_tag!r}",
            file=sys.stderr,
        )
        return 1

    print(f"release tag matches project version: {result.tag}")
    return 0


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry_points(archive: zipfile.ZipFile, names: set[str]) -> dict[str, str]:
    member = next((name for name in names if name.endswith(".dist-info/entry_points.txt")), None)
    if member is None:
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(archive.read(member).decode("utf-8"))
    if not parser.has_section("console_scripts"):
        return {}
    return dict(parser.items("console_scripts"))


def inspect_wheel(
    wheel: str | Path,
    *,
    root: str | Path,
    spec: WheelCheckSpec,
) -> WheelInspection:
    """Verify wheel contents without installing the distribution."""
    project_root = Path(root).resolve()
    wheel_path = Path(wheel).resolve()
    errors: list[str] = []

    with zipfile.ZipFile(wheel_path) as archive:
        names = set(archive.namelist())

        for asset in spec.assets:
            source = project_root / asset.source
            if not source.is_file():
                errors.append(f"canonical packaged asset is missing: {asset.source}")
                continue
            if asset.member not in names:
                errors.append(f"wheel is missing packaged asset: {asset.member}")
                continue
            actual = hashlib.sha256(archive.read(asset.member)).hexdigest()
            if actual != _digest(source):
                errors.append(f"wheel asset differs from canonical bundled source: {asset.source}")

        for member in spec.required_members:
            if member not in names:
                errors.append(f"wheel is missing required member: {member}")

        entry_points = _entry_points(archive, names)
        actual_entry = entry_points.get(spec.console_script)
        if actual_entry is None:
            errors.append(f"wheel is missing the {spec.console_script} console entry point")
        elif actual_entry.strip() != spec.entry_point:
            errors.append(
                f"wheel console entry point differs: {spec.console_script}={actual_entry!r}, "
                f"expected {spec.entry_point!r}"
            )

    return WheelInspection(wheel=wheel_path, errors=tuple(errors))


def _runtime_asset_payload(spec: WheelCheckSpec) -> str:
    checks = []
    for asset in spec.assets:
        if not asset.resolver:
            continue
        module, separator, attribute = asset.resolver.partition(":")
        if not separator or not module or not attribute:
            raise ValueError(f"invalid asset resolver {asset.resolver!r}; expected module:function")
        checks.append(
            {
                "module": module,
                "attribute": attribute,
                "argument": asset.resolver_argument,
                "expected_fragment": asset.expected_runtime_fragment,
            }
        )
    return json.dumps(checks)


def _runtime_asset_smoke_code(payload: str) -> str:
    return f"""
import importlib
import json
from pathlib import Path

for check in json.loads({payload!r}):
    module = importlib.import_module(check["module"])
    resolver = getattr(module, check["attribute"])
    argument = check["argument"]
    path = Path(resolver(argument) if argument is not None else resolver())
    assert path.is_file(), path
    fragment = check["expected_fragment"]
    if fragment:
        assert fragment in path.as_posix(), (fragment, path)
print("Wheel asset smoke test passed.")
"""


def _isolated_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _isolated_script(env_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    directory = "Scripts" if os.name == "nt" else "bin"
    return env_dir / directory / f"{name}{suffix}"


def smoke_test_installed_wheel(wheel: str | Path, *, spec: WheelCheckSpec) -> None:
    """Install ``wheel`` into a temporary venv and verify runtime behavior."""
    wheel_path = Path(wheel).resolve()
    with tempfile.TemporaryDirectory(prefix=f"{spec.distribution}-wheel-") as temp_name:
        temp = Path(temp_name)
        env_dir = temp / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = _isolated_python(env_dir)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--force-reinstall",
                str(wheel_path),
            ],
            cwd=temp,
            check=True,
        )
        subprocess.run([str(python), "-m", "pip", "check"], cwd=temp, check=True)

        payload = _runtime_asset_payload(spec)
        if payload != "[]":
            subprocess.run(
                [str(python), "-c", _runtime_asset_smoke_code(payload)],
                cwd=temp,
                check=True,
            )

        executable = _isolated_script(env_dir, spec.console_script)
        result = subprocess.run(
            [str(executable), "--version"],
            cwd=temp,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = "".join(part for part in (result.stdout, result.stderr) if part)
            raise RuntimeError(
                f"installed {spec.console_script} --version failed with exit code "
                f"{result.returncode}{': ' + detail.strip() if detail else ''}"
            )

        output = result.stdout.strip()
        if not output.startswith(spec.version_prefix):
            raise RuntimeError(
                f"unexpected {spec.console_script} --version output: {result.stdout!r}; "
                f"expected prefix {spec.version_prefix!r}"
            )
        missing = [fragment for fragment in spec.version_contains if fragment not in output]
        if missing:
            raise RuntimeError(
                f"unexpected {spec.console_script} --version output: {result.stdout!r}; "
                f"missing {missing!r}"
            )


def wheel_check_main(
    argv: Sequence[str] | None = None,
    *,
    root: str | Path,
    spec: WheelCheckSpec,
) -> int:
    """CLI adapter for static and isolated wheel verification."""
    parser = argparse.ArgumentParser(description=f"Smoke-test the built {spec.distribution} wheel.")
    parser.parse_args(list(argv) if argv is not None else None)

    project_root = Path(root).resolve()
    wheels = sorted((project_root / "dist").glob(spec.wheel_glob))
    if len(wheels) != 1:
        print(
            f"Expected exactly one built {spec.distribution} wheel, found {len(wheels)}",
            file=sys.stderr,
        )
        return 1

    inspection = inspect_wheel(wheels[0], root=project_root, spec=spec)
    if inspection.errors:
        for error in inspection.errors:
            print(error, file=sys.stderr)
        return 1

    try:
        smoke_test_installed_wheel(wheels[0], spec=spec)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Wheel smoke test passed: {wheels[0].name}")
    return 0
