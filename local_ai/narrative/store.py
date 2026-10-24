"""Narrative state store (Narrative Steward S0).

The Steward's only S0 job: keep narrative STATE — threads, the
evidence attached to them, versioned readings of them, the changes
recognized in them, and the lens fittings proposed for them — as
durable, inspectable, user-governed records. No analysis lives here
(that is S1's slow path), no prose is produced here (the Steward has
no user-facing voice at any phase), and no LLM is imported anywhere
in this package.

Conventions follow the fellowship observations store: own SQLite
database (``data/narrative/narrative.db``), frozen dataclass records,
strict per-user scoping (every read and write carries user_id and
verifies ownership), loud ValueError validation over silent repair.

Two invariants do the doctrinal work and are enforced HERE, in code,
not left to callers (audit Part II §2, §7):

  1. **No reading without evidence.** A reading is stored only when
     it cites at least one evidence-tier ref, resolved through the
     tier-checked attach path. Dramatizations and interpretations
     offered as evidence are refused by refs.require_evidence_tier —
     inadmissible by type, not by convention.
  2. **No change without NEW evidence.** A thread change is recorded
     only when at least one cited ref was not already attached to
     the thread. The story may be said to have moved only when new
     evidence actually arrived (the anti-manufacture rule).

Part X (ratified 2026-10-23 ~22:32 PT) adds recursive structure,
stored and nothing more: arc associations (thread_links —
many-to-many, relation-typed, read back in either direction) and a
nullable thread-local progression position validated by the same
_validate_progression the readings use. The store walks none of it:
no traversal helpers, no recursion, and the only link guard is the
shallow one its validation style already implies — a thread may
not contain itself.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from local_ai.council.jurisdictions import SEAT_JURISDICTIONS
from local_ai.strands import strand_keys

from .lenses import get_lens
from .models import (
    CHANGE_KINDS,
    CHANGE_STATUSES,
    DISMISSAL_KINDS,
    FITTING_PROPOSERS,
    FITTING_STATUSES,
    INVOLVEMENT_SUBJECT_KINDS,
    PROGRESSION_STATES,
    READING_STATUSES,
    RETIREMENT_REASONS,
    THREAD_LINK_RELATIONS,
    THREAD_ORIGINS,
    THREAD_STATUSES,
    InvolvementMeasure,
    LensFitting,
    NarrativeThread,
    ProgressionPosition,
    StewardDismissal,
    ThreadChange,
    ThreadEvidence,
    ThreadLink,
    ThreadReading,
)
from .refs import SourceRef, require_evidence_tier

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "narrative"
DEFAULT_DB_PATH = DATA_DIR / "narrative.db"

#: Non-seat reading authors (audit Part II §2: seat id | steward | user).
READING_AUTHORS: tuple[str, ...] = ("steward", "user")

_THREAD_TRANSITIONS: dict[str, frozenset[str]] = {
    "nascent": frozenset({"active", "dormant", "resolved", "retired", "archived"}),
    "active": frozenset({"dormant", "resolved", "retired", "archived"}),
    "dormant": frozenset({"active", "resolved", "retired", "archived"}),
    "resolved": frozenset({"retired", "archived"}),
    "retired": frozenset({"archived"}),
    "archived": frozenset(),
}

_FITTING_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"offered", "accepted", "rejected", "retired"}),
    "offered": frozenset({"accepted", "rejected", "retired"}),
    "accepted": frozenset({"retired"}),
    "rejected": frozenset(),
    "retired": frozenset(),
}

_CHANGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"confirmed", "dismissed"}),
    "confirmed": frozenset(),
    "dismissed": frozenset(),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS narrative_threads (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'nascent',
  retirement_reason TEXT,
  successor_thread_id TEXT,
  scope TEXT,
  progression_json TEXT,
  strand_weights_json TEXT NOT NULL DEFAULT '{}',
  cast_json TEXT NOT NULL DEFAULT '[]',
  aspiration_refs_json TEXT NOT NULL DEFAULT '[]',
  standing_reading_id TEXT,
  lens_fitting_id TEXT,
  origin TEXT NOT NULL DEFAULT 'user_declared',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_change_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_threads_user_status
  ON narrative_threads (user_id, status, created_at);

CREATE TABLE IF NOT EXISTS thread_links (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  parent_thread_id TEXT NOT NULL,
  child_thread_id TEXT NOT NULL,
  relation TEXT NOT NULL DEFAULT 'contains',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (parent_thread_id, child_thread_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_thread_links_parent
  ON thread_links (parent_thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_thread_links_child
  ON thread_links (child_thread_id, created_at);

CREATE TABLE IF NOT EXISTS thread_evidence (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  ref_kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  evidence_kind TEXT NOT NULL DEFAULT 'entity_ref',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  entity_ref TEXT,
  UNIQUE (thread_id, ref_kind, ref_id)
);
CREATE INDEX IF NOT EXISTS idx_thread_evidence_thread
  ON thread_evidence (thread_id, created_at);

CREATE TABLE IF NOT EXISTS thread_readings (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  author TEXT NOT NULL,
  reading_json TEXT NOT NULL DEFAULT '{}',
  scales_json TEXT NOT NULL DEFAULT '[]',
  primary_scale TEXT,
  progression_json TEXT NOT NULL DEFAULT '{}',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_thread_readings_thread
  ON thread_readings (thread_id, created_at);

CREATE TABLE IF NOT EXISTS thread_changes (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  prior_reading_id TEXT,
  new_reading_id TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_thread_changes_thread
  ON thread_changes (thread_id, created_at);

CREATE TABLE IF NOT EXISTS lens_fittings (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  lens_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  proposed_by TEXT NOT NULL DEFAULT 'steward',
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_lens_fittings_thread
  ON lens_fittings (thread_id, created_at);

CREATE TABLE IF NOT EXISTS involvement_measures (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  subject_kind TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  user_authored_units REAL NOT NULL DEFAULT 0,
  user_edited_units REAL NOT NULL DEFAULT 0,
  synthesized_units REAL NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, subject_kind, subject_id)
);
CREATE INDEX IF NOT EXISTS idx_involvement_user
  ON involvement_measures (user_id, subject_kind);

CREATE TABLE IF NOT EXISTS steward_dismissals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  signature TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, kind, signature)
);
CREATE INDEX IF NOT EXISTS idx_dismissals_user
  ON steward_dismissals (user_id, kind);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:24]}"


def _loads(text: str | None, default: Any) -> Any:
    try:
        value = json.loads(text or "")
    except (json.JSONDecodeError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


def _loads_progression(text: str | None) -> ProgressionPosition | None:
    """A thread's local progression: NULL is a real value here —
    'no local progression recorded' — distinct from a stored
    position in the unknown state (Part X / Part IX)."""
    if not text:
        return None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict):
        return None
    return ProgressionPosition.from_dict(value)


# -- validation helpers -------------------------------------------------------


def _validate_strand_weights(weights: dict | None) -> dict[str, float]:
    if weights is None:
        return {}
    if not isinstance(weights, dict):
        raise ValueError("strand_weights must be a mapping of strand -> weight")
    known = set(strand_keys())
    out: dict[str, float] = {}
    for key, value in weights.items():
        if key not in known:
            raise ValueError(f"unknown strand in strand_weights: {key!r}")
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"strand weight for {key!r} is not a number: {value!r}"
            ) from None
    return out


def _validate_cast(cast: list | None) -> list[dict[str, Any]]:
    if cast is None:
        return []
    out: list[dict[str, Any]] = []
    for entry in cast:
        if not isinstance(entry, dict) or "seat" not in entry:
            raise ValueError(f"cast entries need a seat: {entry!r}")
        seat = entry["seat"]
        if seat not in SEAT_JURISDICTIONS:
            raise ValueError(f"unknown seat in cast: {seat!r}")
        out.append({"seat": seat, "role": str(entry.get("role") or "")})
    return out


def _validate_reading(reading: dict | None) -> dict[str, Any]:
    """Normalize a reading's structured state; prose is refused shape.

    Readings are structured facts (audit Part II §6 guard (a)): the
    known fields are lists of short strings / a per-seat notes map.
    Unknown keys are preserved (interpretations will grow fields)
    but the known fields are type-checked so state never quietly
    becomes a paragraph a seat is expected to repeat.
    """
    if reading is None:
        return {"tensions": [], "open_questions": [], "milestones": [], "cast_notes": {}}
    if not isinstance(reading, dict):
        raise ValueError("reading must be a mapping of structured state")
    out = dict(reading)
    for key in ("tensions", "open_questions", "milestones"):
        value = out.get(key) or []
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(f"reading[{key!r}] must be a list of strings")
        out[key] = list(value)
    notes = out.get("cast_notes") or {}
    if not isinstance(notes, dict):
        raise ValueError("reading['cast_notes'] must be a mapping")
    out["cast_notes"] = dict(notes)
    return out


def _validate_scales(
    scales: Iterable[str] | None, primary_scale: str | None
) -> tuple[list[str], str | None]:
    out: list[str] = []
    for scale in scales or ():
        if not isinstance(scale, str) or not scale.strip():
            raise ValueError(f"scales must be non-empty labels: {scale!r}")
        label = scale.strip()
        if label not in out:
            out.append(label)
    if primary_scale is not None and primary_scale not in out:
        raise ValueError(
            f"primary_scale {primary_scale!r} is not among the reading's "
            f"scales {out} — a primary scale must be one of the scales "
            "the reading actually carries"
        )
    return out, primary_scale


def _validate_progression(
    progression: ProgressionPosition | dict | None,
) -> ProgressionPosition:
    pos = (
        progression
        if isinstance(progression, ProgressionPosition)
        else ProgressionPosition.from_dict(progression)
    )
    if pos.state not in PROGRESSION_STATES:
        raise ValueError(f"unknown progression state: {pos.state!r}")
    if pos.state == "positioned":
        if not pos.lens_id:
            raise ValueError("a positioned progression needs its lens_id")
        lens = get_lens(pos.lens_id)
        if lens is None:
            raise ValueError(f"unknown lens for progression: {pos.lens_id!r}")
        if not pos.phase:
            raise ValueError("a positioned progression needs a phase")
        if pos.phase not in lens.phase_names():
            raise ValueError(
                f"phase {pos.phase!r} is not a phase of lens "
                f"{pos.lens_id!r} {list(lens.phase_names())} — a "
                "progression position is bound to its lens's own "
                "template, not a shared ladder"
            )
    elif pos.lens_id is not None or pos.phase is not None:
        raise ValueError(
            f"a {pos.state} progression carries no lens or phase — "
            "unknown and inapplicable are complete states, not "
            "positions waiting to be filled in by a consumer"
        )
    return pos


# -- row mapping ---------------------------------------------------------------


def _row_to_thread(row: sqlite3.Row) -> NarrativeThread:
    return NarrativeThread(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        status=row["status"],
        retirement_reason=row["retirement_reason"],
        successor_thread_id=row["successor_thread_id"],
        scope=row["scope"],
        progression=_loads_progression(row["progression_json"]),
        strand_weights=_loads(row["strand_weights_json"], {}),
        cast=_loads(row["cast_json"], []),
        aspiration_refs=_loads(row["aspiration_refs_json"], []),
        standing_reading_id=row["standing_reading_id"],
        lens_fitting_id=row["lens_fitting_id"],
        origin=row["origin"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_change_at=row["last_change_at"],
    )


def _row_to_link(row: sqlite3.Row) -> ThreadLink:
    return ThreadLink(
        id=row["id"],
        user_id=row["user_id"],
        parent_thread_id=row["parent_thread_id"],
        child_thread_id=row["child_thread_id"],
        relation=row["relation"],
        note=row["note"],
        created_at=row["created_at"],
    )


def _row_to_evidence(row: sqlite3.Row) -> ThreadEvidence:
    return ThreadEvidence(
        id=row["id"],
        thread_id=row["thread_id"],
        ref_kind=row["ref_kind"],
        ref_id=row["ref_id"],
        evidence_kind=row["evidence_kind"],
        note=row["note"],
        created_at=row["created_at"],
        entity_ref=row["entity_ref"] if "entity_ref" in row.keys() else None,
    )


def _row_to_reading(row: sqlite3.Row) -> ThreadReading:
    return ThreadReading(
        id=row["id"],
        thread_id=row["thread_id"],
        author=row["author"],
        reading=_loads(row["reading_json"], {}),
        scales=_loads(row["scales_json"], []),
        primary_scale=row["primary_scale"],
        progression=ProgressionPosition.from_dict(
            _loads(row["progression_json"], {})
        ),
        evidence_refs=_loads(row["evidence_refs_json"], []),
        status=row["status"],
        created_at=row["created_at"],
    )


def _row_to_change(row: sqlite3.Row) -> ThreadChange:
    return ThreadChange(
        id=row["id"],
        thread_id=row["thread_id"],
        kind=row["kind"],
        evidence_refs=_loads(row["evidence_refs_json"], []),
        prior_reading_id=row["prior_reading_id"],
        new_reading_id=row["new_reading_id"],
        status=row["status"],
        created_at=row["created_at"],
    )


def _row_to_fitting(row: sqlite3.Row) -> LensFitting:
    return LensFitting(
        id=row["id"],
        thread_id=row["thread_id"],
        lens_id=row["lens_id"],
        status=row["status"],
        evidence_refs=_loads(row["evidence_refs_json"], []),
        proposed_by=row["proposed_by"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
    )


def _row_to_involvement(row: sqlite3.Row) -> InvolvementMeasure:
    return InvolvementMeasure(
        id=row["id"],
        user_id=row["user_id"],
        subject_kind=row["subject_kind"],
        subject_id=row["subject_id"],
        user_authored_units=float(row["user_authored_units"]),
        user_edited_units=float(row["user_edited_units"]),
        synthesized_units=float(row["synthesized_units"]),
        note=row["note"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_dismissal(row: sqlite3.Row) -> StewardDismissal:
    return StewardDismissal(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        signature=row["signature"],
        created_at=row["created_at"],
    )


class NarrativeStore:
    """SQLite-backed store for narrative threads and their records."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # Part X migration: databases created by the original
            # S0 commit have no progression_json column (CREATE TABLE
            # IF NOT EXISTS does not add one). Additive only; a NULL
            # reads back as "no local progression recorded."
            columns = {
                row[1]
                for row in self._conn.execute(
                    "PRAGMA table_info(narrative_threads)"
                ).fetchall()
            }
            if "progression_json" not in columns:
                self._conn.execute(
                    "ALTER TABLE narrative_threads "
                    "ADD COLUMN progression_json TEXT"
                )
            # S1 migration: databases created before S1 have no
            # entity_ref column on thread_evidence (CREATE TABLE
            # IF NOT EXISTS does not add one). Additive only; NULL
            # reads back as "entity unknown" for older rows.
            ev_columns = {
                row[1]
                for row in self._conn.execute(
                    "PRAGMA table_info(thread_evidence)"
                ).fetchall()
            }
            if "entity_ref" not in ev_columns:
                self._conn.execute(
                    "ALTER TABLE thread_evidence "
                    "ADD COLUMN entity_ref TEXT"
                )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- internal helpers -------------------------------------------------------

    def _require_thread(self, user_id: str, thread_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM narrative_threads WHERE id = ? AND user_id = ?",
            (thread_id, user_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown narrative thread: {thread_id!r}")
        return row

    def _touch_thread(self, thread_id: str, *, change: bool = False) -> None:
        now = _utcnow()
        if change:
            self._conn.execute(
                "UPDATE narrative_threads SET updated_at = ?, "
                "last_change_at = ? WHERE id = ?",
                (now, now, thread_id),
            )
        else:
            self._conn.execute(
                "UPDATE narrative_threads SET updated_at = ? WHERE id = ?",
                (now, thread_id),
            )

    def _attach_evidence(
        self,
        thread_id: str,
        refs: Iterable[SourceRef | str],
        *,
        note: str = "",
    ) -> tuple[list[str], set[str]]:
        """Resolve refs to thread_evidence ids, attaching what's new.

        Every SourceRef passes the tier gate (refs.require_evidence_
        tier): Tier I / Tier D refs raise InadmissibleEvidenceError
        here, so no caller can attach a dramatization as evidence by
        any path. A plain string is accepted only as the id of an
        evidence row ALREADY attached to this thread (so readings can
        cite what a thread's birth attached); unknown ids raise.

        Returns (resolved ids in caller order, deduped; ids newly
        attached by this call). Caller must hold the lock.
        """
        existing = {
            (row["ref_kind"], row["ref_id"]): row["id"]
            for row in self._conn.execute(
                "SELECT id, ref_kind, ref_id FROM thread_evidence "
                "WHERE thread_id = ?",
                (thread_id,),
            ).fetchall()
        }
        by_id = {row_id: key for key, row_id in existing.items()}
        resolved: list[str] = []
        newly: set[str] = set()
        for ref in refs:
            if isinstance(ref, str):
                if ref not in by_id:
                    raise ValueError(
                        f"unknown thread evidence id for this thread: {ref!r}"
                    )
                row_id = ref
            elif isinstance(ref, SourceRef):
                require_evidence_tier(ref)
                key = (ref.kind, ref.ref_id)
                row_id = existing.get(key)
                if row_id is None:
                    row_id = _new_id("tev")
                    self._conn.execute(
                        "INSERT INTO thread_evidence (id, thread_id, "
                        "ref_kind, ref_id, evidence_kind, note, "
                        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            row_id, thread_id, ref.kind, ref.ref_id,
                            ref.evidence_kind, note, _utcnow(),
                        ),
                    )
                    existing[key] = row_id
                    by_id[row_id] = key
                    newly.add(row_id)
            else:
                raise ValueError(f"not a source ref or evidence id: {ref!r}")
            if row_id not in resolved:
                resolved.append(row_id)
        return resolved, newly

    # -- threads ------------------------------------------------------------------

    def create_thread(
        self,
        user_id: str,
        *,
        origin: str = "user_declared",
        title: str = "",
        scope: str | None = None,
        progression: ProgressionPosition | dict | None = None,
        strand_weights: dict | None = None,
        cast: list | None = None,
        aspiration_refs: list | None = None,
        evidence_refs: Iterable[SourceRef | str] = (),
    ) -> NarrativeThread:
        """Create a thread and attach its founding evidence.

        ``scope`` is Part IX's optional broad label — stored when
        given, NULL when not; the store never requires one.
        ``progression`` is Part X's optional thread-local position:
        None (the default) records no local progression; a given
        position passes the same lens-binding validation readings
        use. Founding evidence passes the same tier gate as all
        evidence.
        """
        if origin not in THREAD_ORIGINS:
            raise ValueError(f"unknown thread origin: {origin!r}")
        weights = _validate_strand_weights(strand_weights)
        cast_rows = _validate_cast(cast)
        local_pos = (
            None if progression is None else _validate_progression(progression)
        )
        now = _utcnow()
        thread = NarrativeThread(
            id=_new_id("thr"),
            user_id=user_id,
            title=title,
            status="nascent",
            scope=scope,
            progression=local_pos,
            strand_weights=weights,
            cast=cast_rows,
            aspiration_refs=[str(ref) for ref in (aspiration_refs or [])],
            origin=origin,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO narrative_threads (id, user_id, title, "
                "status, retirement_reason, successor_thread_id, "
                "scope, progression_json, strand_weights_json, "
                "cast_json, aspiration_refs_json, "
                "standing_reading_id, lens_fitting_id, origin, "
                "created_at, updated_at, last_change_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thread.id, thread.user_id, thread.title,
                    thread.status, None, None, thread.scope,
                    json.dumps(local_pos.to_dict(), ensure_ascii=False)
                    if local_pos is not None else None,
                    json.dumps(weights, ensure_ascii=False),
                    json.dumps(cast_rows, ensure_ascii=False),
                    json.dumps(thread.aspiration_refs, ensure_ascii=False),
                    None, None, thread.origin, now, now, None,
                ),
            )
            if evidence_refs:
                self._attach_evidence(thread.id, evidence_refs)
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM narrative_threads WHERE id = ?",
                (thread.id,),
            ).fetchone()
        return _row_to_thread(row)

    def get_thread(self, user_id: str, thread_id: str) -> NarrativeThread | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM narrative_threads WHERE id = ? AND "
                "user_id = ?",
                (thread_id, user_id),
            ).fetchone()
        return _row_to_thread(row) if row else None

    def threads_for(
        self,
        user_id: str,
        *,
        seat: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[NarrativeThread]:
        """The user's threads, oldest first. ``seat`` filters by cast
        standing (a seat in the thread's cast), in Python — thread
        counts per user are small and cast is JSON by design."""
        if status is not None and status not in THREAD_STATUSES:
            raise ValueError(f"unknown thread status: {status!r}")
        if seat is not None and seat not in SEAT_JURISDICTIONS:
            raise ValueError(f"unknown seat: {seat!r}")
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM narrative_threads WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        threads = [_row_to_thread(r) for r in rows]
        if seat is not None:
            threads = [
                t for t in threads
                if any(c.get("seat") == seat for c in (t.cast or []))
            ]
        return threads[:limit]

    def update_title(
        self, user_id: str, thread_id: str, title: str
    ) -> NarrativeThread:
        """Titles are user-editable (audit Part II §2); nothing else
        about a thread is rewritten in place — readings supersede,
        they never edit."""
        with self._lock:
            self._require_thread(user_id, thread_id)
            self._conn.execute(
                "UPDATE narrative_threads SET title = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (title, _utcnow(), thread_id, user_id),
            )
            self._conn.commit()
            row = self._require_thread(user_id, thread_id)
        return _row_to_thread(row)

    def set_thread_status(
        self,
        user_id: str,
        thread_id: str,
        status: str,
        *,
        retirement_reason: str | None = None,
        successor_thread_id: str | None = None,
    ) -> NarrativeThread:
        """Move a thread along its lifecycle, loudly.

        Retirement is a first-class ending (Part II §5): it REQUIRES
        a reason, and ``reinterpreted`` requires the successor thread
        (same user, not itself) whose birth the reinterpretation is.
        A user may retire or archive their own thread at any time —
        this method is that act; evidence-driven retirement PROPOSALS
        arrive through record_change in later phases, never as silent
        edits here.
        """
        if status not in THREAD_STATUSES:
            raise ValueError(f"unknown thread status: {status!r}")
        with self._lock:
            row = self._require_thread(user_id, thread_id)
            current = row["status"]
            if status not in _THREAD_TRANSITIONS.get(current, frozenset()):
                raise ValueError(
                    f"thread status cannot move {current} -> {status}"
                )
            reason = row["retirement_reason"]
            successor = row["successor_thread_id"]
            if status == "retired":
                if retirement_reason not in RETIREMENT_REASONS:
                    raise ValueError(
                        "retiring a thread needs a reason, one of "
                        f"{list(RETIREMENT_REASONS)}: {retirement_reason!r}"
                    )
                if retirement_reason == "reinterpreted":
                    if not successor_thread_id:
                        raise ValueError(
                            "a reinterpreted retirement needs its "
                            "successor_thread_id — the thread this "
                            "evidence now belongs to"
                        )
                    if successor_thread_id == thread_id:
                        raise ValueError(
                            "a thread cannot succeed itself"
                        )
                    self._require_thread(user_id, successor_thread_id)
                reason = retirement_reason
                successor = successor_thread_id
            now = _utcnow()
            self._conn.execute(
                "UPDATE narrative_threads SET status = ?, "
                "retirement_reason = ?, successor_thread_id = ?, "
                "updated_at = ?, last_change_at = ? WHERE id = ? "
                "AND user_id = ?",
                (status, reason, successor, now, now, thread_id, user_id),
            )
            self._conn.commit()
            row = self._require_thread(user_id, thread_id)
        return _row_to_thread(row)

    def set_thread_progression(
        self,
        user_id: str,
        thread_id: str,
        progression: ProgressionPosition | dict | None,
    ) -> NarrativeThread:
        """Record (or clear) a thread's LOCAL progression position.

        Part X: the arc's own development at its own resolution,
        stored beside — never instead of — its readings' positions.
        The value passes _validate_progression, the same lens-
        binding rule readings obey: a positioned state must name a
        phase of its own lens's template; unknown and inapplicable
        carry no lens. Passing None clears the position back to
        'none recorded', which is a distinct fact from 'unknown'.
        """
        pos = (
            None if progression is None else _validate_progression(progression)
        )
        with self._lock:
            self._require_thread(user_id, thread_id)
            self._conn.execute(
                "UPDATE narrative_threads SET progression_json = ?, "
                "updated_at = ? WHERE id = ? AND user_id = ?",
                (
                    json.dumps(pos.to_dict(), ensure_ascii=False)
                    if pos is not None else None,
                    _utcnow(), thread_id, user_id,
                ),
            )
            self._conn.commit()
            row = self._require_thread(user_id, thread_id)
        return _row_to_thread(row)

    # -- arc associations (Part X) --------------------------------------------------

    def link_threads(
        self,
        user_id: str,
        parent_thread_id: str,
        child_thread_id: str,
        *,
        relation: str = "contains",
        note: str = "",
    ) -> ThreadLink:
        """Record that one arc contains another (Part X).

        Many-to-many by construction: nothing here limits a child
        to one parent or a parent to one child, so arcs nest and
        overlap exactly as lived stories do. Both threads must be
        the user's. Re-linking the same pair with the same relation
        returns the existing row (links dedupe like evidence).
        The one guard is shallow and deliberate: a thread may not
        contain ITSELF. There is no deeper cycle detection — S0
        stores structure; it does not walk it.
        """
        if relation not in THREAD_LINK_RELATIONS:
            raise ValueError(f"unknown thread link relation: {relation!r}")
        if parent_thread_id == child_thread_id:
            raise ValueError("a thread cannot contain itself")
        with self._lock:
            self._require_thread(user_id, parent_thread_id)
            self._require_thread(user_id, child_thread_id)
            existing = self._conn.execute(
                "SELECT * FROM thread_links WHERE parent_thread_id = ? "
                "AND child_thread_id = ? AND relation = ?",
                (parent_thread_id, child_thread_id, relation),
            ).fetchone()
            if existing is not None:
                return _row_to_link(existing)
            record = ThreadLink(
                id=_new_id("lnk"),
                user_id=user_id,
                parent_thread_id=parent_thread_id,
                child_thread_id=child_thread_id,
                relation=relation,
                note=note,
                created_at=_utcnow(),
            )
            self._conn.execute(
                "INSERT INTO thread_links (id, user_id, "
                "parent_thread_id, child_thread_id, relation, note, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id, record.user_id, record.parent_thread_id,
                    record.child_thread_id, record.relation,
                    record.note, record.created_at,
                ),
            )
            self._conn.commit()
        return record

    def unlink_threads(
        self,
        user_id: str,
        parent_thread_id: str,
        child_thread_id: str,
        *,
        relation: str = "contains",
    ) -> bool:
        """Remove one arc association. Returns True when a link was
        removed, False when none existed — associations are the
        user's structure to revise; removing one rewrites nothing
        about either thread."""
        if relation not in THREAD_LINK_RELATIONS:
            raise ValueError(f"unknown thread link relation: {relation!r}")
        with self._lock:
            self._require_thread(user_id, parent_thread_id)
            self._require_thread(user_id, child_thread_id)
            cursor = self._conn.execute(
                "DELETE FROM thread_links WHERE parent_thread_id = ? "
                "AND child_thread_id = ? AND relation = ?",
                (parent_thread_id, child_thread_id, relation),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def links_for(
        self, user_id: str, thread_id: str
    ) -> list[ThreadLink]:
        """Every association touching a thread, in either direction:
        the arcs it contains and the arcs it participates in.
        (A flat read of stored rows — not a traversal.)"""
        with self._lock:
            self._require_thread(user_id, thread_id)
            rows = self._conn.execute(
                "SELECT * FROM thread_links WHERE parent_thread_id = ? "
                "OR child_thread_id = ? ORDER BY created_at, id",
                (thread_id, thread_id),
            ).fetchall()
        return [_row_to_link(r) for r in rows]

    def links_as_parent(
        self, user_id: str, thread_id: str
    ) -> list[ThreadLink]:
        """The arcs this thread contains (its smaller arcs)."""
        with self._lock:
            self._require_thread(user_id, thread_id)
            rows = self._conn.execute(
                "SELECT * FROM thread_links WHERE parent_thread_id = ? "
                "ORDER BY created_at, id",
                (thread_id,),
            ).fetchall()
        return [_row_to_link(r) for r in rows]

    def links_as_child(
        self, user_id: str, thread_id: str
    ) -> list[ThreadLink]:
        """The arcs this thread participates in (its larger arcs) —
        plural by design: overlapping association is the point."""
        with self._lock:
            self._require_thread(user_id, thread_id)
            rows = self._conn.execute(
                "SELECT * FROM thread_links WHERE child_thread_id = ? "
                "ORDER BY created_at, id",
                (thread_id,),
            ).fetchall()
        return [_row_to_link(r) for r in rows]

    # -- evidence -----------------------------------------------------------------

    def add_evidence(
        self,
        user_id: str,
        thread_id: str,
        ref: SourceRef,
        *,
        note: str = "",
    ) -> ThreadEvidence:
        """Attach one evidence-tier record to a thread (deduped).

        The tier gate lives in _attach_evidence: offering a
        dramatization or interpretation ref here raises
        InadmissibleEvidenceError, whatever the caller intended.
        """
        with self._lock:
            self._require_thread(user_id, thread_id)
            resolved, _ = self._attach_evidence(thread_id, [ref], note=note)
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM thread_evidence WHERE id = ?",
                (resolved[0],),
            ).fetchone()
        return _row_to_evidence(row)

    def evidence_for(
        self, user_id: str, thread_id: str
    ) -> list[ThreadEvidence]:
        with self._lock:
            self._require_thread(user_id, thread_id)
            rows = self._conn.execute(
                "SELECT * FROM thread_evidence WHERE thread_id = ? "
                "ORDER BY created_at, id",
                (thread_id,),
            ).fetchall()
        return [_row_to_evidence(r) for r in rows]

    def annotate_evidence_entities(
        self,
        user_id: str,
        thread_id: str,
        mapping: dict[tuple[str, str], str],
    ) -> int:
        """Record "<type>:<id>" identities on a thread's evidence rows.

        S1 derivation maintains this index for evidence it attaches:
        the row's identity stays (ref_kind, ref_id), but knowing
        what a record is *about* lets later derivation recognize
        that new evidence concerns the same thing as thread evidence
        — the thread-extension path. Rows from other writers keep
        NULL (honest unknown); annotation never invents an entity,
        it only records one the attaching caller already knew.
        Returns how many rows were annotated.
        """
        if not mapping:
            return 0
        with self._lock:
            self._require_thread(user_id, thread_id)
            updated = 0
            for (ref_kind, ref_id), entity_ref in mapping.items():
                if not str(entity_ref or "").strip():
                    continue
                cursor = self._conn.execute(
                    "UPDATE thread_evidence SET entity_ref = ? "
                    "WHERE thread_id = ? AND ref_kind = ? AND ref_id = ?",
                    (entity_ref, thread_id, ref_kind, ref_id),
                )
                updated += cursor.rowcount
            self._conn.commit()
        return updated

    # -- readings -----------------------------------------------------------------

    def propose_reading(
        self,
        user_id: str,
        thread_id: str,
        *,
        author: str,
        reading: dict | None = None,
        evidence_refs: Iterable[SourceRef | str] = (),
        scales: Iterable[str] | None = None,
        primary_scale: str | None = None,
        progression: ProgressionPosition | dict | None = None,
    ) -> ThreadReading:
        """Store a proposed reading of a thread.

        INVARIANT 1: a reading with no evidence cannot be stored —
        empty refs raise, and every ref resolves through the tier
        gate, so 'evidence' here always means evidence-tier records
        actually attached to this thread.
        """
        if author not in SEAT_JURISDICTIONS and author not in READING_AUTHORS:
            raise ValueError(f"unknown reading author: {author!r}")
        reading_data = _validate_reading(reading)
        scale_list, primary = _validate_scales(scales, primary_scale)
        pos = _validate_progression(progression)
        with self._lock:
            self._require_thread(user_id, thread_id)
            resolved, _ = self._attach_evidence(thread_id, evidence_refs)
            if not resolved:
                raise ValueError(
                    "a reading cannot be stored without evidence refs "
                    "(invariant: no reading without at least one "
                    "evidence-tier reference)"
                )
            record = ThreadReading(
                id=_new_id("rdg"),
                thread_id=thread_id,
                author=author,
                reading=reading_data,
                scales=scale_list,
                primary_scale=primary,
                progression=pos,
                evidence_refs=resolved,
                status="proposed",
                created_at=_utcnow(),
            )
            self._conn.execute(
                "INSERT INTO thread_readings (id, thread_id, author, "
                "reading_json, scales_json, primary_scale, "
                "progression_json, evidence_refs_json, status, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id, record.thread_id, record.author,
                    json.dumps(reading_data, ensure_ascii=False),
                    json.dumps(scale_list, ensure_ascii=False),
                    primary,
                    json.dumps(pos.to_dict(), ensure_ascii=False),
                    json.dumps(resolved, ensure_ascii=False),
                    record.status, record.created_at,
                ),
            )
            self._touch_thread(thread_id)
            self._conn.commit()
        return record

    def accept_reading(
        self, user_id: str, reading_id: str
    ) -> ThreadReading:
        """Make a proposed reading the thread's standing reading.

        The previously standing reading is SUPERSEDED, never edited
        or deleted — both persist, so a later disagreement stays
        inspectable (doctrine §6).
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT r.* FROM thread_readings r JOIN "
                "narrative_threads t ON t.id = r.thread_id "
                "WHERE r.id = ? AND t.user_id = ?",
                (reading_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown reading: {reading_id!r}")
            if row["status"] != "proposed":
                raise ValueError(
                    f"only a proposed reading can be accepted "
                    f"(this one is {row['status']})"
                )
            thread_id = row["thread_id"]
            thread = self._require_thread(user_id, thread_id)
            prior_standing = thread["standing_reading_id"]
            if prior_standing and prior_standing != reading_id:
                self._conn.execute(
                    "UPDATE thread_readings SET status = 'superseded' "
                    "WHERE id = ?",
                    (prior_standing,),
                )
            self._conn.execute(
                "UPDATE thread_readings SET status = 'accepted' "
                "WHERE id = ?",
                (reading_id,),
            )
            self._conn.execute(
                "UPDATE narrative_threads SET standing_reading_id = ?, "
                "updated_at = ? WHERE id = ?",
                (reading_id, _utcnow(), thread_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM thread_readings WHERE id = ?",
                (reading_id,),
            ).fetchone()
        return _row_to_reading(row)

    def reject_reading(self, user_id: str, reading_id: str) -> ThreadReading:
        with self._lock:
            row = self._conn.execute(
                "SELECT r.* FROM thread_readings r JOIN "
                "narrative_threads t ON t.id = r.thread_id "
                "WHERE r.id = ? AND t.user_id = ?",
                (reading_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown reading: {reading_id!r}")
            if row["status"] != "proposed":
                raise ValueError(
                    f"only a proposed reading can be rejected "
                    f"(this one is {row['status']})"
                )
            self._conn.execute(
                "UPDATE thread_readings SET status = 'rejected' "
                "WHERE id = ?",
                (reading_id,),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM thread_readings WHERE id = ?",
                (reading_id,),
            ).fetchone()
        return _row_to_reading(row)

    def readings_for(
        self,
        user_id: str,
        thread_id: str,
        *,
        status: str | None = None,
    ) -> list[ThreadReading]:
        if status is not None and status not in READING_STATUSES:
            raise ValueError(f"unknown reading status: {status!r}")
        with self._lock:
            self._require_thread(user_id, thread_id)
            clauses = ["thread_id = ?"]
            args: list[Any] = [thread_id]
            if status is not None:
                clauses.append("status = ?")
                args.append(status)
            rows = self._conn.execute(
                "SELECT * FROM thread_readings WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        return [_row_to_reading(r) for r in rows]

    # -- changes ------------------------------------------------------------------

    def record_change(
        self,
        user_id: str,
        thread_id: str,
        *,
        kind: str,
        evidence_refs: Iterable[SourceRef | str] = (),
        new_reading_id: str | None = None,
        prior_reading_id: str | None = None,
    ) -> ThreadChange:
        """Record that a thread's story moved.

        INVARIANT 2 (the anti-manufacture rule): at least one cited
        ref must be NEW to the thread — evidence ids already attached
        and refs already attached do not count. A change asserted on
        only old evidence raises here, whatever called it.
        """
        if kind not in CHANGE_KINDS:
            raise ValueError(f"unknown thread change kind: {kind!r}")
        with self._lock:
            thread = self._require_thread(user_id, thread_id)
            resolved, newly = self._attach_evidence(thread_id, evidence_refs)
            if not newly:
                raise ValueError(
                    "a thread change cannot be recorded without new "
                    "evidence (invariant: at least one cited ref must "
                    "not have been attached to the thread before)"
                )
            for label, reading_id in (
                ("prior_reading_id", prior_reading_id),
                ("new_reading_id", new_reading_id),
            ):
                if reading_id is not None:
                    found = self._conn.execute(
                        "SELECT id FROM thread_readings WHERE id = ? "
                        "AND thread_id = ?",
                        (reading_id, thread_id),
                    ).fetchone()
                    if found is None:
                        raise ValueError(
                            f"{label} is not a reading of this thread: "
                            f"{reading_id!r}"
                        )
            record = ThreadChange(
                id=_new_id("chg"),
                thread_id=thread_id,
                kind=kind,
                evidence_refs=resolved,
                prior_reading_id=(
                    prior_reading_id
                    if prior_reading_id is not None
                    else thread["standing_reading_id"]
                ),
                new_reading_id=new_reading_id,
                status="proposed",
                created_at=_utcnow(),
            )
            self._conn.execute(
                "INSERT INTO thread_changes (id, thread_id, kind, "
                "evidence_refs_json, prior_reading_id, "
                "new_reading_id, status, created_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id, record.thread_id, record.kind,
                    json.dumps(resolved, ensure_ascii=False),
                    record.prior_reading_id, record.new_reading_id,
                    record.status, record.created_at,
                ),
            )
            self._touch_thread(thread_id, change=True)
            self._conn.commit()
        return record

    def set_change_status(
        self, user_id: str, change_id: str, status: str
    ) -> ThreadChange:
        if status not in CHANGE_STATUSES:
            raise ValueError(f"unknown change status: {status!r}")
        with self._lock:
            row = self._conn.execute(
                "SELECT c.* FROM thread_changes c JOIN "
                "narrative_threads t ON t.id = c.thread_id "
                "WHERE c.id = ? AND t.user_id = ?",
                (change_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown thread change: {change_id!r}")
            current = row["status"]
            if status not in _CHANGE_TRANSITIONS.get(current, frozenset()):
                raise ValueError(
                    f"change status cannot move {current} -> {status}"
                )
            self._conn.execute(
                "UPDATE thread_changes SET status = ? WHERE id = ?",
                (status, change_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM thread_changes WHERE id = ?",
                (change_id,),
            ).fetchone()
        return _row_to_change(row)

    def changes_for(
        self, user_id: str, thread_id: str
    ) -> list[ThreadChange]:
        with self._lock:
            self._require_thread(user_id, thread_id)
            rows = self._conn.execute(
                "SELECT * FROM thread_changes WHERE thread_id = ? "
                "ORDER BY created_at, id",
                (thread_id,),
            ).fetchall()
        return [_row_to_change(r) for r in rows]

    # -- lens fittings --------------------------------------------------------------

    def set_fitting(
        self,
        user_id: str,
        thread_id: str,
        *,
        lens_id: str,
        evidence_refs: Iterable[SourceRef | str] = (),
        proposed_by: str = "steward",
        status: str = "proposed",
    ) -> LensFitting:
        """Record a lens fitting for a thread.

        A fitting must cite the evidence that suggested it (audit
        Part II §4 — proposals require evidence, cited through the
        same tier gate as readings). At most one ACCEPTED fitting is
        live per thread: accepting one while another is live raises;
        retire the old fitting first, so the displacement stays a
        recorded act, never a silent overwrite.
        """
        if get_lens(lens_id) is None:
            raise ValueError(f"unknown lens: {lens_id!r}")
        if proposed_by not in FITTING_PROPOSERS:
            raise ValueError(f"unknown fitting proposer: {proposed_by!r}")
        if status not in FITTING_STATUSES:
            raise ValueError(f"unknown fitting status: {status!r}")
        with self._lock:
            thread = self._require_thread(user_id, thread_id)
            resolved, _ = self._attach_evidence(thread_id, evidence_refs)
            if not resolved:
                raise ValueError(
                    "a lens fitting cannot be proposed without "
                    "evidence refs — the proposal must cite the "
                    "evidence that suggested the lens"
                )
            if status == "accepted" and thread["lens_fitting_id"]:
                raise ValueError(
                    "thread already has a live fitting "
                    f"({thread['lens_fitting_id']}); retire it before "
                    "accepting another — one live fitting per thread"
                )
            now = _utcnow()
            record = LensFitting(
                id=_new_id("fit"),
                thread_id=thread_id,
                lens_id=lens_id,
                status=status,
                evidence_refs=resolved,
                proposed_by=proposed_by,
                created_at=now,
                decided_at=now if status in ("accepted", "rejected") else None,
            )
            self._conn.execute(
                "INSERT INTO lens_fittings (id, thread_id, lens_id, "
                "status, evidence_refs_json, proposed_by, "
                "created_at, decided_at) VALUES (?, ?, ?, ?, ?, ?, "
                "?, ?)",
                (
                    record.id, record.thread_id, record.lens_id,
                    record.status,
                    json.dumps(resolved, ensure_ascii=False),
                    record.proposed_by, record.created_at,
                    record.decided_at,
                ),
            )
            if status == "accepted":
                self._conn.execute(
                    "UPDATE narrative_threads SET lens_fitting_id = ? "
                    "WHERE id = ?",
                    (record.id, thread_id),
                )
            self._touch_thread(thread_id)
            self._conn.commit()
        return record

    def set_fitting_status(
        self, user_id: str, fitting_id: str, status: str
    ) -> LensFitting:
        """Move a fitting along its lifecycle.

        Acceptance and rejection are verdicts: ``decided_at`` is
        stamped, and rejection is durable data (later phases must
        consult it before re-proposing; S0's job is to make sure it
        is faithfully recorded). Accepting enforces the one-live-
        fitting rule against the thread's pointer.
        """
        if status not in FITTING_STATUSES:
            raise ValueError(f"unknown fitting status: {status!r}")
        with self._lock:
            row = self._conn.execute(
                "SELECT f.* FROM lens_fittings f JOIN "
                "narrative_threads t ON t.id = f.thread_id "
                "WHERE f.id = ? AND t.user_id = ?",
                (fitting_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown lens fitting: {fitting_id!r}")
            current = row["status"]
            if status not in _FITTING_TRANSITIONS.get(current, frozenset()):
                raise ValueError(
                    f"fitting status cannot move {current} -> {status}"
                )
            thread_id = row["thread_id"]
            thread = self._require_thread(user_id, thread_id)
            now = _utcnow()
            decided_at = row["decided_at"]
            if status == "accepted":
                live = thread["lens_fitting_id"]
                if live and live != fitting_id:
                    raise ValueError(
                        "thread already has a live fitting "
                        f"({live}); retire it before accepting "
                        "another — one live fitting per thread"
                    )
                self._conn.execute(
                    "UPDATE narrative_threads SET lens_fitting_id = ? "
                    "WHERE id = ?",
                    (fitting_id, thread_id),
                )
                decided_at = now
            elif status == "rejected":
                decided_at = now
            elif status == "retired" and thread["lens_fitting_id"] == fitting_id:
                self._conn.execute(
                    "UPDATE narrative_threads SET lens_fitting_id = "
                    "NULL WHERE id = ?",
                    (thread_id,),
                )
            self._conn.execute(
                "UPDATE lens_fittings SET status = ?, decided_at = ? "
                "WHERE id = ?",
                (status, decided_at, fitting_id),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM lens_fittings WHERE id = ?",
                (fitting_id,),
            ).fetchone()
        return _row_to_fitting(row)

    def fittings_for(
        self,
        user_id: str,
        thread_id: str,
        *,
        status: str | None = None,
    ) -> list[LensFitting]:
        if status is not None and status not in FITTING_STATUSES:
            raise ValueError(f"unknown fitting status: {status!r}")
        with self._lock:
            self._require_thread(user_id, thread_id)
            clauses = ["thread_id = ?"]
            args: list[Any] = [thread_id]
            if status is not None:
                clauses.append("status = ?")
                args.append(status)
            rows = self._conn.execute(
                "SELECT * FROM lens_fittings WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        return [_row_to_fitting(r) for r in rows]

    # -- involvement ledger (Part VII) --------------------------------------------

    def record_involvement(
        self,
        user_id: str,
        *,
        subject_kind: str,
        subject_id: str,
        user_authored_units: float = 0.0,
        user_edited_units: float = 0.0,
        synthesized_units: float = 0.0,
        note: str = "",
    ) -> InvolvementMeasure:
        """Record (or replace) the involvement measure for a subject.

        One current measure per (user, subject): the ledger records
        HOW a thing was made — the user's authored units, the user's
        edited units, and Zenaf-synthesized units in separate
        columns — so attribution can ever be honest (Part VII §4).
        S0 stores the measure; nothing consumes it yet.
        """
        if subject_kind not in INVOLVEMENT_SUBJECT_KINDS:
            raise ValueError(
                f"unknown involvement subject kind: {subject_kind!r}"
            )
        units: dict[str, float] = {}
        for label, value in (
            ("user_authored_units", user_authored_units),
            ("user_edited_units", user_edited_units),
            ("synthesized_units", synthesized_units),
        ):
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{label} is not a number: {value!r}") from None
            if number < 0:
                raise ValueError(f"{label} cannot be negative: {value!r}")
            units[label] = number
        now = _utcnow()
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM involvement_measures WHERE user_id = ? "
                "AND subject_kind = ? AND subject_id = ?",
                (user_id, subject_kind, subject_id),
            ).fetchone()
            if existing is None:
                record = InvolvementMeasure(
                    id=_new_id("inv"),
                    user_id=user_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    note=note,
                    created_at=now,
                    updated_at=now,
                    **units,
                )
                self._conn.execute(
                    "INSERT INTO involvement_measures (id, user_id, "
                    "subject_kind, subject_id, user_authored_units, "
                    "user_edited_units, synthesized_units, note, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, "
                    "?, ?, ?, ?, ?)",
                    (
                        record.id, record.user_id, record.subject_kind,
                        record.subject_id, record.user_authored_units,
                        record.user_edited_units,
                        record.synthesized_units, record.note,
                        record.created_at, record.updated_at,
                    ),
                )
            else:
                self._conn.execute(
                    "UPDATE involvement_measures SET "
                    "user_authored_units = ?, user_edited_units = ?, "
                    "synthesized_units = ?, note = ?, updated_at = ? "
                    "WHERE id = ?",
                    (
                        units["user_authored_units"],
                        units["user_edited_units"],
                        units["synthesized_units"],
                        note, now, existing["id"],
                    ),
                )
                record = InvolvementMeasure(
                    id=existing["id"],
                    user_id=user_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    note=note,
                    created_at=existing["created_at"],
                    updated_at=now,
                    **units,
                )
            self._conn.commit()
        return record

    def involvement_for(
        self, user_id: str, subject_kind: str, subject_id: str
    ) -> InvolvementMeasure | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM involvement_measures WHERE user_id = ? "
                "AND subject_kind = ? AND subject_id = ?",
                (user_id, subject_kind, subject_id),
            ).fetchone()
        return _row_to_involvement(row) if row else None

    def involvements_for(self, user_id: str) -> list[InvolvementMeasure]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM involvement_measures WHERE user_id = ? "
                "ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
        return [_row_to_involvement(r) for r in rows]

    # -- dismissal memory (S1) -------------------------------------------------

    def record_dismissal(
        self, user_id: str, *, kind: str, signature: str
    ) -> StewardDismissal:
        """Remember that the user dismissed a steward proposal.

        The signature is content-addressed (derivation.py builds it
        from the proposal's evidence keys, plus the thread id for
        extensions), so the same evidence is never re-proposed while
        genuinely new evidence produces a new signature and may be
        proposed again. Recording the same dismissal twice returns
        the existing row. This records the user's act only — it
        never deletes or alters the thread, reading, or change that
        was dismissed; those rows keep their own lifecycles.
        """
        if kind not in DISMISSAL_KINDS:
            raise ValueError(f"unknown dismissal kind: {kind!r}")
        if not str(signature or "").strip():
            raise ValueError("a dismissal needs a non-empty signature")
        now = _utcnow()
        with self._lock:
            existing = self._conn.execute(
                "SELECT * FROM steward_dismissals WHERE user_id = ? "
                "AND kind = ? AND signature = ?",
                (user_id, kind, signature),
            ).fetchone()
            if existing is not None:
                return _row_to_dismissal(existing)
            record = StewardDismissal(
                id=_new_id("dsm"),
                user_id=user_id,
                kind=kind,
                signature=signature,
                created_at=now,
            )
            self._conn.execute(
                "INSERT INTO steward_dismissals (id, user_id, kind, "
                "signature, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    record.id, record.user_id, record.kind,
                    record.signature, record.created_at,
                ),
            )
            self._conn.commit()
        return record

    def is_dismissed(
        self, user_id: str, *, kind: str, signature: str
    ) -> bool:
        """Has this exact proposal signature already been dismissed?"""
        if kind not in DISMISSAL_KINDS:
            raise ValueError(f"unknown dismissal kind: {kind!r}")
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM steward_dismissals WHERE user_id = ? "
                "AND kind = ? AND signature = ?",
                (user_id, kind, signature),
            ).fetchone()
        return row is not None

    def dismissals_for(self, user_id: str) -> list[StewardDismissal]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_dismissals WHERE user_id = ? "
                "ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
        return [_row_to_dismissal(r) for r in rows]
