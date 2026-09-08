from envs_xmpp_core.security.redaction import REDACTED, redact_text, redact_url, redact_value


def test_redact_value_handles_nested_secrets_and_url_userinfo() -> None:
    value = {
        "password": "hunter2",
        "items": [
            "https://user:pass@example.org/path",
            {"token": "abc"},
        ],
    }
    redacted = redact_value(value)
    assert redacted["password"] == REDACTED
    assert redacted["items"] == ["https://example.org/path", {"token": REDACTED}]


def test_redact_text_redacts_assignments_without_redacting_plain_words() -> None:
    assert redact_text("password=secret token=abc") == "password=<redacted> token=<redacted>"
    assert redact_text("secret") == "secret"
    assert redact_text("token") == "token"


def test_redact_url_is_robust_to_invalid_port() -> None:
    value = "https://user:pass@example.org:notaport/path"
    assert redact_url(value) == value


def test_redaction_truncates_deterministically() -> None:
    assert redact_text("abcdef", max_length=5) == "ab..."
    assert redact_text("abcdef", max_length=2) == "ab"
