"""Follow-through persistence: nudges, commitments, growth states, engine events.

Own SQLite database (``data/followthrough/followthrough.db``), following the
provenance-store pattern. Growth states live here rather than in the VE tables
on purpose: the legacy VE surface is large and slated for trimming, and growth
is follow-through's progression language — keeping it here keeps VE untouched.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "followthrough"
DEFAULT_DB_PATH = DATA_DIR / "followthrough.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS followthrough_nudges (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  why_text TEXT NOT NULL DEFAULT '',
  entity_title TEXT NOT NULL DEFAULT '',
  suggested_seat TEXT,
  created_at TEXT NOT NULL,
  acked_at TEXT,
  snoozed_until TEXT,
  resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ft_nudges_user_key
  ON followthrough_nudges (user_id, kind, entity_type, entity_id);

CREATE TABLE IF NOT EXISTS commitments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  text TEXT NOT NULL,
  source_quote TEXT,
  linked_task_id TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ft_commitments_user
  ON commitments (user_id, status);

CREATE TABLE IF NOT EXISTS entity_growth (
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  state TEXT NOT NULL,
  transitioned_at TEXT NOT NULL,
  PRIMARY KEY (entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS engine_events (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  event TEXT NOT NULL,
  nudge_id TEXT,
  detail TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ft_events_user
  ON engine_events (user_id, created_at);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


class FollowthroughStore:
    """SQLite-backed store for the follow-through engine."""

    def __init__(self, db_path: Path | str | None = None) -> None:
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

    # -- nudges ---------------------------------------------------------------
    def create_nudge(
        self,
        user_id: str,
        kind: str,
        entity_type: str,
        entity_id: str,
        severity: str,
        why_text: str,
        entity_title: str = "",
        suggested_seat: str | None = None,
    ) -> dict[str, Any]:
        nid = _new_id()
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO followthrough_nudges
                   (id, user_id, kind, entity_type, entity_id, severity, why_text,
                    entity_title, suggested_seat, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (nid, user_id, kind, entity_type, entity_id, severity, why_text,
                 entity_title, suggested_seat, now),
            )
            self._conn.commit()
        return self.get_nudge(nid, user_id) or {}

    def get_nudge(self, nudge_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM followthrough_nudges WHERE id = ? AND user_id = ?",
                (nudge_id, user_id),
            )
            row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def active_nudge(
        self, user_id: str, kind: str, entity_type: str, entity_id: str
    ) -> dict[str, Any] | None:
        """An existing nudge for this (kind, entity) that is still live:
        not acked, not resolved, and not currently snoozed."""
        now = _now_iso()
        with self._lock:
            cur = self._conn.execute(
                """SELECT * FROM followthrough_nudges
                   WHERE user_id = ? AND kind = ? AND entity_type = ? AND entity_id = ?
                     AND acked_at IS NULL AND resolved_at IS NULL
                     AND (snoozed_until IS NULL OR snoozed_until <= ?)
                   ORDER BY created_at DESC LIMIT 1""",
                (user_id, kind, entity_type, entity_id, now),
            )
            row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def recently_acked(
        self, user_id: str, kind: str, entity_type: str, entity_id: str, within_days: int
    ) -> bool:
        """True if the same (kind, entity) was acked within the cooldown window."""
        with self._lock:
            cur = self._conn.execute(
                """SELECT 1 FROM followthrough_nudges
                   WHERE user_id = ? AND kind = ? AND entity_type = ? AND entity_id = ?
                     AND acked_at IS NOT NULL
                     AND acked_at >= datetime('now', ?)
                   LIMIT 1""",
                (user_id, kind, entity_type, entity_id, f"-{int(within_days)} days"),
            )
            return cur.fetchone() is not None

    def snoozed(
        self, user_id: str, kind: str, entity_type: str, entity_id: str
    ) -> bool:
        """True if the same (kind, entity) has a live snooze."""
        now = _now_iso()
        with self._lock:
            cur = self._conn.execute(
                """SELECT 1 FROM followthrough_nudges
                   WHERE user_id = ? AND kind = ? AND entity_type = ? AND entity_id = ?
                     AND acked_at IS NULL AND resolved_at IS NULL
                     AND snoozed_until IS NOT NULL AND snoozed_until > ?
                   LIMIT 1""",
                (user_id, kind, entity_type, entity_id, now),
            )
            return cur.fetchone() is not None

    def list_feed_nudges(self, user_id: str) -> list[dict[str, Any]]:
        """Nudges for the feed: live (not acked/resolved, snooze expired or absent)."""
        now = _now_iso()
        with self._lock:
            cur = self._conn.execute(
                """SELECT * FROM followthrough_nudges
                   WHERE user_id = ? AND acked_at IS NULL AND resolved_at IS NULL
                     AND (snoozed_until IS NULL OR snoozed_until <= ?)
                   ORDER BY created_at ASC""",
                (user_id, now),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]

    def list_active_keys(self, user_id: str) -> set[tuple[str, str, str]]:
        """(kind, entity_type, entity_id) of all live nudges — for auto-resolution."""
        now = _now_iso()
        with self._lock:
            cur = self._conn.execute(
                """SELECT kind, entity_type, entity_id FROM followthrough_nudges
                   WHERE user_id = ? AND acked_at IS NULL AND resolved_at IS NULL
                     AND (snoozed_until IS NULL OR snoozed_until <= ?)""",
                (user_id, now),
            )
            return {(r[0], r[1], r[2]) for r in cur.fetchall()}

    def ack_nudge(self, nudge_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                """UPDATE followthrough_nudges SET acked_at = ?
                   WHERE id = ? AND user_id = ? AND acked_at IS NULL""",
                (_now_iso(), nudge_id, user_id),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
        nudge = self.get_nudge(nudge_id, user_id) or {}
        self.log_event(user_id, "nudge_acked", nudge_id=nudge_id,
                       detail=nudge.get("kind", ""))
        return nudge

    def snooze_nudge(
        self, nudge_id: str, user_id: str, until_iso: str
    ) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                """UPDATE followthrough_nudges SET snoozed_until = ?
                   WHERE id = ? AND user_id = ? AND acked_at IS NULL
                   AND resolved_at IS NULL""",
                (until_iso, nudge_id, user_id),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
        nudge = self.get_nudge(nudge_id, user_id) or {}
        self.log_event(user_id, "nudge_snoozed", nudge_id=nudge_id,
                       detail=f"until={until_iso}")
        return nudge

    def resolve_nudge(self, nudge_id: str, user_id: str) -> None:
        """Auto-resolve: the condition behind the nudge no longer holds."""
        with self._lock:
            self._conn.execute(
                """UPDATE followthrough_nudges SET resolved_at = ?
                   WHERE id = ? AND user_id = ? AND resolved_at IS NULL""",
                (_now_iso(), nudge_id, user_id),
            )
            self._conn.commit()

    # -- commitments ----------------------------------------------------------
    def create_commitment(
        self, user_id: str, text: str, source_quote: str | None = None
    ) -> dict[str, Any]:
        cid = _new_id()
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO commitments
                   (id, user_id, text, source_quote, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'open', ?, ?)""",
                (cid, user_id, text, source_quote, now, now),
            )
            self._conn.commit()
        return self.get_commitment(cid, user_id) or {}

    def get_commitment(
        self, commitment_id: str, user_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM commitments WHERE id = ? AND user_id = ?",
                (commitment_id, user_id),
            )
            row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def list_commitments(
        self, user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if status:
                cur = self._conn.execute(
                    "SELECT * FROM commitments WHERE user_id = ? AND status = ? "
                    "ORDER BY created_at DESC",
                    (user_id, status),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM commitments WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                )
            return [_row_to_dict(r) for r in cur.fetchall()]

    def link_commitment(
        self, commitment_id: str, user_id: str, task_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                """UPDATE commitments SET linked_task_id = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (task_id, _now_iso(), commitment_id, user_id),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_commitment(commitment_id, user_id)

    def set_commitment_status(
        self, commitment_id: str, user_id: str, status: str
    ) -> dict[str, Any] | None:
        if status not in ("open", "done", "dismissed"):
            raise ValueError(f"unknown commitment status {status!r}")
        with self._lock:
            cur = self._conn.execute(
                """UPDATE commitments SET status = ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (status, _now_iso(), commitment_id, user_id),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_commitment(commitment_id, user_id)

    # -- growth states --------------------------------------------------------
    def get_growth(
        self, entity_type: str, entity_id: str, user_id: str
    ) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                """SELECT * FROM entity_growth
                   WHERE entity_type = ? AND entity_id = ? AND user_id = ?""",
                (entity_type, entity_id, user_id),
            )
            row = cur.fetchone()
        return _row_to_dict(row) if row else None

    def set_growth(
        self, entity_type: str, entity_id: str, user_id: str, state: str
    ) -> dict[str, Any]:
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO entity_growth
                   (entity_type, entity_id, user_id, state, transitioned_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (entity_type, entity_id)
                   DO UPDATE SET state = excluded.state,
                                 transitioned_at = excluded.transitioned_at""",
                (entity_type, entity_id, user_id, state, now),
            )
            self._conn.commit()
        return self.get_growth(entity_type, entity_id, user_id) or {}

    def clear_growth(self, entity_type: str, entity_id: str, user_id: str) -> None:
        with self._lock:
            self._conn.execute(
                """DELETE FROM entity_growth
                   WHERE entity_type = ? AND entity_id = ? AND user_id = ?""",
                (entity_type, entity_id, user_id),
            )
            self._conn.commit()

    def growth_user_ids(self, user_id: str) -> dict[tuple[str, str], dict[str, Any]]:
        """All growth states for a user, keyed by (entity_type, entity_id)."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM entity_growth WHERE user_id = ?", (user_id,)
            )
            return {(r["entity_type"], r["entity_id"]): _row_to_dict(r)
                    for r in cur.fetchall()}

    # -- engine events (future training signal for the engine) -----------------
    def log_event(
        self,
        user_id: str,
        event: str,
        nudge_id: str | None = None,
        detail: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO engine_events
                   (id, user_id, event, nudge_id, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (_new_id(), user_id, event, nudge_id, detail, _now_iso()),
            )
            self._conn.commit()

    def list_events(
        self, user_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                """SELECT * FROM engine_events WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
