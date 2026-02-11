import logging

import app.ask_services.email as email_module


class _FakeSMTP:
    last_instance = None

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.login_args = None
        self.sent_message = None
        self.starttls_called = False
        _FakeSMTP.last_instance = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ehlo(self):
        return None

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent_message = msg


def test_send_custom_email_result_uses_smtp_user_for_auth_and_smtp_from_sender(monkeypatch, caplog):
    monkeypatch.setattr(email_module, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_module, "SMTP_PORT", 587)
    monkeypatch.setattr(email_module, "SMTP_USER", "icloud-user@example.com")
    monkeypatch.setattr(email_module, "SMTP_PASS", "app-pass")
    monkeypatch.setattr(email_module, "SMTP_FROM", "support@custom-domain.example")
    monkeypatch.setattr(email_module, "SMTP_USE_TLS", True)
    monkeypatch.setattr(email_module.smtplib, "SMTP", _FakeSMTP)

    with caplog.at_level(logging.INFO):
        ok, error = email_module.send_custom_email_result(
            to_email="recipient@example.com",
            subject="Test Subject",
            text_body="plain body",
            html_body="<p>html body</p>",
            question_id=42,
            log_context="unit_test",
        )

    assert ok is True
    assert error is None

    smtp = _FakeSMTP.last_instance
    assert smtp is not None
    assert smtp.login_args == ("icloud-user@example.com", "app-pass")
    assert smtp.sent_message is not None
    assert smtp.sent_message["From"] == "support@custom-domain.example"
    assert smtp.starttls_called is True

    success_logs = [rec for rec in caplog.records if rec.message.startswith("ask_email_send_success")]
    assert success_logs
    assert "recipient@example.com" in success_logs[0].message
    assert "42" in success_logs[0].message


def test_send_custom_email_result_logs_failure_with_stacktrace(monkeypatch, caplog):
    class _BoomSMTP(_FakeSMTP):
        def send_message(self, msg):
            raise RuntimeError("smtp send failed")

    monkeypatch.setattr(email_module, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_module, "SMTP_PORT", 587)
    monkeypatch.setattr(email_module, "SMTP_USER", "icloud-user@example.com")
    monkeypatch.setattr(email_module, "SMTP_PASS", "app-pass")
    monkeypatch.setattr(email_module, "SMTP_FROM", "support@custom-domain.example")
    monkeypatch.setattr(email_module, "SMTP_USE_TLS", True)
    monkeypatch.setattr(email_module.smtplib, "SMTP", _BoomSMTP)

    with caplog.at_level(logging.ERROR):
        ok, error = email_module.send_custom_email_result(
            to_email="recipient@example.com",
            subject="Test Subject",
            text_body="plain body",
            html_body="<p>html body</p>",
            question_id=99,
            log_context="unit_test_failure",
        )

    assert ok is False
    assert error is not None
    assert "RuntimeError" in error
    failure_logs = [rec for rec in caplog.records if rec.message.startswith("ask_email_send_failure")]
    assert failure_logs
    assert failure_logs[0].exc_info is not None

