"""Contracts for bot-neutral outbound routing and at-least-once identities."""

from __future__ import annotations

import pytest

from envs_xmpp_core.xmpp import ReplyRoute
from envs_xmpp_core.xmpp.outbound import (
    can_persist_without_encryption_context,
    ensure_message_origin_id,
    plan_outbound_message,
    resolve_reply_encryption,
    transport_accepted,
)


def test_reply_route_overrides_destination_and_normalizes_wire_type() -> None:
    plan = plan_outbound_message(
        target="admin@example.org",
        message_type="groupchat",
        reply_route=ReplyRoute("room@conference.example.org/Alice", "normal"),
        inherited_encryption=True,
    )
    assert plan.route == ReplyRoute("room@conference.example.org/Alice", "chat")
    assert plan.encrypted is True
    assert plan.can_persist_without_encryption_context is False


def test_explicit_plaintext_and_durable_policy_are_separate() -> None:
    plan = plan_outbound_message(
        target=" room@conference.example.org ",
        message_type="GROUPCHAT",
        encrypted=False,
        inherited_encryption=True,
        durable=True,
    )
    assert plan.route == ReplyRoute("room@conference.example.org", "groupchat")
    assert plan.encrypted is False
    assert plan.durable is True
    assert plan.can_persist_without_encryption_context is True


def test_unset_encryption_does_not_assume_omemo_policy() -> None:
    plan = plan_outbound_message(target="admin@example.org", message_type="chat")
    assert plan.encrypted is None
    assert plan.can_persist_without_encryption_context is True


def test_stable_origin_id_is_applied_for_every_retry() -> None:
    first = {"origin_id": {}}
    second = {"origin_id": {}}
    stable = ensure_message_origin_id(first, "stable-replay-123", require_stanza_id=True)
    assert ensure_message_origin_id(second, stable, require_stanza_id=True) == stable
    for message in (first, second):
        assert message["id"] == stable
        assert message["origin_id"]["id"] == stable


def test_origin_id_falls_back_to_normal_stanza_id_without_plugin() -> None:
    message = {}
    assert ensure_message_origin_id(message, "stable-123") == "stable-123"
    assert message["id"] == "stable-123"


def test_durable_identity_rejects_unwritable_stanza() -> None:
    class Unwritable:
        def __setitem__(self, _key: str, _value: str) -> None:
            raise RuntimeError("no stanza interfaces")

        def __getitem__(self, _key: str) -> object:
            raise KeyError

    with pytest.raises(RuntimeError, match="stable id"):
        ensure_message_origin_id(Unwritable(), "stable-123", require_stanza_id=True)


def test_shared_encryption_decision_is_explicit_and_fail_closed_for_outbox() -> None:
    assert resolve_reply_encryption(None, True) is True
    assert resolve_reply_encryption(False, True) is False
    assert resolve_reply_encryption(True, False) is True
    assert can_persist_without_encryption_context(True) is False
    assert can_persist_without_encryption_context(None) is True


def test_transport_acceptance_only_rejects_explicit_false() -> None:
    assert transport_accepted(None) is True
    assert transport_accepted(object()) is True
    assert transport_accepted(False) is False
