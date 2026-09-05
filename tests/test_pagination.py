from envs_xmpp_core.pagination import PageSlice, paginate, resolve_page


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
