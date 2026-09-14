from envs_xmpp_core.pagination import (
    PageRequest,
    PageSlice,
    format_page,
    paginate,
    parse_page_request,
    resolve_page,
)


def test_paginate_normalizes_pages_and_supports_last_sentinel():
    result = paginate(["a", "b", "c", "d", "e"], page=-1, page_size=2)
    assert result == PageSlice(
        items=["e"],
        page=3,
        total_pages=3,
        total_items=5,
        page_size=2,
    )


def test_paginate_uses_fallback_for_non_positive_page_size():
    result = paginate(["a", "b", "c"], page=99, page_size=0, fallback_page_size=10)
    assert result.items == ["a", "b", "c"]
    assert result.page == 1
    assert result.total_pages == 1
    assert result.total_items == 3
    assert result.page_size == 10


def test_resolve_page_can_disable_last_page_sentinel():
    current, total = resolve_page(
        -1,
        total_items=5,
        page_size=2,
        last_page_sentinel=None,
    )
    assert (current, total) == (1, 3)


def test_parse_page_request_and_format_page():
    request, remaining = parse_page_request(["last", "extra"])
    assert request == PageRequest(page=-1)
    assert remaining == ["extra"]
    assert format_page(
        "Rooms",
        ["one", "two", "three"],
        page_request=PageRequest(page=2),
        page_size=2,
        preamble=["Summary", "Legend"],
    ) == [
        "Rooms (page 2/2)",
        "Summary",
        "Legend",
        "three",
    ]


def test_parse_page_request_preserves_configured_page_size():
    default = PageRequest(page=1, page_size=20)
    assert parse_page_request(["2"], default=default)[0] == PageRequest(page=2, page_size=20)
    assert parse_page_request(["last"], default=default)[0] == PageRequest(page=-1, page_size=20)
    assert parse_page_request(["all"], default=default)[0] == PageRequest(all=True, page_size=20)


def test_format_page_prefers_page_request_page_size():
    lines = [f"item-{i}" for i in range(25)]
    rendered = format_page(
        "Items",
        lines,
        page_request=PageRequest(page=2, page_size=20),
        page_size=10,
    )
    assert rendered[0] == "Items (page 2/2)"
    assert rendered[1:] == [f"item-{i}" for i in range(20, 25)]
