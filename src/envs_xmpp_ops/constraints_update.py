"""Reproduce or explicitly refresh a project's reviewed Python dependency snapshot.

Run from a bot repository with the project's development environment activated.
Writes snapshots atomically, only after the target interpreter's full closure
has been checked using the current shared constraints checker.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


def _interpreter(version: str) -> str:
    """Honor the same interpreter overrides as the old shell entry point."""
    return os.environ.get(f"PYTHON{version.replace('.', '')}") or f"python{version}"


def update_constraints(version: str, *, refresh: bool = False, root: Path = Path(".")) -> Path:
    """Build and validate a lockfile without changing the old one on failure."""
    root = root.resolve()
    destination = root / "constraints" / f"python{version.replace('.', '')}.txt"
    if not refresh and not destination.is_file():
        raise FileNotFoundError(f"Audited snapshot not found: {destination}")

    with tempfile.TemporaryDirectory(prefix="envs-constraints-") as temporary:
        venv = Path(temporary) / "venv"
        subprocess.run([_interpreter(version), "-m", "venv", str(venv)], cwd=root, check=True)
        python = venv / "bin" / "python"
        install = [str(python), "-m", "pip", "install"]
        if not refresh:
            install.extend(["-c", str(destination)])
        install.extend(["-r", "requirements.txt", "-r", "requirements-dev.txt"])
        subprocess.run(install, cwd=root, check=True)
        freeze = subprocess.run(
            [str(python), "-m", "pip", "freeze", "--all"],
            cwd=root, check=True, capture_output=True, text=True,
        )
        pins = sorted(
            (line for line in freeze.stdout.splitlines()
             if line.strip() and not line.lower().startswith(("pip==", "setuptools==", "wheel=="))),
            key=str.casefold,
        )
        header = [f"# Fully resolved dependency snapshot for Python {version}."]
        if refresh:
            header.append(f"# Refreshed by scripts/update-constraints.sh {version} --refresh.")
        else:
            header.append(f"# Reproduced by scripts/update-constraints.sh {version}.")
        # The target venv may still have the latest *published* Core. Override its
        # import path with this working tree's shared checker during the audit.
        source_parent = str(Path(__file__).resolve().parent.parent)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [source_parent, env.get("PYTHONPATH", "")]))
        fd, pending_name = tempfile.mkstemp(prefix=f".python{version.replace('.', '')}.", suffix=".tmp", dir=destination.parent)
        pending = Path(pending_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("\n".join([*header, *pins, ""]))
            subprocess.run(
                [str(python), "-m", "envs_xmpp_ops.constraints", str(pending)],
                cwd=root, env=env, check=True,
            )
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", choices=("3.12", "3.13", "3.14"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    output = update_constraints(args.version, refresh=args.refresh)
    print(f"updated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
