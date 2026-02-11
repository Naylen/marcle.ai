import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import app.ask_db as ask_db
import app.routers.ask as ask_module
from app.main import app


def _reset_ask_db(tmp_path) -> None:
    existing = getattr(ask_db._local, "conn", None)
    if existing is not None:
        existing.close()
        delattr(ask_db._local, "conn")
    ask_db.ASK_DB_PATH = str(tmp_path / "ask-email-test.db")
    ask_db.init_db()


def _insert_pending_question(user_email: str = "asker@example.com") -> int:
    with ask_db.get_db() as conn:
        user_cursor = conn.execute(
            "INSERT INTO users (google_id, email, name, picture_url, points) VALUES (?, ?, ?, '', 0)",
            (f"google:{user_email}", user_email, "Asker"),
        )
        user_id = int(user_cursor.lastrowid)
        question_cursor = conn.execute(
            "INSERT INTO questions (user_id, question_text, points_spent, status, created_at) "
            "VALUES (?, ?, 0, 'pending', ?)",
            (user_id, "How do I fix this issue?", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return int(question_cursor.lastrowid)


def test_admin_email_test_requires_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    client = TestClient(app)

    response = client.post("/api/ask/admin/email/test", json={"to": "someone@example.com"})

    assert response.status_code == 401


def test_admin_email_test_success(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")

    def _fake_send(*, to_email, subject, text_body, html_body, question_id, log_context):
        assert to_email == "someone@example.com"
        assert question_id is None
        assert log_context == "admin_email_test"
        assert "SMTP test" in subject
        assert "test email" in text_body.lower()
        return True, None

    monkeypatch.setattr(ask_module, "send_custom_email_result", _fake_send)
    client = TestClient(app)

    response = client.post(
        "/api/ask/admin/email/test",
        headers={"Authorization": "Bearer admin-token"},
        json={"to": "someone@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_admin_email_test_failure(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")

    def _fake_send(**_kwargs):
        return False, "RuntimeError: smtp failed"

    monkeypatch.setattr(ask_module, "send_custom_email_result", _fake_send)
    client = TestClient(app)

    response = client.post(
        "/api/ask/admin/email/test",
        headers={"Authorization": "Bearer admin-token"},
        json={"to": "someone@example.com"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["error"] == "RuntimeError: smtp failed"


def test_submit_answer_uses_asker_email_from_db(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    question_id = _insert_pending_question("asker-db@example.com")
    monkeypatch.setenv("SMTP_USER", "smtp-login@example.com")
    monkeypatch.setattr(ask_module, "ASK_ANSWER_WEBHOOK_SECRET", "webhook-secret")

    captured: dict[str, str] = {}

    def _fake_send_answer_email(*, to_email, to_name, question_text, answer_text, question_id):
        captured["to_email"] = to_email
        captured["to_name"] = to_name
        captured["question_text"] = question_text
        captured["answer_text"] = answer_text
        captured["question_id"] = str(question_id)
        return True

    monkeypatch.setattr(ask_module, "send_answer_email", _fake_send_answer_email)
    client = TestClient(app)

    response = client.post(
        "/api/ask/answers",
        headers={"X-Webhook-Secret": "webhook-secret"},
        json={"question_id": question_id, "answer_text": "Try restarting the service."},
    )

    assert response.status_code == 200
    assert captured["to_email"] == "asker-db@example.com"
    assert captured["to_email"] != os.environ["SMTP_USER"]

