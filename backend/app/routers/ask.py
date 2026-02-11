"""Ask app router — question submission, OAuth, answers, admin."""

import asyncio
import html
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from app import config as app_config
from app.ask_db import (
    DEFAULT_STARTING_POINTS,
    POINTS_PER_QUESTION,
    get_db,
)
from app.ask_services.discord import post_question_to_discord
from app.ask_services.email import send_answer_email, send_custom_email, send_custom_email_result
from app.ask_services.llm import generate_local_answer_text, generate_openai_answer_text
from app.ask_services.google_oauth import GOOGLE_REDIRECT_URL, exchange_code, get_login_url, get_user_info
from app.discord_client import post_answer_to_discord

logger = logging.getLogger("marcle.ask")

router = APIRouter(prefix="/api/ask", tags=["ask"])

# --- Config ---
SESSION_SECRET: str = os.getenv("SESSION_SECRET", "change-me-in-production")
ASK_ANSWER_WEBHOOK_SECRET: str = os.getenv("ASK_ANSWER_WEBHOOK_SECRET", "")
BASE_PUBLIC_URL: str = os.getenv("BASE_PUBLIC_URL", "")
ASK_HUMAN_WAIT_SECONDS: int = max(int(app_config.ASK_HUMAN_WAIT_SECONDS), 1)
ASK_OPENAI_WAIT_SECONDS: int = max(int(app_config.ASK_OPENAI_WAIT_SECONDS), ASK_HUMAN_WAIT_SECONDS)
ASK_FALLBACK_SWEEP_SECONDS: int = int(os.getenv("ASK_FALLBACK_SWEEP_SECONDS", "10"))
ASK_POINTS_ENABLED: bool = app_config.ASK_POINTS_ENABLED
ASK_SESSION_MAX_AGE_SECONDS: int = 86400
ASK_CSRF_COOKIE_NAME: str = "ask_csrf"
ASK_WEBHOOK_MAX_BYTES: int = int(os.getenv("ASK_WEBHOOK_MAX_BYTES", str(64 * 1024)))

# Rate limiting: per-user, in-memory
_rate_limit_window: int = 60  # seconds
_rate_limit_max: int = 5  # max questions per window
_rate_limits: dict[int, list[float]] = defaultdict(list)

# In-memory session store (simple; production should use Redis or signed cookies)
# Maps session_token -> {user_id, google_id, email, name, picture_url, created_at}
_sessions: dict[str, dict] = {}

# OAuth state tokens (nonce -> metadata)
_oauth_states: dict[str, dict[str, str | float]] = {}

# SSE subscribers by question_id
_sse_subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
_sse_lock = asyncio.Lock()

# Ask background loop task
_ask_fallback_task: asyncio.Task | None = None
_llm_inflight_question_ids: set[int] = set()


# --- Pydantic Models ---
class QuestionRequest(BaseModel):
    question_text: str = Field(..., min_length=10, max_length=5000)


class AnswerRequest(BaseModel):
    question_id: int
    answer_text: str = Field(..., min_length=1, max_length=10000)


class DiscordQuestionRequest(BaseModel):
    guild_id: str | None = Field(default=None, max_length=64)
    channel_id: str | None = Field(default=None, max_length=64)
    message_id: str | None = Field(default=None, min_length=1, max_length=64)
    thread_id: str | None = Field(default=None, max_length=64)
    discord_guild_id: str | None = Field(default=None, max_length=64)
    discord_channel_id: str | None = Field(default=None, max_length=64)
    discord_message_id: str | None = Field(default=None, min_length=1, max_length=64)
    discord_thread_id: str | None = Field(default=None, max_length=64)
    author_id: str | None = Field(default=None, max_length=128)
    author_name: str | None = Field(default=None, max_length=255)
    author_email: str | None = Field(default=None, max_length=320)
    content: str = Field(..., min_length=1, max_length=10000)
    timestamp: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def _normalize_aliases(self):
        self.discord_guild_id = (self.discord_guild_id or self.guild_id or "").strip() or None
        self.discord_channel_id = (self.discord_channel_id or self.channel_id or "").strip() or None
        self.discord_thread_id = (self.discord_thread_id or self.thread_id or "").strip() or None
        self.discord_message_id = (self.discord_message_id or self.message_id or "").strip() or None
        if not self.discord_message_id:
            raise ValueError("discord_message_id (or message_id) is required")
        return self


class DiscordAnswerRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    answer_message_id: str | None = Field(default=None, max_length=64)
    guild_id: str | None = Field(default=None, max_length=64)
    channel_id: str | None = Field(default=None, max_length=64)
    reply_to_message_id: str | None = Field(default=None, max_length=64)
    thread_id: str | None = Field(default=None, max_length=64)
    answer_text: str | None = Field(default=None, min_length=1, max_length=10000)
    discord_answer_message_id: str | None = Field(default=None, max_length=64)
    discord_guild_id: str | None = Field(default=None, max_length=64)
    discord_channel_id: str | None = Field(default=None, max_length=64)
    author_role_ids: list[str] | None = Field(default=None)
    member_role_ids: list[str] | None = Field(default=None)
    question_permalink: str | None = Field(default=None, max_length=1000)
    thread_permalink: str | None = Field(default=None, max_length=1000)
    answer_permalink: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _validate_lookup_fields(self):
        self.answer_text = (self.answer_text or self.content or "").strip() or None
        if not self.answer_text:
            raise ValueError("answer_text (or content) is required")
        self.discord_answer_message_id = (self.discord_answer_message_id or self.answer_message_id or "").strip() or None
        self.discord_guild_id = (self.discord_guild_id or self.guild_id or "").strip() or None
        self.discord_channel_id = (self.discord_channel_id or self.channel_id or "").strip() or None
        reply_to = (self.reply_to_message_id or "").strip()
        thread_id = (self.thread_id or "").strip()
        if not (reply_to or thread_id):
            raise ValueError("Either reply_to_message_id or thread_id must be provided")
        self.reply_to_message_id = reply_to or None
        self.thread_id = thread_id or None
        # Normalize role id aliases coming from discord/n8n payloads.
        if not self.author_role_ids and self.member_role_ids:
            self.author_role_ids = self.member_role_ids
        self.author_role_ids = [str(role).strip() for role in (self.author_role_ids or []) if str(role).strip()]
        return self


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    picture_url: str
    points: int


class QuestionResponse(BaseModel):
    id: int
    question_text: str
    answer_text: str | None
    points_spent: int
    status: str
    created_at: str
    answered_at: str | None


# --- Helpers ---
def _create_session(user_row: dict) -> str:
    """Create a session token for an authenticated user."""
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user_id": user_row["id"],
        "google_id": user_row["google_id"],
        "email": user_row["email"],
        "name": user_row["name"],
        "picture_url": user_row["picture_url"],
        "csrf_token": csrf_token,
        "created_at": time.time(),
    }
    logger.debug("ask_session_created user_id=%s", user_row["id"])
    logger.debug("ask_csrf_generated user_id=%s", user_row["id"])
    return token


def _get_session(token: str | None) -> dict | None:
    """Retrieve session data from token."""
    if not token:
        return None
    session = _sessions.get(token)
    if session is None:
        return None
    # Sessions expire after 24 hours
    if time.time() - session["created_at"] > ASK_SESSION_MAX_AGE_SECONDS:
        user_id = session.get("user_id")
        _sessions.pop(token, None)
        logger.debug("ask_session_expired user_id=%s", user_id)
        return None
    return session


def _unauthorized_response() -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"error": "unauthorized"})


def _invalid_csrf_response() -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"error": "invalid_csrf"})


def _get_session_or_none(ask_session: str | None = None, request: Request | None = None) -> dict | None:
    token = ask_session
    if token is None and request is not None:
        token = request.cookies.get("ask_session")
    return _get_session(token)


def _ensure_session_csrf(session: dict) -> str:
    token = str(session.get("csrf_token") or "").strip()
    if token:
        return token
    token = secrets.token_urlsafe(32)
    session["csrf_token"] = token
    logger.debug("ask_csrf_generated user_id=%s", session.get("user_id"))
    return token


def _set_csrf_cookie(response: Response, *, secure: bool, token: str) -> str:
    response.set_cookie(
        key=ASK_CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        samesite="lax",
        secure=secure,
        max_age=ASK_SESSION_MAX_AGE_SECONDS,
        expires=ASK_SESSION_MAX_AGE_SECONDS,
        path="/",
    )
    return token


def _validate_csrf(
    *,
    session: dict,
    x_csrf_token: str,
    ask_csrf: str | None,
) -> bool:
    cookie_token = (ask_csrf or "").strip()
    header_token = (x_csrf_token or "").strip()
    session_token = _ensure_session_csrf(session)
    if not cookie_token or not header_token:
        logger.debug(
            "ask_csrf_mismatch reason=missing_token user_id=%s cookie_present=%s header_present=%s",
            session.get("user_id"),
            bool(cookie_token),
            bool(header_token),
        )
        return False
    if not hmac.compare_digest(header_token, cookie_token):
        logger.debug(
            "ask_csrf_mismatch reason=header_cookie user_id=%s",
            session.get("user_id"),
        )
        return False
    if not hmac.compare_digest(header_token, session_token):
        logger.debug(
            "ask_csrf_mismatch reason=session_cookie user_id=%s",
            session.get("user_id"),
        )
        return False
    return True


def _public_question_status(question_row: dict[str, Any]) -> str:
    """Map internal question row to stable public status."""
    return "answered" if question_row.get("answer_text") else "pending"


def _serialize_question_snapshot(question_row: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized snapshot payload for SSE."""
    has_answer = bool(question_row.get("answer_text"))
    return {
        "id": question_row["id"],
        "status": _public_question_status(question_row),
        "question_text": question_row.get("question_text"),
        "answer_text": question_row.get("answer_text"),
        "created_at": question_row.get("created_at"),
        "answered_at": question_row.get("answered_at"),
        "deadline_at": question_row.get("deadline_at"),
        "answered_by": question_row.get("answered_by") if has_answer else None,
    }


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _subscribe_question(question_id: int) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    async with _sse_lock:
        _sse_subscribers[question_id].add(queue)
    return queue


async def _unsubscribe_question(question_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
    async with _sse_lock:
        subscribers = _sse_subscribers.get(question_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            _sse_subscribers.pop(question_id, None)


async def _publish_question_event(question_id: int, event_name: str, payload: dict[str, Any]) -> None:
    async with _sse_lock:
        subscribers = list(_sse_subscribers.get(question_id, set()))
    if not subscribers:
        return
    message = {"event": event_name, "payload": payload}
    for queue in subscribers:
        queue.put_nowait(message)


def _fetch_question_for_user_sync(question_id: int, user_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM questions WHERE id = ? AND user_id = ?",
            (question_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def _fetch_question_by_id_sync(question_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        return dict(row) if row else None


async def _publish_snapshot(question_id: int) -> None:
    row = await asyncio.to_thread(_fetch_question_by_id_sync, question_id)
    if not row:
        return
    await _publish_question_event(question_id, "snapshot", _serialize_question_snapshot(row))


async def _publish_status(question_id: int) -> None:
    row = await asyncio.to_thread(_fetch_question_by_id_sync, question_id)
    if not row:
        return
    await _publish_question_event(
        question_id,
        "status",
        {
            "status": _public_question_status(row),
            "deadline_at": row.get("deadline_at"),
        },
    )


async def _publish_answer(question_id: int) -> None:
    row = await asyncio.to_thread(_fetch_question_by_id_sync, question_id)
    if not row or not row.get("answer_text"):
        return
    await _publish_question_event(
        question_id,
        "answer",
        {
            "answer_text": row.get("answer_text"),
            "answered_at": row.get("answered_at"),
            "answered_by": row.get("answered_by"),
            "status": "answered",
        },
    )


def _check_rate_limit(user_id: int) -> None:
    """Enforce per-user rate limiting on question submissions."""
    now = time.time()
    # Prune old entries
    _rate_limits[user_id] = [t for t in _rate_limits[user_id] if now - t < _rate_limit_window]
    if len(_rate_limits[user_id]) >= _rate_limit_max:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Max {_rate_limit_max} questions per {_rate_limit_window}s.",
        )
    _rate_limits[user_id].append(now)


def _cleanup_expired_oauth_states() -> None:
    """Remove OAuth state tokens older than 10 minutes."""
    now = time.time()
    expired = [k for k, v in _oauth_states.items() if now - float(v.get("created_at", 0.0)) > 600]
    for k in expired:
        _oauth_states.pop(k, None)


def _normalize_base_url(url: str) -> str:
    """Normalize a public base URL by trimming path/query/fragment and trailing slash."""
    candidate = url.strip().rstrip("/")
    if "://" not in candidate:
        candidate = f"https://{candidate.lstrip('/')}"
    parsed = urllib.parse.urlparse(candidate)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def _get_public_base_url(request: Request) -> str:
    """Resolve external base URL from config or request headers."""
    configured = BASE_PUBLIC_URL.strip()
    if configured:
        normalized = _normalize_base_url(configured)
        if normalized:
            return normalized

    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    scheme = forwarded_proto or request.url.scheme
    host = forwarded_host or request.headers.get("host", "") or request.url.netloc
    return _normalize_base_url(f"{scheme}://{host}")


def _get_oauth_redirect_uri(request: Request) -> str:
    """Resolve OAuth callback URI (explicit GOOGLE_REDIRECT_URL wins)."""
    configured_redirect = GOOGLE_REDIRECT_URL.strip()
    if configured_redirect:
        return configured_redirect
    return f"{_get_public_base_url(request)}/api/ask/auth/callback"


def _require_n8n_token(x_n8n_token: str = Header(default="", alias="X-N8N-TOKEN")) -> None:
    """Validate n8n shared token for Discord integration endpoints."""
    n8n_token = os.getenv("N8N_TOKEN", "")
    if not n8n_token or not hmac.compare_digest(x_n8n_token, n8n_token):
        logger.warning("ask_webhook_rejected reason=invalid_n8n_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid n8n token",
        )


async def _require_webhook_size_limit(request: Request) -> None:
    limit = max(ASK_WEBHOOK_MAX_BYTES, 1024)
    content_length_header = (request.headers.get("content-length") or "").strip()
    if content_length_header:
        try:
            content_length = int(content_length_header)
        except ValueError:
            logger.warning(
                "ask_webhook_rejected reason=invalid_content_length path=%s header=%s",
                request.url.path,
                content_length_header[:64],
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Length")
        if content_length > limit:
            logger.warning(
                "ask_webhook_rejected reason=payload_too_large path=%s content_length=%d limit=%d",
                request.url.path,
                content_length,
                limit,
            )
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large")
        return

    body = await request.body()
    if len(body) > limit:
        logger.warning(
            "ask_webhook_rejected reason=payload_too_large path=%s body_len=%d limit=%d",
            request.url.path,
            len(body),
            limit,
        )
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Payload too large")


def _is_admin_override_token(token: str) -> bool:
    candidate = (token or "").strip()
    admin_token = os.getenv("ADMIN_TOKEN", "").strip()
    if not candidate or not admin_token:
        return False
    return hmac.compare_digest(candidate, admin_token)


def _has_support_role(role_ids: list[str]) -> bool:
    required_role = os.getenv("DISCORD_SUPPORT_ROLE_ID", "").strip()
    if not required_role:
        return True
    normalized = {role_id.strip() for role_id in role_ids if role_id and role_id.strip()}
    return required_role in normalized


def _discord_placeholder_email(author_id: str | None) -> str:
    """Build a deterministic fallback email for Discord-origin records."""
    safe_author = "".join(ch for ch in (author_id or "unknown") if ch.isalnum() or ch in {"-", "_"})
    if not safe_author:
        safe_author = "unknown"
    return f"{safe_author}@discord.local"


def _question_preview(question_text: str, limit: int = 72) -> str:
    collapsed = " ".join(question_text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 3]}..."


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_deadlines(created_at: datetime) -> tuple[datetime, datetime]:
    human_deadline_at = created_at + timedelta(seconds=ASK_HUMAN_WAIT_SECONDS)
    openai_deadline_at = created_at + timedelta(seconds=ASK_OPENAI_WAIT_SECONDS)
    if openai_deadline_at < human_deadline_at:
        openai_deadline_at = human_deadline_at
    return human_deadline_at, openai_deadline_at


def _resolve_deadlines(question_row: dict[str, Any]) -> tuple[datetime, datetime]:
    created_at = _parse_datetime(str(question_row.get("created_at") or "")) or datetime.now(timezone.utc)
    default_human_deadline, default_openai_deadline = _build_deadlines(created_at)
    legacy_deadline = _parse_datetime(str(question_row.get("deadline_at") or ""))
    human_deadline = (
        _parse_datetime(str(question_row.get("human_deadline_at") or ""))
        or legacy_deadline
        or default_human_deadline
    )
    openai_deadline = _parse_datetime(str(question_row.get("openai_deadline_at") or "")) or default_openai_deadline
    if openai_deadline < human_deadline:
        openai_deadline = human_deadline
    return human_deadline, openai_deadline


async def _publish_status_value(
    question_id: int,
    status_value: str,
    *,
    detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    row = await asyncio.to_thread(_fetch_question_by_id_sync, question_id)
    payload: dict[str, Any] = {"status": status_value}
    if row is not None:
        payload["deadline_at"] = row.get("deadline_at")
    if detail:
        payload["detail"] = detail[:300]
    if extra:
        payload.update(extra)
    await _publish_question_event(question_id, "status", payload)


async def _publish_failure_status(question_id: int, status_value: str, *, detail: str | None = None) -> None:
    await _publish_status_value(question_id, status_value, detail=detail)


def _build_discord_answer_email(
    *,
    to_name: str,
    question_text: str,
    answer_text: str,
    question_permalink: str | None,
    thread_permalink: str | None,
    answer_permalink: str | None,
) -> tuple[str, str, str]:
    """Create subject + plain/html bodies for Discord answer notifications."""
    preview = _question_preview(question_text)
    subject = f"Answer: {preview}"

    link_pairs = [
        ("Question permalink", question_permalink),
        ("Thread permalink", thread_permalink),
        ("Answer permalink", answer_permalink),
    ]
    present_links = [(label, value) for label, value in link_pairs if value]

    text_body = (
        f"Hi {to_name},\n\n"
        "A Discord question has been answered.\n\n"
        f"--- Question ---\n{question_text}\n\n"
        f"--- Answer ---\n{answer_text}\n"
    )
    if present_links:
        text_body += "\n--- Discord Links ---\n"
        text_body += "\n".join(f"{label}: {value}" for label, value in present_links)
        text_body += "\n"

    html_question = html.escape(question_text).replace("\n", "<br>")
    html_answer = html.escape(answer_text).replace("\n", "<br>")
    html_links = ""
    if present_links:
        items = []
        for label, value in present_links:
            escaped_label = html.escape(label)
            escaped_url = html.escape(value)
            items.append(f'<li><strong>{escaped_label}:</strong> <a href="{escaped_url}">{escaped_url}</a></li>')
        html_links = (
            "<div style=\"margin-top: 16px;\">"
            "<p style=\"margin: 0 0 6px 0; font-size: 12px; text-transform: uppercase; color: #8b949e;\">Discord Links</p>"
            f"<ul style=\"margin: 0; padding-left: 20px; color: #c9d1d9;\">{''.join(items)}</ul>"
            "</div>"
        )

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 640px; margin: 0 auto; padding: 20px; color: #e5ecf5; background: #0c1117;">
  <div style="background: #161b22; border-radius: 12px; padding: 24px; border: 1px solid rgba(255,255,255,0.08);">
    <h2 style="color: #4ade80; margin-top: 0;">Discord Answer</h2>
    <p style="color: #8b949e;">Hi {html.escape(to_name)},</p>

    <div style="background: #0d1117; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 3px solid #5865F2;">
      <p style="color: #8b949e; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase;">Question</p>
      <p style="color: #e5ecf5; margin: 0;">{html_question}</p>
    </div>

    <div style="background: #0d1117; border-radius: 8px; padding: 16px; margin: 16px 0; border-left: 3px solid #4ade80;">
      <p style="color: #8b949e; margin: 0 0 4px 0; font-size: 12px; text-transform: uppercase;">Answer</p>
      <p style="color: #e5ecf5; margin: 0;">{html_answer}</p>
    </div>
    {html_links}
  </div>
</body>
</html>"""
    return subject, text_body, html_body


async def _handle_discord_human_answer(payload: dict[str, str]) -> None:
    """Accept role-gated Discord human answer from bot listener."""
    message_id = (payload.get("message_id") or "").strip()
    thread_id = (payload.get("thread_id") or "").strip()
    reply_to_message_id = (payload.get("reply_to_message_id") or "").strip()
    if not thread_id and not reply_to_message_id:
        logger.info(
            "ask_discord_answer_rejected reason=no_reference source=discord_bot message_id=%s",
            message_id or "unknown",
        )
        return
    if not thread_id:
        thread_id = ""
    answer_text = (payload.get("content") or "").strip()
    if not answer_text:
        logger.info(
            "ask_discord_answer_rejected reason=empty_content source=discord_bot message_id=%s",
            message_id or "unknown",
        )
        return

    def _apply_human_answer():
        with get_db() as conn:
            question = None
            if thread_id:
                question = conn.execute(
                    "SELECT * FROM questions WHERE discord_thread_id = ? ORDER BY id DESC LIMIT 1",
                    (thread_id,),
                ).fetchone()
            if question is None and reply_to_message_id:
                question = conn.execute(
                    "SELECT * FROM questions WHERE discord_message_id = ? ORDER BY id DESC LIMIT 1",
                    (reply_to_message_id,),
                ).fetchone()
            if not question:
                return None, "question_not_found"
            if question["answer_text"]:
                return None, "already_answered"

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE questions SET answer_text = ?, answered_at = ?, answered_by = 'human', status = 'answered', "
                "discord_answer_message_id = ?, "
                "discord_thread_id = COALESCE(?, discord_thread_id), "
                "discord_guild_id = COALESCE(?, discord_guild_id), "
                "discord_channel_id = COALESCE(?, discord_channel_id) "
                "WHERE id = ? AND answer_text IS NULL",
                (
                    answer_text,
                    now,
                    payload.get("message_id"),
                    thread_id or None,
                    payload.get("guild_id"),
                    payload.get("channel_id"),
                    question["id"],
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0] == 0:
                conn.rollback()
                return None, "update_conflict"
            conn.commit()
            return question["id"], None

    question_id, reject_reason = await asyncio.to_thread(_apply_human_answer)
    if question_id is None:
        logger.info(
            "ask_discord_answer_rejected reason=%s source=discord_bot thread_id=%s reply_to_message_id=%s",
            reject_reason or "unknown",
            thread_id or "none",
            reply_to_message_id or "none",
        )
        return
    logger.info(
        "ask_discord_answer_accepted source=discord_bot question_id=%s message_id=%s",
        question_id,
        message_id or "unknown",
    )
    await _publish_status_value(question_id, "answered", extra={"answered_by": "human"})
    await _publish_answer(question_id)
    await _publish_snapshot(question_id)


async def _process_fallback_candidates_once() -> None:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    def _fetch_candidates():
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, question_text, created_at, deadline_at, human_deadline_at, openai_deadline_at, "
                "local_llm_attempted_at, openai_attempted_at, discord_thread_id, discord_channel_id, discord_message_id "
                "FROM questions "
                "WHERE answer_text IS NULL AND status = 'pending' "
                "ORDER BY created_at ASC "
                "LIMIT 100"
            ).fetchall()
            return [dict(r) for r in rows]

    def _claim_stage(question_id: int, stage: str, human_deadline_iso: str, openai_deadline_iso: str) -> bool:
        with get_db() as conn:
            if stage == "local":
                conn.execute(
                    "UPDATE questions "
                    "SET local_llm_attempted_at = ?, "
                    "human_deadline_at = COALESCE(human_deadline_at, ?), "
                    "openai_deadline_at = COALESCE(openai_deadline_at, ?), "
                    "deadline_at = COALESCE(deadline_at, ?) "
                    "WHERE id = ? AND answer_text IS NULL AND status = 'pending' AND local_llm_attempted_at IS NULL",
                    (now_iso, human_deadline_iso, openai_deadline_iso, human_deadline_iso, question_id),
                )
            else:
                conn.execute(
                    "UPDATE questions "
                    "SET openai_attempted_at = ?, "
                    "openai_deadline_at = COALESCE(openai_deadline_at, ?), "
                    "deadline_at = COALESCE(openai_deadline_at, ?) "
                    "WHERE id = ? AND answer_text IS NULL AND status = 'pending' "
                    "AND local_llm_attempted_at IS NOT NULL AND openai_attempted_at IS NULL",
                    (now_iso, openai_deadline_iso, openai_deadline_iso, question_id),
                )
            changed = conn.execute("SELECT changes()").fetchone()[0]
            conn.commit()
            return changed > 0

    def _save_answer(question_id: int, answer_text: str, answered_by: str) -> bool:
        answered_at = datetime.now(timezone.utc).isoformat()
        with get_db() as conn:
            conn.execute(
                "UPDATE questions "
                "SET answer_text = ?, answered_at = ?, answered_by = ?, status = 'answered' "
                "WHERE id = ? AND answer_text IS NULL AND status = 'pending'",
                (answer_text, answered_at, answered_by, question_id),
            )
            changed = conn.execute("SELECT changes()").fetchone()[0]
            conn.commit()
            return changed > 0

    def _set_pending_deadline(question_id: int, deadline_at_iso: str) -> None:
        with get_db() as conn:
            conn.execute(
                "UPDATE questions SET deadline_at = ?, openai_deadline_at = COALESCE(openai_deadline_at, ?) "
                "WHERE id = ? AND answer_text IS NULL AND status = 'pending'",
                (deadline_at_iso, deadline_at_iso, question_id),
            )
            conn.commit()

    candidates = await asyncio.to_thread(_fetch_candidates)
    for candidate in candidates:
        question_id = int(candidate["id"])
        if question_id in _llm_inflight_question_ids:
            continue

        human_deadline_at, openai_deadline_at = _resolve_deadlines(candidate)
        local_attempted = bool((candidate.get("local_llm_attempted_at") or "").strip())
        openai_attempted = bool((candidate.get("openai_attempted_at") or "").strip())

        stage: str | None = None
        if not local_attempted and now >= human_deadline_at:
            stage = "local"
        elif local_attempted and not openai_attempted and now >= openai_deadline_at:
            stage = "openai"
        if stage is None:
            continue

        _llm_inflight_question_ids.add(question_id)
        try:
            claimed = await asyncio.to_thread(
                _claim_stage,
                question_id,
                stage,
                human_deadline_at.isoformat(),
                openai_deadline_at.isoformat(),
            )
            if not claimed:
                continue

            answer_text: str = ""
            if stage == "local":
                try:
                    answer_text = (await generate_local_answer_text(candidate["question_text"])).strip()
                except Exception as exc:
                    logger.exception("Local LLM fallback failed for question_id=%s", question_id)
                    await asyncio.to_thread(_set_pending_deadline, question_id, openai_deadline_at.isoformat())
                    await _publish_failure_status(question_id, "local_llm_failed", detail=str(exc))
                    await _publish_snapshot(question_id)
                    continue
                answered_by = "llm_local"
            else:
                try:
                    answer_text = (await generate_openai_answer_text(candidate["question_text"])).strip()
                except Exception as exc:
                    logger.exception("OpenAI fallback failed for question_id=%s", question_id)
                    await _publish_failure_status(question_id, "openai_failed", detail=str(exc))
                    await _publish_snapshot(question_id)
                    continue
                answered_by = "llm_openai"

            if not answer_text:
                if stage == "local":
                    await asyncio.to_thread(_set_pending_deadline, question_id, openai_deadline_at.isoformat())
                    await _publish_failure_status(question_id, "local_llm_failed", detail="Model returned empty output")
                else:
                    await _publish_failure_status(question_id, "openai_failed", detail="Model returned empty output")
                await _publish_snapshot(question_id)
                continue

            stored = await asyncio.to_thread(_save_answer, question_id, answer_text, answered_by)
            if not stored:
                continue

            await _publish_status_value(question_id, "answered", extra={"answered_by": answered_by})
            await post_answer_to_discord(
                answer_text=answer_text,
                thread_id=candidate.get("discord_thread_id"),
                channel_id=candidate.get("discord_channel_id"),
                reply_to_message_id=candidate.get("discord_message_id"),
            )
            await _publish_answer(question_id)
            await _publish_snapshot(question_id)
        except Exception:
            logger.exception("Failed processing Ask fallback for question_id=%s", question_id)
        finally:
            _llm_inflight_question_ids.discard(question_id)


async def _ask_fallback_loop() -> None:
    while True:
        try:
            await _process_fallback_candidates_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ask fallback loop failed")
        await asyncio.sleep(max(ASK_FALLBACK_SWEEP_SECONDS, 1))


async def start_ask_background_workers() -> None:
    """Start Ask fallback loop + Discord human-answer listener."""
    global _ask_fallback_task
    if _ask_fallback_task is None or _ask_fallback_task.done():
        _ask_fallback_task = asyncio.create_task(_ask_fallback_loop(), name="ask-fallback-loop")

    from app.discord_client import start_discord_client

    await start_discord_client(_handle_discord_human_answer)


async def stop_ask_background_workers() -> None:
    """Stop Ask fallback loop + Discord human-answer listener."""
    global _ask_fallback_task
    if _ask_fallback_task is not None:
        _ask_fallback_task.cancel()
        try:
            await _ask_fallback_task
        except asyncio.CancelledError:
            pass
        _ask_fallback_task = None

    from app.discord_client import stop_discord_client

    await stop_discord_client()


# --- Auth Endpoints ---
@router.get("/auth/login")
async def auth_login(request: Request):
    """Redirect user to Google OAuth2 login."""
    _cleanup_expired_oauth_states()
    state = secrets.token_urlsafe(32)
    redirect_uri = _get_oauth_redirect_uri(request)
    base_public_url = _get_public_base_url(request)
    _oauth_states[state] = {
        "created_at": time.time(),
        "redirect_uri": redirect_uri,
        "base_public_url": base_public_url,
    }
    url = get_login_url(state, redirect_uri)
    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": url},
    )


@router.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle Google OAuth2 callback."""
    # Validate state
    if state not in _oauth_states:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    oauth_state = _oauth_states.pop(state, None) or {}
    redirect_uri = str(oauth_state.get("redirect_uri") or _get_oauth_redirect_uri(request))
    base_public_url = str(oauth_state.get("base_public_url") or _get_public_base_url(request))

    # Exchange code for tokens
    try:
        token_data = await exchange_code(code, redirect_uri)
    except Exception:
        logger.exception("Failed to exchange OAuth code")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="OAuth token exchange failed")

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No access token received")

    # Get user info
    try:
        user_info = await get_user_info(access_token)
    except Exception:
        logger.exception("Failed to fetch user info from Google")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to get user info")

    google_id = user_info.get("id", "")
    email = user_info.get("email", "")
    name = user_info.get("name", "")
    picture_url = user_info.get("picture", "")

    if not google_id or not email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incomplete user info from Google")

    # Upsert user in DB
    def _upsert_user():
        with get_db() as conn:
            # Try to find existing user
            row = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET email = ?, name = ?, picture_url = ?, updated_at = ? WHERE google_id = ?",
                    (email, name, picture_url, datetime.now(timezone.utc).isoformat(), google_id),
                )
                conn.commit()
                return dict(conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone())
            else:
                conn.execute(
                    "INSERT INTO users (google_id, email, name, picture_url, points) VALUES (?, ?, ?, ?, ?)",
                    (google_id, email, name, picture_url, DEFAULT_STARTING_POINTS),
                )
                conn.commit()
                return dict(conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone())

    user_row = await asyncio.to_thread(_upsert_user)
    session_token = _create_session(user_row)
    session = _sessions.get(session_token) or {}
    csrf_token = _ensure_session_csrf(session)
    cookie_secure = base_public_url.startswith("https")

    # Redirect to /ask with session cookie
    response = Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"{base_public_url}/ask"},
    )
    response.set_cookie(
        key="ask_session",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure,
        max_age=ASK_SESSION_MAX_AGE_SECONDS,
        expires=ASK_SESSION_MAX_AGE_SECONDS,
        path="/",
    )
    _set_csrf_cookie(response, secure=cookie_secure, token=csrf_token)
    logger.info("ask_auth_login_success user_id=%s", user_row["id"])
    return response


@router.post("/auth/logout")
async def auth_logout(
    request: Request,
    ask_session: str | None = Cookie(default=None),
    ask_csrf: str | None = Cookie(default=None, alias=ASK_CSRF_COOKIE_NAME),
    x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
):
    """Clear the session."""
    session = _get_session_or_none(ask_session, request)
    if session is None:
        return _unauthorized_response()
    if not _validate_csrf(session=session, x_csrf_token=x_csrf_token, ask_csrf=ask_csrf):
        return _invalid_csrf_response()

    removed = False
    if ask_session:
        removed = _sessions.pop(ask_session, None) is not None
    response = Response(status_code=status.HTTP_200_OK, content='{"ok": true}')
    response.headers["Content-Type"] = "application/json"
    response.delete_cookie(key="ask_session", path="/")
    response.delete_cookie(key=ASK_CSRF_COOKIE_NAME, path="/")
    logger.info("ask_auth_logout session_removed=%s", removed)
    return response


# --- User Endpoints ---
@router.get("/me")
async def get_me(
    request: Request,
    response: Response,
    ask_session: str | None = Cookie(default=None),
):
    """Return current user info and points balance."""
    session = _get_session_or_none(ask_session, request)
    if session is None:
        return _unauthorized_response()
    user_id = session["user_id"]

    def _fetch_user():
        with get_db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    user = await asyncio.to_thread(_fetch_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    secure_cookie = _get_public_base_url(request).startswith("https")
    _set_csrf_cookie(
        response,
        secure=secure_cookie,
        token=_ensure_session_csrf(session),
    )
    return UserResponse(
        id=user["id"],
        name=user["name"],
        email=user["email"],
        picture_url=user["picture_url"],
        points=user["points"],
    )


# --- Question Endpoints ---
@router.post("/questions", status_code=status.HTTP_201_CREATED)
async def submit_question(
    body: QuestionRequest,
    request: Request,
    ask_session: str | None = Cookie(default=None),
    ask_csrf: str | None = Cookie(default=None, alias=ASK_CSRF_COOKIE_NAME),
    x_csrf_token: str = Header(default="", alias="X-CSRF-Token"),
):
    """Submit a question. Deducts points only when ASK_POINTS_ENABLED is true."""
    session = _get_session_or_none(ask_session, request)
    if session is None:
        return _unauthorized_response()
    if not _validate_csrf(session=session, x_csrf_token=x_csrf_token, ask_csrf=ask_csrf):
        return _invalid_csrf_response()
    user_id = session["user_id"]

    normalized_question_text = (body.question_text or "").strip()
    if not normalized_question_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_question"})
    if len(normalized_question_text) > 5000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "question_too_long"})
    if len(normalized_question_text) < 10:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "question_too_short"})

    _check_rate_limit(user_id)

    def _create_question():
        with get_db() as conn:
            user = conn.execute("SELECT id, points, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                return None, "User not found"

            points_spent = POINTS_PER_QUESTION if ASK_POINTS_ENABLED else 0
            remaining_points: int | None = None

            if ASK_POINTS_ENABLED:
                # Atomic: decrement points + insert question in one transaction
                if user["points"] < POINTS_PER_QUESTION:
                    return None, "Insufficient points"

                conn.execute(
                    "UPDATE users SET points = points - ?, updated_at = ? WHERE id = ? AND points >= ?",
                    (POINTS_PER_QUESTION, datetime.now(timezone.utc).isoformat(), user_id, POINTS_PER_QUESTION),
                )
                # Verify the update actually happened (race condition guard)
                if conn.execute("SELECT changes()").fetchone()[0] == 0:
                    conn.rollback()
                    return None, "Insufficient points (race)"

            created_at = datetime.now(timezone.utc)
            human_deadline_at, openai_deadline_at = _build_deadlines(created_at)
            cursor = conn.execute(
                "INSERT INTO questions (user_id, question_text, points_spent, status, created_at, deadline_at, human_deadline_at, openai_deadline_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)",
                (
                    user_id,
                    normalized_question_text,
                    points_spent,
                    created_at.isoformat(),
                    human_deadline_at.isoformat(),
                    human_deadline_at.isoformat(),
                    openai_deadline_at.isoformat(),
                ),
            )
            conn.commit()

            question_id = cursor.lastrowid
            if ASK_POINTS_ENABLED:
                remaining_points = conn.execute("SELECT points FROM users WHERE id = ?", (user_id,)).fetchone()["points"]
            return {
                "question_id": question_id,
                "user_name": user["name"],
                "user_email": user["email"],
                "remaining_points": remaining_points,
                "deadline_at": human_deadline_at.isoformat(),
                "points_spent": points_spent,
            }, None

    result, error = await asyncio.to_thread(_create_question)
    if error:
        if "not found" in error.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error)
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error)

    # Post to Discord (best-effort, don't fail the request)
    discord_result = await post_question_to_discord(
        question_id=result["question_id"],
        user_name=result["user_name"],
        user_email=result["user_email"],
        question_text=normalized_question_text,
    )

    # Update Discord metadata (best effort)
    def _mark_discord():
        with get_db() as conn:
            conn.execute(
                "UPDATE questions "
                "SET discord_sent = ?, "
                "discord_guild_id = COALESCE(?, discord_guild_id), "
                "discord_channel_id = COALESCE(?, discord_channel_id), "
                "discord_message_id = COALESCE(?, discord_message_id), "
                "discord_thread_id = COALESCE(?, discord_thread_id) "
                "WHERE id = ?",
                (
                    1 if discord_result.delivered else 0,
                    discord_result.guild_id,
                    discord_result.channel_id,
                    discord_result.message_id,
                    discord_result.thread_id,
                    result["question_id"],
                ),
            )
            conn.commit()

    await asyncio.to_thread(_mark_discord)
    await _publish_status(result["question_id"])
    if discord_result.delivered:
        await _publish_status_value(
            result["question_id"],
            "posted_to_discord",
            extra={
                "discord_message_id": discord_result.message_id,
                "discord_thread_id": discord_result.thread_id,
            },
        )
    await _publish_snapshot(result["question_id"])
    logger.info(
        "ask_question_submitted user_id=%s question_id=%s discord_notified=%s",
        user_id,
        result["question_id"],
        discord_result.delivered,
    )

    return {
        "question_id": result["question_id"],
        "points_spent": result["points_spent"],
        "remaining_points": result["remaining_points"],
        "discord_notified": discord_result.delivered,
    }


@router.get("/questions")
async def list_questions(
    request: Request,
    ask_session: str | None = Cookie(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List the current user's questions."""
    session = _get_session_or_none(ask_session, request)
    if session is None:
        return _unauthorized_response()
    user_id = session["user_id"]

    def _fetch():
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    questions = await asyncio.to_thread(_fetch)
    return [
        QuestionResponse(
            id=q["id"],
            question_text=q["question_text"],
            answer_text=q["answer_text"],
            points_spent=q["points_spent"],
            status=_public_question_status(q),
            created_at=q["created_at"],
            answered_at=q["answered_at"],
        )
        for q in questions
    ]


@router.get("/questions/{question_id}/events")
async def question_events_stream(question_id: int, request: Request):
    """Stream live Ask updates for one question via SSE."""
    session = _get_session_or_none(request=request)
    if session is None:
        return _unauthorized_response()
    user_id = int(session["user_id"])

    question = await asyncio.to_thread(_fetch_question_for_user_sync, question_id, user_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    async def _event_stream() -> AsyncIterator[str]:
        queue = await _subscribe_question(question_id)
        try:
            current = await asyncio.to_thread(_fetch_question_for_user_sync, question_id, user_id)
            if current is not None:
                yield _sse_event("snapshot", _serialize_question_snapshot(current))
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _sse_event(event["event"], event["payload"])
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await _unsubscribe_question(question_id, queue)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/discord/question")
async def upsert_discord_question(
    body: DiscordQuestionRequest,
    _: None = Depends(_require_n8n_token),
    __: None = Depends(_require_webhook_size_limit),
):
    """Upsert a question record from a Discord message for n8n."""

    def _upsert():
        with get_db() as conn:
            created_at = datetime.now(timezone.utc)
            now = created_at.isoformat()
            human_deadline_at, openai_deadline_at = _build_deadlines(created_at)
            author_id = (body.author_id or "").strip() or "unknown"
            author_name = (body.author_name or f"Discord User {author_id}").strip()[:255]
            author_email = (body.author_email or _discord_placeholder_email(author_id)).strip()[:320]
            google_id = f"discord:{author_id}"

            user_row = conn.execute(
                "SELECT id FROM users WHERE google_id = ?",
                (google_id,),
            ).fetchone()
            if user_row:
                user_id = user_row["id"]
                conn.execute(
                    "UPDATE users SET email = ?, name = ?, updated_at = ? WHERE id = ?",
                    (author_email, author_name, now, user_id),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO users (google_id, email, name, picture_url, points) VALUES (?, ?, ?, ?, ?)",
                    (google_id, author_email, author_name, "", 0),
                )
                user_id = cursor.lastrowid

            existing = conn.execute(
                "SELECT id FROM questions WHERE discord_message_id = ?",
                (body.discord_message_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE questions "
                    "SET user_id = ?, question_text = ?, discord_guild_id = ?, discord_channel_id = ?, discord_thread_id = ?, "
                    "status = CASE WHEN answer_text IS NULL THEN 'pending' ELSE status END, "
                    "deadline_at = CASE WHEN answer_text IS NULL THEN COALESCE(deadline_at, ?) ELSE deadline_at END, "
                    "human_deadline_at = CASE WHEN answer_text IS NULL THEN COALESCE(human_deadline_at, ?) ELSE human_deadline_at END, "
                    "openai_deadline_at = CASE WHEN answer_text IS NULL THEN COALESCE(openai_deadline_at, ?) ELSE openai_deadline_at END "
                    "WHERE id = ?",
                    (
                        user_id,
                        body.content,
                        body.discord_guild_id,
                        body.discord_channel_id,
                        body.discord_thread_id,
                        human_deadline_at.isoformat(),
                        human_deadline_at.isoformat(),
                        openai_deadline_at.isoformat(),
                        existing["id"],
                    ),
                )
                conn.commit()
                return existing["id"], "updated"

            cursor = conn.execute(
                "INSERT INTO questions (user_id, question_text, points_spent, status, discord_sent, discord_guild_id, discord_channel_id, discord_message_id, discord_thread_id, deadline_at, human_deadline_at, openai_deadline_at) "
                "VALUES (?, ?, ?, 'pending', 1, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    body.content,
                    0,
                    body.discord_guild_id,
                    body.discord_channel_id,
                    body.discord_message_id,
                    body.discord_thread_id,
                    human_deadline_at.isoformat(),
                    human_deadline_at.isoformat(),
                    openai_deadline_at.isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid, "created"

    question_id, result = await asyncio.to_thread(_upsert)
    await _publish_status(question_id)
    await _publish_snapshot(question_id)
    return {
        "question_id": question_id,
        "status": result,
    }


@router.post("/discord/answer")
async def attach_discord_answer(
    body: DiscordAnswerRequest,
    _: None = Depends(_require_n8n_token),
    __: None = Depends(_require_webhook_size_limit),
    x_admin_override: str = Header(default="", alias="X-ADMIN-OVERRIDE"),
):
    """Attach a Discord answer to a question, then email it."""
    role_ids = body.author_role_ids or []
    if not _has_support_role(role_ids):
        logger.warning(
            "ask_discord_answer_rejected reason=missing_support_role source=n8n reply_to_message_id=%s thread_id=%s",
            body.reply_to_message_id or "none",
            body.thread_id or "none",
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Support role required")
    admin_override = _is_admin_override_token(x_admin_override)

    def _attach():
        with get_db() as conn:
            question = None
            if body.reply_to_message_id:
                question = conn.execute(
                    "SELECT q.*, u.email, u.name FROM questions q JOIN users u ON q.user_id = u.id WHERE q.discord_message_id = ? ORDER BY q.id DESC LIMIT 1",
                    (body.reply_to_message_id,),
                ).fetchone()
            if question is None and body.thread_id:
                question = conn.execute(
                    "SELECT q.*, u.email, u.name FROM questions q JOIN users u ON q.user_id = u.id WHERE q.discord_thread_id = ? ORDER BY q.id DESC LIMIT 1",
                    (body.thread_id,),
                ).fetchone()

            if question is None:
                return None, "Question not found", status.HTTP_404_NOT_FOUND
            if question["answer_text"] and not admin_override:
                return None, "Question already answered", status.HTTP_409_CONFLICT

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE questions SET answer_text = ?, answered_at = ?, status = 'answered', answered_by = 'human', "
                "discord_answer_message_id = ?, "
                "discord_thread_id = COALESCE(?, discord_thread_id), "
                "discord_guild_id = COALESCE(?, discord_guild_id), "
                "discord_channel_id = COALESCE(?, discord_channel_id) "
                "WHERE id = ? " + ("" if admin_override else "AND answer_text IS NULL"),
                (
                    body.answer_text,
                    now,
                    body.discord_answer_message_id,
                    body.thread_id,
                    body.discord_guild_id,
                    body.discord_channel_id,
                    question["id"],
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0] == 0:
                conn.rollback()
                return None, "Question already answered", status.HTTP_409_CONFLICT
            conn.commit()
            return dict(question), None, status.HTTP_200_OK

    question_data, error, status_code = await asyncio.to_thread(_attach)
    if error:
        logger.info(
            "ask_discord_answer_rejected reason=%s source=n8n reply_to_message_id=%s thread_id=%s admin_override=%s",
            error,
            body.reply_to_message_id or "none",
            body.thread_id or "none",
            admin_override,
        )
        raise HTTPException(status_code=status_code, detail=error)

    subject, text_body, html_body = _build_discord_answer_email(
        to_name=question_data["name"] or "there",
        question_text=question_data["question_text"],
        answer_text=body.answer_text or "",
        question_permalink=body.question_permalink,
        thread_permalink=body.thread_permalink,
        answer_permalink=body.answer_permalink,
    )
    email_ok = await asyncio.to_thread(
        send_custom_email,
        to_email=question_data["email"],
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        question_id=int(question_data["id"]),
        log_context=f"discord_question_id={question_data['id']}",
    )
    if not email_ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to send answer email")

    logger.info(
        "ask_discord_answer_accepted source=n8n question_id=%s admin_override=%s",
        question_data["id"],
        admin_override,
    )
    await _publish_status_value(int(question_data["id"]), "answered", extra={"answered_by": "human"})
    await _publish_answer(int(question_data["id"]))
    await _publish_snapshot(int(question_data["id"]))

    return {
        "question_id": question_data["id"],
        "emailed": True,
    }


# --- Answer Endpoint (webhook from Marc / n8n) ---
@router.post("/answers")
async def submit_answer(
    body: AnswerRequest,
    request: Request,
    _: None = Depends(_require_webhook_size_limit),
):
    """Accept an answer for a question. Secured by shared secret header."""
    if not ASK_ANSWER_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Answer webhook not configured")

    secret_header = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(secret_header, ASK_ANSWER_WEBHOOK_SECRET):
        logger.warning("ask_webhook_rejected reason=invalid_answer_webhook_secret path=/api/ask/answers")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    def _answer_question():
        with get_db() as conn:
            question = conn.execute(
                "SELECT q.*, u.email, u.name FROM questions q JOIN users u ON q.user_id = u.id WHERE q.id = ?",
                (body.question_id,),
            ).fetchone()
            if not question:
                return None, "Question not found"

            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE questions SET answer_text = ?, status = 'answered', answered_at = ?, answered_by = 'human' WHERE id = ?",
                (body.answer_text, now, body.question_id),
            )
            conn.commit()
            return dict(question), None

    question_data, error = await asyncio.to_thread(_answer_question)
    if error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error)

    # Send email to user (best-effort)
    email_ok = await asyncio.to_thread(
        send_answer_email,
        to_email=question_data["email"],
        to_name=question_data["name"],
        question_text=question_data["question_text"],
        answer_text=body.answer_text,
        question_id=body.question_id,
    )

    await _publish_status_value(body.question_id, "answered", extra={"answered_by": "human"})
    await _publish_answer(body.question_id)
    await _publish_snapshot(body.question_id)
    logger.info("ask_webhook_answer_applied question_id=%s", body.question_id)

    return {
        "question_id": body.question_id,
        "status": "answered",
        "email_sent": email_ok,
    }


# --- Admin Endpoints ---
@router.get("/admin/users")
async def admin_list_users(request: Request):
    """List all users. Requires ADMIN_TOKEN."""
    _require_admin_token(request)

    def _fetch():
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    return await asyncio.to_thread(_fetch)


class AdminAdjustPointsRequest(BaseModel):
    user_id: int
    points_delta: int = Field(..., description="Positive to add, negative to subtract")


@router.post("/admin/points")
async def admin_adjust_points(body: AdminAdjustPointsRequest, request: Request):
    """Adjust a user's point balance. Requires ADMIN_TOKEN."""
    _require_admin_token(request)
    if not ASK_POINTS_ENABLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Points system disabled")

    def _adjust():
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (body.user_id,)).fetchone()
            if not user:
                return None, "User not found"
            new_balance = user["points"] + body.points_delta
            if new_balance < 0:
                return None, "Would result in negative balance"
            conn.execute(
                "UPDATE users SET points = ?, updated_at = ? WHERE id = ?",
                (new_balance, datetime.now(timezone.utc).isoformat(), body.user_id),
            )
            conn.commit()
            return {"user_id": body.user_id, "new_balance": new_balance}, None

    result, error = await asyncio.to_thread(_adjust)
    if error:
        status_code = status.HTTP_404_NOT_FOUND if "not found" in error.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=error)
    return result


class AdminEmailTestRequest(BaseModel):
    to: str = Field(..., min_length=3, max_length=320)


@router.post("/admin/email/test")
async def admin_email_test(body: AdminEmailTestRequest, request: Request):
    """Send an SMTP test message using current Ask email settings. Requires ADMIN_TOKEN."""
    _require_admin_token(request)

    subject = "marcle.ai Ask SMTP test"
    text_body = (
        "This is a test email from marcle.ai Ask admin endpoint.\n\n"
        "If you received this, SMTP settings are working."
    )
    html_body = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
  <p>This is a test email from <strong>marcle.ai Ask admin endpoint</strong>.</p>
  <p>If you received this, SMTP settings are working.</p>
</body>
</html>"""

    ok, error = await asyncio.to_thread(
        send_custom_email_result,
        to_email=body.to,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        question_id=None,
        log_context="admin_email_test",
    )
    if ok:
        return {"ok": True}
    return {"ok": False, "error": error or "Email send failed"}


def _require_admin_token(request: Request) -> None:
    """Validate admin bearer token for Ask admin endpoints."""
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin API is disabled")
    auth = request.headers.get("Authorization", "")
    prefix = "Bearer "
    token = auth[len(prefix):] if auth.startswith(prefix) else ""
    if not hmac.compare_digest(token, admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )
