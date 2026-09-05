"""systemd command and inspection helpers."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


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
