import logging

from app.log_redact import SecretRedactionFilter, redact_text, redact_url


def test_redact_url_masks_sensitive_query_values():
    raw_url = "http://example.test/api/v2?cmd=status&apikey=abc123&X-Plex-Token=def456"
    redacted = redact_url(raw_url)

    assert "cmd=status" in redacted
    assert "apikey=***" in redacted
    assert "X-Plex-Token=***" in redacted
    assert "abc123" not in redacted
    assert "def456" not in redacted


def test_redact_text_masks_url_bearer_and_key_value_patterns():
    message = (
        "HTTP Request: GET http://example.test/check?access_token=abc123 "
        "Authorization: Bearer qwerty token=zzzz"
    )
    redacted = redact_text(message)

    assert "access_token=***" in redacted
    assert "Bearer ***" in redacted
    assert "token=***" in redacted
    assert "abc123" not in redacted
    assert "qwerty" not in redacted
    assert "zzzz" not in redacted


def test_secret_redaction_filter_sanitizes_formatted_message():
    record = logging.LogRecord(
        name="unit-test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="probe url=%s",
        args=("http://example.test/ping?apikey=plain-secret",),
        exc_info=None,
    )

    filter_instance = SecretRedactionFilter()
    assert filter_instance.filter(record) is True
    assert "apikey=***" in record.msg
    assert "plain-secret" not in record.msg
    assert record.args == ()
