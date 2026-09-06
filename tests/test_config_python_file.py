from __future__ import annotations

import os

import pytest

from envs_xmpp_core.config.python_file import (
    ConfigFileTransactionError,
    apply_config_edit_transaction,
    prepare_assignment_edit,
)


def test_prepare_assignment_edit_replaces_multiline_and_preserves_original(tmp_path):
    path = tmp_path / "config.py"
    original = "VALUES = [\n    'one',\n    'two',\n]\nLOG_LEVEL = 'INFO'\n"
    path.write_text(original, encoding="utf-8")

    edit = prepare_assignment_edit(path, "VALUES", "VALUES = ['three']")

    assert edit.original_text == original
    assert "VALUES = ['three']" in edit.updated_text
    assert "'one'" not in edit.updated_text
    assert path.read_text(encoding="utf-8") == original


def test_prepared_edit_writes_atomically_with_private_mode(tmp_path):
    path = tmp_path / "config.py"
    path.write_text("LOG_LEVEL = 'INFO'\n", encoding="utf-8")
    path.chmod(0o644)
    edit = prepare_assignment_edit(path, "LOG_LEVEL", "LOG_LEVEL = 'DEBUG'")

    old_umask = os.umask(0o022)
    try:
        edit.write()
    finally:
        os.umask(old_umask)

    assert path.read_text(encoding="utf-8") == "LOG_LEVEL = 'DEBUG'\n"
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_config_edit_transaction_returns_apply_result(tmp_path):
    path = tmp_path / "config.py"
    path.write_text("LOG_LEVEL = 'INFO'\n", encoding="utf-8")
    edit = prepare_assignment_edit(path, "LOG_LEVEL", "LOG_LEVEL = 'DEBUG'")

    async def apply() -> str:
        assert path.read_text(encoding="utf-8") == "LOG_LEVEL = 'DEBUG'\n"
        return "applied"

    result = await apply_config_edit_transaction(edit, apply=apply)

    assert result == "applied"
    assert path.read_text(encoding="utf-8") == "LOG_LEVEL = 'DEBUG'\n"


@pytest.mark.asyncio
async def test_config_edit_transaction_restores_file_and_runtime_on_apply_failure(tmp_path):
    path = tmp_path / "config.py"
    original = "LOG_LEVEL = 'INFO'\n"
    path.write_text(original, encoding="utf-8")
    edit = prepare_assignment_edit(path, "LOG_LEVEL", "LOG_LEVEL = 'DEBUG'")
    rollback_calls: list[bool] = []

    async def apply() -> None:
        raise RuntimeError("apply failed")

    async def rollback_apply(file_restored: bool) -> None:
        rollback_calls.append(file_restored)

    with pytest.raises(ConfigFileTransactionError) as exc_info:
        await apply_config_edit_transaction(
            edit,
            apply=apply,
            rollback_apply=rollback_apply,
        )

    error = exc_info.value
    assert error.phase == "apply"
    assert str(error.error) == "apply failed"
    assert error.rollback_errors == ()
    assert rollback_calls == [True]
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_config_edit_transaction_rolls_back_after_write_failure(tmp_path, monkeypatch):
    path = tmp_path / "config.py"
    original = "LOG_LEVEL = 'INFO'\n"
    path.write_text(original, encoding="utf-8")
    edit = prepare_assignment_edit(path, "LOG_LEVEL", "LOG_LEVEL = 'DEBUG'")
    apply_called = False

    def fail_write(self) -> None:
        raise OSError("write failed")

    async def apply() -> None:
        nonlocal apply_called
        apply_called = True

    monkeypatch.setattr(type(edit), "write", fail_write)

    with pytest.raises(ConfigFileTransactionError) as exc_info:
        await apply_config_edit_transaction(edit, apply=apply)

    assert exc_info.value.phase == "write"
    assert str(exc_info.value.error) == "write failed"
    assert apply_called is False
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_config_edit_transaction_preserves_rollback_diagnostics(tmp_path):
    path = tmp_path / "config.py"
    original = "LOG_LEVEL = 'INFO'\n"
    path.write_text(original, encoding="utf-8")
    edit = prepare_assignment_edit(path, "LOG_LEVEL", "LOG_LEVEL = 'DEBUG'")

    async def apply() -> None:
        raise RuntimeError("apply failed")

    async def rollback_apply(_file_restored: bool) -> None:
        raise RuntimeError("runtime rollback failed")

    with pytest.raises(ConfigFileTransactionError) as exc_info:
        await apply_config_edit_transaction(
            edit,
            apply=apply,
            rollback_apply=rollback_apply,
        )

    error = exc_info.value
    assert error.phase == "apply"
    assert [str(item) for item in error.rollback_errors] == ["runtime rollback failed"]
    assert path.read_text(encoding="utf-8") == original
