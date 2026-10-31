"""Per-response feedback persistence: one row per explicit widget submit.

Own SQLite database (``data/feedback/feedback.db``), following the
per-domain convention (personality, followthrough, provenance, conversation).
Strict per-user rows: every read and write is scoped by user_id.

V1 boundary: rows are inert data. Nothing here analyzes feedback, discusses
it, or writes training data, preferences, or profile changes — a future
review-queue tie-in reads these rows; this module never acts on them.
An untouched widget creates no row at all (the frontend only POSTs on
explicit submit), so absence of a row means "no feedback", never "neutral".
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
DATA_DIR = REPO_ROOT / "data" / "feedback"
DEFAULT_DB_PATH = DATA_DIR / "feedback.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS response_feedback (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  response_ref TEXT NOT NULL,
  conversation_id TEXT NOT NULL DEFAULT 'local',
  seat TEXT NOT NULL,
  slider INTEGER NOT NULL,
  checks_json TEXT NOT NULL DEFAULT '[]',
  note TEXT NOT NULL DEFAULT '',
  review_status TEXT NOT NULL DEFAULT 'unreviewed',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_user_created
  ON response_feedback (user_id, created_at, id);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeedbackStore:
    """SQLite-backed store for per-response feedback records."""

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

    def add_feedback(
        self,
        user_id: str,
        response_ref: str,
        conversation_id: str,
        seat: str,
        slider: int,
        checks: list[str],
        note: str,
    ) -> dict[str, Any]:
        """Insert exactly one record for one explicit widget submit."""
        row_id = uuid.uuid4().hex[:16]
        now = _utcnow()
        checks_json = json.dumps(list(checks), ensure_ascii=True)
        with self._lock:
            self._conn.execute(
                "INSERT INTO response_feedback (id, user_id, response_ref, "
                "conversation_id, seat, slider, checks_json, note, "
                "review_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row_id,
                    user_id,
                    response_ref,
                    conversation_id or "local",
                    seat,
                    slider,
                    checks_json,
                    note or "",
                    "unreviewed",
                    now,
                ),
            )
            self._conn.commit()
        return {
            "id": row_id,
            "user_id": user_id,
            "response_ref": response_ref,
            "conversation_id": conversation_id or "local",
            "seat": seat,
            "slider": slider,
            "checks": list(checks),
            "note": note or "",
            "review_status": "unreviewed",
            "created_at": now,
        }

    def list_feedback(
        self,
        user_id: str,
        conversation_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Newest-first records for this user (optionally one thread).
        Strictly per-user; a user never sees another user's rows."""
        limit = max(1, min(int(limit or 50), 200))
        with self._lock:
            if conversation_id:
                rows = self._conn.execute(
                    "SELECT id, user_id, response_ref, conversation_id, seat, "
                    "slider, checks_json, note, review_status, created_at "
                    "FROM response_feedback "
                    "WHERE user_id = ? AND conversation_id = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (user_id, conversation_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, user_id, response_ref, conversation_id, seat, "
                    "slider, checks_json, note, review_status, created_at "
                    "FROM response_feedback WHERE user_id = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                checks = json.loads(r["checks_json"] or "[]")
            except Exception:
                checks = []
            out.append(
                {
                    "id": r["id"],
                    "user_id": r["user_id"],
                    "response_ref": r["response_ref"],
                    "conversation_id": r["conversation_id"],
                    "seat": r["seat"],
                    "slider": r["slider"],
                    "checks": checks,
                    "note": r["note"],
                    "review_status": r["review_status"],
                    "created_at": r["created_at"],
                }
            )
        return out
