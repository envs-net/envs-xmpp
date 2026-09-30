"""Stable, bot-neutral contract vectors for both XMPP consumers.

This is **test tooling**, not runtime policy. Both bot suites import the same
cases to catch adapter drift without making either bot depend on the other.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IncomingCase:
    name: str
    sender: str
    message_type: str
    expected_kind: str
    reply_target: str
    reply_type: str
    public_command: bool
    private_command: bool


INCOMING_CASES = (
    IncomingCase(
        "public-muc", "room@conference.example.test/Alice", "groupchat",
        "groupchat", "room@conference.example.test", "groupchat", True, False,
    ),
    IncomingCase(
        "muc-private-message", "room@conference.example.test/Alice", "chat",
        "muc-pm", "room@conference.example.test/Alice", "chat", False, True,
    ),
    IncomingCase(
        "direct-chat", "alice@example.test/Phone", "chat",
        "chat", "alice@example.test/Phone", "chat", False, True,
    ),
    IncomingCase(
        "ordinary-message", "alice@example.test/Phone", "normal",
        "chat", "alice@example.test/Phone", "chat", False, True,
    ),
)


@dataclass(frozen=True, slots=True)
class RoomCase:
    name: str
    lifecycle: str
    presence_verified: bool
    expected_state: str
    needs_attention: bool


ROOM_CASES = (
    RoomCase("joining", "joining", False, "joining", True),
    RoomCase("failed", "failed", False, "failed", True),
    RoomCase("deferred", "deferred", False, "deferred", True),
    RoomCase("intentional-leave", "leaving", False, "leaving", False),
    RoomCase("stale-confirmation", "joined", False, "attention", True),
    RoomCase("verified-presence", "joined", True, "joined", False),
)


@dataclass(frozen=True, slots=True)
class EncryptionCase:
    name: str
    explicit: bool | None
    inherited: bool | None
    effective: bool | None
    plaintext_persistence_allowed: bool


ENCRYPTION_CASES = (
    EncryptionCase("encrypted-command", None, True, True, False),
    EncryptionCase("plain-command", None, False, False, True),
    EncryptionCase("explicit-plain", False, True, False, True),
    EncryptionCase("explicit-encrypted", True, False, True, False),
    EncryptionCase("proactive", None, None, None, True),
)


@dataclass(frozen=True, slots=True)
class ConfigCase:
    name: str
    before: dict[str, object]
    after: dict[str, object]
    secret: str


CONFIG_CASES = (
    ConfigCase(
        "secret-setting", {"api_key": "old-plaintext-token"},
        {"api_key": "new-plaintext-token"}, "plaintext-token",
    ),
    ConfigCase(
        "nested-token", {"settings": {"token": "old-private-token", "enabled": False}},
        {"settings": {"token": "new-private-token", "enabled": True}}, "private-token",
    ),
)


__all__ = [
    "CONFIG_CASES", "ENCRYPTION_CASES", "INCOMING_CASES", "ROOM_CASES",
    "ConfigCase", "EncryptionCase", "IncomingCase", "RoomCase",
]
