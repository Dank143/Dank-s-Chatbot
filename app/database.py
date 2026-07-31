import asyncio
import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar

DB_PATH: Path = Path(__file__).parent.parent / "chatbot.db"
DBFetchMode = Literal["all", "one", "none"]
DatabaseRow = dict[str, Any]
T = TypeVar("T")


def get_db() -> sqlite3.Connection:
    """Create a configured SQLite connection for a single unit of work."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    """Return the existing column names for a SQLite table."""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def init_db() -> None:
    """Create tables if absent and apply lightweight migrations."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chats (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL DEFAULT 'New Chat',
                model      TEXT,
                starred    INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                duo_mode   INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                chat_id     TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                attachments TEXT,
                model       TEXT,
                duo_side    INTEGER NOT NULL DEFAULT 0,
                search_data TEXT,
                FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
        """)
        chat_columns = _table_columns(conn, "chats")
        message_columns = _table_columns(conn, "messages")

        if "attachments" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN attachments TEXT")
        if "model" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        if "duo_mode" not in chat_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN duo_mode INTEGER NOT NULL DEFAULT 0")
        if "duo_side" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN duo_side INTEGER NOT NULL DEFAULT 0")
            conn.execute("""
                WITH numbered AS (
                    SELECT id, (ROW_NUMBER() OVER(PARTITION BY chat_id ORDER BY created_at) - 1) % 2 AS side
                    FROM messages 
                    WHERE role = 'assistant' AND chat_id IN (SELECT id FROM chats WHERE duo_mode = 1)
                )
                UPDATE messages SET duo_side = (SELECT side FROM numbered WHERE numbered.id = messages.id)
                WHERE id IN (SELECT id FROM numbered);
            """)
        if "search_data" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN search_data TEXT")
        if "timing_data" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN timing_data TEXT")
        if "persona" not in chat_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN persona TEXT NOT NULL DEFAULT 'default'")
        if "model2" not in chat_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN model2 TEXT")
        if "persona2" not in chat_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN persona2 TEXT")
        if "persona" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN persona TEXT")

        # Index: every send/regenerate queries messages by (chat_id, created_at).
        # Without this, SQLite full-scans the entire table on every request.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at)")


def now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


async def db_execute(
    query: str,
    params: Sequence[Any] = (),
    fetch: DBFetchMode = "none",
) -> list[DatabaseRow] | DatabaseRow | None:
    """Run one SQL statement in a worker thread and return dictionary rows."""

    def _work() -> list[DatabaseRow] | DatabaseRow | None:
        with get_db() as conn:
            res = conn.execute(query, params)
            if fetch == "all":
                return [dict(row) for row in res.fetchall()]
            if fetch == "one":
                row = res.fetchone()
                return dict(row) if row is not None else None
            return None

    return await asyncio.to_thread(_work)


async def run_db_task(func: Callable[[sqlite3.Connection], T]) -> T:
    """Run a database unit of work in a thread with a managed connection."""

    def _work() -> T:
        with get_db() as conn:
            return func(conn)

    return await asyncio.to_thread(_work)
