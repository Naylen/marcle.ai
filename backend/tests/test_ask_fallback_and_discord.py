import asyncio
from datetime import datetime, timedelta, timezone

import app.ask_db as ask_db
import app.routers.ask as ask_module


def _reset_ask_db(tmp_path):
    existing = getattr(ask_db._local, "conn", None)
    if existing is not None:
        existing.close()
        delattr(ask_db._local, "conn")
    ask_db.ASK_DB_PATH = str(tmp_path / "ask-test.db")
    ask_db.init_db()


def _insert_user(email: str = "user@example.com", name: str = "User") -> int:
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
    question_text: str,
    discord_message_id: str | None = None,
    discord_thread_id: str | None = None,
    created_at: datetime | None = None,
    human_deadline_at: datetime | None = None,
    openai_deadline_at: datetime | None = None,
    local_llm_attempted_at: datetime | None = None,
    openai_attempted_at: datetime | None = None,
) -> int:
    created = created_at or datetime.now(timezone.utc)
    with ask_db.get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO questions ("
            "user_id, question_text, points_spent, status, created_at, deadline_at, human_deadline_at, openai_deadline_at, "
            "discord_message_id, discord_thread_id, local_llm_attempted_at, openai_attempted_at"
            ") VALUES (?, ?, 0, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                question_text,
                created.isoformat(),
                human_deadline_at.isoformat() if human_deadline_at else None,
                human_deadline_at.isoformat() if human_deadline_at else None,
                openai_deadline_at.isoformat() if openai_deadline_at else None,
                discord_message_id,
                discord_thread_id,
                local_llm_attempted_at.isoformat() if local_llm_attempted_at else None,
                openai_attempted_at.isoformat() if openai_attempted_at else None,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _fetch_question(question_id: int) -> dict:
    with ask_db.get_db() as conn:
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
        return dict(row)


def test_discord_human_answer_accepts_thread_and_reply(tmp_path):
    _reset_ask_db(tmp_path)
    user_id = _insert_user()

    thread_question_id = _insert_question(
        user_id=user_id,
        question_text="Thread question",
        discord_message_id="msg-thread",
        discord_thread_id="thread-1",
    )
    reply_question_id = _insert_question(
        user_id=user_id,
        question_text="Reply question",
        discord_message_id="msg-reply",
    )

    asyncio.run(
        ask_module._handle_discord_human_answer(
            {
                "thread_id": "thread-1",
                "content": "Handled in thread",
                "message_id": "answer-1",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
            }
        )
    )
    asyncio.run(
        ask_module._handle_discord_human_answer(
            {
                "reply_to_message_id": "msg-reply",
                "content": "Handled by channel reply",
                "message_id": "answer-2",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
            }
        )
    )

    thread_question = _fetch_question(thread_question_id)
    assert thread_question["answer_text"] == "Handled in thread"
    assert thread_question["answered_by"] == "human"
    assert thread_question["status"] == "answered"

    reply_question = _fetch_question(reply_question_id)
    assert reply_question["answer_text"] == "Handled by channel reply"
    assert reply_question["answered_by"] == "human"
    assert reply_question["status"] == "answered"


def test_local_llm_failure_keeps_question_pending_and_emits_status(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    user_id = _insert_user(email="pending@example.com")

    now = datetime.now(timezone.utc)
    question_id = _insert_question(
        user_id=user_id,
        question_text="Need help with local fallback",
        discord_message_id="msg-local-fail",
        created_at=now - timedelta(minutes=6),
        human_deadline_at=now - timedelta(minutes=1),
        openai_deadline_at=now + timedelta(minutes=4),
    )

    async def _raise_local(_question_text: str) -> str:
        raise RuntimeError("local llm unavailable")

    async def _should_not_call_openai(_question_text: str) -> str:
        raise AssertionError("openai should not run before openai deadline")

    events: list[tuple[str, dict]] = []

    async def _capture_event(question_id_arg: int, event_name: str, payload: dict):
        if question_id_arg == question_id:
            events.append((event_name, payload))

    monkeypatch.setattr(ask_module, "generate_local_answer_text", _raise_local)
    monkeypatch.setattr(ask_module, "generate_openai_answer_text", _should_not_call_openai)
    monkeypatch.setattr(ask_module, "_publish_question_event", _capture_event)

    asyncio.run(ask_module._process_fallback_candidates_once())

    question = _fetch_question(question_id)
    assert question["answer_text"] is None
    assert question["status"] == "pending"
    assert question["local_llm_attempted_at"] is not None
    assert question["openai_attempted_at"] is None

    status_events = [payload for event, payload in events if event == "status"]
    assert any(event_payload.get("status") == "local_llm_failed" for event_payload in status_events)


def test_openai_stage_runs_only_after_local_stage(tmp_path, monkeypatch):
    _reset_ask_db(tmp_path)
    user_id = _insert_user(email="openai@example.com")

    now = datetime.now(timezone.utc)
    question_id = _insert_question(
        user_id=user_id,
        question_text="Need help with openai fallback",
        discord_message_id="msg-openai",
        created_at=now - timedelta(minutes=20),
        human_deadline_at=now - timedelta(minutes=15),
        openai_deadline_at=now - timedelta(minutes=10),
        local_llm_attempted_at=now - timedelta(minutes=14),
    )

    async def _should_not_call_local(_question_text: str) -> str:
        raise AssertionError("local stage should not run when already attempted")

    async def _openai_answer(_question_text: str) -> str:
        return "OpenAI fallback answer"

    async def _noop_post_answer(**_kwargs):
        return True

    monkeypatch.setattr(ask_module, "generate_local_answer_text", _should_not_call_local)
    monkeypatch.setattr(ask_module, "generate_openai_answer_text", _openai_answer)
    monkeypatch.setattr(ask_module, "post_answer_to_discord", _noop_post_answer)

    asyncio.run(ask_module._process_fallback_candidates_once())

    question = _fetch_question(question_id)
    assert question["answer_text"] == "OpenAI fallback answer"
    assert question["answered_by"] == "llm_openai"
    assert question["status"] == "answered"
    assert question["openai_attempted_at"] is not None

