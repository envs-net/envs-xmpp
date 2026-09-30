"""The contract vectors must describe the *actual* shared core behavior."""

from __future__ import annotations

import pytest

from envs_xmpp_core.config.operator import format_config_change_lines
from envs_xmpp_core.presentation import RoomView, room_view_with_lifecycle
from envs_xmpp_core.runtime.rooms import RoomLifecycleRegistry
from envs_xmpp_core.xmpp.messaging import message_context_from_stanza
from envs_xmpp_core.xmpp.omemo import require_omemo_bare_jid
from envs_xmpp_core.xmpp.outbound import plan_outbound_message
from envs_xmpp_ops.contract_cases import CONFIG_CASES, ENCRYPTION_CASES, INCOMING_CASES, ROOM_CASES


@pytest.mark.parametrize("case", INCOMING_CASES, ids=lambda case: case.name)
def test_incoming_contract(case) -> None:
    sender_bare, _, resource = case.sender.partition("/")
    stanza = {"from": case.sender, "type": case.message_type, "mucnick": resource, "body": "!status"}
    context = message_context_from_stanza(stanza, joined_rooms={"room@conference.example.test"})
    assert context.kind == case.expected_kind
    assert (context.reply_route.target, context.reply_route.message_type) == (
        case.reply_target, case.reply_type
    )
    assert context.is_room == case.public_command
    assert not context.real_jid  # A displayed nick must never become an authenticated identity.
    assert context.sender_bare == sender_bare


@pytest.mark.parametrize("case", ROOM_CASES, ids=lambda case: case.name)
def test_room_presence_contract(case) -> None:
    room = "room@conference.example.test"
    registry = RoomLifecycleRegistry()
    if case.lifecycle == "joining":
        registry.begin_join(room)
    elif case.lifecycle == "failed":
        registry.mark_failed(room)
    elif case.lifecycle == "deferred":
        registry.mark_deferred(room)
    elif case.lifecycle == "leaving":
        registry.begin_leave(room)
    elif case.lifecycle == "joined":
        registry.confirm_self_presence(room, "Bot")
    view = room_view_with_lifecycle(
        RoomView(jid=room, joined=case.presence_verified, unavailable=not case.presence_verified),
        registry.get(room),
    )
    assert view.state == case.expected_state
    assert view.needs_attention == case.needs_attention


@pytest.mark.parametrize("case", ENCRYPTION_CASES, ids=lambda case: case.name)
def test_reply_encryption_contract(case) -> None:
    plan = plan_outbound_message(
        target="alice@example.test", message_type="chat", encrypted=case.explicit,
        inherited_encryption=case.inherited, durable=True,
    )
    assert plan.encrypted is case.effective
    assert plan.can_persist_without_encryption_context is case.plaintext_persistence_allowed


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Alice@Example.test/Phone", "alice@example.test"),
        ("BOB@EXAMPLE.TEST", "bob@example.test"),
        ("", None),
        ("bad@ ", None),
        ("someone@ ", None),
    ],
)
def test_strict_omemo_identity_contract(value: str, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(ValueError, match="valid bare JID"):
            require_omemo_bare_jid(value)
    else:
        assert require_omemo_bare_jid(value) == expected


@pytest.mark.parametrize("case", CONFIG_CASES, ids=lambda case: case.name)
def test_config_contract_never_exposes_secrets(case) -> None:
    lines = format_config_change_lines(case.before, case.after)
    assert lines
    assert case.secret not in "\n".join(lines)
    assert "<redacted>" in "\n".join(lines)


@pytest.mark.parametrize(
    ("members", "expected"),
    [
        ((), "absent"),
        (("omemo",), "incomplete"),
        (("omemo_identity",), "incomplete"),
        (("omemo", "omemo_identity"), "complete"),
    ],
)
def test_backup_companion_contract(members, expected) -> None:
    from envs_xmpp_core.storage.backup import inspect_backup_companion_pair

    pair = inspect_backup_companion_pair(
        members, primary="omemo", companion="omemo_identity"
    )
    assert pair.state == expected
    assert pair.complete is (expected == "complete")


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("room invites accept", "room invite accept"),
        ("rtbl pub status", "rtbl publish status"),
        ("rooms list", "room list"),
    ],
)
def test_nested_help_alias_contract(topic: str, expected: str) -> None:
    from envs_xmpp_core.commands import resolve_help_topic

    aliases = {"room invites": "room invite", "rtbl pub": "rtbl publish", "rooms": "room"}
    assert resolve_help_topic(topic, aliases) == expected


def test_shared_omemo_logger_policy_preserves_debug_mode() -> None:
    import logging

    from envs_xmpp_core.xmpp.omemo import configure_omemo_dependency_logging

    root = logging.getLogger()
    logger_names = ("omemo", "omemo.core", "slixmpp_omemo", "slixmpp_omemo.xep_0384")
    loggers = [logging.getLogger(name) for name in logger_names]
    old_root = root.level
    old_levels = [logger.level for logger in loggers]
    try:
        root.setLevel(logging.WARNING)
        for logger in loggers:
            logger.setLevel(logging.INFO)
        configure_omemo_dependency_logging()
        assert all(logger.level == logging.ERROR for logger in loggers)
        root.setLevel(logging.DEBUG)
        for logger in loggers:
            logger.setLevel(logging.INFO)
        configure_omemo_dependency_logging()
        assert all(logger.level == logging.INFO for logger in loggers)
    finally:
        root.setLevel(old_root)
        for logger, old_level in zip(loggers, old_levels, strict=True):
            logger.setLevel(old_level)
