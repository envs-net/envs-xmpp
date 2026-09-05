"""Callback-driven service lifecycle helpers."""

from __future__ import annotations

from collections.abc import Callable


def stop_active_service(
    service: str,
    *,
    reason: str,
    is_active: Callable[[], bool],
    require_confirmation: Callable[[str], None],
    run_systemctl: Callable[[str, str], object],
) -> bool:
    """Stop an active service after explicit confirmation."""
    if not is_active():
        print(f"Service {service} is not active; no stop required.")
        return False
    require_confirmation(f"Stop {service} {reason}?")
    run_systemctl("stop", service)
    return True


def ask_start(
    service: str,
    *,
    exists: Callable[[], bool],
    is_active: Callable[[], bool],
    confirm: Callable[[str], bool],
    run_systemctl: Callable[[str, str], object],
) -> None:
    """Offer to start an installed inactive service."""
    if not exists():
        print(f"No installed systemd service {service}; not starting anything.")
        return
    if is_active():
        print(f"Service {service} is already active.")
        return
    if confirm(f"Start {service} now?"):
        run_systemctl("start", service)
        run_systemctl("is-active", service)
    else:
        print(f"LEAVE {service} stopped (operator choice)")
