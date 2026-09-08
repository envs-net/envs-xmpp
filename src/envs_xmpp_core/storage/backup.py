"""Shared managed backup archive build and verification primitives."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import zipfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive import (
    UnsafeArchiveMember,
    extract_zip_member,
    validate_zip_member_name,
    zip_member_sha256,
)
from .files import fsync_directory, sha256_file

DEFAULT_MANIFEST_NAME = "manifest.json"


class BackupArchiveError(ValueError):
    """Raised when a managed backup archive is invalid or cannot be built."""


@dataclass(frozen=True)
class BackupArchiveSource:
    """One file that may be included in a managed backup archive."""

    name: str
    path: Path
    source: str | Path | None = None
    required: bool = False




@dataclass(frozen=True)
class BackupArchiveEntrySpec:
    """One known archive member to stage for restore/inspection."""

    key: str
    member: str
    required: bool = False
    mode: int = 0o600


@dataclass(frozen=True)
class StagedBackupArchive:
    """Verified archive metadata plus staged known members."""

    path: Path
    manifest: dict[str, Any] | None
    members: frozenset[str]
    entries: Mapping[str, Path | None]


@dataclass(frozen=True)
class BackupArchiveVerification:
    """Structured result of a managed backup archive verification."""

    path: Path
    manifest: dict[str, Any] | None
    members: frozenset[str]
    files: tuple[str, ...]
    errors: tuple[str, ...]
    checksum_mismatches: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _member_names(archive: zipfile.ZipFile) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    duplicates: list[str] = []
    for info in archive.infolist():
        name = validate_zip_member_name(info.filename)
        if name in names:
            duplicates.append(name)
        names.add(name)
    return names, duplicates


def read_backup_manifest(
    path: str | Path,
    *,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
) -> dict[str, Any]:
    """Read and validate the JSON manifest object from one ZIP archive."""
    archive_path = Path(path)
    validate_zip_member_name(manifest_name)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names, duplicates = _member_names(archive)
            if duplicates:
                raise BackupArchiveError(
                    "duplicate archive member(s): " + ", ".join(sorted(set(duplicates)))
                )
            if manifest_name not in names:
                raise BackupArchiveError(f"archive has no {manifest_name}")
            raw = archive.read(manifest_name)
    except BackupArchiveError:
        raise
    except (OSError, zipfile.BadZipFile, UnsafeArchiveMember) as exc:
        raise BackupArchiveError(f"could not read backup archive: {exc}") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupArchiveError(f"could not read backup manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise BackupArchiveError("backup manifest must be a JSON object")
    return data


def verify_backup_archive(
    path: str | Path,
    *,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_fields: Mapping[str, object] | None = None,
    required_members: Iterable[str] = (),
    allow_legacy_without_files: bool = True,
    verify_checksums: bool = True,
) -> BackupArchiveVerification:
    """Verify ZIP safety, manifest structure, required members and file metadata."""
    archive_path = Path(path)
    errors: list[str] = []
    checksum_mismatches: list[str] = []
    manifest: dict[str, Any] | None = None
    members: set[str] = set()
    file_names: list[str] = []

    try:
        validate_zip_member_name(manifest_name)
        with zipfile.ZipFile(archive_path) as archive:
            try:
                members, duplicates = _member_names(archive)
            except UnsafeArchiveMember as exc:
                errors.append(str(exc))
                return BackupArchiveVerification(
                    archive_path,
                    None,
                    frozenset(),
                    (),
                    tuple(errors),
                    (),
                )

            if duplicates:
                errors.append(
                    "duplicate archive member(s): " + ", ".join(sorted(set(duplicates)))
                )

            bad_member = archive.testzip()
            if bad_member is not None:
                errors.append(f"zip CRC failed for {bad_member}")

            if manifest_name not in members:
                errors.append(f"missing archive member: {manifest_name}")
            else:
                try:
                    raw_manifest = archive.read(manifest_name)
                    parsed = json.loads(raw_manifest.decode("utf-8"))
                    if isinstance(parsed, dict):
                        manifest = parsed
                    else:
                        errors.append("backup manifest must be a JSON object")
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    errors.append(f"invalid backup manifest: {exc}")

            for required in required_members:
                try:
                    validate_zip_member_name(required)
                except UnsafeArchiveMember as exc:
                    errors.append(str(exc))
                    continue
                if required not in members:
                    errors.append(f"missing archive member: {required}")

            if manifest is not None:
                for key, expected in (expected_fields or {}).items():
                    actual = manifest.get(key)
                    if actual != expected:
                        errors.append(
                            f"unexpected manifest {key}: expected {expected!r}, got {actual!r}"
                        )

                files_value = manifest.get("files")
                if files_value is None:
                    if not allow_legacy_without_files:
                        errors.append("backup manifest has no files metadata")
                elif not isinstance(files_value, list):
                    errors.append("backup manifest files must be a list")
                else:
                    seen_manifest_names: set[str] = set()
                    for item in files_value:
                        if not isinstance(item, dict):
                            errors.append("manifest file entry must be an object")
                            continue
                        name = item.get("name")
                        if not isinstance(name, str) or not name:
                            errors.append("manifest file without name")
                            continue
                        try:
                            validate_zip_member_name(name)
                        except UnsafeArchiveMember as exc:
                            errors.append(str(exc))
                            continue
                        if name in seen_manifest_names:
                            errors.append(f"duplicate manifest file entry: {name}")
                            continue
                        seen_manifest_names.add(name)
                        file_names.append(name)
                        if name not in members:
                            errors.append(f"missing archive member: {name}")
                            continue

                        if not verify_checksums:
                            continue

                        expected_size = item.get("size")
                        if isinstance(expected_size, int):
                            actual_size = archive.getinfo(name).file_size
                            if actual_size != expected_size:
                                errors.append(
                                    f"size mismatch: {name} (expected {expected_size}, got {actual_size})"
                                )

                        expected_sha256 = item.get("sha256")
                        if isinstance(expected_sha256, str) and expected_sha256:
                            actual_sha256 = zip_member_sha256(archive, name)
                            if actual_sha256 != expected_sha256:
                                checksum_mismatches.append(name)
                                errors.append(f"checksum mismatch: {name}")
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid backup archive: {exc}")

    return BackupArchiveVerification(
        path=archive_path,
        manifest=manifest,
        members=frozenset(members),
        files=tuple(file_names),
        errors=tuple(errors),
        checksum_mismatches=tuple(checksum_mismatches),
    )


def build_backup_archive(
    path: str | Path,
    *,
    sources: Iterable[BackupArchiveSource],
    manifest: Mapping[str, Any],
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    mode: int = 0o600,
    json_newline: bool = False,
) -> dict[str, Any]:
    """Build, verify and atomically publish one managed ZIP backup archive."""
    archive_path = Path(path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    validate_zip_member_name(manifest_name)

    source_items = list(sources)
    seen_names: set[str] = set()
    for item in source_items:
        validate_zip_member_name(item.name)
        if item.name == manifest_name:
            raise BackupArchiveError(f"archive source collides with {manifest_name}: {item.name}")
        if item.name in seen_names:
            raise BackupArchiveError(f"duplicate archive source: {item.name}")
        seen_names.add(item.name)

    built_manifest = copy.deepcopy(dict(manifest))
    files: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    built_manifest["files"] = files
    built_manifest["missing"] = missing

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{archive_path.name}.", suffix=".tmp", dir=archive_path.parent
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    os.chmod(tmp_path, mode)

    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in source_items:
                source_path = Path(item.path)
                display_source = str(item.source if item.source is not None else source_path)
                if not source_path.is_file():
                    if item.required:
                        raise FileNotFoundError(source_path)
                    missing.append({"name": item.name, "source": display_source})
                    continue

                archive.write(source_path, item.name)
                files.append(
                    {
                        "name": item.name,
                        "source": display_source,
                        "size": source_path.stat().st_size,
                        "sha256": sha256_file(source_path),
                    }
                )

            manifest_text = json.dumps(built_manifest, indent=2, sort_keys=True)
            if json_newline:
                manifest_text += "\n"
            archive.writestr(manifest_name, manifest_text)

        verification = verify_backup_archive(
            tmp_path,
            manifest_name=manifest_name,
            allow_legacy_without_files=False,
        )
        if not verification.ok:
            raise BackupArchiveError(
                "new backup archive failed verification: " + "; ".join(verification.errors)
            )

        with tmp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp_path, archive_path)
        os.chmod(archive_path, mode)
        with suppress(OSError):
            fsync_directory(archive_path.parent)
        return built_manifest
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def stage_backup_archive(
    path: str | Path,
    target_dir: str | Path,
    *,
    entries: Iterable[BackupArchiveEntrySpec],
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    expected_fields: Mapping[str, object] | None = None,
    allow_legacy_without_files: bool = True,
    verify_checksums: bool = True,
) -> StagedBackupArchive:
    """Verify one backup archive and extract only caller-declared members.

    Required entries participate in archive verification. Optional entries are
    returned as ``None`` when absent. Extraction happens only after the complete
    archive/manifest/checksum verification succeeds, so callers can safely build
    restore transactions from the staged paths without duplicating ZIP policy.
    """
    archive_path = Path(path)
    target = Path(target_dir)
    items = tuple(entries)
    if not items:
        raise ValueError("backup archive staging has no entries")

    seen_keys: set[str] = set()
    seen_members: set[str] = set()
    for item in items:
        if not item.key:
            raise ValueError("backup archive entry key must not be empty")
        validate_zip_member_name(item.member)
        if item.key in seen_keys:
            raise ValueError(f"duplicate backup archive entry key: {item.key}")
        if item.member in seen_members:
            raise ValueError(f"duplicate backup archive member spec: {item.member}")
        seen_keys.add(item.key)
        seen_members.add(item.member)

    verification = verify_backup_archive(
        archive_path,
        manifest_name=manifest_name,
        expected_fields=expected_fields,
        required_members=(item.member for item in items if item.required),
        allow_legacy_without_files=allow_legacy_without_files,
        verify_checksums=verify_checksums,
    )
    if not verification.ok:
        raise BackupArchiveError("invalid backup archive: " + "; ".join(verification.errors))

    target.mkdir(parents=True, exist_ok=True)
    staged: dict[str, Path | None] = {}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for index, item in enumerate(items):
                if item.member not in verification.members:
                    staged[item.key] = None
                    continue
                destination = target / f"{index:03d}-{Path(item.member).name}"
                staged[item.key] = extract_zip_member(
                    archive,
                    item.member,
                    destination,
                    mode=item.mode,
                    fsync=True,
                )
    except BackupArchiveError:
        raise
    except (OSError, zipfile.BadZipFile, UnsafeArchiveMember) as exc:
        raise BackupArchiveError(f"could not stage backup archive: {exc}") from exc

    return StagedBackupArchive(
        path=archive_path,
        manifest=verification.manifest,
        members=verification.members,
        entries=staged,
    )
