"""Transactional file restore primitives for managed runtime state."""

from __future__ import annotations

import asyncio
import inspect
import os
import shutil
import tempfile
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .files import fsync_directory

RestorePhase = Literal["prepare", "snapshot", "apply", "validate"]
RestoreHook = Callable[[], Any | Awaitable[Any]]


@dataclass(frozen=True)
class RestoreFileSpec:
    """One staged source file and its live restore target."""

    name: str
    source: Path
    target: Path
    mode: int = 0o600
    parent_mode: int | None = None


@dataclass(frozen=True)
class RestoreTargetSnapshot:
    """Exact pre-restore state for one target after runtime preparation."""

    spec: RestoreFileSpec
    existed: bool
    snapshot: Path | None


@dataclass(frozen=True)
class RestoreTransactionResult:
    """Successful managed restore transaction result."""

    restored: tuple[str, ...]


class RestoreTransactionError(RuntimeError):
    """Restore failure with rollback/recovery diagnostics."""

    def __init__(
        self,
        phase: RestorePhase,
        cause: Exception,
        *,
        rollback_attempted: bool = False,
        rollback_errors: tuple[BaseException, ...] = (),
        recovery_attempted: bool = False,
        recovery_errors: tuple[BaseException, ...] = (),
    ) -> None:
        self.phase = phase
        self.cause = cause
        self.rollback_attempted = rollback_attempted
        self.rollback_errors = rollback_errors
        self.recovery_attempted = recovery_attempted
        self.recovery_errors = recovery_errors
        details = f"restore {phase} failed: {cause}"
        if rollback_errors:
            details += "; rollback failed: " + "; ".join(str(item) for item in rollback_errors)
        if recovery_errors:
            details += "; runtime recovery failed: " + "; ".join(
                str(item) for item in recovery_errors
            )
        super().__init__(details)

    @property
    def rollback_ok(self) -> bool:
        return self.rollback_attempted and not self.rollback_errors and not self.recovery_errors

    @property
    def recovery_ok(self) -> bool:
        return self.recovery_attempted and not self.recovery_errors


def _normalize_specs(specs: Iterable[RestoreFileSpec]) -> tuple[RestoreFileSpec, ...]:
    items = tuple(specs)
    seen_targets: set[Path] = set()
    seen_names: set[str] = set()
    for item in items:
        if not item.name:
            raise ValueError("restore file name must not be empty")
        target = item.target.resolve()
        if target in seen_targets:
            raise ValueError(f"duplicate restore target: {item.target}")
        if item.name in seen_names:
            raise ValueError(f"duplicate restore name: {item.name}")
        if not item.source.is_file():
            raise FileNotFoundError(item.source)
        seen_targets.add(target)
        seen_names.add(item.name)
    if not items:
        raise ValueError("restore transaction has no files")
    return items


def replace_restore_file(spec: RestoreFileSpec) -> None:
    """Atomically replace one live target from a staged source file."""
    source = Path(spec.source)
    target = Path(spec.target)
    if not source.is_file():
        raise FileNotFoundError(source)

    target.parent.mkdir(parents=True, exist_ok=True)
    if spec.parent_mode is not None:
        os.chmod(target.parent, spec.parent_mode)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    tmp = Path(tmp_name)
    try:
        with source.open("rb") as input_handle, os.fdopen(fd, "wb") as output_handle:
            os.chmod(tmp, spec.mode)
            shutil.copyfileobj(input_handle, output_handle)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.replace(tmp, target)
        os.chmod(target, spec.mode)
        fsync_directory(target.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def snapshot_restore_targets(
    specs: Iterable[RestoreFileSpec],
    directory: str | Path,
) -> tuple[RestoreTargetSnapshot, ...]:
    """Snapshot exact live target contents for deterministic rollback."""
    items = _normalize_specs(specs)
    snapshot_dir = Path(directory)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshots: list[RestoreTargetSnapshot] = []

    for index, spec in enumerate(items):
        target = Path(spec.target)
        if not target.exists():
            snapshots.append(RestoreTargetSnapshot(spec, False, None))
            continue
        if not target.is_file():
            raise ValueError(f"restore target is not a regular file: {target}")
        snapshot = snapshot_dir / f"{index:03d}-{target.name}"
        with target.open("rb") as source, snapshot.open("wb") as destination:
            shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(snapshot, spec.mode)
        snapshots.append(RestoreTargetSnapshot(spec, True, snapshot))

    with suppress(OSError):
        fsync_directory(snapshot_dir)
    return tuple(snapshots)


def apply_restore_files(
    specs: Iterable[RestoreFileSpec],
    *,
    replace_file: Callable[[RestoreFileSpec], None] = replace_restore_file,
) -> tuple[str, ...]:
    """Publish all staged restore files in caller-defined order."""
    items = _normalize_specs(specs)
    restored: list[str] = []
    for spec in items:
        replace_file(spec)
        restored.append(spec.name)
    return tuple(restored)


def rollback_restore_targets(
    snapshots: Iterable[RestoreTargetSnapshot],
    *,
    replace_file: Callable[[RestoreFileSpec], None] = replace_restore_file,
) -> None:
    """Restore exact pre-restore contents, deleting targets that were absent."""
    for snapshot in snapshots:
        spec = snapshot.spec
        target = Path(spec.target)
        if snapshot.existed:
            if snapshot.snapshot is None or not snapshot.snapshot.is_file():
                raise RuntimeError(f"rollback snapshot is unavailable for {target}")
            replace_file(
                RestoreFileSpec(
                    name=spec.name,
                    source=snapshot.snapshot,
                    target=target,
                    mode=spec.mode,
                    parent_mode=spec.parent_mode,
                )
            )
            continue
        if target.exists():
            target.unlink()
            fsync_directory(target.parent)


async def _maybe_await_hook(hook: RestoreHook | None) -> None:
    if hook is None:
        return
    result = hook()
    if inspect.isawaitable(result):
        await result


async def _run_blocking[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run blocking file work without letting cancellation race the worker thread."""
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(task)
        finally:
            raise


async def _collect_hook_error(hook: RestoreHook | None) -> tuple[BaseException, ...]:
    if hook is None:
        return ()
    try:
        await _maybe_await_hook(hook)
    except BaseException as exc:  # noqa: BLE001 - recovery diagnostics must be retained
        return (exc,)
    return ()


async def run_restore_transaction(
    specs: Iterable[RestoreFileSpec],
    *,
    rollback_directory: str | Path,
    prepare: RestoreHook | None = None,
    validate: RestoreHook | None = None,
    before_rollback: RestoreHook | None = None,
    after_rollback: RestoreHook | None = None,
    recover_unmodified: RestoreHook | None = None,
    replace_file: Callable[[RestoreFileSpec], None] = replace_restore_file,
) -> RestoreTransactionResult:
    """Prepare, snapshot, publish and validate runtime files transactionally.

    The exact live targets are snapshotted *after* ``prepare`` completes. Any
    failure while publishing or validating triggers all-file rollback. Hooks
    allow callers to quiesce/reopen runtime state without moving bot policy into
    the shared storage layer.
    """
    items = _normalize_specs(specs)
    phase: RestorePhase = "prepare"
    snapshots: tuple[RestoreTargetSnapshot, ...] = ()
    rollback_attempted = False
    recovery_attempted = False
    rollback_errors: list[BaseException] = []
    recovery_errors: list[BaseException] = []

    try:
        await _maybe_await_hook(prepare)
        phase = "snapshot"
        snapshots = await _run_blocking(snapshot_restore_targets, items, rollback_directory)
        phase = "apply"
        restored = await _run_blocking(apply_restore_files, items, replace_file=replace_file)
        phase = "validate"
        await _maybe_await_hook(validate)
        return RestoreTransactionResult(restored=restored)
    except BaseException as exc:
        if phase in {"apply", "validate"} and snapshots:
            rollback_attempted = True
            rollback_errors.extend(await _collect_hook_error(before_rollback))
            try:
                await _run_blocking(
                    rollback_restore_targets,
                    snapshots,
                    replace_file=replace_file,
                )
            except BaseException as rollback_exc:  # noqa: BLE001
                rollback_errors.append(rollback_exc)
            recovery_attempted = after_rollback is not None
            recovery_errors.extend(await _collect_hook_error(after_rollback))
        elif phase in {"prepare", "snapshot"} and recover_unmodified is not None:
            recovery_attempted = True
            recovery_errors.extend(await _collect_hook_error(recover_unmodified))

        if isinstance(exc, Exception):
            raise RestoreTransactionError(
                phase,
                exc,
                rollback_attempted=rollback_attempted,
                rollback_errors=tuple(rollback_errors),
                recovery_attempted=recovery_attempted,
                recovery_errors=tuple(recovery_errors),
            ) from exc

        for error in (*rollback_errors, *recovery_errors):
            exc.add_note(f"restore recovery failure: {error}")
        raise
