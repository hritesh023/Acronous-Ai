import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.environ.get("DATABASE_PATH", "./apex_ai.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'anonymous',
            title TEXT DEFAULT 'New Conversation',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_id TEXT DEFAULT 'anonymous',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            type TEXT DEFAULT 'text',
            sources TEXT,
            analysis TEXT,
            label TEXT,
            image TEXT,
            media_url TEXT,
            video_url TEXT,
            audio_url TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
    """)
    # Migrate existing tables: add missing columns if they don't exist
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    for col in ('label', 'image', 'media_url', 'video_url', 'audio_url'):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT")
    conn.commit()
    conn.close()


def create_conversation(conv_id: str, title: str = "New Conversation", user_id: str = "anonymous") -> dict:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (conv_id, user_id, title, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    conn.close()
    return dict(row) if row else {"id": conv_id, "title": title}


def get_conversations(user_id: str = "anonymous") -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation(conv_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_conversation(conv_id: str, title: str) -> Optional[dict]:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, conv_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_conversation(conv_id: str) -> bool:
    conn = get_connection()
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def add_message(
    msg_id: str,
    conv_id: str,
    role: str,
    content: str,
    msg_type: str = "text",
    user_id: str = "anonymous",
    sources: Optional[str] = None,
    analysis: Optional[str] = None,
    label: Optional[str] = None,
    image: Optional[str] = None,
    media_url: Optional[str] = None,
    video_url: Optional[str] = None,
    audio_url: Optional[str] = None,
) -> dict:
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO messages (id, conversation_id, user_id, role, content, type, sources, analysis, label, image, media_url, video_url, audio_url, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (msg_id, conv_id, user_id, role, content, msg_type, sources, analysis, label, image, media_url, video_url, audio_url, now),
    )
    conn.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
    conn.close()
    return dict(row) if row else {"id": msg_id, "role": role, "content": content}


def get_messages(conv_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC", (conv_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_conversation_context(conv_id: str, limit: int = 50) -> list[dict]:
    msgs = get_messages(conv_id)
    return [
        {"role": m["role"], "content": m["content"]}
        for m in msgs[-limit:]
    ]
