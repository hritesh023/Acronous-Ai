import sqlite3
import json
import os
from datetime import datetime
from collections import deque

class MemorySystem:
    def __init__(self, config):
        self.config = config
        self.db_path = config.DB_PATH
        self.short_term = deque(maxlen=config.MAX_HISTORY)
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TEXT,
                metadata TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER,
                rating INTEGER,
                comment TEXT,
                timestamp TEXT
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT,
                source TEXT,
                confidence REAL,
                timestamp TEXT
            )
        """)
        self.conn.commit()

    def add(self, session_id, role, content, metadata=None):
        return self.add_message(session_id, role, content, metadata)

    def add_message(self, session_id, role, content, metadata=None):
        ts = datetime.now().isoformat()
        self.short_term.append({
            "role": role,
            "content": content,
            "timestamp": ts
        })
        self.cursor.execute(
            "INSERT INTO conversations (session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, ts, json.dumps(metadata or {}))
        )
        self.conn.commit()

    def get_history(self, session_id, limit=None):
        if limit is None:
            limit = self.config.MAX_HISTORY
        self.cursor.execute(
            "SELECT role, content, timestamp FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit)
        )
        rows = self.cursor.fetchall()
        return [
            {"role": r[0], "content": r[1], "timestamp": r[2]}
            for r in reversed(rows)
        ]

    def get_recent_context(self, session_id, n=10):
        self.cursor.execute(
            "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, n)
        )
        rows = self.cursor.fetchall()
        context = []
        for r in reversed(rows):
            context.append(f"{r[0].capitalize()}: {r[1]}")
        return "\n".join(context)

    def add_feedback(self, conversation_id, rating, comment=""):
        ts = datetime.now().isoformat()
        self.cursor.execute(
            "INSERT INTO feedback (conversation_id, rating, comment, timestamp) VALUES (?, ?, ?, ?)",
            (conversation_id, rating, comment, ts)
        )
        self.conn.commit()

    def store_knowledge(self, key, value, source="user", confidence=1.0):
        ts = datetime.now().isoformat()
        self.cursor.execute("""
            INSERT INTO knowledge (key, value, source, confidence, timestamp)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                confidence = (confidence + excluded.confidence) / 2,
                timestamp = excluded.timestamp
        """, (key, value, source, confidence, ts))
        self.conn.commit()

    def retrieve_knowledge(self, key):
        self.cursor.execute(
            "SELECT value, confidence FROM knowledge WHERE key = ?",
            (key,)
        )
        row = self.cursor.fetchone()
        if row:
            return {"value": row[0], "confidence": row[1]}
        return None

    def search_knowledge(self, query, limit=5):
        self.cursor.execute(
            "SELECT key, value, confidence FROM knowledge WHERE key LIKE ? OR value LIKE ? ORDER BY confidence DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)
        )
        return [{"key": r[0], "value": r[1], "confidence": r[2]} for r in self.cursor.fetchall()]

    def get_all_sessions(self):
        self.cursor.execute(
            "SELECT DISTINCT session_id FROM conversations ORDER BY MAX(id) DESC"
        )
        return [r[0] for r in self.cursor.fetchall()]

    def clear_session(self, session_id):
        self.cursor.execute(
            "DELETE FROM conversations WHERE session_id = ?",
            (session_id,)
        )
        self.conn.commit()

    def get_stats(self):
        self.cursor.execute("SELECT COUNT(*) FROM conversations")
        total_msgs = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(DISTINCT session_id) FROM conversations")
        total_sessions = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT AVG(rating) FROM feedback")
        avg_rating = self.cursor.fetchone()[0]
        return {
            "total_messages": total_msgs,
            "total_sessions": total_sessions,
            "avg_rating": round(avg_rating, 2) if avg_rating else 0
        }

    def close(self):
        self.conn.close()
