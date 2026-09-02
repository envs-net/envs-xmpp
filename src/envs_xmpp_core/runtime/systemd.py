"""Minimal systemd notification helpers without python-systemd."""
from __future__ import annotations

import logging
import os
import socket

log = logging.getLogger(__name__)


def sd_notify(payload: str) -> bool:
    address = os.environ.get("NOTIFY_SOCKET", "")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(payload.encode("utf-8"))
        return True
    except OSError:
        log.debug("systemd sd_notify failed", exc_info=True)
        return False
    finally:
        sock.close()


def systemd_watchdog_interval(default: float) -> float:
    """Return a heartbeat cadence safely below WATCHDOG_USEC."""
    try:
        watchdog_usec = int(os.environ.get("WATCHDOG_USEC", "0") or 0)
    except (TypeError, ValueError):
        watchdog_usec = 0
    if watchdog_usec <= 0:
        return max(0.1, float(default))
    watchdog_seconds = watchdog_usec / 1_000_000.0
    return max(0.1, min(float(default), watchdog_seconds / 2.0))
