"""Stable deployment tooling for envs.net XMPP bots."""

from envs_xmpp_core import __version__

from .dependency_drift import (
    DependencyDriftReport,
    DependencyVersion,
    inspect_dependency_drift,
)
from .deploy import DeploymentTarget
from .layout import (
    deployment_environment,
    resolve_environment_path,
    service_account,
    split_systemd_words,
    systemd_environment_value,
    systemd_exec_path,
    systemd_path_set,
    systemd_venv,
    venv_binary,
)
from .profile import DeploymentProfile

__all__ = [
    "DependencyDriftReport",
    "DependencyVersion",
    "DeploymentProfile",
    "DeploymentTarget",
    "__version__",
    "deployment_environment",
    "inspect_dependency_drift",
    "resolve_environment_path",
    "service_account",
    "split_systemd_words",
    "systemd_environment_value",
    "systemd_exec_path",
    "systemd_path_set",
    "systemd_venv",
    "venv_binary",
]
