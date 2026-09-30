from __future__ import annotations

import asyncio
import stat
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from envs_xmpp_core.xmpp.omemo import (
    TaskLocalEncryptionMode,
    current_identity,
    decrypt_incoming_message,
    ensure_identity_metadata,
    extract_unusable_recipients,
    identity_metadata_path,
    message_has_omemo_payload,
    normalize_bare_jid,
    prepare_storage_file,
    read_identity_metadata,
    recipient_bare_jids,
    rotate_storage_identity,
    wait_for_omemo_ready,
)


class Message:
    def __init__(self, xml=None):
        self.xml = xml if xml is not None else ET.Element("message")


def test_task_local_encryption_mode_does_not_leak_to_child_task():
    async def run():
        mode = TaskLocalEncryptionMode("test-encrypted")
        token = mode.set(True)
        try:
            assert mode.get() is True
            async def child_value():
                await asyncio.sleep(0)
                return mode.get()
            child = asyncio.create_task(child_value())
            assert await child is None
        finally:
            mode.reset(token)
        assert mode.get() is None
    asyncio.run(run())


def test_storage_identity_lifecycle(tmp_path):
    storage = prepare_storage_file(tmp_path / "private" / "omemo.json")
    identity = {"jid": "bot@example.org", "resource": "service", "nick": "Bot"}
    backup, changed = ensure_identity_metadata(storage, identity, reset_on_change=True)
    assert backup is None and changed is True
    metadata = identity_metadata_path(storage)
    assert read_identity_metadata(metadata) == identity
    assert stat.S_IMODE(storage.stat().st_mode) == 0o600
    assert stat.S_IMODE(storage.parent.stat().st_mode) == 0o700

    storage.write_text('{"session": 1}\n', encoding="utf8")
    new_identity = {**identity, "jid": "new@example.org"}
    backup, changed = ensure_identity_metadata(
        storage, new_identity, reset_on_change=True, timestamp="20260928-120000"
    )
    assert changed is True
    assert backup is not None and backup.exists()
    assert read_identity_metadata(metadata) == new_identity


def test_rotate_storage_identity(tmp_path):
    storage = prepare_storage_file(tmp_path / "omemo.json")
    identity = {"jid": "bot@example.org", "resource": "service", "nick": "Bot"}
    ensure_identity_metadata(storage, identity, reset_on_change=True)
    storage.write_text('{"old": true}\n', encoding="utf8")
    storage_backup, metadata_backup = rotate_storage_identity(
        storage, identity, timestamp="20260928-120001"
    )
    assert storage_backup is not None and storage_backup.exists()
    assert metadata_backup is not None and metadata_backup.exists()
    assert not storage.exists()
    assert read_identity_metadata(identity_metadata_path(storage)) == identity


def test_jid_and_recipient_helpers():
    assert normalize_bare_jid("Alice@Example.org/Phone") == "alice@example.org"
    assert recipient_bare_jids(
        {"Alice@Example.org/Phone", "bot@example.org/service", "bad"},
        own_jid="bot@example.org/service",
    ) == {"alice@example.org", "bad", "bot@example.org"}
    assert extract_unusable_recipients(RuntimeError("missing 'Alice@Example.org/Phone'")) == {
        "alice@example.org"
    }


def test_message_payload_detection():
    encrypted = Message(ET.fromstring("<message><encrypted xmlns='urn:xmpp:omemo:2'/></message>"))
    plain = Message(ET.fromstring("<message><body>fallback</body></message>"))
    assert message_has_omemo_payload(encrypted) is True
    assert message_has_omemo_payload(plain) is False


@pytest.mark.asyncio
async def test_decrypt_is_fail_closed_and_successful():
    encrypted = Message(ET.fromstring("<message><encrypted xmlns='urn:xmpp:omemo:2'/></message>"))
    ready = asyncio.Event()
    ready.set()
    assert await decrypt_incoming_message(
        encrypted, enabled=False, plugin_map={}, ready_event=ready
    ) == (None, True, "disabled")

    decrypted = Message()
    plugin = SimpleNamespace(
        is_encrypted=lambda _msg: "urn:xmpp:omemo:2",
        decrypt_message=lambda _msg: asyncio.sleep(0, result=(decrypted, object())),
    )
    result = await decrypt_incoming_message(
        encrypted,
        enabled=True,
        plugin_map={"xep_0384": plugin},
        ready_event=ready,
    )
    assert result == (decrypted, True, None)


@pytest.mark.asyncio
async def test_wait_for_ready_timeout():
    assert await wait_for_omemo_ready(asyncio.Event(), enabled=True, timeout=0) is False
    assert await wait_for_omemo_ready(asyncio.Event(), enabled=False) is False


def test_current_identity_from_mapping():
    assert current_identity({"jid": " a@b ", "resource": " r ", "nick": " n "}) == {
        "jid": "a@b", "resource": "r", "nick": "n"
    }


def test_storage_helpers_cover_missing_metadata_and_no_reset(tmp_path):
    from envs_xmpp_core.xmpp.omemo import (
        backup_existing_path,
        backup_path,
        collect_storage_device_hints,
        format_device_ids,
        write_identity_metadata,
    )

    storage = prepare_storage_file(tmp_path / "state" / "omemo.json")
    storage.write_text('{"alice@example.org/device_id": 12345}\n', encoding="utf8")
    identity = {"jid": "bot@example.org", "resource": "svc", "nick": "Bot"}
    backup, changed = ensure_identity_metadata(storage, identity, reset_on_change=False)
    assert backup is None and changed is True
    assert storage.exists()

    metadata = identity_metadata_path(storage)
    other = {**identity, "resource": "other"}
    backup, changed = ensure_identity_metadata(storage, other, reset_on_change=False)
    assert backup is None and changed is True
    assert read_identity_metadata(metadata) == identity

    write_identity_metadata(metadata, other)
    assert read_identity_metadata(metadata) == other
    hints = collect_storage_device_hints(storage)
    assert hints == {"alice@example.org": {"12345"}}
    assert format_device_ids({"10", "2"}) == "2, 10"
    assert "exact device IDs" in format_device_ids(set())

    candidate = backup_path(storage, "stamp")
    candidate.write_text("occupied", encoding="utf8")
    assert backup_path(storage, "stamp").name.endswith("-1")
    moved = backup_existing_path(candidate, "next")
    assert moved is not None and moved.exists() and not candidate.exists()
    assert backup_existing_path(candidate, "none") is None


def test_prepare_storage_rejects_directory(tmp_path):
    with pytest.raises(RuntimeError, match="directory"):
        prepare_storage_file(tmp_path)


@pytest.mark.asyncio
async def test_decrypt_reason_matrix():
    encrypted = Message(ET.fromstring("<message><encrypted xmlns='urn:xmpp:omemo:2'/></message>"))
    ready = asyncio.Event()
    ready.set()

    assert (await decrypt_incoming_message(
        encrypted, enabled=True, plugin_map={}, ready_event=ready
    ))[2] == "plugin-unavailable"

    class InspectFail:
        def is_encrypted(self, _msg):
            raise RuntimeError("boom")

    assert (await decrypt_incoming_message(
        encrypted, enabled=True, plugin_map={"xep_0384": InspectFail()}, ready_event=ready
    ))[2] == "inspection-failed"

    class Unknown:
        def is_encrypted(self, _msg):
            return None

    assert (await decrypt_incoming_message(
        encrypted, enabled=True, plugin_map={"xep_0384": Unknown()}, ready_event=ready
    ))[2] == "unrecognized-payload"

    class DeviceFail:
        def is_encrypted(self, _msg):
            return "urn:xmpp:omemo:2"
        async def decrypt_message(self, _msg):
            raise RuntimeError("Bundle download failed")

    assert (await decrypt_incoming_message(
        encrypted, enabled=True, plugin_map={"xep_0384": DeviceFail()}, ready_event=ready
    ))[2] == "device-info-unavailable"

    class OtherFail(DeviceFail):
        async def decrypt_message(self, _msg):
            raise RuntimeError("unexpected")

    assert (await decrypt_incoming_message(
        encrypted, enabled=True, plugin_map={"xep_0384": OtherFail()}, ready_event=ready
    ))[2] == "decrypt-failed"


@pytest.mark.asyncio
async def test_encrypt_and_send_single_mapping_and_retry():
    from envs_xmpp_core.xmpp.omemo import encrypt_and_send

    class Stanza:
        def __init__(self):
            self.sent = 0
        def send(self):
            self.sent += 1

    direct = Stanza()
    class DirectPlugin:
        async def encrypt_message(self, _msg, recipients):
            assert recipients == "alice@example.org"
            return direct

    assert await encrypt_and_send(DirectPlugin(), object(), "alice@example.org", mto="alice@example.org") is direct
    assert direct.sent == 1

    good = Stanza()
    calls = []
    class GroupPlugin:
        async def encrypt_message(self, _msg, recipients):
            calls.append(set(recipients))
            if "bad@example.org" in recipients:
                raise RuntimeError("missing 'bad@example.org'")
            return ({"good@example.org": good}, [])

    result = await encrypt_and_send(
        GroupPlugin(), object(), {"bad@example.org", "good@example.org"}, mto="room@example.org"
    )
    assert result is good and good.sent == 1
    assert calls == [
        {"bad@example.org", "good@example.org"},
        {"good@example.org"},
    ]


@pytest.mark.asyncio
async def test_encrypt_and_send_empty_and_no_progress_failures():
    from envs_xmpp_core.xmpp.omemo import encrypt_and_send

    class EmptyPlugin:
        async def encrypt_message(self, _msg, _recipients):
            return None

    with pytest.raises(RuntimeError, match="produced no encrypted messages"):
        await encrypt_and_send(EmptyPlugin(), object(), "a@example.org", mto="a@example.org")

    class MissingPlugin:
        async def encrypt_message(self, _msg, _recipients):
            raise RuntimeError("missing 'someone-else@example.org'")

    with pytest.raises(RuntimeError, match="someone-else"):
        await encrypt_and_send(MissingPlugin(), object(), {"a@example.org"}, mto="room@example.org")


@pytest.mark.asyncio
async def test_encrypt_and_send_stamps_actual_encrypted_wire_stanza_with_durable_id():
    from envs_xmpp_core.xmpp.omemo import encrypt_and_send

    class WireMessage:
        def __init__(self):
            self.fields = {"origin_id": {}}
            self.sent = False

        def __getitem__(self, key):
            return self.fields[key]

        def __setitem__(self, key, value):
            self.fields[key] = value

        def send(self):
            self.sent = True

    encrypted_stanza = WireMessage()

    class Encryptor:
        async def encrypt_message(self, _msg, _recipients):
            return encrypted_stanza

    result = await encrypt_and_send(
        Encryptor(), object(), "alice@example.org",
        mto="alice@example.org", origin_id="persisted-123",
    )
    assert result is encrypted_stanza
    assert encrypted_stanza.sent
    assert encrypted_stanza["id"] == "persisted-123"
    assert encrypted_stanza["origin_id"]["id"] == "persisted-123"
