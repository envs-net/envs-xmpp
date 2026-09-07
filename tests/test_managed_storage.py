from __future__ import annotations

import os
from pathlib import Path

import pytest

from envs_xmpp_core.storage.managed import (
    list_managed_files,
    prune_managed_files,
    resolve_managed_file,
    select_managed_files_for_prune,
)


def _managed_files(tmp_path: Path):
    managed = tmp_path / "managed"
    managed.mkdir()
    paths = []
    for index, stamp in enumerate((100.0, 200.0, 300.0, 400.0)):
        path = managed / f"item-{index}.dat"
        path.write_text(str(index), encoding="utf-8")
        os.utime(path, (stamp, stamp))
        paths.append(path)
    return managed, paths, list_managed_files(managed, "item-*.dat")


def test_managed_files_list_and_resolve_are_contained(tmp_path: Path):
    managed, paths, files = _managed_files(tmp_path)
    outside = tmp_path / "outside.dat"
    outside.write_text("outside", encoding="utf-8")

    assert [item.path for item in files] == list(reversed(paths))
    assert files[0].name == "item-3.dat"
    assert files[0].size == 1
    assert resolve_managed_file(managed, "latest", files) == paths[3]
    assert resolve_managed_file(managed, "last", files, latest_aliases=("last",)) == paths[3]
    assert resolve_managed_file(managed, paths[1].name, files) == paths[1]
    assert resolve_managed_file(managed, str(paths[0].resolve()), files) == paths[0]
    assert resolve_managed_file(managed, str(outside.resolve()), files) is None
    assert resolve_managed_file(managed, "../outside.dat", files) is None


def test_managed_file_retention_combines_count_age_and_preserve(tmp_path: Path):
    _managed, paths, files = _managed_files(tmp_path)

    planned = select_managed_files_for_prune(
        files,
        keep=2,
        preserve=paths[0],
        max_age_seconds=150,
        now=400,
    )

    # item-3 and item-2 fit the count budget. item-0 is explicitly preserved.
    # item-1 is both beyond the count budget and older than the age cutoff.
    assert [item.path for item in planned] == [paths[1]]


@pytest.mark.asyncio
async def test_prune_managed_files_deletes_companions(tmp_path: Path):
    managed, paths, files = _managed_files(tmp_path)
    companion = managed / f"{paths[0].name}.config.py"
    companion.write_text("config", encoding="utf-8")

    removed = await prune_managed_files(
        files,
        keep=3,
        delete_companions=lambda path: [path.with_name(path.name + ".config.py")],
    )

    assert removed == [paths[0], companion]
    assert not paths[0].exists()
    assert not companion.exists()
