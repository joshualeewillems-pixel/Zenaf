"""Durable store for per-seat "You" profiles — one row per (user, archetype).

SQLite, following the PersonalityStore conventions (one shared DB file,
rows owner-scoped by user_id, thread-locked connection).

What belongs here (and ONLY here):
  - personal_name — the private name the user co-gave their inner echo of
    this seat in the keystone-4 recognition conversation. It exists nowhere
    else in the system. (Distinct from the seat rename in naming.py: that
    renames the *character*; this names the *user's own part*.)
  - avatar_ref — a reference (asset id / URL) for the echo's avatar.
  - current_snapshot_id — a POINTER into the PersonalityStore's snapshot
    table: which archived era this seat's echo currently anchors to. The
    snapshot payload itself stays in the PersonalityStore.

What NEVER belongs here: depth scores, training signals, persona payloads,
snapshot payloads, conversation state (thread_state). Those have ground-truth
stores; duplicating them here would create a parallel model that drifts.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "you_profiles"
DEFAULT_DB_PATH = DATA_DIR / "you_profiles.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS you_profiles (
    user_id TEXT NOT NULL,
    archetype_id TEXT NOT NULL,
    personal_name TEXT,
    avatar_ref TEXT,
    current_snapshot_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, archetype_id)
);
"""

#: Fields the upsert may touch. Everything else about a seat's echo is
#: derived from its ground-truth store at read time.
_WRITABLE_FIELDS = ("personal_name", "avatar_ref", "current_snapshot_id")

#: Max length for the echo's personal name (mirrors naming.MAX_DISPLAY_NAME_LEN).
MAX_PERSONAL_NAME_LEN = 60
#: Max length for an avatar reference (asset id or URL).
MAX_AVATAR_REF_LEN = 2000


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Unset:
    """Sentinel for "field not provided" (distinct from an explicit None)."""


UNSET = _Unset()


class YouProfileStore:
    """Owner-scoped durable store for per-seat echo identity records."""

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

    def get(self, user_id: str, archetype_id: str) -> dict[str, Any] | None:
        """The echo identity record for (user, seat), or None if never set."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM you_profiles WHERE user_id = ? AND archetype_id = ?",
                (user_id, archetype_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """All echo identity records for a user, ordered by archetype id."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM you_profiles WHERE user_id = ? ORDER BY archetype_id",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert(
        self,
        user_id: str,
        archetype_id: str,
        *,
        personal_name: Any = UNSET,
        avatar_ref: Any = UNSET,
        current_snapshot_id: Any = UNSET,
    ) -> dict[str, Any]:
        """Create or partially update the echo record. Idempotent.

        Only fields explicitly passed are touched; passing None clears a
        field. Returns the full record after the write.
        """
        provided: dict[str, Any] = {}
        for name, value in (
            ("personal_name", personal_name),
            ("avatar_ref", avatar_ref),
            ("current_snapshot_id", current_snapshot_id),
        ):
            if value is not UNSET:
                provided[name] = value
        _validate(provided)

        now = _iso_now()
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM you_profiles WHERE user_id = ? AND archetype_id = ?",
                (user_id, archetype_id),
            ).fetchone()
            if existing is None:
                row = {
                    "user_id": user_id,
                    "archetype_id": archetype_id,
                    "personal_name": None,
                    "avatar_ref": None,
                    "current_snapshot_id": None,
                    "created_at": now,
                    "updated_at": now,
                }
                row.update(provided)
                self._conn.execute(
                    "INSERT INTO you_profiles"
                    " (user_id, archetype_id, personal_name, avatar_ref,"
                    "  current_snapshot_id, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["user_id"],
                        row["archetype_id"],
                        row["personal_name"],
                        row["avatar_ref"],
                        row["current_snapshot_id"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
            else:
                row = dict(existing)
                row.update(provided)
                row["updated_at"] = now
                assignments = ", ".join(f"{k} = ?" for k in provided)
                if assignments:
                    self._conn.execute(
                        f"UPDATE you_profiles SET {assignments}, updated_at = ?"
                        " WHERE user_id = ? AND archetype_id = ?",
                        (*provided.values(), now, user_id, archetype_id),
                    )
            self._conn.commit()
        return row

    def delete(self, user_id: str, archetype_id: str) -> bool:
        """Remove the echo record entirely. Returns True if one existed."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM you_profiles WHERE user_id = ? AND archetype_id = ?",
                (user_id, archetype_id),
            )
            self._conn.commit()
            return cur.rowcount > 0


def _validate(provided: dict[str, Any]) -> None:
    name = provided.get("personal_name")
    if name is not None:
        if not isinstance(name, str):
            raise ValueError("personal_name must be a string")
        if len(name.strip()) > MAX_PERSONAL_NAME_LEN:
            raise ValueError(
                f"personal_name must be {MAX_PERSONAL_NAME_LEN} characters or fewer"
            )
    avatar_ref = provided.get("avatar_ref")
    if avatar_ref is not None:
        if not isinstance(avatar_ref, str):
            raise ValueError("avatar_ref must be a string")
        if len(avatar_ref) > MAX_AVATAR_REF_LEN:
            raise ValueError(
                f"avatar_ref must be {MAX_AVATAR_REF_LEN} characters or fewer"
            )
    snapshot_id = provided.get("current_snapshot_id")
    if snapshot_id is not None and not isinstance(snapshot_id, str):
        raise ValueError("current_snapshot_id must be a string")
