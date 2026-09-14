"""Neutral pagination primitives shared by XMPP bot frontends."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class PageSlice[T]:
    """One normalized page of materialized items."""

    items: list[T]
    page: int
    total_pages: int
    total_items: int
    page_size: int



@dataclass(frozen=True)
class PageRequest:
    """Shared optional page selector used by operator commands."""

    page: int = 1
    all: bool = False
    page_size: int | None = None


def parse_page_request(
    args: Sequence[str],
    *,
    default: PageRequest | None = None,
) -> tuple[PageRequest, list[str]]:
    """Parse one leading ``all|last|<page>`` token and return leftovers."""
    remaining = [str(value).strip() for value in args if str(value).strip()]
    fallback = default or PageRequest()
    if not remaining:
        return fallback, []
    token = remaining[0].lower()
    if token == "all":
        return PageRequest(all=True, page_size=fallback.page_size), remaining[1:]
    if token == "last":
        return PageRequest(page=-1, page_size=fallback.page_size), remaining[1:]
    try:
        page = int(token)
    except ValueError:
        return fallback, remaining
    if page < 1:
        return fallback, remaining
    return PageRequest(page=page, page_size=fallback.page_size), remaining[1:]


def format_page(
    title: str,
    entries: Sequence[str] | Iterable[str],
    *,
    page_request: PageRequest | None = None,
    page_size: int = 10,
    command_hint: str | None = None,
    preamble: Sequence[str] | Iterable[str] = (),
) -> list[str]:
    """Render a title, persistent preamble, and paginated operator entries."""
    request = page_request or PageRequest()
    materialized = list(entries)
    preamble_rows = list(preamble)
    if request.all:
        return [title, *preamble_rows, *(materialized or ["—"])]

    effective_page_size = request.page_size if request.page_size is not None else page_size
    result = paginate(
        materialized,
        page=request.page,
        page_size=effective_page_size,
        last_page_sentinel=-1,
    )
    suffix = f" (page {result.page}/{result.total_pages})" if result.total_pages > 1 else ""
    lines = [title + suffix, *preamble_rows, *(result.items or ["—"])]
    if result.total_pages > 1 and command_hint:
        lines.append(f"Use {command_hint} <page|last|all> for more.")
    return lines

def resolve_page(
    page: int,
    *,
    total_items: int,
    page_size: int,
    last_page_sentinel: int | None = -1,
) -> tuple[int, int]:
    """Return normalized page and total pages for a positive page size."""
    page_size = max(1, int(page_size))
    total_pages = max(1, ceil(max(0, int(total_items)) / page_size))
    if last_page_sentinel is not None and page == last_page_sentinel:
        return total_pages, total_pages
    return min(max(int(page), 1), total_pages), total_pages


def paginate[T](
    items: Sequence[T] | Iterable[T],
    *,
    page: int = 1,
    page_size: int = 10,
    fallback_page_size: int = 10,
    last_page_sentinel: int | None = -1,
) -> PageSlice[T]:
    """Materialize items and return a normalized page slice."""
    materialized = list(items)
    normalized_size = int(page_size)
    if normalized_size <= 0:
        normalized_size = max(1, int(fallback_page_size))

    current_page, total_pages = resolve_page(
        page,
        total_items=len(materialized),
        page_size=normalized_size,
        last_page_sentinel=last_page_sentinel,
    )
    start = (current_page - 1) * normalized_size
    end = start + normalized_size
    return PageSlice(
        items=materialized[start:end],
        page=current_page,
        total_pages=total_pages,
        total_items=len(materialized),
        page_size=normalized_size,
    )
