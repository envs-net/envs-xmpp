"""Virtual-environment bootstrap helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def ensure_venv(path: str | Path, *, python: str = sys.executable) -> Path:
    target = Path(path)
    if not (target / "bin" / "python").exists():
        subprocess.run([python, "-m", "venv", str(target)], check=True)
    return target


def pip_install(venv: str | Path, *args: str) -> None:
    pip = Path(venv) / "bin" / "python"
    subprocess.run([str(pip), "-m", "pip", "install", *args], check=True)
