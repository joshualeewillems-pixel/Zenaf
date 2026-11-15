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

-- Steward D2 erasure (packet §§8.4/9.2): the mirror barrier. The
-- mirror tombstone carries the same content-free fields as the
-- narrative tombstone; the manifest is the same transaction-local
-- attestation (rows written inside add()'s transaction, deleted
-- before its commit — never persisted, never borrowable). While
-- the mirror stands, an observation insert lands only when the
-- event it derives from was attested in this transaction with a
-- provenance time strictly after the boundary.
CREATE TABLE IF NOT EXISTS steward_erasure_tombstones (
  user_id TEXT PRIMARY KEY,
  erased_at TEXT NOT NULL,
  operation_id TEXT NOT NULL DEFAULT '',
  counts_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steward_erasure_manifest (
  run_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  erased_at_seen TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_time TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_erasure_manifest_lookup
  ON steward_erasure_manifest (user_id, erased_at_seen, source_kind, source_id);
CREATE TRIGGER IF NOT EXISTS trg_erasure_observation_insert
BEFORE INSERT ON observations
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = NEW.user_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM steward_erasure_manifest m
    JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
    WHERE m.user_id = NEW.user_id
      AND m.erased_at_seen = tb.erased_at
      AND m.source_kind = 'event'
      AND m.source_id = NEW.event_ref
      AND m.source_time > tb.erased_at
  );
END;
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ErasureBarrierRefusal(ValueError):
    """A derivation write refused under the erasure barrier.

    Mirror of the narrative store's refusal (packet §9.2): raised
    by ObservationStore.add when the mirror tombstone stands and
    the write carries no eligibility manifest attesting its event.
    The trigger backstop raises sqlite3.IntegrityError instead.
    """


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

    # -- erasure barrier (Steward D2, packet §9.2) --------------------------

    def _erasure_tombstone_locked(self, user_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT user_id, erased_at, operation_id, counts_json, "
            "created_at FROM steward_erasure_tombstones WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def get_erasure_tombstone(self, user_id: str) -> dict | None:
        """The mirror erasure tombstone for the user, or None."""
        with self._lock:
            return self._erasure_tombstone_locked(user_id)

    def write_erasure_tombstone(
        self, user_id: str, erased_at: str, operation_id: str = ""
    ) -> dict:
        """Write the mirror tombstone if none stands (first writer
        wins — the boundary is the operation record's T)."""
        with self._lock:
            existing = self._erasure_tombstone_locked(user_id)
            if existing is None:
                self._conn.execute(
                    "INSERT INTO steward_erasure_tombstones (user_id, "
                    "erased_at, operation_id, counts_json, created_at) "
                    "VALUES (?, ?, ?, '{}', ?)",
                    (user_id, erased_at, operation_id, _utcnow()),
                )
                self._conn.commit()
                existing = self._erasure_tombstone_locked(user_id)
        return existing

    def rewrite_erasure_tombstone(
        self, user_id: str, erased_at: str, operation_id: str = ""
    ) -> dict:
        """Reconcile the mirror tombstone to the operation record's
        T (only under a signature-verified record's authority)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO steward_erasure_tombstones (user_id, "
                "erased_at, operation_id, counts_json, created_at) "
                "VALUES (?, ?, ?, '{}', ?) ON CONFLICT(user_id) DO "
                "UPDATE SET erased_at = excluded.erased_at, "
                "operation_id = excluded.operation_id",
                (user_id, erased_at, operation_id, _utcnow()),
            )
            self._conn.commit()
            row = self._erasure_tombstone_locked(user_id)
        return row

    def set_erasure_tombstone_counts(
        self, user_id: str, counts: dict[str, int]
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE steward_erasure_tombstones SET counts_json = ? "
                "WHERE user_id = ?",
                (json.dumps(counts, ensure_ascii=False), user_id),
            )
            self._conn.commit()

    def vacuum(self) -> None:
        """VACUUM the database (packet §8.2 step 5, file hygiene)."""
        with self._lock:
            self._conn.commit()
            self._conn.execute("VACUUM")

    def delete_for_user(self, user_id: str) -> int:
        """Hard-delete every observation row for the user (packet
        §6.2.2). The wired flow writes the mirror tombstone before
        calling this; the tombstone itself is residue and stays."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM observations WHERE user_id = ?",
                (user_id,),
            )
            self._conn.commit()
        return cursor.rowcount

    def delete_observation(self, user_id: str, observation_id: str) -> bool:
        """Delete one observation (the §9.5 audit's mop-up)."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM observations WHERE id = ? AND user_id = ?",
                (observation_id, user_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def count_for_user(self, user_id: str) -> int:
        """The user's surviving observation count (recount)."""
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM observations WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]

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
        admitted_sources: Any = None,
    ) -> Observation:
        """Persist one derived observation at status ``pending``.

        ``admitted_sources`` is the Steward D2 eligibility manifest
        (packet §9.2): (source_kind, source_id, source_time) triples
        from the caller's eligibility evaluation. Consulted only
        when the mirror erasure tombstone stands for the user; then
        the event this observation derives from must be attested
        with a provenance time after the boundary, or the write is
        refused (the trigger is the backstop).
        """
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
            try:
                tombstone = self._erasure_tombstone_locked(user_id)
                run_id: str | None = None
                if tombstone is not None:
                    if admitted_sources is None:
                        raise ErasureBarrierRefusal(
                            "steward erasure barrier: observation "
                            f"write for user {user_id!r} refused — "
                            "the mirror erasure tombstone stands "
                            f"(erased_at {tombstone['erased_at']}) and "
                            "the write carries no eligibility manifest"
                        )
                    admitted = [tuple(e) for e in admitted_sources]
                    if ("event", event_ref) not in {
                        (str(k), str(r)) for k, r, _ in admitted
                    }:
                        raise ErasureBarrierRefusal(
                            "steward erasure barrier: observation "
                            f"write for user {user_id!r} refused — "
                            f"event {event_ref!r} is not attested by "
                            "this run's eligibility evaluation"
                        )
                    run_id = f"mrun-{uuid.uuid4().hex[:24]}"
                    for kind, ref_id, source_time in admitted:
                        self._conn.execute(
                            "INSERT INTO steward_erasure_manifest "
                            "(run_id, user_id, erased_at_seen, "
                            "source_kind, source_id, source_time) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                run_id, user_id, tombstone["erased_at"],
                                str(kind), str(ref_id), str(source_time),
                            ),
                        )
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
                if run_id is not None:
                    self._conn.execute(
                        "DELETE FROM steward_erasure_manifest "
                        "WHERE run_id = ?",
                        (run_id,),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
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
