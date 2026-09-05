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
