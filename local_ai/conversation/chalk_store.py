"""OPS-7 chalk drawings — persistence for Jynx's [[chalk]] carriage.

Own SQLite database (``data/chalk/chalk.db``), following the
per-domain convention (conversations, personality, provenance).
Strictly per-user rows: every read and write is scoped by user_id,
and a drawing id resolves only for its owner — a foreign or
nonexistent id yields nothing, indistinguishably (PR #409
owner-isolation discipline).

A drawing is the parsed product of one [[chalk]] tail instruction
set: an ordered list of marks (stencil-kit stamps and freehand
strokes) in its own coordinate space, keyed to the conversation
that produced it and to that conversation's selected subject where
one exists (the LiveContext entity the turn was focused on). The
store is written only by the conversation service's chalk seam,
only for Jynx (maverick) turns, and only while the
``ZENAF_CHALK_CARRIAGE`` rollout flag is on; the read side is the
Scroll's drawing feed (GET /conversation/drawings).

Erasure note, stated plainly: this store is a new record home and
is NOT yet enumerated by the Scope S erasure operation (neither is
the conversations store itself). Drawings are Jynx's made marks,
not visitor records; the gap is recorded in the OPS-7 build report
rather than silently claimed covered.

Threading: one connection guarded by a lock, as with the
conversation store.
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
DATA_DIR = REPO_ROOT / "data" / "chalk"
DEFAULT_DB_PATH = DATA_DIR / "chalk.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chalk_drawings (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  subject_type TEXT,
  subject_id TEXT,
  user_message_id TEXT,
  reply_message_id TEXT,
  title TEXT,
  space_w INTEGER NOT NULL,
  space_h INTEGER NOT NULL,
  marks_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chalk_drawings_user_order
  ON chalk_drawings (user_id, created_at, id);
"""

#: The read feed's bound: the Scroll shows drawings as sections in
#: the order made; 500 is far beyond any real session count and
#: keeps a runaway store from expanding a response without limit.
LIST_LIMIT = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChalkStore:
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

    # -- writes -----------------------------------------------------

    def record_drawing(
        self,
        *,
        user_id: str,
        conversation_id: str,
        title: str | None,
        space: dict[str, Any],
        marks: list[dict[str, Any]],
        subject_type: str | None = None,
        subject_id: str | None = None,
        user_message_id: str | None = None,
        reply_message_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist one validated drawing for its owner; return it."""
        drawing_id = str(uuid.uuid4())
        created_at = _now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chalk_drawings (
                  id, user_id, conversation_id, subject_type, subject_id,
                  user_message_id, reply_message_id, title,
                  space_w, space_h, marks_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    drawing_id,
                    user_id,
                    conversation_id,
                    subject_type,
                    subject_id,
                    user_message_id,
                    reply_message_id,
                    title,
                    int(space["w"]),
                    int(space["h"]),
                    json.dumps(marks),
                    created_at,
                ),
            )
            self._conn.commit()
        return self.get_drawing(user_id, drawing_id)

    # -- reads (owner-scoped, always) --------------------------------

    def get_drawing(self, user_id: str, drawing_id: str) -> dict[str, Any] | None:
        """One drawing by id, for its owner only. A foreign or
        nonexistent id returns None — the two are indistinguishable."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM chalk_drawings WHERE id = ? AND user_id = ?",
                (drawing_id, user_id),
            ).fetchone()
        return self._row_to_drawing(row) if row is not None else None

    def list_drawings(self, user_id: str, limit: int = LIST_LIMIT) -> list[dict[str, Any]]:
        """The owner's drawings in the order they were made."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM chalk_drawings
                WHERE user_id = ?
                ORDER BY created_at, rowid
                LIMIT ?
                """,
                (user_id, int(limit)),
            ).fetchall()
        return [self._row_to_drawing(r) for r in rows]

    # -- shape --------------------------------------------------------

    @staticmethod
    def _row_to_drawing(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "space": {"w": row["space_w"], "h": row["space_h"]},
            "marks": json.loads(row["marks_json"]),
            "conversation_id": row["conversation_id"],
            "subject_type": row["subject_type"],
            "subject_id": row["subject_id"],
            "user_message_id": row["user_message_id"],
            "reply_message_id": row["reply_message_id"],
            "created_at": row["created_at"],
        }
