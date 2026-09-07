"""Command execution helpers shared by deployment frontends."""

from __future__ import annotations

import os
import pwd
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

type ErrorFactory = Callable[[str], Exception]
type ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
type Which = Callable[[str], str | None]
type EffectiveUid = Callable[[], int]
type PwdUidLookup = Callable[[int], Any]
type PwdNameLookup = Callable[[str], Any]


def quote_command(command: Sequence[object]) -> str:
    """Return a shell-style display string without executing through a shell."""
    return " ".join(shlex.quote(str(part)) for part in command)


def _print_error(message: str) -> None:
    print(message, file=sys.stderr)


def run_deploy_command(
    command: Sequence[object],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    service_user: str | None = None,
    capture: bool = False,
    check: bool = True,
    announce: bool = True,
    announce_prefix: str = "+",
    error_factory: ErrorFactory = RuntimeError,
    run_process: ProcessRunner = subprocess.run,
    which: Which = shutil.which,
    get_euid: EffectiveUid = os.geteuid,
    getpwuid: PwdUidLookup = pwd.getpwuid,
    getpwnam: PwdNameLookup = pwd.getpwnam,
    print_func: Callable[[str], None] = print,
    error_func: Callable[[str], None] = _print_error,
) -> subprocess.CompletedProcess[str]:
    """Execute one deployment command with common safety and diagnostics.

    ``service_user`` requests execution as that account.  Running as another
    account is only permitted when the current process is root; ``runuser`` is
    preferred and ``sudo`` is used as a fallback.  This prevents deployment
    frontends from silently creating runtime files as the wrong non-root user.
    """
    argv = [str(part) for part in command]
    if not argv:
        raise error_factory("cannot execute an empty command")

    if service_user:
        euid = get_euid()
        current_user = getpwuid(euid).pw_name
        if service_user != current_user:
            if euid != 0:
                raise error_factory(
                    f"run this command as {service_user!r} or as root; current user is {current_user!r}"
                )
            try:
                getpwnam(service_user)
            except KeyError as exc:
                raise error_factory(f"service user does not exist: {service_user}") from exc

            if which("runuser"):
                argv = ["runuser", "-u", service_user, "--", *argv]
            elif which("sudo"):
                argv = ["sudo", "-u", service_user, "--", *argv]
            else:
                raise error_factory("runuser/sudo is required to execute commands as the service user")

    if announce:
        print_func(f"{announce_prefix} {quote_command(argv)}")

    try:
        result = run_process(
            argv,
            check=False,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            capture_output=capture,
            text=True,
        )
    except OSError as exc:
        raise error_factory(f"could not execute {argv[0]}: {exc}") from exc

    if check and result.returncode != 0:
        if capture:
            if result.stdout.strip():
                print_func(result.stdout.rstrip())
            if result.stderr.strip():
                error_func(result.stderr.rstrip())
        raise error_factory(f"command failed with exit code {result.returncode}: {quote_command(argv)}")
    return result
