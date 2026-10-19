"""Conversation-skeleton persistence: one ongoing conversation per user.

Own SQLite database (``data/conversations/conversations.db``), following the
per-domain convention (personality, followthrough, provenance). Strict
per-user rows: every read and write is scoped by user_id.

Tables:
  conversations    — one row per (user_id, conversation_id); the skeleton
                     itself. kind='skeleton' for the main thread.
  messages         — every turn, tagged with archetype_id (the seat branch;
                     NULL only for future trunk turns), role, body, the mode
                     used, and a live-context snapshot (JSON).
  thread_state     — per-seat rolling summary + activity: the quiet
                     background continuity each persona carries.
  suggestion_runs  — cached suggestion-engine output, watermarked by the
                     latest message id so GET /conversation/suggestions
                     doesn't re-run the LLM on every call.

Threading: one connection guarded by a lock is enough for user-triggered use.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "conversations"
DEFAULT_DB_PATH = DATA_DIR / "conversations.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'skeleton',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, conversation_id)
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  archetype_id TEXT,
  role TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT 'trained',
  context_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_messages_user_conv
  ON messages (user_id, conversation_id, created_at, id);
CREATE TABLE IF NOT EXISTS thread_state (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  archetype_id TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  last_active TEXT NOT NULL DEFAULT '',
  messages_since_summary INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, conversation_id, archetype_id)
);
CREATE TABLE IF NOT EXISTS suggestion_runs (
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  up_to_message_id TEXT NOT NULL,
  suggestions_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, conversation_id)
);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationStore:
    """SQLite-backed store for the conversation skeleton."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- conversations --------------------------------------------------------

    def ensure_conversation(
        self, user_id: str, conversation_id: str = "skeleton", kind: str = "skeleton"
    ) -> dict[str, Any]:
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO conversations "
                "(user_id, conversation_id, kind, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, conversation_id, kind, now, now),
            )
            self._conn.execute(
                "UPDATE conversations SET updated_at = ? "
                "WHERE user_id = ? AND conversation_id = ?",
                (now, user_id, conversation_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT user_id, conversation_id, kind, created_at, updated_at "
                "FROM conversations WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
        return dict(row)

    # -- messages --------------------------------------------------------------

    def append_message(
        self,
        user_id: str,
        conversation_id: str,
        archetype_id: str | None,
        role: str,
        body: str,
        mode: str = "trained",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        msg_id = uuid.uuid4().hex[:16]
        now = _utcnow()
        context_json = json.dumps(context or {}, ensure_ascii=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (id, user_id, conversation_id, archetype_id, "
                "role, body, mode, context_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg_id,
                    user_id,
                    conversation_id,
                    archetype_id,
                    role,
                    body or "",
                    mode or "trained",
                    context_json,
                    now,
                ),
            )
            self._conn.commit()
        return {
            "id": msg_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "archetype_id": archetype_id,
            "role": role,
            "body": body or "",
            "mode": mode or "trained",
            "context": context or {},
            "created_at": now,
        }

    def history(
        self, user_id: str, conversation_id: str = "skeleton", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Oldest-first message history for hydration. Strictly per-user."""
        limit = max(1, min(int(limit or 50), 200))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, user_id, conversation_id, archetype_id, role, body, "
                "mode, context_json, created_at FROM messages "
                "WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (user_id, conversation_id, limit),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in reversed(rows):
            try:
                context = json.loads(r["context_json"] or "{}")
            except Exception:
                context = {}
            out.append(
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "conversation_id": r["conversation_id"],
                    "archetype_id": r["archetype_id"],
                    "role": r["role"],
                    "body": r["body"],
                    "mode": r["mode"],
                    "context": context,
                    "created_at": r["created_at"],
                }
            )
        return out

    def latest_message_id(self, user_id: str, conversation_id: str = "skeleton") -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM messages WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (user_id, conversation_id),
            ).fetchone()
        return row["id"] if row else None

    # -- thread state -----------------------------------------------------------

    def get_thread_state(
        self, user_id: str, conversation_id: str, archetype_id: str
    ) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, conversation_id, archetype_id, summary, "
                "last_active, messages_since_summary FROM thread_state "
                "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                (user_id, conversation_id, archetype_id),
            ).fetchone()
        if row is None:
            return {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "archetype_id": archetype_id,
                "summary": "",
                "last_active": "",
                "messages_since_summary": 0,
            }
        return dict(row)

    def update_thread_state(
        self,
        user_id: str,
        conversation_id: str,
        archetype_id: str,
        *,
        summary: str | None = None,
        increment: int = 0,
        reset_counter: bool = False,
    ) -> dict[str, Any]:
        """Touch a seat's thread: optionally replace the summary, bump the
        since-summary counter, or reset it (after a summarization pass)."""
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO thread_state "
                "(user_id, conversation_id, archetype_id, summary, last_active, "
                "messages_since_summary) VALUES (?, ?, ?, '', ?, 0)",
                (user_id, conversation_id, archetype_id, now),
            )
            if summary is not None:
                self._conn.execute(
                    "UPDATE thread_state SET summary = ? "
                    "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                    (summary, user_id, conversation_id, archetype_id),
                )
            if increment:
                self._conn.execute(
                    "UPDATE thread_state SET messages_since_summary = "
                    "messages_since_summary + ? "
                    "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                    (increment, user_id, conversation_id, archetype_id),
                )
            if reset_counter:
                self._conn.execute(
                    "UPDATE thread_state SET messages_since_summary = 0 "
                    "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                    (user_id, conversation_id, archetype_id),
                )
            self._conn.execute(
                "UPDATE thread_state SET last_active = ? "
                "WHERE user_id = ? AND conversation_id = ? AND archetype_id = ?",
                (now, user_id, conversation_id, archetype_id),
            )
            self._conn.commit()
        return self.get_thread_state(user_id, conversation_id, archetype_id)

    # -- suggestion runs (cache) --------------------------------------------------

    def get_suggestion_run(
        self, user_id: str, conversation_id: str = "skeleton"
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, conversation_id, up_to_message_id, "
                "suggestions_json, created_at FROM suggestion_runs "
                "WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchone()
        if row is None:
            return None
        try:
            suggestions = json.loads(row["suggestions_json"] or "{}")
        except Exception:
            suggestions = {}
        return {
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "up_to_message_id": row["up_to_message_id"],
            "suggestions": suggestions,
            "created_at": row["created_at"],
        }

    def save_suggestion_run(
        self,
        user_id: str,
        conversation_id: str,
        up_to_message_id: str,
        suggestions: dict[str, Any],
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO suggestion_runs "
                "(user_id, conversation_id, up_to_message_id, suggestions_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    user_id,
                    conversation_id,
                    up_to_message_id,
                    json.dumps(suggestions, ensure_ascii=True),
                    _utcnow(),
                ),
            )
            self._conn.commit()
