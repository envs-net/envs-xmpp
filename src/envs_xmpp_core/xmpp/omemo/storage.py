"""Bot-neutral private OMEMO storage and identity metadata helpers."""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def identity_metadata_path(storage_path: Path) -> Path:
    """Return the identity metadata file paired with *storage_path*."""
    if storage_path.suffix:
        return storage_path.with_name(f"{storage_path.stem}.identity.json")
    return storage_path.with_name(f"{storage_path.name}.identity.json")


def current_identity(config: Mapping[str, Any]) -> dict[str, str]:
    """Return normalized JID/resource/nick identity metadata."""
    return {
        "jid": str(config.get("jid") or "").strip(),
        "resource": str(config.get("resource") or "").strip(),
        "nick": str(config.get("nick") or "").strip(),
    }


def read_identity_metadata(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"OMEMO identity metadata is not an object: {path}")
    return {
        "jid": str(data.get("jid", "")).strip(),
        "resource": str(data.get("resource", "")).strip(),
        "nick": str(data.get("nick", "")).strip(),
    }


def ensure_private_directory(path: Path) -> Path:
    path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    os.chmod(path, PRIVATE_DIRECTORY_MODE)
    return path


def write_identity_metadata(path: Path, identity: Mapping[str, object]) -> None:
    ensure_private_directory(path.parent)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf8") as handle:
        json.dump({key: str(value or "").strip() for key, value in identity.items()}, handle, sort_keys=True)
        handle.write("\n")
    os.chmod(tmp_path, PRIVATE_FILE_MODE)
    tmp_path.replace(path)
    os.chmod(path, PRIVATE_FILE_MODE)


def backup_path(path: Path, timestamp: str) -> Path:
    candidate = path.with_name(f"{path.name}.bak-{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak-{timestamp}-{counter}")
        counter += 1
    return candidate


def backup_existing_path(path: Path, timestamp: str) -> Path | None:
    if not path.exists():
        return None
    backup = backup_path(path, timestamp)
    shutil.move(str(path), str(backup))
    os.chmod(backup, PRIVATE_FILE_MODE)
    return backup


def prepare_storage_file(path: Path) -> Path:
    """Create and secure a JSON OMEMO storage file."""
    path = Path(path).expanduser()
    if not str(path).strip():
        raise RuntimeError("OMEMO storage path must not be empty")
    ensure_private_directory(path.parent)
    if path.exists():
        if path.is_dir():
            raise RuntimeError(f"OMEMO storage path is a directory: {path}")
        os.chmod(path, PRIVATE_FILE_MODE)
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf8") as handle:
            handle.write("{}\n")
    return path


def ensure_identity_metadata(
    storage_path: Path,
    identity: Mapping[str, object],
    *,
    reset_on_change: bool,
    timestamp: str | None = None,
) -> tuple[Path | None, bool]:
    """Ensure storage is tied to *identity*.

    Returns ``(storage_backup, changed)``.  When identity changed and
    ``reset_on_change`` is enabled both storage and metadata are rotated.
    """
    storage_path = Path(storage_path)
    metadata_path = identity_metadata_path(storage_path)
    normalized = {key: str(identity.get(key, "") or "").strip() for key in ("jid", "resource", "nick")}
    previous = read_identity_metadata(metadata_path)

    if previous is None:
        storage_backup = None
        if reset_on_change and storage_path.exists() and storage_path.is_file():
            try:
                content = storage_path.read_text(encoding="utf8").strip()
            except UnicodeDecodeError:
                content = "<binary>"
            if content and content != "{}":
                stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
                storage_backup = backup_existing_path(storage_path, stamp)
        write_identity_metadata(metadata_path, normalized)
        return storage_backup, True

    if previous == normalized:
        return None, False
    if not reset_on_change:
        return None, True

    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    storage_backup = backup_existing_path(storage_path, stamp)
    backup_existing_path(metadata_path, stamp)
    write_identity_metadata(metadata_path, normalized)
    return storage_backup, True


def rotate_storage_identity(
    storage_path: Path,
    identity: Mapping[str, object],
    *,
    timestamp: str | None = None,
) -> tuple[Path | None, Path | None]:
    """Rotate OMEMO storage and metadata, then write fresh identity metadata."""
    storage_path = Path(storage_path)
    metadata_path = identity_metadata_path(storage_path)
    stamp = timestamp or time.strftime("%Y%m%d-%H%M%S")
    storage_backup = backup_existing_path(storage_path, stamp)
    metadata_backup = backup_existing_path(metadata_path, stamp)
    write_identity_metadata(metadata_path, identity)
    return storage_backup, metadata_backup


def collect_storage_device_hints(storage_path: Path) -> dict[str, set[str]]:
    """Best-effort extract JID/device-id hints from an OMEMO JSON store."""
    import re

    path = Path(storage_path).expanduser()
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf8") or "{}")
    except Exception:  # noqa: BLE001 - malformed optional storage is treated as no hints
        return {}

    devices: dict[str, set[str]] = {}
    jid_re = re.compile(r"([A-Za-z0-9_.%+\-]+@[A-Za-z0-9.\-]+)")
    device_key_re = re.compile(r"(?:^|[_\-:./])(?:device[_\-]?id|device|dev)(?:$|[_\-:./])", re.IGNORECASE)
    device_with_id_re = re.compile(r"(?:device[_\-]?id|device|dev)[^0-9]{0,8}([0-9]{3,12})", re.IGNORECASE)

    def add_device(jid: str | None, value: Any) -> None:
        if not jid or isinstance(value, bool):
            return
        text = str(value).strip() if isinstance(value, (int, str)) else ""
        if text.isdigit() and 0 < int(text) < 10_000_000_000:
            devices.setdefault(jid, set()).add(text)

    def walk(obj: Any, context_jid: str | None = None) -> None:
        if isinstance(obj, dict):
            local_jid = context_jid
            for key, value in obj.items():
                key_text = str(key)
                jid_match = jid_re.search(key_text)
                if jid_match:
                    local_jid = jid_match.group(1).lower()
                    devices.setdefault(local_jid, set())
                keyed_device = device_with_id_re.search(key_text)
                if keyed_device and local_jid:
                    add_device(local_jid, keyed_device.group(1))
                elif device_key_re.search(key_text) and local_jid:
                    add_device(local_jid, value)
                walk(value, local_jid)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, context_jid)
        elif isinstance(obj, str):
            jid_match = jid_re.search(obj)
            if jid_match:
                devices.setdefault(jid_match.group(1).lower(), set())
            dev_match = device_with_id_re.search(obj)
            if dev_match and context_jid:
                add_device(context_jid, dev_match.group(1))

    walk(data)
    return devices


def format_device_ids(ids: set[str], *, limit: int = 12) -> str:
    """Render stable local OMEMO device-id hints."""
    numeric = sorted(int(value) for value in ids if str(value).isdigit())
    if not numeric:
        return "storage entry found, exact device IDs not visible"
    shown = [str(value) for value in numeric[:limit]]
    suffix = "" if len(numeric) <= limit else f", … ({len(numeric)} hints)"
    return f"{', '.join(shown)}{suffix}"


__all__ = [
    "PRIVATE_DIRECTORY_MODE",
    "PRIVATE_FILE_MODE",
    "backup_existing_path",
    "backup_path",
    "collect_storage_device_hints",
    "current_identity",
    "ensure_identity_metadata",
    "ensure_private_directory",
    "format_device_ids",
    "identity_metadata_path",
    "prepare_storage_file",
    "read_identity_metadata",
    "rotate_storage_identity",
    "write_identity_metadata",
]
