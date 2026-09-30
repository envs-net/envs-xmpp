from __future__ import annotations

from envs_xmpp_core.config.operator import (
    ConfigReloadReport,
    format_config_diff_entries,
    render_config_reload_report,
)


def test_config_reload_report_preserves_operator_sections_and_order() -> None:
    report = ConfigReloadReport(
        changes=("- LIMIT: 1 → 2",),
        warnings=("check room memberships",),
        runtime_actions=("refreshed caches",),
        restarted_tasks=("poller",),
        startup_changes=("JID: restart needed",),
    )
    assert render_config_reload_report(
        report, heading="Reloaded", no_changes="No changes",
    ) == (
        "Reloaded\n\n⚠️ Warnings:\n- check room memberships"
        "\n\nChanged:\n- LIMIT: 1 → 2"
        "\n\nApplied at runtime:\n- refreshed caches"
        "\n\nRestarted plugin tasks:\n- poller"
        "\n\nStartup-only changes detected and NOT applied. Restart the bot to activate:"
        "\nJID: restart needed"
    )


def test_config_reload_no_changes_omits_disabled_sections() -> None:
    assert render_config_reload_report(
        ConfigReloadReport(), heading="ok", no_changes="unchanged",
        show_runtime=False, show_tasks=False, show_startup=False,
    ) == "ok\n\nunchanged"


def test_config_diff_redacts_nested_values_and_skips_sensitive_names() -> None:
    rows = (
        ("PASSWORD", "super-secret", "default-secret"),
        ("LOG_LEVEL", "DEBUG", "INFO"),
        ("NESTED", {"api_token": "private", "enabled": True}, {}),
    )
    display = "\n".join(format_config_diff_entries(rows))
    assert "PASSWORD" not in display
    assert "super-secret" not in display
    assert "private" not in display
    assert "LOG_LEVEL" in display
    assert "DEBUG" in display
    assert "enabled" in display


def test_config_diff_empty_and_all_filtered() -> None:
    assert format_config_diff_entries([]) == []
    assert format_config_diff_entries([("PASSWORD", "secret", "other")]) == []


def test_config_change_lines_are_ordered_and_redacted() -> None:
    from envs_xmpp_core.config.operator import format_config_change_lines

    lines = format_config_change_lines(
        {"PASSWORD": "before-secret", "ENABLED": False},
        {"PASSWORD": "after-secret", "ENABLED": True},
        keys=("ENABLED", "PASSWORD"),
        display_key=str.lower,
    )
    assert lines[0] == "- enabled: False → True"
    assert "before-secret" not in "\n".join(lines)
    assert "after-secret" not in "\n".join(lines)
    assert "<redacted>" in lines[1]
