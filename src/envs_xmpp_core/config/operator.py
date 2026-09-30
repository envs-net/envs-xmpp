"""Bot-neutral, read-only operator presentations for config changes and reloads.

Rendering accepts *already validated* changes; it must never be used to bypass
application-specific validation, file transactions, or startup-only policy.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from envs_xmpp_core.security import is_secret_key, redact_named


@dataclass(frozen=True, slots=True)
class ConfigReloadReport:
    """Structured post-validation reload diagnostics (no raw config values)."""

    changes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    runtime_actions: tuple[str, ...] = ()
    restarted_tasks: tuple[str, ...] = ()
    startup_changes: tuple[str, ...] = ()


def render_config_reload_report(
    report: ConfigReloadReport,
    *,
    heading: str,
    no_changes: str,
    warnings_heading: str = "⚠️ Warnings:",
    changes_heading: str = "Changed:",
    runtime_heading: str = "Applied at runtime:",
    tasks_heading: str = "Restarted plugin tasks:",
    startup_heading: str = "Startup-only changes detected and NOT applied. Restart the bot to activate:",
    show_warnings: bool = True,
    show_runtime: bool = True,
    show_tasks: bool = True,
    show_startup: bool = True,
) -> str:
    """Render one deterministic report, preserving a caller's wording and policy.

    Inputs must contain only safe, already-redacted diagnostic lines.  Never
    pass raw secret-bearing config values or untrusted exception tracebacks.
    """

    lines = [heading]
    if show_warnings and report.warnings:
        lines.append("\n" + warnings_heading)
        lines.extend(f"- {warning}" for warning in report.warnings)
    if report.changes:
        lines.append("\n" + changes_heading)
        lines.extend(report.changes)
    else:
        lines.append("\n" + no_changes)
    if show_runtime and report.runtime_actions:
        lines.append("\n" + runtime_heading)
        lines.extend(f"- {action}" for action in report.runtime_actions)
    if show_tasks and report.restarted_tasks:
        lines.append("\n" + tasks_heading)
        lines.extend(f"- {task}" for task in report.restarted_tasks)
    if show_startup and report.startup_changes:
        lines.append("\n" + startup_heading)
        lines.extend(report.startup_changes)
    return "\n".join(lines)


def format_config_diff_entries(
    changes: Iterable[tuple[str, object, object]],
    *,
    format_value: Callable[[str, object], str] | None = None,
    hidden: Callable[[str], bool] = is_secret_key,
) -> list[str]:
    """Format default/current previews without printing secret-named settings.

    ``changes`` are (name, current, default) tuples.  Redaction is enforced
    before optional bot-specific rendering, including for nested values.
    """

    if format_value is None:
        format_value = lambda _name, value: repr(value)
    lines: list[str] = []
    for name, current, default in changes:
        if hidden(name):
            continue
        safe_current = redact_named(name, current)
        safe_default = redact_named(name, default)
        lines.extend((
            f"• {name}",
            f"  current: {format_value(name, safe_current)}",
            f"  default: {format_value(name, safe_default)}",
            "",
        ))
    if lines:
        lines.pop()
    return lines


def format_config_change_lines(
    before: dict[str, object],
    after: dict[str, object],
    *,
    keys: Iterable[str] | None = None,
    display_key: Callable[[str], str] = str,
) -> list[str]:
    """Render deterministic runtime-change lines with nested-secret redaction."""

    from .changes import config_value_changes

    return [
        f"- {display_key(change.key)}: "
        f"{redact_named(change.key, change.before)!r} → "
        f"{redact_named(change.key, change.after)!r}"
        for change in config_value_changes(before, after, keys=keys)
    ]
