import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "chatbot.db"


def get_db():
    """New DB connection with FK, WAL, and busy timeout."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db():
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
        # Migration: add attachments column if missing.
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN attachments TEXT")
        except sqlite3.OperationalError:
            pass
        # Migration: add model column if missing.
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN model TEXT")
        except sqlite3.OperationalError:
            pass
        # Migration: add duo_mode column if missing.
        try:
            conn.execute("ALTER TABLE chats ADD COLUMN duo_mode INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        # Migration: add duo_side column if missing, and fix existing duo chats.
        try:
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
        except sqlite3.OperationalError:
            pass
        # Migration: add search_data column if missing.
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN search_data TEXT")
        except sqlite3.OperationalError:
            pass
        # Migration: add timing_data column if missing.
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN timing_data TEXT")
        except sqlite3.OperationalError:
            pass
        # Migration: add persona column if missing.
        try:
            conn.execute("ALTER TABLE chats ADD COLUMN persona TEXT NOT NULL DEFAULT 'default'")
        except sqlite3.OperationalError:
            pass
        # Migration: add model2 column if missing.
        try:
            conn.execute("ALTER TABLE chats ADD COLUMN model2 TEXT")
        except sqlite3.OperationalError:
            pass
        # Migration: add persona2 column if missing.
        try:
            conn.execute("ALTER TABLE chats ADD COLUMN persona2 TEXT")
        except sqlite3.OperationalError:
            pass
        # Migration: add persona column to messages if missing.
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN persona TEXT")
        except sqlite3.OperationalError:
            pass

        # Index: every send/regenerate queries messages by (chat_id, created_at).
        # Without this, SQLite full-scans the entire table on every request.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, created_at)")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def db_execute(query: str, params: tuple | list = (), fetch: str = "none"):
    """Execute a query and fetch 'all', 'one', or 'none'. Returns dicts."""
    def _work():
        with get_db() as conn:
            res = conn.execute(query, params)
            if fetch == "all": return [dict(r) for r in res.fetchall()]
            if fetch == "one":
                row = res.fetchone()
                return dict(row) if row else None
            return None
    return await asyncio.to_thread(_work)


async def run_db_task(func):
    """Run a custom function in a background thread, passing it a managed DB connection."""
    def _work():
        with get_db() as conn:
            return func(conn)
    return await asyncio.to_thread(_work)
