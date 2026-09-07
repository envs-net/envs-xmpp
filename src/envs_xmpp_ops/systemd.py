"""systemd command and inspection helpers."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class UnitInstallResult:
    """Outcome of a preservation-first systemd unit installation."""

    created: bool
    reason: str


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)


def install_unit_if_missing(
    *,
    unit: Path,
    service: str,
    render_unit: Callable[[], str],
    service_exists: Callable[[], bool],
    confirm: Callable[[str], bool],
    run_command: CommandRunner,
    which: Callable[[str], str | None] = shutil.which,
    print_func: Callable[[str], None] = print,
    error_func: Callable[[str], None] = _print_error,
) -> UnitInstallResult:
    """Install a newly rendered unit without ever replacing an existing one.

    The caller owns unit rendering and service-specific policy.  This helper
    centralizes the shared preservation boundary: detect an existing file or
    loaded unit, ask before creation, use exclusive file creation, set mode
    ``0644``, optionally verify with ``systemd-analyze``, remove an invalid
    newly-created unit, and reload systemd only after successful installation.
    """
    if unit.exists() or service_exists():
        print_func(f"KEEP existing systemd service for {service}; it will not be replaced.")
        return UnitInstallResult(created=False, reason="existing")

    if not confirm(f"Install a new systemd unit at {unit}?"):
        print_func("SKIP systemd unit installation (operator choice)")
        return UnitInstallResult(created=False, reason="declined")

    rendered = render_unit()
    unit.parent.mkdir(parents=True, exist_ok=True)
    try:
        with unit.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    except FileExistsError:
        print_func(f"KEEP existing {unit}; it appeared before installation completed.")
        return UnitInstallResult(created=False, reason="appeared")

    unit.chmod(0o644)
    print_func(f"CREATE {unit}")
    if which("systemd-analyze"):
        try:
            run_command(["systemd-analyze", "verify", unit])
        except BaseException:
            unit.unlink(missing_ok=True)
            error_func(f"REMOVE invalid newly created unit {unit}")
            raise

    run_command(["systemctl", "daemon-reload"])
    return UnitInstallResult(created=True, reason="created")


def systemctl(*args: str) -> None:
    """Run systemctl and require success."""
    subprocess.run(["systemctl", *args], check=True)


def daemon_reload() -> None:
    systemctl("daemon-reload")


def restart(service_name: str) -> None:
    systemctl("restart", service_name)


def systemd_property(
    service: str,
    prop: str,
    *,
    run_process: ProcessRunner = subprocess.run,
) -> str:
    """Read one systemd property, returning an empty string on failure."""
    try:
        result = run_process(
            ["systemctl", "show", service, f"--property={prop}", "--value"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def systemctl_exists(
    service: str,
    *,
    run_command: CommandRunner,
    which: Callable[[str], str | None] = shutil.which,
) -> bool:
    """Return whether systemctl can load the service unit."""
    if not which("systemctl"):
        return False
    result = run_command(
        ["systemctl", "cat", service],
        check=False,
        capture=True,
        announce=False,
    )
    return result.returncode == 0


def service_active(
    service: str,
    *,
    run_command: CommandRunner,
    which: Callable[[str], str | None] = shutil.which,
    capture: bool = False,
) -> bool:
    """Return whether systemd reports the service active."""
    if not which("systemctl"):
        return False
    result = run_command(
        ["systemctl", "is-active", "--quiet", service],
        check=False,
        capture=capture,
        announce=False,
    )
    return result.returncode == 0
