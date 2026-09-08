from __future__ import annotations

import json
import warnings
import zipfile
from pathlib import Path

import pytest

from envs_xmpp_core.storage.backup import (
    BackupArchiveError,
    BackupArchiveSource,
    build_backup_archive,
    read_backup_manifest,
    verify_backup_archive,
)


def test_build_backup_archive_publishes_manifest_checksums_and_private_mode(tmp_path: Path):
    source = tmp_path / "database.sqlite3"
    source.write_bytes(b"database")
    target = tmp_path / "backups" / "backup.zip"

    manifest = build_backup_archive(
        target,
        sources=[BackupArchiveSource("database.sqlite3", source, source="/var/lib/app/db.sqlite3")],
        manifest={"format": "example-v1", "app": "example"},
    )

    assert target.exists()
    assert target.stat().st_mode & 0o777 == 0o600
    assert manifest["files"][0]["name"] == "database.sqlite3"
    assert manifest["files"][0]["source"] == "/var/lib/app/db.sqlite3"
    assert len(manifest["files"][0]["sha256"]) == 64
    assert manifest["missing"] == []
    assert read_backup_manifest(target)["format"] == "example-v1"
    assert verify_backup_archive(target, expected_fields={"format": "example-v1"}).ok


def test_build_backup_archive_records_missing_optional_source(tmp_path: Path):
    target = tmp_path / "backup.zip"
    missing = tmp_path / "optional.txt"

    manifest = build_backup_archive(
        target,
        sources=[BackupArchiveSource("optional.txt", missing, source="/etc/example/optional.txt")],
        manifest={"format": "example-v1"},
    )

    assert manifest["files"] == []
    assert manifest["missing"] == [
        {"name": "optional.txt", "source": "/etc/example/optional.txt"}
    ]


def test_build_backup_archive_rejects_missing_required_source_without_partial(tmp_path: Path):
    target = tmp_path / "backup.zip"

    with pytest.raises(FileNotFoundError):
        build_backup_archive(
            target,
            sources=[BackupArchiveSource("db", tmp_path / "missing", required=True)],
            manifest={"format": "example-v1"},
        )

    assert not target.exists()
    assert not list(tmp_path.glob(".backup.zip.*.tmp"))


@pytest.mark.parametrize("names", [["manifest.json"], ["a", "a"]])
def test_build_backup_archive_rejects_manifest_collision_and_duplicates(
    tmp_path: Path, names: list[str]
):
    source = tmp_path / "source"
    source.write_text("x", encoding="utf-8")

    with pytest.raises(BackupArchiveError):
        build_backup_archive(
            tmp_path / "backup.zip",
            sources=[BackupArchiveSource(name, source) for name in names],
            manifest={"format": "example-v1"},
        )


def test_verify_backup_archive_detects_checksum_tampering(tmp_path: Path):
    source = tmp_path / "data.txt"
    source.write_text("original", encoding="utf-8")
    target = tmp_path / "backup.zip"
    build_backup_archive(
        target,
        sources=[BackupArchiveSource("data.txt", source)],
        manifest={"format": "example-v1"},
    )

    rewritten = tmp_path / "rewritten.zip"
    with zipfile.ZipFile(target) as old, zipfile.ZipFile(rewritten, "w") as new:
        for info in old.infolist():
            content = b"tampered" if info.filename == "data.txt" else old.read(info.filename)
            new.writestr(info, content)
    rewritten.replace(target)

    result = verify_backup_archive(target, expected_fields={"format": "example-v1"})
    assert result.ok is False
    assert result.checksum_mismatches == ("data.txt",)
    assert "checksum mismatch: data.txt" in result.errors


def test_verify_backup_archive_accepts_legacy_manifest_without_files(tmp_path: Path):
    target = tmp_path / "legacy.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("database.sqlite3", b"db")
        archive.writestr("manifest.json", json.dumps({"format": "legacy-v1"}))

    compatible = verify_backup_archive(
        target,
        expected_fields={"format": "legacy-v1"},
        required_members=["database.sqlite3"],
    )
    strict = verify_backup_archive(
        target,
        expected_fields={"format": "legacy-v1"},
        required_members=["database.sqlite3"],
        allow_legacy_without_files=False,
    )

    assert compatible.ok is True
    assert strict.ok is False
    assert "backup manifest has no files metadata" in strict.errors


def test_read_backup_manifest_rejects_duplicate_manifest_member(tmp_path: Path):
    target = tmp_path / "duplicate.zip"
    with warnings.catch_warnings(), zipfile.ZipFile(target, "w") as archive:
        warnings.simplefilter("ignore", UserWarning)
        archive.writestr("manifest.json", "{}")
        archive.writestr("manifest.json", "{}")

    with pytest.raises(BackupArchiveError, match="duplicate archive member"):
        read_backup_manifest(target)
