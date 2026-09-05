"""ZIP archive safety and streaming primitives."""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

_CHUNK_SIZE = 1024 * 1024


class UnsafeArchiveMember(ValueError):
    """Raised when an archive entry could escape the intended extraction root."""


def validate_zip_member_name(name: str) -> str:
    """Validate a ZIP member name and return it unchanged when safe."""
    if not name or "\x00" in name:
        raise UnsafeArchiveMember(f"Unsafe archive entry: {name!r}")

    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise UnsafeArchiveMember(f"Unsafe archive entry: {name}")
    return name


def safe_zip_members(archive: zipfile.ZipFile) -> set[str]:
    """Return validated ZIP member names."""
    names: set[str] = set()
    for info in archive.infolist():
        names.add(validate_zip_member_name(info.filename))
    return names


def extract_zip_member(
    archive: zipfile.ZipFile,
    member: str,
    target: str | Path,
    *,
    mode: int | None = None,
    fsync: bool = False,
) -> Path:
    """Stream one validated ZIP member to a caller-selected target path."""
    validate_zip_member_name(member)
    resolved = Path(target)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member, "r") as source, resolved.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=_CHUNK_SIZE)
        if fsync:
            destination.flush()
            os.fsync(destination.fileno())
    if mode is not None:
        os.chmod(resolved, mode)
    return resolved


def zip_member_sha256(archive: zipfile.ZipFile, member: str) -> str:
    """Hash one validated ZIP member without loading it entirely into memory."""
    validate_zip_member_name(member)
    digest = hashlib.sha256()
    with archive.open(member, "r") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
