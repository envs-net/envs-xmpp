"""Virtual-environment bootstrap helpers."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path


def ensure_venv(path: str | Path, *, python: str = sys.executable) -> Path:
    """Create *path* as a virtual environment when missing."""
    target = Path(path)
    if not (target / "bin" / "python").exists():
        subprocess.run([python, "-m", "venv", str(target)], check=True)
    return target


def pip_install(venv: str | Path, *args: str) -> None:
    """Install packages into *venv* with its Python interpreter."""
    python = Path(venv) / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", *args], check=True)


def create_venv_if_missing(
    *,
    venv: Path,
    venv_python: Path,
    python: str,
    run_command: Callable[..., object],
    deployment: object,
) -> bool:
    """Create a deployment venv through the caller's command runner.

    Returns True when a venv was created and False when an existing venv was
    preserved.
    """
    if venv_python.is_file():
        print(f"KEEP existing virtualenv {venv}")
        return False
    print(f"CREATE virtualenv {venv}")
    run_command(
        [python, "-m", "venv", venv],
        deployment=deployment,
        as_service_user=True,
    )
    return True
