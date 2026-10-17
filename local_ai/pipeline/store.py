"""Pipeline-local storage: journal entries, taste observations/profiles, and
narrative-marker precision stats.

The artifact registry itself lives in `local_ai.provenance`; this store
holds pipeline working state. Journal entries are ALSO registered as
`journal_entry` artifacts in the provenance registry (private by default)
so the story→entry link is walkable in the lineage view — `artifact_id`
here points at that record.
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
DATA_DIR = REPO_ROOT / "data" / "pipeline"
DEFAULT_DB_PATH = DATA_DIR / "pipeline.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_entries (
    entry_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    artifact_id TEXT,
    suggested_at TEXT,
    suggested_marker TEXT,
    suggested_modality TEXT,
    suggestion_copy TEXT,
    dismissed INTEGER NOT NULL DEFAULT 0,
    storified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_journal_user ON journal_entries(user_id, created_at);
CREATE TABLE IF NOT EXISTS taste_observations (
    obs_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_taste_user ON taste_observations(user_id, created_at);
CREATE TABLE IF NOT EXISTS taste_profiles (
    user_id TEXT PRIMARY KEY,
    shaped INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    style_anchors TEXT NOT NULL DEFAULT '[]',
    tools TEXT NOT NULL DEFAULT '[]',
    modalities TEXT NOT NULL DEFAULT '[]',
    observation_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS marker_stats (
    marker TEXT PRIMARY KEY,
    suggestions INTEGER NOT NULL DEFAULT 0,
    accepts INTEGER NOT NULL DEFAULT 0
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class PipelineStore:
    """SQLite-backed pipeline state."""

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

    # -- journal entries ----------------------------------------------------

    def create_entry(
        self, user_id: str, text: str, source_hash: str, artifact_id: str | None = None
    ) -> dict[str, Any]:
        entry_id = _new_id()
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO journal_entries
                   (entry_id, user_id, text, created_at, source_hash, artifact_id)
                   VALUES (?,?,?,?,?,?)""",
                (entry_id, user_id, text, now, source_hash, artifact_id),
            )
            self._conn.commit()
        return self.get_entry(entry_id)

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM journal_entries WHERE entry_id = ?", (entry_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_entries(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM journal_entries WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_entry(self, entry_id: str, **fields: Any) -> dict[str, Any] | None:
        allowed = {
            "artifact_id", "suggested_at", "suggested_marker", "suggested_modality",
            "suggestion_copy", "dismissed", "storified",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if "dismissed" in updates:
            updates["dismissed"] = int(bool(updates["dismissed"]))
        if "storified" in updates:
            updates["storified"] = int(bool(updates["storified"]))
        if not updates:
            return self.get_entry(entry_id)
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with self._lock:
            self._conn.execute(
                f"UPDATE journal_entries SET {set_clause} WHERE entry_id = ?",
                (*updates.values(), entry_id),
            )
            self._conn.commit()
        return self.get_entry(entry_id)

    # -- taste ----------------------------------------------------------------

    def add_taste_observation(
        self, user_id: str, question: str, answer: str
    ) -> dict[str, Any]:
        obs_id = _new_id()
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                """INSERT INTO taste_observations (obs_id, user_id, question, answer, created_at)
                   VALUES (?,?,?,?,?)""",
                (obs_id, user_id, question, answer, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM taste_observations WHERE obs_id = ?", (obs_id,)
            ).fetchone()
        return dict(row) if row else {}

    def count_observations(self, user_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM taste_observations WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return int(row["n"])

    def list_observations(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM taste_observations WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_taste_profile(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM taste_profiles WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return {
                "user_id": user_id,
                "shaped": False,
                "summary": "",
                "style_anchors": [],
                "tools": [],
                "modalities": [],
                "observation_count": 0,
                "updated_at": None,
            }
        d = dict(row)
        d["shaped"] = bool(d["shaped"])
        for key in ("style_anchors", "tools", "modalities"):
            try:
                d[key] = json.loads(d[key] or "[]")
            except (json.JSONDecodeError, TypeError):
                d[key] = []
        return d

    def save_taste_profile(
        self,
        user_id: str,
        *,
        summary: str = "",
        style_anchors: list[str] | None = None,
        tools: list[str] | None = None,
        modalities: list[str] | None = None,
        observation_count: int = 0,
    ) -> dict[str, Any]:
        now = _now_iso()
        shaped = int(bool(summary or style_anchors or tools or modalities))
        with self._lock:
            self._conn.execute(
                """INSERT INTO taste_profiles
                   (user_id, shaped, summary, style_anchors, tools, modalities,
                    observation_count, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     shaped=excluded.shaped, summary=excluded.summary,
                     style_anchors=excluded.style_anchors, tools=excluded.tools,
                     modalities=excluded.modalities,
                     observation_count=excluded.observation_count,
                     updated_at=excluded.updated_at""",
                (
                    user_id, shaped, summary,
                    json.dumps(style_anchors or []),
                    json.dumps(tools or []),
                    json.dumps(modalities or []),
                    observation_count, now,
                ),
            )
            self._conn.commit()
        return self.get_taste_profile(user_id)

    # -- marker stats -----------------------------------------------------------

    def record_suggestion(self, marker: str, accepted: bool) -> dict[str, int]:
        """Per-marker precision tracking: suggestions shown vs. accepted.

        Call with accepted=False on dismiss, accepted=True when a suggested
        entry gets storified. Cheap tuning signal — no model involved.
        """
        with self._lock:
            self._conn.execute(
                """INSERT INTO marker_stats (marker, suggestions, accepts)
                   VALUES (?, 1, ?)
                   ON CONFLICT(marker) DO UPDATE SET
                     suggestions = suggestions + 1,
                     accepts = accepts + excluded.accepts""",
                (marker, 1 if accepted else 0),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT suggestions, accepts FROM marker_stats WHERE marker = ?",
                (marker,),
            ).fetchone()
        return {"suggestions": row["suggestions"], "accepts": row["accepts"]}

    def marker_precision(self, marker: str) -> float | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT suggestions, accepts FROM marker_stats WHERE marker = ?",
                (marker,),
            ).fetchone()
        if row is None or row["suggestions"] < 5:
            return None  # not enough data to judge
        return row["accepts"] / row["suggestions"]
