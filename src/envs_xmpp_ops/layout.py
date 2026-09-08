"""Shared deployment-layout and systemd discovery helpers."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from pathlib import Path


def split_systemd_words(value: str) -> list[str]:
    """Split a systemd property value while tolerating malformed quoting."""
    if not value:
        return []
    try:
        return shlex.split(value)
    except ValueError:
        return value.split()


def systemd_environment_value(value: str, key: str) -> str | None:
    """Extract one ``KEY=value`` assignment from ``systemctl show Environment``."""
    prefix = f"{key}="
    for assignment in split_systemd_words(value):
        if assignment.startswith(prefix):
            result = assignment[len(prefix) :]
            return result if result else None
    return None


def systemd_exec_path(value: str) -> Path | None:
    """Extract the executable path from ``systemctl show ExecStart`` output."""
    marker = "path="
    if marker not in value:
        return None
    executable = value.split(marker, 1)[1].split(";", 1)[0].strip()
    if not executable:
        return None
    return Path(executable).expanduser()


def systemd_venv(value: str, executable_name: str) -> Path | None:
    """Return a virtualenv inferred from a systemd ExecStart executable."""
    path = systemd_exec_path(value)
    if path is None or path.name != executable_name or path.parent.name != "bin":
        return None
    return path.parent.parent.resolve()


def systemd_path_set(value: str) -> set[str]:
    """Normalize a systemd path-list property for exact comparisons."""
    return set(split_systemd_words(value))


def resolve_environment_path(
    value: str | None,
    *,
    working_directory: str | Path | None = None,
    fallback_directory: str | Path | None = None,
) -> Path | None:
    """Resolve an environment-provided path using systemd WorkingDirectory."""
    if value is None or not str(value).strip():
        return None
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        base_value = working_directory or fallback_directory
        if base_value is not None:
            path = Path(base_value).expanduser() / path
    return path.resolve()


def service_account(
    *,
    environment: Mapping[str, str],
    environment_name: str,
    discovered: str | None,
    fallback: str,
) -> str:
    """Resolve a service account from override, systemd discovery and fallback."""
    configured = str(environment.get(environment_name, "") or "").strip()
    if configured:
        return configured
    discovered_value = str(discovered or "").strip()
    return discovered_value or str(fallback)


def deployment_environment(
    *,
    config_environment: str,
    config: str | Path,
    base: Mapping[str, str] | None = None,
    disable_bytecode: bool = False,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a deployment subprocess environment with one selected config path."""
    result = dict(os.environ if base is None else base)
    result[str(config_environment)] = str(config)
    if disable_bytecode:
        result["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        result.update({str(key): str(value) for key, value in extra.items()})
    return result


def venv_binary(venv: str | Path, name: str) -> Path:
    """Return one executable path below a virtualenv's ``bin`` directory."""
    return Path(venv) / "bin" / str(name)
