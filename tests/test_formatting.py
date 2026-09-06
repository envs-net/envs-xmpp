from __future__ import annotations

import pytest

from envs_xmpp_core.formatting import format_bytes, format_duration


def test_format_duration_supports_domain_specific_zero_label():
    assert format_duration(0) == "0s"
    assert format_duration(-5, zero_label="permanent") == "permanent"
    assert format_duration(3661) == "1h 1m 1s"
    assert format_duration(24 * 3600 + 60) == "1d 1m"


def test_format_bytes_supports_negative_policy_and_unit_cap():
    assert format_bytes(0) == "0 B"
    assert format_bytes(0, bytes_decimals=1) == "0.0 B"
    assert format_bytes(-1) == "unknown"
    assert format_bytes(-1, negative_label=None) == "-1 B"
    assert format_bytes(2048) == "2.0 KiB"
    assert format_bytes(1024**3, max_unit="MiB") == "1024.0 MiB"
    assert format_bytes(1024**4) == "1.0 TiB"


def test_format_bytes_rejects_unknown_unit():
    with pytest.raises(ValueError, match="Unsupported max_unit"):
        format_bytes(1, max_unit="ZiB")
