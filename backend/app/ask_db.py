"""SQLite database initialization and connection management for Ask app."""

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

ASK_DB_PATH: str = os.getenv("ASK_DB_PATH", "/data/ask.db")
DEFAULT_STARTING_POINTS: int = int(os.getenv("DEFAULT_STARTING_POINTS", "10"))
POINTS_PER_QUESTION: int = int(os.getenv("POINTS_PER_QUESTION", "1"))

_local = threading.local()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id       TEXT    UNIQUE NOT NULL,
    email           TEXT    NOT NULL,
    name            TEXT    NOT NULL DEFAULT '',
    picture_url     TEXT    NOT NULL DEFAULT '',
    points          INTEGER NOT NULL DEFAULT {default_points} CHECK (points >= 0),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    question_text   TEXT    NOT NULL,
    answer_text     TEXT,
    discord_guild_id TEXT,
    discord_channel_id TEXT,
    discord_message_id TEXT,
    discord_thread_id TEXT,
    discord_answer_message_id TEXT,
    points_spent    INTEGER NOT NULL DEFAULT {points_per_question},
    status          TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'answered', 'failed')),
    discord_sent    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    answered_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_questions_user_id ON questions(user_id);
CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(status);
"""


def _migrate_questions_table(conn: sqlite3.Connection) -> None:
    """Add newly introduced Ask columns/indexes without breaking existing DBs."""
    question_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(questions)").fetchall()
    }

    required_columns: list[tuple[str, str]] = [
        ("discord_guild_id", "TEXT"),
        ("discord_channel_id", "TEXT"),
        ("discord_message_id", "TEXT"),
        ("discord_thread_id", "TEXT"),
        ("discord_answer_message_id", "TEXT"),
        ("answer_text", "TEXT"),
        ("answered_at", "TEXT"),
    ]

    for column_name, column_def in required_columns:
        if column_name not in question_columns:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {column_name} {column_def}")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_questions_discord_message_id "
        "ON questions(discord_message_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_questions_discord_thread_id "
        "ON questions(discord_thread_id)"
    )


def _get_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        Path(ASK_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(ASK_DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_connection()
    schema = SCHEMA_SQL.format(
        default_points=DEFAULT_STARTING_POINTS,
        points_per_question=POINTS_PER_QUESTION,
    )
    conn.executescript(schema)
    _migrate_questions_table(conn)
    conn.commit()


@contextmanager
def get_db():
    """Yield a SQLite connection for use in a request context."""
    conn = _get_connection()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
