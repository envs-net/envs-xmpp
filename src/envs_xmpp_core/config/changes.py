"""Generic configuration change and diff primitives.

The helpers in this module intentionally operate on plain mappings.  They do
not know about bot-specific display formatting, validation policy or reload
behaviour; applications keep those concerns while sharing one implementation
for detecting and flattening value changes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConfigValueChange:
    """One changed configuration value."""

    key: str
    before: object
    after: object


def config_value_changes(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    keys: Iterable[str] | None = None,
) -> tuple[ConfigValueChange, ...]:
    """Return changed values, preserving an explicit key order when supplied.

    Without ``keys`` the union of both mappings is sorted for deterministic
    output.  Missing values intentionally behave like ``Mapping.get`` and are
    therefore represented as ``None``; this matches the existing bot-facing
    config diff/reload semantics.
    """

    ordered_keys = (
        sorted(set(before) | set(after))
        if keys is None
        else list(dict.fromkeys(keys))
    )

    return tuple(
        ConfigValueChange(key, before.get(key), after.get(key))
        for key in ordered_keys
        if before.get(key) != after.get(key)
    )


def flatten_config_value(name: str, value: object) -> tuple[tuple[str, object], ...]:
    """Flatten nested mappings into deterministic dotted configuration names."""

    if not isinstance(value, Mapping):
        return ((name, value),)

    flattened: list[tuple[str, object]] = []
    for key in sorted(value, key=str):
        child_name = f"{name}.{key}"
        child_value: Any = value[key]
        if isinstance(child_value, Mapping):
            flattened.extend(flatten_config_value(child_name, child_value))
        else:
            flattened.append((child_name, child_value))
    return tuple(flattened)


def flattened_config_value_changes(
    name: str,
    before: object,
    after: object,
) -> tuple[ConfigValueChange, ...]:
    """Return leaf-level changes for one possibly nested config value."""

    before_items = dict(flatten_config_value(name, before))
    after_items = dict(flatten_config_value(name, after))
    return config_value_changes(before_items, after_items)
