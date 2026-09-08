from envs_xmpp_core.runtime.diagnostics import diagnostic_error, diagnostic_payload, exception_summary


def test_exception_summary_redacts_and_falls_back_to_type() -> None:
    assert exception_summary(RuntimeError("token=abc failed")) == "token=<redacted> failed"
    assert exception_summary(RuntimeError()) == "RuntimeError"


def test_diagnostic_error_and_payload_are_operator_safe() -> None:
    error = diagnostic_error(ValueError("https://user:pass@example.org/path"))
    assert error.as_dict() == {
        "type": "ValueError",
        "message": "https://example.org/path",
    }
    assert diagnostic_payload({"password": "secret", "status": "ok"}) == {
        "password": "<redacted>",
        "status": "ok",
    }
