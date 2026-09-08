"""Shared safe diagnostic payload helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envs_xmpp_core.security.redaction import redact_text, redact_value


@dataclass(frozen=True)
class DiagnosticError:
    """A compact redacted exception representation safe for operator output."""

    type: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "message": self.message}


def exception_summary(exc: BaseException, *, max_length: int = 300) -> str:
    """Return a compact redacted exception message, falling back to its type."""
    text = str(exc).strip()
    if not text:
        return type(exc).__name__
    return redact_text(text, max_length=max_length)


def diagnostic_error(exc: BaseException, *, max_length: int = 300) -> DiagnosticError:
    """Build a typed redacted diagnostic error."""
    return DiagnosticError(
        type=type(exc).__name__,
        message=exception_summary(exc, max_length=max_length),
    )


def diagnostic_payload(
    values: dict[str, Any],
    *,
    max_string: int = 240,
) -> dict[str, Any]:
    """Redact a mapping intended for structured logs or admin diagnostics."""
    redacted = redact_value(values, max_string=max_string)
    return dict(redacted) if isinstance(redacted, dict) else {}
