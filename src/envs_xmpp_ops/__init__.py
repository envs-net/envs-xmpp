"""Stable deployment tooling for envs.net XMPP bots."""

from envs_xmpp_core import __version__

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
    "DeploymentProfile",
    "__version__",
    "deployment_environment",
    "resolve_environment_path",
    "service_account",
    "split_systemd_words",
    "systemd_environment_value",
    "systemd_exec_path",
    "systemd_path_set",
    "systemd_venv",
    "venv_binary",
]
