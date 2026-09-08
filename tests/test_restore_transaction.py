from __future__ import annotations

from pathlib import Path

import pytest

from envs_xmpp_core.storage.restore import (
    RestoreFileSpec,
    RestoreTransactionError,
    run_restore_transaction,
)


@pytest.mark.asyncio
async def test_restore_transaction_publishes_and_validates(tmp_path: Path) -> None:
    source = tmp_path / "staged.db"
    target = tmp_path / "live" / "bot.db"
    rollback = tmp_path / "rollback"
    source.write_text("backup", encoding="utf-8")
    target.parent.mkdir()
    target.write_text("current", encoding="utf-8")
    events: list[str] = []

    async def prepare() -> None:
        events.append("prepare")

    async def validate() -> None:
        events.append("validate")
        assert target.read_text(encoding="utf-8") == "backup"

    result = await run_restore_transaction(
        [RestoreFileSpec("bot.db", source, target)],
        rollback_directory=rollback,
        prepare=prepare,
        validate=validate,
    )

    assert result.restored == ("bot.db",)
    assert target.read_text(encoding="utf-8") == "backup"
    assert events == ["prepare", "validate"]


@pytest.mark.asyncio
async def test_restore_transaction_rolls_back_all_files_on_publish_failure(tmp_path: Path) -> None:
    source_a = tmp_path / "a.new"
    source_b = tmp_path / "b.new"
    target_a = tmp_path / "a"
    target_b = tmp_path / "b"
    source_a.write_text("new-a", encoding="utf-8")
    source_b.write_text("new-b", encoding="utf-8")
    target_a.write_text("old-a", encoding="utf-8")
    target_b.write_text("old-b", encoding="utf-8")

    from envs_xmpp_core.storage.restore import replace_restore_file

    calls = 0

    def fail_second(spec: RestoreFileSpec) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publish failed")
        replace_restore_file(spec)

    with pytest.raises(RestoreTransactionError) as captured:
        await run_restore_transaction(
            [
                RestoreFileSpec("a", source_a, target_a),
                RestoreFileSpec("b", source_b, target_b),
            ],
            rollback_directory=tmp_path / "rollback",
            replace_file=fail_second,
        )

    error = captured.value
    assert error.phase == "apply"
    assert error.rollback_ok is True
    assert target_a.read_text(encoding="utf-8") == "old-a"
    assert target_b.read_text(encoding="utf-8") == "old-b"


@pytest.mark.asyncio
async def test_restore_transaction_rolls_back_when_runtime_validation_fails(tmp_path: Path) -> None:
    source = tmp_path / "new"
    target = tmp_path / "live"
    source.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    events: list[str] = []

    async def validate() -> None:
        raise RuntimeError("runtime reload failed")

    async def before_rollback() -> None:
        events.append("close-new")

    async def after_rollback() -> None:
        events.append("reload-old")

    with pytest.raises(RestoreTransactionError) as captured:
        await run_restore_transaction(
            [RestoreFileSpec("state", source, target)],
            rollback_directory=tmp_path / "rollback",
            validate=validate,
            before_rollback=before_rollback,
            after_rollback=after_rollback,
        )

    error = captured.value
    assert error.phase == "validate"
    assert error.rollback_ok is True
    assert target.read_text(encoding="utf-8") == "old"
    assert events == ["close-new", "reload-old"]


@pytest.mark.asyncio
async def test_restore_transaction_recovers_runtime_when_snapshot_fails(tmp_path: Path) -> None:
    source = tmp_path / "new"
    source.write_text("new", encoding="utf-8")
    target = tmp_path / "directory-target"
    target.mkdir()
    recovered = False

    async def recover() -> None:
        nonlocal recovered
        recovered = True

    with pytest.raises(RestoreTransactionError) as captured:
        await run_restore_transaction(
            [RestoreFileSpec("state", source, target)],
            rollback_directory=tmp_path / "rollback",
            recover_unmodified=recover,
        )

    assert captured.value.phase == "snapshot"
    assert captured.value.recovery_ok is True
    assert recovered is True
