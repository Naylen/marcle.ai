"""Email service for sending answers to users."""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.env_utils import get_env

logger = logging.getLogger("marcle.ask.email")

SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = get_env("SMTP_USER", "")
SMTP_PASS: str = get_env("SMTP_PASS", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "")
SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}


def _validate_email_config() -> tuple[bool, str | None]:
    missing: list[str] = []
    if not SMTP_HOST.strip():
        missing.append("SMTP_HOST")
    if not SMTP_USER.strip():
        missing.append("SMTP_USER")
    if not SMTP_PASS.strip():
        missing.append("SMTP_PASS")
    if not SMTP_FROM.strip():
        missing.append("SMTP_FROM")
    if missing:
        return False, f"Missing SMTP config: {', '.join(missing)}"
    return True, None


def send_custom_email_result(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    question_id: int | None = None,
    log_context: str = "",
) -> tuple[bool, str | None]:
    """Send a custom email via SMTP and return (ok, error)."""
    config_ok, config_error = _validate_email_config()
    if not config_ok:
        logger.warning(
            "ask_email_send_skipped recipient=%s question_id=%s reason=%s",
            to_email,
            question_id if question_id is not None else "none",
            config_error,
        )
        return False, config_error

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if SMTP_USE_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

        logger.info(
            "ask_email_send_success recipient=%s question_id=%s context=%s",
            to_email,
            question_id if question_id is not None else "none",
            log_context or "none",
        )
        return True, None
    except Exception as exc:
        error_text = f"{exc.__class__.__name__}: {exc}"
        logger.exception(
            "ask_email_send_failure recipient=%s question_id=%s error_type=%s error=%s context=%s",
            to_email,
            question_id if question_id is not None else "none",
            exc.__class__.__name__,
            str(exc),
            log_context or "none",
        )
        return False, error_text


def send_custom_email(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str,
    question_id: int | None = None,
    log_context: str = "",
) -> bool:
    """Send a custom email via SMTP. Returns True on success."""
    ok, _error = send_custom_email_result(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        question_id=question_id,
        log_context=log_context,
    )
    return ok


def send_answer_email(
    *,
    to_email: str,
    to_name: str,
    question_text: str,
    answer_text: str,
    question_id: int,
) -> bool:
    """Send the answer to the user via SMTP. Returns True on success."""
    subject = f"Your question on marcle.ai has been answered (#{question_id})"

    # Plain text body
    text_body = (
        f"Hi {to_name},\n\n"
        f"Your question has been answered!\n\n"
        f"--- Your Question ---\n{question_text}\n\n"
        f"--- Answer ---\n{answer_text}\n\n"
        f"Thanks for using marcle.ai!\n"
        f"— Marc\n"
    )

    # HTML body
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #e5ecf5; background: #0c1117;">
  <div style="background: #161b22; border-radius: 12px; padding: 24px; border: 1px solid rgba(255,255,255,0.08);">
    <h2 style="color: #4ade80; margin-top: 0;">Your Question Has Been Answered!</h2>
    <p style="color: #8b949e;">Hi {to_name},</p>

    <div style="background: #0d1117; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 3px solid #5865F2;">
      <p style="color: #8b949e; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase;">Your Question</p>
      <p style="color: #e5ecf5; margin: 0;">{question_text}</p>
    </div>

    <div style="background: #0d1117; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 3px solid #4ade80;">
      <p style="color: #8b949e; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase;">Answer</p>
      <p style="color: #e5ecf5; margin: 0;">{answer_text}</p>
    </div>

    <p style="color: #8b949e; margin-bottom: 0;">Thanks for using marcle.ai!<br>&mdash; Marc</p>
  </div>
</body>
</html>"""

    return send_custom_email(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        question_id=question_id,
        log_context=f"question_id={question_id}",
    )
