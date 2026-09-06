from __future__ import annotations

from envs_xmpp_core.config.changes import (
    ConfigValueChange,
    config_value_changes,
    flatten_config_value,
    flattened_config_value_changes,
)


def test_config_value_changes_is_deterministic_without_explicit_keys():
    assert config_value_changes(
        {"z": 1, "a": 1},
        {"z": 2, "a": 1, "m": 3},
    ) == (
        ConfigValueChange("m", None, 3),
        ConfigValueChange("z", 1, 2),
    )


def test_config_value_changes_preserves_explicit_order_and_deduplicates_keys():
    assert config_value_changes(
        {"a": 1, "b": 2},
        {"a": 3, "b": 4},
        keys=("b", "a", "b"),
    ) == (
        ConfigValueChange("b", 2, 4),
        ConfigValueChange("a", 1, 3),
    )


def test_flatten_config_value_uses_dotted_sorted_leaf_names():
    assert flatten_config_value(
        "IDLERPG",
        {"z": 1, "nested": {"b": 2, "a": 1}},
    ) == (
        ("IDLERPG.nested.a", 1),
        ("IDLERPG.nested.b", 2),
        ("IDLERPG.z", 1),
    )


def test_flattened_config_value_changes_reports_only_changed_leaves():
    assert flattened_config_value_changes(
        "DUCKS",
        {"spawn": 20, "nested": {"enabled": True}},
        {"spawn": 10, "nested": {"enabled": True, "limit": 5}},
    ) == (
        ConfigValueChange("DUCKS.nested.limit", None, 5),
        ConfigValueChange("DUCKS.spawn", 20, 10),
    )
