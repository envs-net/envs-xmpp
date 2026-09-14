"""Defensive stanza-plugin helpers."""

from __future__ import annotations

import inspect
from typing import Any


def safe_get_plugin(stanza: Any, plugin_name: str) -> Any | None:
    get_plugin = getattr(stanza, "get_plugin", None)
    if not callable(get_plugin):
        return None
    try:
        return get_plugin(plugin_name, check=True)
    except TypeError:
        try:
            return get_plugin(plugin_name)
        except Exception:  # noqa: BLE001 - defensive boundary around third-party stanza plugins
            return None
    except Exception:  # noqa: BLE001 - defensive boundary around third-party stanza plugins
        return None


def safe_plugin_value(plugin: Any, key: str) -> str:
    if plugin is None:
        return ""
    try:
        value = plugin.get(key)
    except Exception:  # noqa: BLE001 - plugin mappings may raise implementation-specific errors
        try:
            value = plugin[key]
        except Exception:  # noqa: BLE001 - plugin mappings may raise implementation-specific errors
            return ""
    return "" if value is None else str(value).strip()


async def maybe_await_result(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


def iq_error_condition(exc: BaseException | object) -> str:
    """Return a normalized IQ error condition without rendering the stanza."""
    condition = getattr(exc, "condition", None)
    if condition not in (None, ""):
        return str(condition).strip()

    iq = getattr(exc, "iq", None)
    try:
        error = iq["error"] if iq is not None else None
        if error is not None:
            value = error.get("condition") if hasattr(error, "get") else error["condition"]
            if value not in (None, ""):
                return str(value).strip()
    except Exception:  # noqa: BLE001 - third-party stanza mappings vary
        return ""
    return ""


def iq_error_text(exc: BaseException | object) -> str:
    """Return IQ error text without falling back to ``str(exc)``."""
    text = getattr(exc, "text", None)
    if text not in (None, ""):
        return str(text).strip()

    iq = getattr(exc, "iq", None)
    try:
        error = iq["error"] if iq is not None else None
        if error is not None:
            value = error.get("text") if hasattr(error, "get") else error["text"]
            if value not in (None, ""):
                return str(value).strip()
    except Exception:  # noqa: BLE001 - third-party stanza mappings vary
        return ""
    return ""


def iq_error_summary(exc: BaseException | object) -> str:
    """Return a compact stanza-safe summary for IQ timeout/error exceptions."""
    name = type(exc).__name__
    if name == "IqTimeout":
        return "IQ timeout"

    condition = iq_error_condition(exc)
    text = iq_error_text(exc)
    if condition or text or name == "IqError":
        detail = f"IQ error {condition or 'unknown'}"
        return f"{detail}: {text}" if text else detail

    return name or "IQ error"
