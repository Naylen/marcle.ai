"""Ask app router — question submission, OAuth, answers, admin."""

import asyncio
import hmac
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.ask_db import (
    DEFAULT_STARTING_POINTS,
    POINTS_PER_QUESTION,
    get_db,
)
from app.ask_services.discord import post_question_to_discord
from app.ask_services.email import send_answer_email
from app.ask_services.google_oauth import exchange_code, get_login_url, get_user_info

logger = logging.getLogger("marcle.ask")

router = APIRouter(prefix="/api/ask", tags=["ask"])

# --- Config ---
SESSION_SECRET: str = os.getenv("SESSION_SECRET", "change-me-in-production")
ASK_ANSWER_WEBHOOK_SECRET: str = os.getenv("ASK_ANSWER_WEBHOOK_SECRET", "")
BASE_PUBLIC_URL: str = os.getenv("BASE_PUBLIC_URL", "http://localhost:9182")

# Rate limiting: per-user, in-memory
_rate_limit_window: int = 60  # seconds
_rate_limit_max: int = 5  # max questions per window
_rate_limits: dict[int, list[float]] = defaultdict(list)

# In-memory session store (simple; production should use Redis or signed cookies)
# Maps session_token -> {user_id, google_id, email, name, picture_url, created_at}
_sessions: dict[str, dict] = {}

# OAuth state tokens (nonce -> timestamp)
_oauth_states: dict[str, float] = {}


# --- Pydantic Models ---
class QuestionRequest(BaseModel):
    question_text: str = Field(..., min_length=10, max_length=5000)


class AnswerRequest(BaseModel):
    question_id: int
    answer_text: str = Field(..., min_length=1, max_length=10000)


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
    _sessions[token] = {
        "user_id": user_row["id"],
        "google_id": user_row["google_id"],
        "email": user_row["email"],
        "name": user_row["name"],
        "picture_url": user_row["picture_url"],
        "created_at": time.time(),
    }
    return token


def _get_session(token: str | None) -> dict | None:
    """Retrieve session data from token."""
    if not token:
        return None
    session = _sessions.get(token)
    if session is None:
        return None
    # Sessions expire after 24 hours
    if time.time() - session["created_at"] > 86400:
        _sessions.pop(token, None)
        return None
    return session


def _require_session(ask_session: str | None) -> dict:
    """Validate session or raise 401."""
    session = _get_session(ask_session)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return session


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
    expired = [k for k, v in _oauth_states.items() if now - v > 600]
    for k in expired:
        _oauth_states.pop(k, None)


# --- Auth Endpoints ---
@router.get("/auth/login")
async def auth_login():
    """Redirect user to Google OAuth2 login."""
    _cleanup_expired_oauth_states()
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = time.time()
    url = get_login_url(state)
    return Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": url},
    )


@router.get("/auth/callback")
async def auth_callback(
    code: str = Query(...),
    state: str = Query(...),
):
    """Handle Google OAuth2 callback."""
    # Validate state
    if state not in _oauth_states:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    _oauth_states.pop(state, None)

    # Exchange code for tokens
    try:
        token_data = await exchange_code(code)
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

    # Redirect to /ask with session cookie
    response = Response(
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Location": f"{BASE_PUBLIC_URL}/ask"},
    )
    response.set_cookie(
        key="ask_session",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=BASE_PUBLIC_URL.startswith("https"),
        max_age=86400,
        path="/",
    )
    return response


@router.post("/auth/logout")
async def auth_logout(ask_session: str | None = Cookie(default=None)):
    """Clear the session."""
    if ask_session:
        _sessions.pop(ask_session, None)
    response = Response(status_code=status.HTTP_200_OK, content='{"ok": true}')
    response.headers["Content-Type"] = "application/json"
    response.delete_cookie(key="ask_session", path="/")
    return response


# --- User Endpoints ---
@router.get("/me")
async def get_me(ask_session: str | None = Cookie(default=None)):
    """Return current user info and points balance."""
    session = _require_session(ask_session)
    user_id = session["user_id"]

    def _fetch_user():
        with get_db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    user = await asyncio.to_thread(_fetch_user)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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
    ask_session: str | None = Cookie(default=None),
):
    """Submit a question. Costs POINTS_PER_QUESTION points. Posts to Discord."""
    session = _require_session(ask_session)
    user_id = session["user_id"]

    _check_rate_limit(user_id)

    def _create_question():
        with get_db() as conn:
            # Atomic: decrement points + insert question in one transaction
            user = conn.execute("SELECT id, points, name, email FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user:
                return None, "User not found"
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

            cursor = conn.execute(
                "INSERT INTO questions (user_id, question_text, points_spent) VALUES (?, ?, ?)",
                (user_id, body.question_text, POINTS_PER_QUESTION),
            )
            conn.commit()

            question_id = cursor.lastrowid
            remaining_points = conn.execute("SELECT points FROM users WHERE id = ?", (user_id,)).fetchone()["points"]
            return {
                "question_id": question_id,
                "user_name": user["name"],
                "user_email": user["email"],
                "remaining_points": remaining_points,
            }, None

    result, error = await asyncio.to_thread(_create_question)
    if error:
        if "not found" in error.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error)
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error)

    # Post to Discord (best-effort, don't fail the request)
    discord_ok = await post_question_to_discord(
        question_id=result["question_id"],
        user_name=result["user_name"],
        user_email=result["user_email"],
        question_text=body.question_text,
    )

    # Update discord_sent flag
    if discord_ok:
        def _mark_discord():
            with get_db() as conn:
                conn.execute("UPDATE questions SET discord_sent = 1 WHERE id = ?", (result["question_id"],))
                conn.commit()
        await asyncio.to_thread(_mark_discord)

    return {
        "question_id": result["question_id"],
        "points_spent": POINTS_PER_QUESTION,
        "remaining_points": result["remaining_points"],
        "discord_notified": discord_ok,
    }


@router.get("/questions")
async def list_questions(
    ask_session: str | None = Cookie(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    """List the current user's questions."""
    session = _require_session(ask_session)
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
            status=q["status"],
            created_at=q["created_at"],
            answered_at=q["answered_at"],
        )
        for q in questions
    ]


# --- Answer Endpoint (webhook from Marc / n8n) ---
@router.post("/answers")
async def submit_answer(body: AnswerRequest, request: Request):
    """Accept an answer for a question. Secured by shared secret header."""
    if not ASK_ANSWER_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Answer webhook not configured")

    secret_header = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(secret_header, ASK_ANSWER_WEBHOOK_SECRET):
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
                "UPDATE questions SET answer_text = ?, status = 'answered', answered_at = ? WHERE id = ?",
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
