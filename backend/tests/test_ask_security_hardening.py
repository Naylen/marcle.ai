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


def _reset_sse_tracking() -> None:
    with ask_module._sse_conn_guard:
        ask_module._sse_active_conn_by_session.clear()
        ask_module._sse_active_conn_by_ip.clear()
        ask_module._sse_conn_starts_by_session.clear()


def _reset_ask_db(tmp_path) -> None:
    existing = getattr(ask_db._local, "conn", None)
    if existing is not None:
        existing.close()
        delattr(ask_db._local, "conn")
    ask_db.ASK_DB_PATH = str(tmp_path / "ask-security.db")
    ask_db.init_db()
    ask_module._sessions.clear()
    _reset_sse_tracking()


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


def _create_session(
    user_id: int,
    email: str,
    name: str = "User",
    csrf_token: str | None = None,
    created_at: float | None = None,
) -> str:
    token = f"sess-{user_id}-{int(time.time() * 1000)}"
    csrf_value = csrf_token or f"csrf-{user_id}-{int(time.time() * 1000)}"
    ask_module._sessions[token] = {
        "user_id": user_id,
        "google_id": f"google:{email}",
        "email": email,
        "name": name,
        "picture_url": "",
        "csrf_token": csrf_value,
        "created_at": created_at if created_at is not None else time.time(),
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
    session_token = _create_session(user_id, "owner@example.com", csrf_token="csrf-token-1")

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
    assert missing.json() == {"error": "invalid_csrf"}

    mismatch = client.post(
        "/api/ask/questions",
        cookies=cookies,
        headers={"X-CSRF-Token": "different-token"},
        json=payload,
    )
    assert mismatch.status_code == 403
    assert mismatch.json() == {"error": "invalid_csrf"}

    wrong_server_token = client.post(
        "/api/ask/questions",
        cookies=cookies,
        headers={"X-CSRF-Token": "csrf-token-1"},
        json=payload,
    )
    assert wrong_server_token.status_code == 201

    ask_module._sessions[session_token]["csrf_token"] = "server-side-different-token"
    session_mismatch = client.post(
        "/api/ask/questions",
        cookies=cookies,
        headers={"X-CSRF-Token": "csrf-token-1"},
        json=payload,
    )
    assert session_mismatch.status_code == 403
    assert session_mismatch.json() == {"error": "invalid_csrf"}


def test_logout_requires_csrf(tmp_path):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("owner@example.com")
    session_token = _create_session(user_id, "owner@example.com", csrf_token="csrf-token-logout")

    client = TestClient(app)
    cookies = {"ask_session": session_token, "ask_csrf": "csrf-token-logout"}

    missing = client.post("/api/ask/auth/logout", cookies=cookies)
    assert missing.status_code == 403
    assert missing.json() == {"error": "invalid_csrf"}

    ok = client.post("/api/ask/auth/logout", cookies=cookies, headers={"X-CSRF-Token": "csrf-token-logout"})
    assert ok.status_code == 200
    assert session_token not in ask_module._sessions


def test_submit_question_rejects_whitespace_only(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("space@example.com")
    session_token = _create_session(user_id, "space@example.com", csrf_token="csrf-whitespace")

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
    response = client.post(
        "/api/ask/questions",
        cookies={"ask_session": session_token, "ask_csrf": "csrf-whitespace"},
        headers={"X-CSRF-Token": "csrf-whitespace"},
        json={"question_text": "          "},
    )

    assert response.status_code == 400
    assert response.json().get("detail", {}).get("error") == "invalid_question"


def test_session_expiration_returns_unauthorized(tmp_path):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("expired@example.com")
    session_token = _create_session(
        user_id,
        "expired@example.com",
        created_at=time.time() - (ask_module.ASK_SESSION_MAX_AGE_SECONDS + 5),
    )

    client = TestClient(app)
    response = client.get("/api/ask/me", cookies={"ask_session": session_token})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert session_token not in ask_module._sessions


def test_oauth_callback_sets_hardened_session_and_csrf_cookies(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    async def _fake_exchange_code(code, redirect_uri):
        return {"access_token": f"token-{code}-{redirect_uri}"}

    async def _fake_get_user_info(access_token):
        return {
            "id": "google-user-1",
            "email": "cookie-test@example.com",
            "name": "Cookie Test",
            "picture": "",
        }

    monkeypatch.setattr(ask_module, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(ask_module, "get_user_info", _fake_get_user_info)

    state = "oauth-state-cookie-test"
    ask_module._oauth_states[state] = {
        "created_at": time.time(),
        "redirect_uri": "http://localhost:9182/api/ask/auth/callback",
        "base_public_url": "http://localhost:9182",
    }

    client = TestClient(app)
    response = client.get(f"/api/ask/auth/callback?code=abc123&state={state}", follow_redirects=False)

    assert response.status_code == 307
    set_cookies = response.headers.get_list("set-cookie")
    ask_session_cookie = next((item for item in set_cookies if item.startswith("ask_session=")), "")
    ask_csrf_cookie = next((item for item in set_cookies if item.startswith("ask_csrf=")), "")

    assert ask_session_cookie
    assert "HttpOnly" in ask_session_cookie
    assert "SameSite=lax" in ask_session_cookie
    assert "Path=/" in ask_session_cookie
    assert "Max-Age=86400" in ask_session_cookie

    assert ask_csrf_cookie
    assert "HttpOnly" not in ask_csrf_cookie
    assert "SameSite=lax" in ask_csrf_cookie
    assert "Path=/" in ask_csrf_cookie
    assert "Max-Age=86400" in ask_csrf_cookie


def test_sse_enforces_question_ownership(tmp_path):
    _reset_ask_db(tmp_path)
    user_one_id = _insert_user("user1@example.com")
    user_two_id = _insert_user("user2@example.com")
    foreign_question_id = _insert_question(user_id=user_two_id, text="Question from another user")
    session_token = _create_session(user_one_id, "user1@example.com")

    client = TestClient(app)
    response = client.get(f"/api/ask/questions/{foreign_question_id}/events", cookies={"ask_session": session_token})

    assert response.status_code == 404


def test_sse_connection_limit_and_release(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("owner@example.com")
    question_id = _insert_question(user_id=user_id, text="Question from owner")
    session_token = _create_session(user_id, "owner@example.com")
    client_ip = "127.0.0.1"

    monkeypatch.setattr(ask_module, "ASK_SSE_MAX_CONN_PER_SESSION", 1)
    monkeypatch.setattr(ask_module, "ASK_SSE_MAX_CONN_PER_IP", 10)
    monkeypatch.setattr(ask_module, "ASK_SSE_CONN_RATE_PER_MIN", 10)

    assert ask_module._allow_sse_stream(session_token, client_ip) is True
    client = TestClient(app)
    blocked = client.get(
        f"/api/ask/questions/{question_id}/events",
        cookies={"ask_session": session_token},
    )
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "too_many_streams"}

    with ask_module._sse_conn_guard:
        assert ask_module._sse_active_conn_by_session.get(session_token, 0) == 1
        assert ask_module._sse_active_conn_by_ip.get(client_ip, 0) == 1

    # Simulate stream disconnect/finally cleanup.
    ask_module._release_sse_stream(session_token, client_ip)
    with ask_module._sse_conn_guard:
        assert ask_module._sse_active_conn_by_session.get(session_token, 0) == 0
        assert ask_module._sse_active_conn_by_ip.get(client_ip, 0) == 0

    assert ask_module._allow_sse_stream(session_token, client_ip) is True
    ask_module._release_sse_stream(session_token, client_ip)


def test_sse_connection_rate_limited_per_minute(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("owner@example.com")
    question_id = _insert_question(user_id=user_id, text="Question from owner")
    session_token = _create_session(user_id, "owner@example.com")
    client_ip = "127.0.0.1"

    monkeypatch.setattr(ask_module, "ASK_SSE_MAX_CONN_PER_SESSION", 2)
    monkeypatch.setattr(ask_module, "ASK_SSE_MAX_CONN_PER_IP", 10)
    monkeypatch.setattr(ask_module, "ASK_SSE_CONN_RATE_PER_MIN", 1)

    assert ask_module._allow_sse_stream(session_token, client_ip) is True
    ask_module._release_sse_stream(session_token, client_ip)

    client = TestClient(app)
    blocked = client.get(
        f"/api/ask/questions/{question_id}/events",
        cookies={"ask_session": session_token},
    )
    assert blocked.status_code == 429
    assert blocked.json() == {"error": "too_many_streams"}


def test_question_list_omits_discord_internal_fields(tmp_path):
    _reset_ask_db(tmp_path)
    user_id = _insert_user("owner@example.com")
    question_id = _insert_question(
        user_id=user_id,
        text="Question from owner",
        discord_message_id="discord-message-1",
        discord_thread_id="discord-thread-1",
    )
    with ask_db.get_db() as conn:
        conn.execute(
            "UPDATE questions SET discord_channel_id = ?, discord_guild_id = ? WHERE id = ?",
            ("discord-channel-1", "discord-guild-1", question_id),
        )
        conn.commit()

    session_token = _create_session(user_id, "owner@example.com")
    client = TestClient(app)
    response = client.get("/api/ask/questions", cookies={"ask_session": session_token})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list) and payload
    first = payload[0]
    assert "discord_message_id" not in first
    assert "discord_thread_id" not in first
    assert "discord_channel_id" not in first
    assert "discord_guild_id" not in first


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
