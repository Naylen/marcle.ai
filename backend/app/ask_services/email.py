"""Email service for sending answers to users."""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("marcle.ask.email")

SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASS: str = os.getenv("SMTP_PASS", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", "")
SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}


def send_answer_email(
    *,
    to_email: str,
    to_name: str,
    question_text: str,
    answer_text: str,
    question_id: int,
) -> bool:
    """Send the answer to the user via SMTP. Returns True on success."""
    if not SMTP_HOST:
        logger.warning("SMTP_HOST not set; skipping email send")
        return False

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

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or SMTP_USER
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if SMTP_USE_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if SMTP_USER:
                    server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_USER:
                    server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)

        logger.info("Answer email sent to %s for question_id=%d", to_email, question_id)
        return True
    except Exception:
        logger.exception("Failed to send email to %s for question_id=%d", to_email, question_id)
        return False
