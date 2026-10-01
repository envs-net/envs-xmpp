"""Bound deployment frontend operations shared by envs.net bots.

The low-level helpers in :mod:`envs_xmpp_ops` stay independently reusable.
This module binds them to one consumer repository's small policy surface so
bot deployment scripts do not need to repeat the same adapter functions.
"""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol

from .accounts import account_exists
from .dependency_drift import (
    DependencyDriftReport,
    inspect_dependency_drift,
    require_clean_dependency_drift,
)
from .git import (
    describe_revision,
    head_is_detached,
    prepare_release_target,
    release_target_relation,
    require_clean_tracked_tree,
)
from .interaction import confirm, require_confirmation
from .process import run_deploy_command
from .service import ask_start, stop_active_service
from .systemd import service_active, systemctl_exists, systemd_property
from .venv import create_venv_if_missing, install_editable_checkout

type ErrorFactory = Callable[[str], Exception]


class FrontendDeployment(Protocol):
    """Structural deployment target required by :class:`DeploymentFrontend`."""

    root: Path
    venv: Path
    service: str
    service_user: str
    python: str

    @property
    def pip(self) -> Path: ...

    @property
    def venv_python(self) -> Path: ...

    @property
    def environment(self) -> dict[str, str]: ...


@dataclass(frozen=True, slots=True)
class DeploymentFrontend:
    """Bind common deployment operations to one bot frontend.

    Consumer repositories keep their declarative paths, install/update plans,
    systemd-unit rendering, and application-specific validation.  This adapter
    centralizes the repeated glue that binds those frontends to the shared
    process, Git, systemd, virtualenv, confirmation, and dependency-drift
    primitives.
    """

    project_name: str
    release_remote_environment: str
    error_factory: ErrorFactory = RuntimeError
    cancelled_error_factory: ErrorFactory = RuntimeError
    announce_prefix: str = "+"
    default_cwd_to_deployment_root: bool = False
    service_active_capture: bool = False
    supported_python_minors: tuple[int, ...] = (12, 13, 14)

    def run(
        self,
        command: Sequence[object],
        *,
        deployment: FrontendDeployment | None = None,
        as_service_user: bool = False,
        capture: bool = False,
        check: bool = True,
        cwd: Path | None = None,
        announce: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Execute one deployment command using this frontend's policy."""
        resolved_cwd = cwd
        if resolved_cwd is None and self.default_cwd_to_deployment_root and deployment is not None:
            resolved_cwd = deployment.root
        return run_deploy_command(
            command,
            cwd=resolved_cwd,
            env=deployment.environment if deployment is not None else None,
            service_user=(
                deployment.service_user
                if as_service_user and deployment is not None
                else None
            ),
            capture=capture,
            check=check,
            announce=announce,
            announce_prefix=self.announce_prefix,
            error_factory=self.error_factory,
        )

    def git(
        self,
        deployment: FrontendDeployment,
        *args: str,
        capture: bool = False,
        check: bool = True,
        announce: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run Git in the deployment checkout as the service account."""
        return self.run(
            ["git", *args],
            deployment=deployment,
            as_service_user=True,
            capture=capture,
            check=check,
            cwd=deployment.root,
            announce=announce,
        )

    def confirm(self, prompt: str) -> bool:
        """Ask for an explicit operator confirmation."""
        return confirm(prompt, input_func=input)

    def require_confirmation(self, prompt: str) -> None:
        """Require an operator confirmation using the frontend cancellation type."""
        require_confirmation(
            prompt,
            confirm_func=self.confirm,
            error_factory=self.cancelled_error_factory,
        )

    def account_exists(self, user: str) -> bool:
        """Return whether a local service account exists."""
        return account_exists(user, getpwnam=pwd.getpwnam)

    def require_service_account(self, deployment: FrontendDeployment) -> None:
        """Require the configured local service account to exist."""
        if not self.account_exists(deployment.service_user):
            raise self.error_factory(
                f"service user {deployment.service_user!r} does not exist; "
                "create it manually or use --user"
            )

    def systemd_property(self, service: str, prop: str) -> str:
        """Read one systemd property using the live subprocess runner."""
        return systemd_property(service, prop, run_process=subprocess.run)

    def systemctl_exists(self, deployment: FrontendDeployment) -> bool:
        """Return whether deployment.service is installed in systemd."""
        return systemctl_exists(
            deployment.service,
            run_command=self.run,
            which=shutil.which,
        )

    def service_active(self, deployment: FrontendDeployment) -> bool:
        """Return whether deployment.service is currently active."""
        return service_active(
            deployment.service,
            run_command=self.run,
            which=shutil.which,
            capture=self.service_active_capture,
        )

    def stop_active_service(self, deployment: FrontendDeployment, *, reason: str) -> bool:
        """Stop an active service after explicit confirmation."""
        return stop_active_service(
            deployment.service,
            reason=reason,
            is_active=partial(self.service_active, deployment),
            require_confirmation=self.require_confirmation,
            run_systemctl=lambda action, service: self.run(["systemctl", action, service]),
        )

    def ask_start(self, deployment: FrontendDeployment) -> None:
        """Offer to start an installed inactive service."""
        ask_start(
            deployment.service,
            exists=partial(self.systemctl_exists, deployment),
            is_active=partial(self.service_active, deployment),
            confirm=self.confirm,
            run_systemctl=lambda action, service: self.run(["systemctl", action, service]),
        )

    def create_venv_if_missing(self, deployment: FrontendDeployment) -> None:
        """Create the deployment virtualenv when its Python is missing."""
        create_venv_if_missing(
            venv=deployment.venv,
            venv_python=deployment.venv_python,
            python=deployment.python,
            run_command=self.run,
            deployment=deployment,
        )

    def venv_version(self, deployment: FrontendDeployment) -> tuple[int, int]:
        """Return the deployment virtualenv's Python ``(major, minor)``."""
        if not deployment.venv_python.is_file():
            raise self.error_factory(f"virtualenv Python not found: {deployment.venv_python}")
        result = self.run(
            [
                deployment.venv_python,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            deployment=deployment,
            capture=True,
            announce=False,
        )
        try:
            major, minor = result.stdout.strip().split(".", 1)
            return int(major), int(minor)
        except (AttributeError, TypeError, ValueError) as exc:
            raise self.error_factory("could not determine virtualenv Python version") from exc

    def constraint_file(self, deployment: FrontendDeployment) -> Path:
        """Return the reviewed constraint snapshot for the deployment Python."""
        major, minor = self.venv_version(deployment)
        if major != 3 or minor not in set(self.supported_python_minors):
            supported = "/".join(f"3.{value}" for value in self.supported_python_minors)
            raise self.error_factory(
                f"unsupported Python version {major}.{minor}; "
                f"{self.project_name} supports Python {supported}"
            )
        path = deployment.root / f"constraints/python3{minor}.txt"
        if not path.is_file():
            raise self.error_factory(f"constraint snapshot missing: {path}")
        return path

    def install_dependencies(self, deployment: FrontendDeployment) -> None:
        """Install the checkout editable under its reviewed constraint snapshot."""
        install_editable_checkout(
            pip=deployment.pip,
            root=deployment.root,
            constraints=self.constraint_file(deployment),
            run_command=self.run,
            deployment=deployment,
        )

    def dependency_drift(self, deployment: FrontendDeployment) -> DependencyDriftReport:
        """Compare installed runtime dependencies with reviewed constraints."""
        if not deployment.venv_python.is_file():
            raise self.error_factory(f"virtualenv Python not found: {deployment.venv_python}")
        try:
            return inspect_dependency_drift(
                deployment.root,
                deployment.venv_python,
                self.constraint_file(deployment),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise self.error_factory(f"could not inspect runtime dependency drift: {exc}") from exc

    def require_clean_dependency_drift(self, deployment: FrontendDeployment) -> None:
        """Require the runtime dependency set to match reviewed constraints."""
        require_clean_dependency_drift(
            self.dependency_drift(deployment),
            error_factory=self.error_factory,
        )

    def current_revision(self, deployment: FrontendDeployment) -> str:
        """Return the operator-facing current Git revision."""
        return describe_revision(partial(self.git, deployment))

    def head_is_detached(self, deployment: FrontendDeployment) -> bool:
        """Return whether the checkout is detached."""
        return head_is_detached(
            partial(self.git, deployment),
            error_factory=self.error_factory,
        )

    def require_clean_tracked_tree(self, deployment: FrontendDeployment) -> None:
        """Reject tracked checkout modifications before update."""
        require_clean_tracked_tree(
            partial(self.git, deployment),
            error_factory=self.error_factory,
        )

    def prepare_release_target(
        self,
        deployment: FrontendDeployment,
        requested_tag: str | None,
    ) -> tuple[str, str]:
        """Refresh release metadata and return ``(remote, stable_tag)``."""
        return prepare_release_target(
            partial(self.git, deployment),
            requested_tag,
            configured_remote=os.environ.get(self.release_remote_environment),
            error_factory=self.error_factory,
        )

    def target_relation(self, deployment: FrontendDeployment, target: str) -> str:
        """Classify a target tag relative to the current checkout."""
        return release_target_relation(
            partial(self.git, deployment),
            target,
            error_factory=self.error_factory,
        )
