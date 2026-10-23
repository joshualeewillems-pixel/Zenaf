"""Observations store (Fellowship Runtime P1).

An *observation* is the pipeline's middle made durable (doctrine §2,
steps 2–3): one seat's attributable, inspectable, correctable reading
of shared evidence. It is NOT a claim: it is never filed into the
review queue by this layer, and it never writes a training signal —
it is a character's proposal, waiting for the attention layer (P2) to
surface it and for the user to decide what, if anything, it becomes.

Evidence discipline (doctrine §9 — evidence and interpretation remain
distinguishable):
  - ``evidence`` is the verbatim quote from the record when the event
    carried user words (``evidence_kind == "quote"``), or the entity
    reference ``"<entity_type>:<entity_id>"`` when it did not
    (``evidence_kind == "entity_ref"``). Never a paraphrase.
  - ``interpretation`` is the seat's own reading, in its register.
  - ``derivation`` records how the observation came to be (pre-filter
    match reasons, model operation) so the reading stays inspectable.

Status lifecycle: ``pending`` (derived, not yet surfaced) →
``surfaced`` (shown to the user by the attention layer) →
``discussed`` (taken up in the seat's conversation; terminal), with
``dismissed`` reachable from pending/surfaced (terminal). P1 writes
only ``pending``; the later transitions belong to P2/P4 consumers and
are implemented here so the lifecycle is testable now.

Own SQLite database (``data/fellowship/observations.db``), following
the per-domain convention (conversations, personality, provenance).
Strictly per-user rows: every read and write is scoped by user_id.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "fellowship"
DEFAULT_DB_PATH = DATA_DIR / "observations.db"

STATUSES: tuple[str, ...] = ("pending", "surfaced", "discussed", "dismissed")

#: Allowed status transitions. Terminal states map to the empty set.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"surfaced", "dismissed"}),
    "surfaced": frozenset({"discussed", "dismissed"}),
    "discussed": frozenset(),
    "dismissed": frozenset(),
}

EVIDENCE_KINDS: tuple[str, ...] = ("quote", "entity_ref")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  seat TEXT NOT NULL,
  event_ref TEXT NOT NULL DEFAULT '',
  event_kind TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '',
  evidence_kind TEXT NOT NULL DEFAULT 'entity_ref',
  interpretation TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  derivation_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_user_status
  ON observations (user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_observations_user_seat
  ON observations (user_id, seat, created_at);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Observation:
    """One seat's reading of one event's evidence."""

    id: str
    user_id: str
    seat: str
    event_ref: str
    event_kind: str
    evidence: str
    evidence_kind: str  # "quote" | "entity_ref"
    interpretation: str
    status: str = "pending"
    derivation: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "seat": self.seat,
            "event_ref": self.event_ref,
            "event_kind": self.event_kind,
            "evidence": self.evidence,
            "evidence_kind": self.evidence_kind,
            "interpretation": self.interpretation,
            "status": self.status,
            "derivation": self.derivation or {},
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_observation(row: sqlite3.Row) -> Observation:
    try:
        derivation = json.loads(row["derivation_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        derivation = {}
    return Observation(
        id=row["id"],
        user_id=row["user_id"],
        seat=row["seat"],
        event_ref=row["event_ref"],
        event_kind=row["event_kind"],
        evidence=row["evidence"],
        evidence_kind=row["evidence_kind"],
        interpretation=row["interpretation"],
        status=row["status"],
        derivation=derivation if isinstance(derivation, dict) else {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ObservationStore:
    """SQLite-backed store for derived observations."""

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

    # -- writes ---------------------------------------------------------------

    def add(
        self,
        *,
        user_id: str,
        seat: str,
        event_ref: str,
        event_kind: str,
        evidence: str,
        evidence_kind: str,
        interpretation: str,
        derivation: dict[str, Any] | None = None,
    ) -> Observation:
        """Persist one derived observation at status ``pending``."""
        if evidence_kind not in EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence_kind: {evidence_kind!r}")
        now = _utcnow()
        obs = Observation(
            id=f"obs-{uuid.uuid4().hex[:24]}",
            user_id=user_id,
            seat=seat,
            event_ref=event_ref,
            event_kind=event_kind,
            evidence=evidence,
            evidence_kind=evidence_kind,
            interpretation=interpretation,
            status="pending",
            derivation=derivation or {},
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO observations (id, user_id, seat, event_ref, "
                "event_kind, evidence, evidence_kind, interpretation, "
                "status, derivation_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    obs.id, obs.user_id, obs.seat, obs.event_ref,
                    obs.event_kind, obs.evidence, obs.evidence_kind,
                    obs.interpretation, obs.status,
                    json.dumps(obs.derivation or {}, ensure_ascii=False),
                    obs.created_at, obs.updated_at,
                ),
            )
            self._conn.commit()
        return obs

    def set_status(self, user_id: str, observation_id: str, status: str) -> Observation:
        """Move an observation along its lifecycle.

        Raises ValueError for an unknown status, an unknown id (for
        this user), or a transition the lifecycle forbids — a caller
        skipping states silently would corrupt the attention layer's
        bookkeeping, so this fails loudly instead.
        """
        if status not in STATUSES:
            raise ValueError(f"unknown observation status: {status!r}")
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM observations WHERE id = ? AND user_id = ?",
                (observation_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown observation: {observation_id!r}")
            current = row["status"]
            if status not in _TRANSITIONS.get(current, frozenset()):
                raise ValueError(
                    f"observation status cannot move {current} -> {status}"
                )
            now = _utcnow()
            self._conn.execute(
                "UPDATE observations SET status = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (status, now, observation_id, user_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM observations WHERE id = ? AND user_id = ?",
                (observation_id, user_id),
            ).fetchone()
        return _row_to_observation(row)

    # -- reads ------------------------------------------------------------------

    def get(self, user_id: str, observation_id: str) -> Observation | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM observations WHERE id = ? AND user_id = ?",
                (observation_id, user_id),
            ).fetchone()
        return _row_to_observation(row) if row else None

    def list_for_user(
        self,
        user_id: str,
        *,
        seat: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Observation]:
        """Oldest first (derivation order) within the filters."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if seat is not None:
            clauses.append("seat = ?")
            args.append(seat)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM observations WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id LIMIT ?",
                args,
            ).fetchall()
        return [_row_to_observation(r) for r in rows]
