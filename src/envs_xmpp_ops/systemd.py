"""systemd command helpers."""

from __future__ import annotations

import subprocess


def systemctl(*args: str) -> None:
    subprocess.run(["systemctl", *args], check=True)


def daemon_reload() -> None:
    systemctl("daemon-reload")


def restart(service_name: str) -> None:
    systemctl("restart", service_name)
