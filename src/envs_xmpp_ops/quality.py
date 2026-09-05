"""Shared repository quality runner for envs.net XMPP projects."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectCheck:
    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class QualityConfig:
    compile_targets: tuple[str, ...]
    project_checks: tuple[ProjectCheck, ...]
    ruff_targets: tuple[str, ...]
    mypy_targets: tuple[str, ...]
    mypy_args: tuple[str, ...]
    constraints_dir: str = "constraints"


def _tool_config(root: Path) -> dict[str, Any]:
    with (root / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    tool = data.get("tool", {})
    envs_xmpp = tool.get("envs-xmpp", {})
    if not isinstance(envs_xmpp, dict):
        raise TypeError("[tool.envs-xmpp] must be a table")
    return envs_xmpp


def load_quality_config(root: Path = Path(".")) -> QualityConfig:
    raw = _tool_config(root).get("quality")
    if not isinstance(raw, dict):
        raise TypeError("missing [tool.envs-xmpp.quality] configuration")

    checks: list[ProjectCheck] = []
    for item in raw.get("project-checks", []):
        if not isinstance(item, dict):
            raise TypeError("quality project-checks entries must be tables")
        name = str(item.get("name", "")).strip()
        command = item.get("command")
        if not name or not isinstance(command, list) or not command:
            raise ValueError("quality project-checks require name and command")
        checks.append(ProjectCheck(name=name, command=tuple(str(part) for part in command)))

    def strings(key: str) -> tuple[str, ...]:
        value = raw.get(key, [])
        if not isinstance(value, list):
            raise TypeError(f"quality {key} must be an array")
        return tuple(str(item) for item in value)

    compile_targets = strings("compile-targets")
    ruff_targets = strings("ruff-targets")
    mypy_targets = strings("mypy-targets")
    if not compile_targets or not ruff_targets or not mypy_targets:
        raise ValueError("quality compile-targets, ruff-targets and mypy-targets must not be empty")

    return QualityConfig(
        compile_targets=compile_targets,
        project_checks=tuple(checks),
        ruff_targets=ruff_targets,
        mypy_targets=mypy_targets,
        mypy_args=strings("mypy-args"),
        constraints_dir=str(raw.get("constraints-dir", "constraints")),
    )


def _python_command(parts: tuple[str, ...]) -> list[str]:
    if parts and parts[0] == "python":
        return [sys.executable, *parts[1:]]
    return list(parts)


def _run(command: list[str], *, root: Path) -> None:
    subprocess.run(command, cwd=root, check=True)


def _git_whitespace_check(root: Path) -> None:
    tag = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        cwd=root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout.strip()
    if tag:
        _run(["git", "--no-pager", "diff", "--check", tag], root=root)

    _run(["git", "--no-pager", "diff", "--check", "HEAD"], root=root)

    dirty = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--"],
        cwd=root,
        check=False,
    ).returncode
    if dirty == 0:
        empty_tree = subprocess.run(
            ["git", "hash-object", "-t", "tree", "/dev/null"],
            cwd=root,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()
        _run(["git", "--no-pager", "diff", "--check", empty_tree, "HEAD"], root=root)


def run_quality(*, root: Path = Path("."), fix: bool = False, skip_tests: bool = False) -> None:
    config = load_quality_config(root)
    steps = 9

    print(f"[1/{steps}] Python compilation", flush=True)
    _run([sys.executable, "-m", "compileall", "-q", *config.compile_targets], root=root)

    print(f"[2/{steps}] Project validation", flush=True)
    if config.project_checks:
        for check in config.project_checks:
            print(f"  - {check.name}", flush=True)
            _run(_python_command(check.command), root=root)
    else:
        print("  - no project-specific checks configured", flush=True)

    print(f"[3/{steps}] Test suite (warning strict)", flush=True)
    if skip_tests:
        print("  - skipped by request", flush=True)
    else:
        _run([sys.executable, "-m", "envs_xmpp_ops.testing"], root=root)

    fix_args = ["--fix"] if fix else []

    print(f"[4/{steps}] Ruff: repository checks", flush=True)
    _run([sys.executable, "-m", "ruff", "check", *fix_args, "."], root=root)

    print(f"[5/{steps}] Ruff: unused imports (F401)", flush=True)
    _run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            *fix_args,
            "--select",
            "F401",
            "--extend-exclude",
            "**/__init__.py",
            ".",
        ],
        root=root,
    )

    print(f"[6/{steps}] Ruff: imports, modernization, and Bugbear (I,UP,B)", flush=True)
    _run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            *fix_args,
            "--select",
            "I,UP,B",
            *config.ruff_targets,
        ],
        root=root,
    )

    print(f"[7/{steps}] mypy: configured production source tree", flush=True)
    _run(
        [sys.executable, "-m", "mypy", *config.mypy_args, *config.mypy_targets],
        root=root,
    )

    print(f"[8/{steps}] Git whitespace errors", flush=True)
    _git_whitespace_check(root)

    print(f"[9/{steps}] Dependency audit (pip-audit)", flush=True)
    minor = f"{sys.version_info.major}{sys.version_info.minor}"
    constraint_file = root / config.constraints_dir / f"python{minor}.txt"
    if not constraint_file.is_file():
        raise SystemExit(f"No audited dependency snapshot for Python {minor}")
    _run([sys.executable, "-m", "pip_audit", "-r", str(constraint_file)], root=root)

    print(f"Quality checks passed ({steps}/{steps}).", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="apply Ruff auto-fixes")
    parser.add_argument("--skip-tests", action="store_true", help="skip pytest when CI runs it separately")
    args = parser.parse_args(argv)
    run_quality(fix=args.fix, skip_tests=args.skip_tests)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
