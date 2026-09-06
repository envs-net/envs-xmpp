"""AST-based, atomic updates for simple Python config assignments."""

from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from envs_xmpp_core.storage.files import atomic_write_text

from .literals import render_assignment


@dataclass(frozen=True, slots=True)
class PythonConfigEdit:
    """Prepared atomic edit for one Python configuration file."""

    path: Path
    original_text: str
    updated_text: str
    mode: int = 0o600
    encoding: str = "utf-8"

    def write(self) -> None:
        """Persist the prepared candidate atomically."""
        atomic_write_text(
            self.path,
            self.updated_text,
            mode=self.mode,
            encoding=self.encoding,
        )

    def rollback(self) -> None:
        """Restore the exact source text captured while preparing the edit."""
        atomic_write_text(
            self.path,
            self.original_text,
            mode=self.mode,
            encoding=self.encoding,
        )


class ConfigFileTransactionError(RuntimeError):
    """A config-file write/apply failed after a rollback was attempted."""

    def __init__(
        self,
        phase: Literal["write", "apply"],
        error: Exception,
        rollback_errors: tuple[BaseException, ...] = (),
    ) -> None:
        self.phase = phase
        self.error = error
        self.rollback_errors = rollback_errors
        super().__init__(str(error))


def assignment_span(text: str, name: str, *, filename: str = "<config>") -> tuple[int, int]:
    tree = ast.parse(text, filename=filename)
    matches: list[ast.stmt] = []
    for node in tree.body:
        is_assignment = isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        )
        is_annotated_assignment = (
            isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name
        )
        if is_assignment or is_annotated_assignment:
            matches.append(node)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one assignment for {name}, found {len(matches)}")
    node = matches[0]
    if not hasattr(node, "end_lineno") or node.end_lineno is None:
        raise ValueError(f"cannot determine assignment span for {name}")
    return node.lineno, node.end_lineno


def replace_assignment_text(text: str, name: str, value: Any, *, filename: str = "<config>") -> str:
    start, end = assignment_span(text, name, filename=filename)
    lines = text.splitlines(keepends=True)
    newline = "\n"
    if lines[start - 1].endswith("\r\n"):
        newline = "\r\n"
    replacement = render_assignment(name, value) + newline
    updated = "".join(lines[: start - 1] + [replacement] + lines[end:])
    ast.parse(updated, filename=filename)
    return updated


def update_assignment(path: str | Path, name: str, value: Any) -> str:
    target = Path(path)
    original = target.read_text(encoding="utf-8")
    updated = replace_assignment_text(original, name, value, filename=str(target))
    atomic_write_text(target, updated)
    return original


def restore_text(path: str | Path, original: str) -> None:
    atomic_write_text(path, original)


def assignment_ranges(text: str, *, uppercase_only: bool = False) -> dict[str, tuple[int, int, str]]:
    tree = ast.parse(text)
    lines = text.splitlines()
    ranges: dict[str, tuple[int, int, str]] = {}
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        for name in names:
            if uppercase_only and not name.isupper():
                continue
            start = max(0, int(getattr(node, "lineno", 1)) - 1)
            end = int(getattr(node, "end_lineno", start + 1))
            line = lines[start] if start < len(lines) else ""
            indent = line[: len(line) - len(line.lstrip())]
            ranges[name] = (start, end, indent)
    return ranges


def replace_or_append_assignment_text(
    text: str,
    name: str,
    assignment: str,
    *,
    section_comment: str = "# Runtime config edits",
    filename: str = "config.py",
) -> str:
    tree = ast.parse(text, filename=filename)
    count = 0
    for node in tree.body:
        if isinstance(node, ast.Assign):
            count += sum(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            count += 1
    if count > 1:
        raise ValueError(f"Config contains multiple top-level assignments for {name}")
    lines = text.splitlines()
    had_trailing_newline = text.endswith("\n")
    match = assignment_ranges(text).get(name)
    assignment_lines = assignment.splitlines()
    if match is not None:
        start, end, indent = match
        replacement = [indent + assignment_lines[0]]
        replacement.extend(indent + line for line in assignment_lines[1:])
        lines[start:end] = replacement
    else:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines.append(section_comment)
        lines.extend(assignment_lines)
    result = "\n".join(lines)
    result = result + "\n" if had_trailing_newline or not result.endswith("\n") else result
    compile(result, filename, "exec")
    return result


def prepare_assignment_edit(
    path: str | Path,
    name: str,
    assignment: str,
    *,
    section_comment: str = "# Runtime config edits",
    mode: int = 0o600,
    encoding: str = "utf-8",
) -> PythonConfigEdit:
    """Read and prepare one validated assignment edit without touching disk."""
    target = Path(path)
    original = target.read_text(encoding=encoding)
    updated = replace_or_append_assignment_text(
        original,
        name,
        assignment,
        section_comment=section_comment,
        filename=str(target),
    )
    return PythonConfigEdit(
        path=target,
        original_text=original,
        updated_text=updated,
        mode=mode,
        encoding=encoding,
    )


async def _rollback_config_edit(
    edit: PythonConfigEdit,
    rollback_apply: Callable[[bool], Awaitable[None]] | None,
) -> tuple[BaseException, ...]:
    errors: list[BaseException] = []
    file_restored = False
    try:
        edit.rollback()
        file_restored = True
    except BaseException as exc:  # noqa: BLE001 - rollback must report every failure
        errors.append(exc)

    if rollback_apply is not None:
        try:
            await rollback_apply(file_restored)
        except BaseException as exc:  # noqa: BLE001 - preserve rollback diagnostics
            errors.append(exc)
    return tuple(errors)


async def apply_config_edit_transaction[T](
    edit: PythonConfigEdit,
    *,
    apply: Callable[[], Awaitable[T]],
    rollback_apply: Callable[[bool], Awaitable[None]] | None = None,
) -> T:
    """Write, apply and automatically roll back one prepared config edit.

    ``apply`` owns bot-specific loading, validation and live application. If the
    file write or that callback fails, the exact original file is restored.
    ``rollback_apply`` can then restore in-memory state and is told whether the
    file rollback itself succeeded.
    """
    phase: Literal["write", "apply"] = "write"
    try:
        edit.write()
        phase = "apply"
        return await apply()
    except BaseException as exc:
        rollback_errors = await _rollback_config_edit(edit, rollback_apply)
        if isinstance(exc, Exception):
            raise ConfigFileTransactionError(phase, exc, rollback_errors) from exc
        for rollback_error in rollback_errors:
            exc.add_note(f"config rollback failure: {rollback_error}")
        raise
