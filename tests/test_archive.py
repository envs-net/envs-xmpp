import zipfile
from pathlib import Path

import pytest

from envs_xmpp_core.storage.archive import (
    UnsafeArchiveMember,
    extract_zip_member,
    safe_zip_members,
    validate_zip_member_name,
    zip_member_sha256,
)


def test_validate_zip_member_name_rejects_traversal_and_absolute_paths():
    for name in ("../escape", "/absolute", "C:/absolute", r"..\\escape"):
        with pytest.raises(UnsafeArchiveMember):
            validate_zip_member_name(name)


def test_archive_helpers_validate_extract_and_hash(tmp_path: Path):
    archive_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", "{}\n")
        archive.writestr("data/database.sqlite3", b"database")

    with zipfile.ZipFile(archive_path) as archive:
        assert safe_zip_members(archive) == {"manifest.json", "data/database.sqlite3"}
        target = tmp_path / "out" / "database.sqlite3"
        assert extract_zip_member(archive, "data/database.sqlite3", target, mode=0o600, fsync=True) == target
        assert target.read_bytes() == b"database"
        assert target.stat().st_mode & 0o777 == 0o600
        assert zip_member_sha256(archive, "data/database.sqlite3") == (
            "3549b0028b75d981cdda2e573e9cb49dedc200185876df299f912b79f69dabd8"
        )


def test_safe_zip_members_rejects_unsafe_archive(tmp_path: Path):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape", "bad")

    with zipfile.ZipFile(archive_path) as archive, pytest.raises(UnsafeArchiveMember):
        safe_zip_members(archive)
