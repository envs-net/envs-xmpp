"""Safe filesystem primitives for bot state and configuration."""
from __future__ import annotations
import hashlib
import os
import tempfile
from pathlib import Path


def ensure_private_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    os.chmod(target, 0o700)
    return target


def ensure_private_file(path: str | Path) -> Path:
    target = Path(path)
    if target.exists():
        os.chmod(target, 0o600)
    return target


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_directory(path: str | Path) -> None:
    directory = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_text(path: str | Path, text: str, *, mode: int = 0o600, encoding: str = "utf-8") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            os.chmod(tmp, mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        os.chmod(target, mode)
        fsync_directory(target.parent)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        finally:
            raise
