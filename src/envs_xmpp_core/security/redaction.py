"""Conservative redaction helpers for logs, diagnostics and admin output."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
)
REDACTED = "<redacted>"
DEFAULT_MAX_STRING = 240
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|apikey|access[_-]?key|private[_-]?key)\s*=\s*([^\s,;]+)"
)


def _redact_secret_assignments(value: str) -> str:
    """Redact secret-looking key=value assignments in free-form text."""
    return _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}={REDACTED}",
        value,
    )


def is_secret_key(key: object) -> bool:
    """Return True when a mapping key likely contains a secret."""
    key_lc = str(key or "").lower()
    return any(part in key_lc for part in SECRET_KEY_PARTS)


def redact_url(value: str) -> str:
    """Return a URL with userinfo removed while preserving the non-secret URL."""
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc or "@" not in parsed.netloc:
            return value
        host = parsed.hostname or ""
        port = parsed.port
    except (TypeError, ValueError):
        return value
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def _truncate(text: str, *, max_length: int = DEFAULT_MAX_STRING) -> str:
    limit = max(0, int(max_length))
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def redact_value(
    value: Any,
    *,
    key: object | None = None,
    max_string: int = DEFAULT_MAX_STRING,
) -> Any:
    """Redact nested data while preserving its useful container shape."""
    if key is not None and is_secret_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            item_key: redact_value(item_value, key=item_key, max_string=max_string)
            for item_key, item_value in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_value(item, max_string=max_string) for item in value)
    if isinstance(value, list):
        return [redact_value(item, max_string=max_string) for item in value]
    if isinstance(value, set):
        redacted_set: set[Any] = set()
        for item in value:
            redacted_item = redact_value(item, max_string=max_string)
            try:
                redacted_set.add(redacted_item)
            except TypeError:
                redacted_set.add(_truncate(str(redacted_item), max_length=max_string))
        return redacted_set
    if isinstance(value, str):
        return _truncate(
            _redact_secret_assignments(redact_url(value)),
            max_length=max_string,
        )
    return value


def redact_named(
    name: object,
    value: Any,
    *,
    max_string: int = DEFAULT_MAX_STRING,
) -> Any:
    """Redact a value using an explicit field name."""
    return redact_value(value, key=name, max_string=max_string)


def redact_text(
    text: object,
    *,
    max_length: int = DEFAULT_MAX_STRING,
) -> str:
    """Return compact redacted text for logs, diagnostics and audit records."""
    value = _redact_secret_assignments(redact_url(str(text)))
    return _truncate(value, max_length=max_length)
