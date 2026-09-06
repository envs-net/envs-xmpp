"""Declarative configuration schema primitives shared by envs.net XMPP bots.

The schema deliberately contains metadata only.  Applications keep ownership of
bot-specific validation (JIDs, filesystem layout, cross-field policy, ...),
while common type/range/lifecycle semantics live here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MISSING = object()

AcceptedType = type | tuple[type, ...]


@dataclass(frozen=True)
class ConfigKeySpec:
    """Describe one configuration setting.

    ``python_key`` is the name used in a Python config module.  The mapping key
    may be a normalized/internal name instead, which lets applications keep
    their existing public config syntax while sharing the same schema engine.
    """

    default: Any
    python_key: str
    accepted_type: AcceptedType
    startup_only: bool = False
    required: bool = False
    minimum: float | int | None = None
    maximum: float | int | None = None
    minimum_exclusive: bool = False
    choices: tuple[str, ...] = ()
    allow_empty: bool = False
    section: str = "Other"
    description: str = ""
    sensitive: bool = False
    sample: Any = MISSING
    runtime_writable: bool = False


def schema_defaults(fields: Mapping[str, ConfigKeySpec]) -> dict[str, Any]:
    """Return declared non-missing defaults keyed by schema name."""
    return {
        name: field.default
        for name, field in fields.items()
        if field.default is not MISSING
    }


def schema_python_defaults(fields: Mapping[str, ConfigKeySpec]) -> dict[str, Any]:
    """Return declared non-missing defaults keyed by Python config name."""
    return {
        field.python_key: field.default
        for field in fields.values()
        if field.default is not MISSING
    }


def schema_sample_defaults(fields: Mapping[str, ConfigKeySpec]) -> dict[str, Any]:
    """Return documented sample values keyed by schema name."""
    result: dict[str, Any] = {}
    for name, field in fields.items():
        value = field.sample if field.sample is not MISSING else field.default
        if value is not MISSING:
            result[name] = value
    return result


def schema_required_types(fields: Mapping[str, ConfigKeySpec]) -> dict[str, AcceptedType]:
    return {
        name: field.accepted_type
        for name, field in fields.items()
        if field.required
    }


def schema_optional_types(fields: Mapping[str, ConfigKeySpec]) -> dict[str, AcceptedType]:
    return {
        name: field.accepted_type
        for name, field in fields.items()
        if not field.required
    }


def schema_python_key_map(fields: Mapping[str, ConfigKeySpec]) -> dict[str, str]:
    """Map Python config names to schema names."""
    return {field.python_key: name for name, field in fields.items()}


def schema_startup_only_keys(
    fields: Mapping[str, ConfigKeySpec], *, python_keys: bool = False
) -> set[str]:
    return {
        field.python_key if python_keys else name
        for name, field in fields.items()
        if field.startup_only
    }


def schema_sensitive_keys(
    fields: Mapping[str, ConfigKeySpec], *, python_keys: bool = False
) -> set[str]:
    return {
        field.python_key if python_keys else name
        for name, field in fields.items()
        if field.sensitive
    }


def schema_runtime_writable_keys(
    fields: Mapping[str, ConfigKeySpec], *, python_keys: bool = False
) -> tuple[str, ...]:
    return tuple(
        field.python_key if python_keys else name
        for name, field in fields.items()
        if field.runtime_writable
    )


def schema_display_sections(
    fields: Mapping[str, ConfigKeySpec],
    section_order: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return Python config names grouped in a deliberate section order."""
    sections: dict[str, list[str]] = {}
    for field in fields.values():
        sections.setdefault(field.section, []).append(field.python_key)

    unknown_sections = set(sections) - set(section_order)
    if unknown_sections:
        names = ", ".join(sorted(unknown_sections))
        raise RuntimeError(f"Config section order missing: {names}")

    return tuple(
        (title, tuple(sections[title]))
        for title in section_order
        if title in sections
    )


def is_config_int(value: object) -> bool:
    """Return True for real integers, but not bool values."""
    return isinstance(value, int) and not isinstance(value, bool)


def expected_type_name(expected_type: AcceptedType) -> str:
    """Return a readable name for one or more accepted config types."""
    if isinstance(expected_type, tuple):
        return " or ".join(item.__name__ for item in expected_type)
    return expected_type.__name__


def matches_expected_type(value: object, expected_type: AcceptedType) -> bool:
    """Match config values without treating bool as int/float."""
    expected_types = (
        expected_type if isinstance(expected_type, tuple) else (expected_type,)
    )
    for typ in expected_types:
        if typ is int and is_config_int(value):
            return True
        if typ is float and isinstance(value, float) and not isinstance(value, bool):
            return True
        if typ is bool and isinstance(value, bool):
            return True
        if typ not in {int, float, bool} and isinstance(value, typ):
            return True
    return False


def effective_value(value: object, field: ConfigKeySpec) -> object:
    """Apply the common ``None means use the declared default`` convention."""
    if value is None and field.default is not MISSING:
        return field.default
    return value
