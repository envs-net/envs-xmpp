"""Safe parsing/rendering of Python configuration literals."""

from __future__ import annotations

import ast
from typing import Any


def parse_literal(text: str) -> Any:
    value = str(text).strip()
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"none", "null"}:
        return None
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return value


def render_assignment(name: str, value: Any) -> str:
    return f"{name} = {value!r}"
