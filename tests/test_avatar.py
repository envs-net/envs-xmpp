from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from envs_xmpp_core.xmpp.avatar import (
    AvatarPayload,
    avatar_sha1,
    cache_xep0153_hash,
    load_avatar_payload,
    normalize_avatar_media_type,
    publish_xep0084_avatar,
    set_presence_avatar_hash,
    xmpp_strict_active,
)


def test_avatar_sha1_matches_xmpp_digest() -> None:
    data = b"avatar-bytes"
    assert avatar_sha1(data) == hashlib.sha1(data).hexdigest()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("image/png", "image/png"),
        ("IMAGE/JPEG", "image/jpeg"),
        ("image/jpg", "image/jpeg"),
        ("image/pjpeg", "image/jpeg"),
    ],
)
def test_normalize_avatar_media_type(value: str, expected: str) -> None:
    assert normalize_avatar_media_type(value) == expected


def test_normalize_avatar_media_type_from_path_and_rejects_unknown() -> None:
    assert normalize_avatar_media_type(path="avatar.jpg") == "image/jpeg"
    assert normalize_avatar_media_type(path="avatar.jpeg") == "image/jpeg"
    assert normalize_avatar_media_type(path="avatar.png") == "image/png"
    with pytest.raises(ValueError, match="image/png or image/jpeg"):
        normalize_avatar_media_type(path="avatar.webp")


def test_load_avatar_payload(tmp_path: Path) -> None:
    path = tmp_path / "avatar.jpg"
    path.write_bytes(b"jpeg-data")

    payload = load_avatar_payload(path)

    assert payload == AvatarPayload(
        data=b"jpeg-data",
        media_type="image/jpeg",
        sha1=hashlib.sha1(b"jpeg-data").hexdigest(),
    )
    assert payload.size == len(b"jpeg-data")
    assert payload.xep0084_metadata() == {
        "id": payload.sha1,
        "type": "image/jpeg",
        "bytes": len(b"jpeg-data"),
    }


@pytest.mark.asyncio
async def test_publish_xep0084_avatar_publishes_data_and_metadata() -> None:
    calls: list[tuple[str, object]] = []

    class Plugin:
        async def publish_avatar(self, data: bytes) -> None:
            calls.append(("data", data))

        async def publish_avatar_metadata(self, metadata: object) -> None:
            calls.append(("metadata", metadata))

    class Client(dict):
        pass

    client = Client(xep_0084=Plugin())
    payload = AvatarPayload(b"data", "image/png", "abc123")

    await publish_xep0084_avatar(client, payload)

    assert calls == [
        ("data", b"data"),
        (
            "metadata",
            [{"id": "abc123", "type": "image/png", "bytes": 4}],
        ),
    ]


@pytest.mark.asyncio
async def test_cache_xep0153_hash_supports_async_and_failure() -> None:
    calls: list[tuple[object, str]] = []

    async def set_hash(jid: object, *, args: str) -> None:
        calls.append((jid, args))

    boundjid = SimpleNamespace(bare="bot@example.org")

    class Client(dict):
        def __init__(self) -> None:
            super().__init__(xep_0153=SimpleNamespace(api={"set_hash": set_hash}))
            self.boundjid = boundjid

    client = Client()
    assert await cache_xep0153_hash(client, "abc123") is True
    assert calls == [(boundjid, "abc123")]

    client["xep_0153"] = SimpleNamespace()
    assert await cache_xep0153_hash(client, "abc123") is False


def test_xmpp_strict_active_uses_explicit_connection_state() -> None:
    assert xmpp_strict_active(SimpleNamespace(is_connected=lambda: True)) is True
    assert xmpp_strict_active(SimpleNamespace(is_connected=lambda: False)) is False
    assert xmpp_strict_active(SimpleNamespace(connected=True)) is True
    assert xmpp_strict_active(SimpleNamespace()) is False


def test_set_presence_avatar_hash_uses_stanza_plugin() -> None:
    values: dict[str, str] = {}

    class Update:
        def __setitem__(self, key: str, value: str) -> None:
            values[key] = value

    class Presence:
        def __getitem__(self, key: str) -> Update:
            assert key == "vcard_temp_update"
            return Update()

    set_presence_avatar_hash(Presence(), "abc123")
    assert values == {"photo": "abc123"}
