"""Append-only SQLite store for presence-ingest signals.

Layout (under <repo>/data/presence_ingest/):
  signals.db            — import_sessions, presence_events, training_signals

Design rules (from the training-signal spec):
- Signals are append-only. Review marks a signal approved/rejected; rejected
  rows are kept as an audit trail, never deleted.
- Redaction happens at capture: only redacted text is stored here.
- Every signal carries provenance.

Threading: one connection guarded by a lock is enough for user-triggered use.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import ContributionClaim, ImportSession, PresenceEvent, TrainingSignal

# Anchor the data dir to the repo root so the location is stable regardless
# of the process working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "presence_ingest"
DEFAULT_DB_PATH = DATA_DIR / "signals.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS import_sessions (
    session_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    file_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    counts TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS presence_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source TEXT NOT NULL,
    ts TEXT,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '{}',
    provenance TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (session_id) REFERENCES import_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_events_session ON presence_events(session_id);
CREATE TABLE IF NOT EXISTS training_signals (
    signal_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    layer TEXT NOT NULL,
    zone TEXT NOT NULL,
    actor TEXT NOT NULL,
    summary TEXT NOT NULL,
    context_ref TEXT NOT NULL DEFAULT '{}',
    payload_redacted TEXT NOT NULL DEFAULT '',
    valence TEXT NOT NULL,
    correction_diff TEXT,
    kind TEXT NOT NULL DEFAULT 'distilled',
    provenance TEXT NOT NULL DEFAULT '{}',
    supersedes TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY (session_id) REFERENCES import_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_session ON training_signals(session_id);
CREATE INDEX IF NOT EXISTS idx_signals_status ON training_signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_zone ON training_signals(zone);
CREATE TABLE IF NOT EXISTS contribution_claims (
    claim_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_ids TEXT NOT NULL DEFAULT '[]',
    work_title TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    parts TEXT NOT NULL DEFAULT '',
    extent TEXT NOT NULL DEFAULT '{}',
    collaborators TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    attestations TEXT NOT NULL DEFAULT '[]',
    license_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES import_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_claims_session ON contribution_claims(session_id);
"""


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _session_from_row(row: sqlite3.Row) -> ImportSession:
    return ImportSession(
        session_id=row["session_id"],
        source=row["source"],
        file_name=row["file_name"],
        status=row["status"],
        counts=_json_loads(row["counts"], {}),
        created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
        provenance=_json_loads(row["provenance"], {}),
    )


def _event_from_row(row: sqlite3.Row) -> PresenceEvent:
    return PresenceEvent(
        event_id=row["event_id"],
        source=row["source"],
        ts=_parse_dt(row["ts"]),
        actor=row["actor"],
        kind=row["kind"],
        text=row["text"],
        context=_json_loads(row["context"], {}),
        provenance=_json_loads(row["provenance"], {}),
    )


def _signal_from_row(row: sqlite3.Row) -> TrainingSignal:
    return TrainingSignal(
        signal_id=row["signal_id"],
        ts_ms=row["ts_ms"],
        layer=row["layer"],
        zone=row["zone"],
        actor=row["actor"],
        summary=row["summary"],
        context_ref=_json_loads(row["context_ref"], {}),
        payload_redacted=row["payload_redacted"] or "",
        valence=row["valence"],
        correction_diff=row["correction_diff"],
        kind=row["kind"] if "kind" in row.keys() and row["kind"] else "distilled",
        provenance=_json_loads(row["provenance"], {}),
        supersedes=row["supersedes"],
        status=row["status"],
        session_id=row["session_id"],
    )


def _claim_from_row(row: sqlite3.Row) -> ContributionClaim:
    return ContributionClaim(
        claim_id=row["claim_id"],
        session_id=row["session_id"],
        event_ids=_json_loads(row["event_ids"], []),
        work_title=row["work_title"] or "",
        role=row["role"],
        parts=row["parts"] or "",
        extent=_json_loads(row["extent"], {}),
        collaborators=_json_loads(row["collaborators"], []),
        note=row["note"] or "",
        attestations=_json_loads(row["attestations"], []),
        license_id=row["license_id"] or "",
        created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
    )


class PresenceStore:
    """SQLite-backed, append-only store for ingestion sessions and signals."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # Migration guard: databases created before provenance existed.
            cols = {
                r["name"]
                for r in self._conn.execute("PRAGMA table_info(import_sessions)")
            }
            if "provenance" not in cols:
                self._conn.execute(
                    "ALTER TABLE import_sessions "
                    "ADD COLUMN provenance TEXT NOT NULL DEFAULT '{}'"
                )
            # Migration guard: databases created before typed signal kinds.
            sig_cols = {
                r["name"]
                for r in self._conn.execute("PRAGMA table_info(training_signals)")
            }
            if "kind" not in sig_cols:
                self._conn.execute(
                    "ALTER TABLE training_signals "
                    "ADD COLUMN kind TEXT NOT NULL DEFAULT 'distilled'"
                )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- sessions ------------------------------------------------------

    def create_session(self, session: ImportSession) -> ImportSession:
        with self._lock:
            self._conn.execute(
                "INSERT INTO import_sessions "
                "(session_id, source, file_name, status, counts, created_at, "
                " provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session.session_id,
                    session.source,
                    session.file_name,
                    session.status,
                    json.dumps(session.counts),
                    _iso(session.created_at),
                    json.dumps(session.provenance),
                ),
            )
            self._conn.commit()
        return session

    def get_session(self, session_id: str) -> ImportSession | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM import_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def list_sessions(self) -> list[ImportSession]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM import_sessions ORDER BY created_at DESC"
            ).fetchall()
        return [_session_from_row(r) for r in rows]

    def update_session(
        self,
        session_id: str,
        *,
        status: str | None = None,
        counts: dict | None = None,
    ) -> None:
        with self._lock:
            if status is not None:
                self._conn.execute(
                    "UPDATE import_sessions SET status = ? WHERE session_id = ?",
                    (status, session_id),
                )
            if counts is not None:
                self._conn.execute(
                    "UPDATE import_sessions SET counts = ? WHERE session_id = ?",
                    (json.dumps(counts), session_id),
                )
            self._conn.commit()

    # -- events --------------------------------------------------------

    def save_events(self, session_id: str, events: list[PresenceEvent]) -> int:
        with self._lock:
            for e in events:
                self._conn.execute(
                    "INSERT OR REPLACE INTO presence_events "
                    "(event_id, session_id, source, ts, actor, kind, text, "
                    " context, provenance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        e.event_id,
                        session_id,
                        e.source,
                        _iso(e.ts),
                        e.actor,
                        e.kind,
                        e.text,
                        json.dumps(e.context),
                        json.dumps(e.provenance),
                    ),
                )
            self._conn.commit()
        return len(events)

    def list_events(self, session_id: str) -> list[PresenceEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM presence_events WHERE session_id = ? "
                "ORDER BY rowid",
                (session_id,),
            ).fetchall()
        return [_event_from_row(r) for r in rows]

    def count_events(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM presence_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["n"])

    def delete_events(self, session_id: str) -> int:
        """Remove a session's raw (redacted) events. Signals are untouched."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM presence_events WHERE session_id = ?",
                (session_id,),
            )
            self._conn.commit()
            return cur.rowcount

    # -- signals -------------------------------------------------------

    def save_candidate_signals(self, signals: list[TrainingSignal]) -> int:
        with self._lock:
            for s in signals:
                self._conn.execute(
                    "INSERT OR REPLACE INTO training_signals "
                    "(signal_id, session_id, ts_ms, layer, zone, actor, summary, "
                    " context_ref, payload_redacted, valence, correction_diff, "
                    " kind, provenance, supersedes, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        s.signal_id,
                        s.session_id,
                        s.ts_ms,
                        s.layer,
                        s.zone,
                        s.actor,
                        s.summary,
                        json.dumps(s.context_ref),
                        s.payload_redacted,
                        s.valence,
                        s.correction_diff,
                        s.kind,
                        json.dumps(s.provenance),
                        s.supersedes,
                        s.status,
                    ),
                )
            self._conn.commit()
        return len(signals)

    def list_candidates(self, session_id: str) -> list[TrainingSignal]:
        """Pending signals awaiting user review for one import session."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM training_signals "
                "WHERE session_id = ? AND status = 'pending' ORDER BY rowid",
                (session_id,),
            ).fetchall()
        return [_signal_from_row(r) for r in rows]

    def review_signals(self, signal_ids: list[str], approve: bool) -> int:
        """Mark signals approved/rejected. Rejected rows are kept as audit trail."""
        if not signal_ids:
            return 0
        status = "approved" if approve else "rejected"
        with self._lock:
            cur = self._conn.executemany(
                "UPDATE training_signals SET status = ? "
                "WHERE signal_id = ? AND status = 'pending'",
                [(status, sid) for sid in signal_ids],
            )
            self._conn.commit()
            return cur.rowcount

    def update_signal_context(self, signal_id: str, context: dict) -> bool:
        """Set the decision envelope on a PENDING signal's context_ref.

        Returns True when a pending row was updated. Approved/rejected rows
        are NEVER touched — review history is immutable. The context dict is
        normalized defensively (unrecognized values become "unknown").
        """
        from local_ai.personality.context import (
            CONTEXT_REF_KEY,
            parse_decision_context,
        )

        envelope = parse_decision_context(context).model_dump()
        with self._lock:
            row = self._conn.execute(
                "SELECT context_ref FROM training_signals "
                "WHERE signal_id = ? AND status = 'pending'",
                (signal_id,),
            ).fetchone()
            if row is None:
                return False
            ref = _json_loads(row["context_ref"], {})
            if not isinstance(ref, dict):
                ref = {}
            ref[CONTEXT_REF_KEY] = envelope
            self._conn.execute(
                "UPDATE training_signals SET context_ref = ? "
                "WHERE signal_id = ? AND status = 'pending'",
                (json.dumps(ref), signal_id),
            )
            self._conn.commit()
            return True

    def list_signals(
        self,
        zone: str | None = None,
        status: str = "approved",
        kind: str | None = None,
    ) -> list[TrainingSignal]:
        """Query signals, defaulting to approved ones (the training set).

        Pass kind to restrict to one typed channel (e.g. "taste_observation").
        """
        clauses = ["status = ?"]
        params: list[Any] = [status]
        if zone:
            clauses.append("zone = ?")
            params.append(zone)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM training_signals WHERE "
                + " AND ".join(clauses)
                + " ORDER BY ts_ms DESC",
                params,
            ).fetchall()
        return [_signal_from_row(r) for r in rows]

    def list_signals_by_kind(
        self,
        kind: str,
        *,
        actor: str | None = None,
        status: str = "approved",
        limit: int | None = None,
    ) -> list[TrainingSignal]:
        """All signals of one typed channel, newest first."""
        clauses = ["kind = ?", "status = ?"]
        params: list[Any] = [kind, status]
        if actor is not None:
            clauses.append("actor = ?")
            params.append(actor)
        sql = (
            "SELECT * FROM training_signals WHERE "
            + " AND ".join(clauses)
            + " ORDER BY ts_ms DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_signal_from_row(r) for r in rows]

    def count_signals_by_kind(
        self, kind: str, *, actor: str | None = None, status: str = "approved"
    ) -> int:
        """Count signals of one typed channel."""
        clauses = ["kind = ?", "status = ?"]
        params: list[Any] = [kind, status]
        if actor is not None:
            clauses.append("actor = ?")
            params.append(actor)
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM training_signals WHERE "
                + " AND ".join(clauses),
                params,
            ).fetchone()
        return int(row["n"])

    def count_signals(self, session_id: str, status: str | None = None) -> int:
        with self._lock:
            if status:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM training_signals "
                    "WHERE session_id = ? AND status = ?",
                    (session_id, status),
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM training_signals WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
        return int(row["n"])

    # -- contribution claims ---------------------------------------------

    def save_claim(self, claim: ContributionClaim) -> ContributionClaim:
        """Create or replace a contribution claim.

        Claims are user assertions about their own part in collaborative
        work — freely editable, unlike append-only signals.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO contribution_claims "
                "(claim_id, session_id, event_ids, work_title, role, parts, "
                " extent, collaborators, note, attestations, license_id, "
                " created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim.claim_id,
                    claim.session_id,
                    json.dumps(claim.event_ids),
                    claim.work_title,
                    claim.role,
                    claim.parts,
                    json.dumps(claim.extent),
                    json.dumps(claim.collaborators),
                    claim.note,
                    json.dumps(claim.attestations),
                    claim.license_id,
                    _iso(claim.created_at),
                ),
            )
            self._conn.commit()
        return claim

    def list_claims(self, session_id: str) -> list[ContributionClaim]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM contribution_claims WHERE session_id = ? "
                "ORDER BY rowid",
                (session_id,),
            ).fetchall()
        return [_claim_from_row(r) for r in rows]

    def get_claim(self, claim_id: str) -> ContributionClaim | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM contribution_claims WHERE claim_id = ?",
                (claim_id,),
            ).fetchone()
        return _claim_from_row(row) if row else None

    def delete_claim(self, claim_id: str) -> bool:
        """Remove a claim. Returns True if a row was deleted."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM contribution_claims WHERE claim_id = ?",
                (claim_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0
