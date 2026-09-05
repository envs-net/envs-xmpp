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
