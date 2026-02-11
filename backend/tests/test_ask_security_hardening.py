import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.ask_db as ask_db
import app.routers.ask as ask_module
from app.main import app


def _reset_ask_db(tmp_path) -> None:
    existing = getattr(ask_db._local, "conn", None)
    if existing is not None:
        existing.close()
        delattr(ask_db._local, "conn")
    ask_db.ASK_DB_PATH = str(tmp_path / "ask-security.db")
    ask_db.init_db()
    ask_module._sessions.clear()


def _insert_user(email: str, name: str = "User") -> int:
    with ask_db.get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO users (google_id, email, name, picture_url, points) VALUES (?, ?, ?, '', 0)",
            (f"google:{email}", email, name),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _insert_question(
    *,
    user_id: int,
    text: str,
    discord_message_id: str | None = None,
    discord_thread_id: str | None = None,
    answer_text: str | None = None,
) -> int:
    with ask_db.get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO questions (user_id, question_text, points_spent, status, created_at, discord_message_id, discord_thread_id, answer_text) "
            "VALUES (?, ?, 0, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?, ?, ?)",
            (
                user_id,
                text,
                "answered" if answer_text else "pending",
                discord_message_id,
                discord_thread_id,
                answer_text,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _create_session(user_id: int, email: str, name: str = "User") -> str:
    token = f"sess-{user_id}-{int(time.time() * 1000)}"
    ask_module._sessions[token] = {
        "user_id": user_id,
        "google_id": f"google:{email}",
        "email": email,
        "name": name,
        "picture_url": "",
        "created_at": time.time(),
    }
    return token


def _fetch_question(question_id: int) -> dict:
    with ask_db.get_db() as conn:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        return dict(row)


def test_get_me_sets_csrf_cookie(tmp_path):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("owner@example.com")
    session_token = _create_session(user_id, "owner@example.com")

    client = TestClient(app)
    response = client.get("/api/ask/me", cookies={"ask_session": session_token})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "ask_csrf=" in set_cookie
    assert "HttpOnly" not in set_cookie
    assert "Max-Age=86400" in set_cookie


def test_submit_question_requires_csrf(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("owner@example.com")
    session_token = _create_session(user_id, "owner@example.com")

    async def _fake_post_question(**_kwargs):
        return SimpleNamespace(
            delivered=False,
            guild_id=None,
            channel_id=None,
            message_id=None,
            thread_id=None,
        )

    monkeypatch.setattr(ask_module, "post_question_to_discord", _fake_post_question)
    client = TestClient(app)
    cookies = {"ask_session": session_token, "ask_csrf": "csrf-token-1"}
    payload = {"question_text": "How do I troubleshoot this issue quickly?"}

    missing = client.post("/api/ask/questions", cookies=cookies, json=payload)
    assert missing.status_code == 403

    mismatch = client.post(
        "/api/ask/questions",
        cookies=cookies,
        headers={"X-CSRF-Token": "different-token"},
        json=payload,
    )
    assert mismatch.status_code == 403

    ok = client.post(
        "/api/ask/questions",
        cookies=cookies,
        headers={"X-CSRF-Token": "csrf-token-1"},
        json=payload,
    )
    assert ok.status_code == 201


def test_logout_requires_csrf(tmp_path):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("owner@example.com")
    session_token = _create_session(user_id, "owner@example.com")

    client = TestClient(app)
    cookies = {"ask_session": session_token, "ask_csrf": "csrf-token-logout"}

    missing = client.post("/api/ask/auth/logout", cookies=cookies)
    assert missing.status_code == 403

    ok = client.post("/api/ask/auth/logout", cookies=cookies, headers={"X-CSRF-Token": "csrf-token-logout"})
    assert ok.status_code == 200
    assert session_token not in ask_module._sessions


def test_sse_enforces_question_ownership(tmp_path):
    _reset_ask_db(tmp_path)
    user_one_id = _insert_user("user1@example.com")
    user_two_id = _insert_user("user2@example.com")
    foreign_question_id = _insert_question(user_id=user_two_id, text="Question from another user")
    session_token = _create_session(user_one_id, "user1@example.com")

    client = TestClient(app)
    response = client.get(f"/api/ask/questions/{foreign_question_id}/events", cookies={"ask_session": session_token})

    assert response.status_code == 404


def test_answer_webhook_uses_constant_time_compare(monkeypatch):
    monkeypatch.setattr(ask_module, "ASK_ANSWER_WEBHOOK_SECRET", "webhook-secret")
    captured: dict[str, str] = {}

    def _fake_compare_digest(left, right):
        captured["left"] = left
        captured["right"] = right
        return False

    monkeypatch.setattr(ask_module.hmac, "compare_digest", _fake_compare_digest)
    client = TestClient(app)

    response = client.post(
        "/api/ask/answers",
        headers={"X-Webhook-Secret": "wrong-secret"},
        json={"question_id": 1, "answer_text": "Test"},
    )

    assert response.status_code == 401
    assert captured["left"] == "wrong-secret"
    assert captured["right"] == "webhook-secret"


def test_n8n_webhook_uses_constant_time_compare(monkeypatch):
    monkeypatch.setenv("N8N_TOKEN", "n8n-secret")
    captured: dict[str, str] = {}

    def _fake_compare_digest(left, right):
        captured["left"] = left
        captured["right"] = right
        return False

    monkeypatch.setattr(ask_module.hmac, "compare_digest", _fake_compare_digest)
    client = TestClient(app)

    response = client.post(
        "/api/ask/discord/question",
        headers={"X-N8N-TOKEN": "wrong-token"},
        json={"message_id": "m1", "content": "hello"},
    )

    assert response.status_code == 401
    assert captured["left"] == "wrong-token"
    assert captured["right"] == "n8n-secret"


def _request_with_headers(path: str, headers: dict[str, str]) -> Request:
    raw_headers = [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()]

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("backend", 8000),
    }
    return Request(scope, receive)


def test_webhook_size_limit_rejects_large_content_length(monkeypatch):
    monkeypatch.setattr(ask_module, "ASK_WEBHOOK_MAX_BYTES", 64 * 1024)
    request = _request_with_headers("/api/ask/answers", {"Content-Length": str(70 * 1024)})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(ask_module._require_webhook_size_limit(request))
    assert exc.value.status_code == 413


def test_discord_answer_requires_support_role_and_is_idempotent(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("asker@example.com")
    question_id = _insert_question(
        user_id=user_id,
        text="Original question",
        discord_message_id="discord-msg-1",
        answer_text="Existing answer",
    )

    monkeypatch.setenv("N8N_TOKEN", "n8n-secret")
    monkeypatch.setenv("DISCORD_SUPPORT_ROLE_ID", "support-role")
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setattr(ask_module, "send_custom_email", lambda **_kwargs: True)
    client = TestClient(app)

    missing_role = client.post(
        "/api/ask/discord/answer",
        headers={"X-N8N-TOKEN": "n8n-secret"},
        json={
            "reply_to_message_id": "discord-msg-1",
            "answer_text": "Attempted overwrite",
            "author_role_ids": ["random-role"],
        },
    )
    assert missing_role.status_code == 403

    no_override = client.post(
        "/api/ask/discord/answer",
        headers={"X-N8N-TOKEN": "n8n-secret"},
        json={
            "reply_to_message_id": "discord-msg-1",
            "answer_text": "Attempted overwrite",
            "author_role_ids": ["support-role"],
        },
    )
    assert no_override.status_code == 409

    override = client.post(
        "/api/ask/discord/answer",
        headers={"X-N8N-TOKEN": "n8n-secret", "X-ADMIN-OVERRIDE": "admin-token"},
        json={
            "reply_to_message_id": "discord-msg-1",
            "answer_text": "Overwritten by admin override",
            "author_role_ids": ["support-role"],
        },
    )
    assert override.status_code == 200

    updated = _fetch_question(question_id)
    assert updated["answer_text"] == "Overwritten by admin override"

