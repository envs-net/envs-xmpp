"""Shared XMPP avatar/profile primitives.

The helpers in this module intentionally use duck typing instead of importing
Slixmpp.  That keeps :mod:`envs_xmpp_core` lightweight while still providing a
single implementation for the avatar semantics used by envs.net bots.
"""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png"})
_MEDIA_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
}
_SUFFIX_MEDIA_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
}


@dataclass(frozen=True, slots=True)
class AvatarPayload:
    """Normalized avatar bytes and the metadata required by XMPP avatar XEPs."""

    data: bytes
    media_type: str
    sha1: str

    @property
    def size(self) -> int:
        """Return the avatar payload size in bytes."""
        return len(self.data)

    def xep0084_metadata(self) -> dict[str, str | int]:
        """Return one XEP-0084 metadata item for this avatar."""
        return {
            "id": self.sha1,
            "type": self.media_type,
            "bytes": self.size,
        }


def avatar_sha1(data: bytes) -> str:
    """Return the SHA-1 hex digest required by XEP-0084 and XEP-0153."""
    return hashlib.sha1(data).hexdigest()


def normalize_avatar_media_type(
    media_type: str | None = None,
    *,
    path: str | Path | None = None,
) -> str:
    """Normalize and validate an avatar MIME type.

    PNG and JPEG are the common interoperable formats supported by the bots.
    If *media_type* is omitted, the type is derived from *path*.
    """
    normalized = str(media_type or "").strip().lower()
    if normalized:
        normalized = _MEDIA_TYPE_ALIASES.get(normalized, normalized)
    elif path is not None:
        normalized = _SUFFIX_MEDIA_TYPES.get(Path(path).suffix.lower(), "")

    if normalized not in _SUPPORTED_MEDIA_TYPES:
        raise ValueError("avatar must use image/png or image/jpeg")
    return normalized


def load_avatar_payload(
    path: str | Path,
    *,
    media_type: str | None = None,
) -> AvatarPayload:
    """Read and normalize one local avatar file."""
    avatar_path = Path(path)
    data = avatar_path.read_bytes()
    normalized_type = normalize_avatar_media_type(media_type, path=avatar_path)
    return AvatarPayload(
        data=data,
        media_type=normalized_type,
        sha1=avatar_sha1(data),
    )


async def publish_xep0084_avatar(xmpp: Any, payload: AvatarPayload) -> None:
    """Publish XEP-0084 avatar data and its metadata as one logical operation."""
    plugin = xmpp["xep_0084"]
    result = plugin.publish_avatar(payload.data)
    if inspect.isawaitable(result):
        await result

    metadata_result = plugin.publish_avatar_metadata([payload.xep0084_metadata()])
    if inspect.isawaitable(metadata_result):
        await metadata_result


async def cache_xep0153_hash(
    xmpp: Any,
    avatar_hash: str,
    *,
    jid: Any | None = None,
) -> bool:
    """Seed Slixmpp's XEP-0153 outgoing-presence hash cache.

    ``False`` means the cache could not be updated.  Callers should avoid
    advertising an XEP-0153 hash in that case because Slixmpp's outgoing
    presence filter can otherwise replace the explicit hash with an empty one.
    """
    try:
        plugin = xmpp["xep_0153"]
        api = getattr(plugin, "api", None)
        if api is None:
            return False
        setter = api["set_hash"]
        target = jid if jid is not None else xmpp.boundjid
        result = setter(target, args=avatar_hash)
        if inspect.isawaitable(result):
            result = await result
        return result is not False
    except (AttributeError, KeyError, TypeError, RuntimeError):
        return False


def xmpp_strict_active(xmpp: Any) -> bool:
    """Return whether an XMPP client explicitly reports an active stream.

    The helper deliberately does not guess ``True`` when a client exposes no
    connection state.  Production Slixmpp clients provide ``is_connected()``;
    the stricter fallback prevents detached presence stanzas from being sent
    during teardown or partial test doubles.
    """
    checker = getattr(xmpp, "is_connected", None)
    if callable(checker):
        try:
            return bool(checker())
        except (AttributeError, TypeError, RuntimeError):
            return False

    if hasattr(xmpp, "connected"):
        try:
            return bool(xmpp.connected)
        except (AttributeError, TypeError, RuntimeError):
            return False

    return False


def set_presence_avatar_hash(presence: Any, avatar_hash: str) -> None:
    """Attach one XEP-0153 ``photo`` hash to a presence stanza."""
    presence["vcard_temp_update"]["photo"] = avatar_hash
