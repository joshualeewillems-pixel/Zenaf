"""Palace overhead layout records — persistence for the dome's
task-level plan (the hybrid packing port, 2026-11-27).

Own SQLite database (``data/palace_layout/palace_layout.db``),
following the per-domain convention (conversations, chalk,
personality, provenance) and the chalk store's shape in
particular: one connection guarded by a lock, strictly per-user
rows — every read and write is scoped by user_id, and a project
key resolves only for its owner; a foreign or nonexistent key
yields nothing, indistinguishably (PR #409 owner-isolation
discipline).

One record per (user, project): the overhead plan's layout for
that project, in the port proposal's shape — ``{version, scale,
positions: {taskId: [x, y]}, weights: {taskId: weight},
lastTransition: {reflow, steppedDown, movedRooms}, unplaced:
[{id, radius, cause}]}``. The record is derived geometry, not a
visitor record: it is written by the Palace surface only when a
layout is computed or changes, read when a project opens, and a
lost record costs one visible re-layout, never corruption. The
layout rule itself lives client-side (palaceOverheadLogic.ts);
this store validates the record's shape fail-closed and keeps
it — it never computes a layout.

The loose-tasks grouping rides under the reserved key
``loose-tasks``: it names no Vision Execution record, and the
key is still owner-scoped like any other.

Erasure note, stated plainly (the chalk store's precedent): this
store is a new record home and is NOT yet enumerated by the
Scope S erasure operation. A layout record holds no visitor
words — task ids, weights and coordinates only — and the gap is
recorded here rather than silently claimed covered.

Threading: one connection guarded by a lock, as with the chalk
and conversation stores.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "palace_layout"
DEFAULT_DB_PATH = DATA_DIR / "palace_layout.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS palace_layouts (
  user_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  record_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, project_id)
);
"""

#: Bounds that keep a runaway or hostile payload out of the store:
#: a real project's plan is a few KB; 500 rooms is far beyond any
#: real project, and 256 KB is far beyond 500 rooms' geometry.
MAX_ROOMS = 500
MAX_RECORD_BYTES = 256 * 1024

_UNPLACED_CAUSES = {"PROVEN_INFEASIBLE", "SEARCH_EXHAUSTION"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_layout_record(record: Any) -> dict[str, Any]:
    """The record's shape, fail-closed. Returns the record
    normalized to exactly the stored fields; raises ValueError on
    anything malformed — a bad record is refused whole, never
    partially persisted."""
    if not isinstance(record, dict):
        raise ValueError("layout record must be an object")
    version = record.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("layout record version must be a positive integer")
    scale = record.get("scale")
    if not _is_finite_number(scale) or scale <= 0:
        raise ValueError("layout record scale must be a positive number")
    positions = record.get("positions")
    if not isinstance(positions, dict) or len(positions) > MAX_ROOMS:
        raise ValueError("layout record positions must be an object of at most 500 entries")
    clean_positions: dict[str, list[float]] = {}
    for task_id, xy in positions.items():
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("layout record position keys must be task ids")
        if (
            not isinstance(xy, (list, tuple))
            or len(xy) != 2
            or not all(_is_finite_number(v) for v in xy)
        ):
            raise ValueError("layout record positions must be [x, y] number pairs")
        clean_positions[task_id] = [float(xy[0]), float(xy[1])]
    weights = record.get("weights")
    if not isinstance(weights, dict) or len(weights) > MAX_ROOMS:
        raise ValueError("layout record weights must be an object of at most 500 entries")
    clean_weights: dict[str, float] = {}
    for task_id, w in weights.items():
        if not isinstance(task_id, str) or not task_id or not _is_finite_number(w) or w <= 0:
            raise ValueError("layout record weights must be positive numbers keyed by task id")
        clean_weights[task_id] = float(w)
    transition = record.get("lastTransition")
    if not isinstance(transition, dict):
        raise ValueError("layout record lastTransition must be an object")
    reflow = transition.get("reflow")
    stepped = transition.get("steppedDown")
    moved = transition.get("movedRooms")
    if not isinstance(reflow, bool):
        raise ValueError("layout record lastTransition.reflow must be a boolean")
    if not isinstance(stepped, int) or isinstance(stepped, bool) or stepped < 0:
        raise ValueError("layout record lastTransition.steppedDown must be a non-negative integer")
    if not isinstance(moved, int) or isinstance(moved, bool) or moved < 0:
        raise ValueError("layout record lastTransition.movedRooms must be a non-negative integer")
    unplaced = record.get("unplaced")
    if not isinstance(unplaced, list) or len(unplaced) > MAX_ROOMS:
        raise ValueError("layout record unplaced must be a list of at most 500 entries")
    clean_unplaced: list[dict[str, Any]] = []
    for entry in unplaced:
        if not isinstance(entry, dict):
            raise ValueError("layout record unplaced entries must be objects")
        uid = entry.get("id")
        radius = entry.get("radius")
        cause = entry.get("cause")
        if not isinstance(uid, str) or not uid:
            raise ValueError("layout record unplaced entries need a task id")
        if not _is_finite_number(radius) or radius <= 0:
            raise ValueError("layout record unplaced entries need a positive radius")
        if cause not in _UNPLACED_CAUSES:
            raise ValueError("layout record unplaced entries need a known cause")
        clean_unplaced.append({"id": uid, "radius": float(radius), "cause": cause})
    clean = {
        "version": version,
        "scale": float(scale),
        "positions": clean_positions,
        "weights": clean_weights,
        "lastTransition": {"reflow": reflow, "steppedDown": stepped, "movedRooms": moved},
        "unplaced": clean_unplaced,
    }
    if len(json.dumps(clean)) > MAX_RECORD_BYTES:
        raise ValueError("layout record is too large")
    return clean


class PalaceLayoutStore:
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

    def put_layout(
        self,
        *,
        user_id: str,
        project_id: str,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one project's layout record for its owner
        (upsert: the current record replaces the previous one —
        the plan keeps only the standing composition). The record
        is validated fail-closed before it is stored; the stored
        (normalized) record is returned."""
        clean = validate_layout_record(record)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO palace_layouts (user_id, project_id, record_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, project_id)
                DO UPDATE SET record_json = excluded.record_json,
                              updated_at = excluded.updated_at
                """,
                (user_id, project_id, json.dumps(clean), _now_iso()),
            )
            self._conn.commit()
        return clean

    # -- reads (owner-scoped, always) --------------------------------

    def get_layout(self, user_id: str, project_id: str) -> dict[str, Any] | None:
        """One project's layout record, for its owner only. A
        foreign or nonexistent key returns None — the two are
        indistinguishable."""
        with self._lock:
            row = self._conn.execute(
                "SELECT record_json FROM palace_layouts WHERE user_id = ? AND project_id = ?",
                (user_id, project_id),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["record_json"])
