"""AST-based, atomic updates for simple Python config assignments."""
from __future__ import annotations
import ast
from pathlib import Path
from typing import Any
from .literals import render_assignment
from envs_xmpp_core.storage.files import atomic_write_text


def assignment_span(text: str, name: str, *, filename: str = "<config>") -> tuple[int, int]:
    tree = ast.parse(text, filename=filename)
    matches: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            matches.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
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
