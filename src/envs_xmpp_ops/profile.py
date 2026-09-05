"""Declarative deployment profiles."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DeploymentProfile:
    app_name: str
    executable: str
    service_name: str
    config_environment: str
    default_config: str
    default_data: str
    service_user: str
    service_group: str
    venv_name: str = ".venv"
