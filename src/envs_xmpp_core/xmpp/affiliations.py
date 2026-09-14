"""Bounded MUC affiliation IQ helpers without bot-specific policy."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

_DEFAULT_TRANSIENT_CONDITIONS = frozenset(
    {
        "internal-server-error",
        "recipient-unavailable",
        "remote-server-timeout",
        "service-unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class AffiliationQueryOptions:
    """Timeout/retry policy for one MUC affiliation IQ."""

    timeout_seconds: float = 10.0
    attempts: int = 2
    retry_delay_seconds: float = 1.0
    transient_conditions: frozenset[str] = _DEFAULT_TRANSIENT_CONDITIONS

    def normalized(self) -> AffiliationQueryOptions:
        return AffiliationQueryOptions(
            timeout_seconds=max(0.1, float(self.timeout_seconds)),
            attempts=max(1, int(self.attempts)),
            retry_delay_seconds=max(0.0, float(self.retry_delay_seconds)),
            transient_conditions=frozenset(str(value) for value in self.transient_conditions),
        )


@dataclass(frozen=True, slots=True)
class AffiliationQueryResult:
    """Structured result that avoids leaking raw IQ stanzas into logs."""

    room: str
    affiliation: str
    ok: bool
    items: tuple[Any, ...]
    attempts: int
    error_kind: str | None = None
    error_condition: str | None = None
    error_message: str | None = None
    retryable: bool = False
    retry_reasons: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        if self.ok:
            return f"{len(self.items)} item(s)"
        if self.error_kind == "timeout":
            return self.error_message or "IQ timeout"
        if self.error_condition:
            suffix = f": {self.error_message}" if self.error_message else ""
            return f"IQ error {self.error_condition}{suffix}"
        return self.error_message or self.error_kind or "affiliation query failed"


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _exception_kind(exc: Exception) -> tuple[str, str | None, str | None, bool]:
    name = type(exc).__name__
    if isinstance(exc, TimeoutError) or name.endswith("IqTimeout"):
        return "timeout", None, "IQ timeout", True
    if name.endswith("IqError") or hasattr(exc, "condition"):
        raw_condition = getattr(exc, "condition", None)
        condition = str(raw_condition or "").strip()
        if not condition:
            fallback = str(exc).strip().lower()
            if fallback and fallback.replace("-", "").isalnum() and " " not in fallback:
                condition = fallback
        condition = condition or "unknown"
        text = str(getattr(exc, "text", "") or "").strip() or None
        return "iq-error", condition, text, condition in _DEFAULT_TRANSIENT_CONDITIONS
    detail = str(exc).strip()
    message = f"{name}: {detail}" if detail else name
    return "error", None, message, False


def _accepts_keyword(callable_obj: Any, keyword: str) -> bool:
    """Return whether a callable's inspectable signature accepts a keyword."""
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return True
    if keyword in signature.parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _normalize_result_items(result: Any) -> tuple[Any, ...]:
    """Extract affiliation items from common Slixmpp result shapes."""
    if result is None:
        return ()

    try:
        query = result["mucadmin_query"]
    except (KeyError, TypeError, AttributeError, IndexError):
        query = None
    if query is not None:
        try:
            items = query["items"]
        except (KeyError, TypeError, AttributeError, IndexError):
            items = None
        if items is not None:
            return tuple(items)

    get = getattr(result, "get", None)
    if callable(get):
        try:
            query = get("mucadmin_query")
        except (KeyError, TypeError, AttributeError):
            query = None
        if isinstance(query, dict) and query.get("items") is not None:
            return tuple(query["items"])

    if isinstance(result, dict):
        return tuple(result.values())
    if isinstance(result, (str, bytes)):
        return (result,)
    try:
        return tuple(result)
    except TypeError:
        return (result,)


async def _request_affiliation(
    muc_plugin: Any,
    room: str,
    affiliation: str,
    *,
    timeout: float,
) -> tuple[Any, ...]:
    getter = getattr(muc_plugin, "get_affiliation_list", None)
    if callable(getter):
        if _accepts_keyword(getter, "timeout"):
            result = await _maybe_await(getter(room, affiliation, timeout=timeout))
        else:
            result = await asyncio.wait_for(
                _maybe_await(getter(room, affiliation)),
                timeout=timeout,
            )
        return _normalize_result_items(result)

    legacy = getattr(muc_plugin, "get_users_by_affiliation", None)
    if not callable(legacy):
        raise TypeError("XEP-0045 affiliation query is unavailable")
    result = await asyncio.wait_for(_maybe_await(legacy(room, affiliation)), timeout=timeout)
    return _normalize_result_items(result)


async def query_muc_affiliation(
    muc_plugin: Any,
    room: str,
    affiliation: str,
    *,
    options: AffiliationQueryOptions | None = None,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> AffiliationQueryResult:
    """Query one MUC affiliation with bounded retries and sanitized errors."""
    policy = (options or AffiliationQueryOptions()).normalized()
    last: AffiliationQueryResult | None = None
    retry_reasons: list[str] = []
    for attempt in range(1, policy.attempts + 1):
        try:
            items = await _request_affiliation(
                muc_plugin,
                str(room),
                str(affiliation),
                timeout=policy.timeout_seconds,
            )
            return AffiliationQueryResult(
                room=str(room),
                affiliation=str(affiliation),
                ok=True,
                items=items,
                attempts=attempt,
                retry_reasons=tuple(retry_reasons),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize third-party IQ failures
            kind, condition, message, default_retryable = _exception_kind(exc)
            retryable = default_retryable
            if kind == "iq-error" and condition is not None:
                retryable = condition in policy.transient_conditions
            timeout_message = f"IQ timeout after {policy.timeout_seconds:g}s" if kind == "timeout" else message
            last = AffiliationQueryResult(
                room=str(room),
                affiliation=str(affiliation),
                ok=False,
                items=(),
                attempts=attempt,
                error_kind=kind,
                error_condition=condition,
                error_message=timeout_message,
                retryable=retryable,
                retry_reasons=tuple(retry_reasons),
            )
            if not retryable or attempt >= policy.attempts:
                return last
            retry_reasons.append(last.summary)
            if policy.retry_delay_seconds:
                await sleep(policy.retry_delay_seconds)
    assert last is not None
    return last
