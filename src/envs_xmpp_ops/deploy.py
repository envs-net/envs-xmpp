"""Shared high-level deployment path calculations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .profile import DeploymentProfile


@dataclass(frozen=True)
class DeploymentPaths:
    root: Path
    venv: Path
    config: Path
    data: Path


def resolve_paths(root: str | Path, profile: DeploymentProfile) -> DeploymentPaths:
    app_root = Path(root).resolve()
    return DeploymentPaths(
        root=app_root,
        venv=app_root / profile.venv_name,
        config=Path(profile.default_config),
        data=Path(profile.default_data),
    )
