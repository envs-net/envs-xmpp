from __future__ import annotations

import pytest

from envs_xmpp_core.config.schema import (
    MISSING,
    ConfigKeySpec,
    effective_value,
    expected_type_name,
    matches_expected_type,
    schema_defaults,
    schema_display_sections,
    schema_optional_types,
    schema_python_defaults,
    schema_python_key_map,
    schema_required_types,
    schema_runtime_writable_keys,
    schema_sample_defaults,
    schema_sensitive_keys,
    schema_startup_only_keys,
)

FIELDS = {
    "jid": ConfigKeySpec(
        MISSING,
        "JID",
        str,
        required=True,
        startup_only=True,
        section="Account",
        sample="bot@example.org",
    ),
    "password": ConfigKeySpec(
        MISSING,
        "PASSWORD",
        str,
        required=True,
        startup_only=True,
        sensitive=True,
        section="Account",
        sample="secret",
    ),
    "limit": ConfigKeySpec(
        10,
        "LIMIT",
        int,
        minimum=1,
        maximum=100,
        runtime_writable=True,
        section="Runtime",
    ),
}


def test_schema_derives_defaults_types_and_key_sets():
    assert schema_defaults(FIELDS) == {"limit": 10}
    assert schema_python_defaults(FIELDS) == {"LIMIT": 10}
    assert schema_sample_defaults(FIELDS) == {
        "jid": "bot@example.org",
        "password": "secret",
        "limit": 10,
    }
    assert schema_required_types(FIELDS) == {"jid": str, "password": str}
    assert schema_optional_types(FIELDS) == {"limit": int}
    assert schema_python_key_map(FIELDS) == {
        "JID": "jid",
        "PASSWORD": "password",
        "LIMIT": "limit",
    }
    assert schema_startup_only_keys(FIELDS) == {"jid", "password"}
    assert schema_startup_only_keys(FIELDS, python_keys=True) == {"JID", "PASSWORD"}
    assert schema_sensitive_keys(FIELDS, python_keys=True) == {"PASSWORD"}
    assert schema_runtime_writable_keys(FIELDS, python_keys=True) == ("LIMIT",)


def test_schema_display_sections_uses_declared_order():
    assert schema_display_sections(FIELDS, ("Account", "Runtime")) == (
        ("Account", ("JID", "PASSWORD")),
        ("Runtime", ("LIMIT",)),
    )
    with pytest.raises(RuntimeError, match="Config section order missing: Runtime"):
        schema_display_sections(FIELDS, ("Account",))


def test_schema_type_matching_rejects_bool_as_number():
    assert matches_expected_type(3, int)
    assert not matches_expected_type(True, int)
    assert matches_expected_type(1.5, (int, float))
    assert not matches_expected_type(True, (int, float))
    assert expected_type_name((int, float)) == "int or float"


def test_effective_value_uses_default_for_none_only_when_declared():
    field = ConfigKeySpec(10, "LIMIT", int)
    assert effective_value(None, field) == 10
    assert effective_value(5, field) == 5
    missing = ConfigKeySpec(MISSING, "JID", str)
    assert effective_value(None, missing) is None


def test_schema_python_sample_defaults_uses_python_names():
    from envs_xmpp_core.config.schema import schema_python_sample_defaults

    assert schema_python_sample_defaults(FIELDS) == {
        "JID": "bot@example.org",
        "PASSWORD": "secret",
        "LIMIT": 10,
    }


def test_schema_value_violation_reports_generic_constraints():
    from envs_xmpp_core.config.schema import schema_value_violation

    integer = ConfigKeySpec(10, "LIMIT", int, minimum=1, maximum=20)
    assert schema_value_violation(True, integer) == "type"
    assert schema_value_violation(0, integer) == "minimum"
    assert schema_value_violation(21, integer) == "maximum"
    assert schema_value_violation(10, integer) is None

    exclusive = ConfigKeySpec(1.0, "DELAY", (int, float), minimum=0, minimum_exclusive=True)
    assert schema_value_violation(0, exclusive) == "minimum_exclusive"

    choice = ConfigKeySpec("INFO", "LOG_LEVEL", str, choices=("INFO", "DEBUG"))
    assert schema_value_violation("", choice) == "empty"
    assert schema_value_violation("TRACE", choice) == "choice"
    assert schema_value_violation("DEBUG", choice) is None
    assert schema_value_violation(None, choice) is None
    assert schema_value_violation(None, choice, none_is_valid=False) == "type"
