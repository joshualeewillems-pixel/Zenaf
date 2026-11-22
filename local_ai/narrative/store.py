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
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from local_ai.council.jurisdictions import SEAT_JURISDICTIONS
from local_ai.identity.boundary import (
    BoundaryState,
    boundary_state_for,
    register_boundary_state,
    unregister_boundary_state,
)
from local_ai.strands import strand_keys

from .lenses import get_lens
from .models import (
    ARTIFACT_VERSION_STATUSES,
    CHANGE_KINDS,
    CHANGE_STATUSES,
    DISMISSAL_KINDS,
    FITTING_PROPOSERS,
    FITTING_STATUSES,
    INVOLVEMENT_SUBJECT_KINDS,
    OBSERVABLE_KINDS,
    PROGRESSION_STATES,
    READING_STATUSES,
    RETIREMENT_REASONS,
    THREAD_LINK_RELATIONS,
    THREAD_ORIGINS,
    THREAD_STATUSES,
    ArtifactVersion,
    Correspondence,
    CorrespondenceResponse,
    DiscrepancyFlag,
    InvolvementMeasure,
    LensFitting,
    NarrativeThread,
    OversightProposal,
    ProgressionPosition,
    ReadingReconsideration,
    RelevanceAssessment,
    ReviewVerdict,
    StewardArtifact,
    StewardDismissal,
    StewardObservable,
    CandidateAct,
    CandidateMembership,
    CandidateMention,
    CandidateSighting,
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

#: Phase 6 artifact-version transitions (models
#: ARTIFACT_VERSION_STATUSES). One-way forward: a proposed version
#: enters review, then is accepted or rejected; an accepted version
#: is superseded only by a later acceptance. No backward moves, no
#: resurrection — a rejected or superseded version keeps its row
#: (durable rejection, retrievable predecessor) and never advances.
_ARTIFACT_VERSION_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"in_review"}),
    "in_review": frozenset({"accepted", "rejected"}),
    "accepted": frozenset({"superseded"}),
    "rejected": frozenset(),
    "superseded": frozenset(),
}

#: Steward D2 (§2.3): the tables erase_user_material covers and
#: erasure_recount counts. Thread-keyed tables have no user_id
#: column; they are counted (and orphan-swept) through
#: narrative_threads.
_ERASURE_THREAD_KEYED_TABLES: tuple[str, ...] = (
    "thread_evidence",
    "thread_readings",
    "thread_changes",
    "lens_fittings",
)
_ERASURE_USER_TABLES: tuple[str, ...] = (
    "thread_links",
    "involvement_measures",
    "steward_dismissals",
    "steward_deferred_prose",
    "steward_observables",
    "steward_signal_states",
    "steward_relevance_assessments",
    "steward_discrepancy_flags",
    "steward_review_verdicts",
    "steward_correspondences",
    "steward_correspondence_responses",
    "steward_oversight_proposals",
    "steward_reading_reconsiderations",
    "steward_artifacts",
    "steward_artifact_versions",
    # Steward D1 (packet §8.2 point 1, Q10 as ruled): the
    # candidate-mention family joins Scope S coverage WITH the
    # D1 landing — deletion here, the recount below (same tuple),
    # the §9.5 audit in eligibility.py, and the barrier triggers
    # in the schema block.
    "steward_candidate_mentions",
    "steward_candidate_sightings",
    "steward_candidate_membership",
    "steward_candidate_acts",
)

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
  created_at TEXT NOT NULL,
  reason TEXT,
  successor_thread_id TEXT,
  absence_window_days INTEGER,
  absence_last_evidence_at TEXT
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

-- Increment A: prose owed by records-first derivation. A deferred
-- row is written atomically WITH the thread/evidence rows it owes
-- prose for (see create_thread_with_deferred_prose /
-- attach_evidence_with_deferred_prose); the worker renders the
-- reading later and marks the row done in the same transaction as
-- the reading. evidence_texts_json carries the verbatim texts the
-- worker needs for its prompt: prompt inputs, not evidence rows —
-- deleted with the row on completion or thread deletion.
CREATE TABLE IF NOT EXISTS steward_deferred_prose (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  evidence_signature TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  evidence_texts_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_attempt_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE (user_id, thread_id, evidence_signature)
);
CREATE INDEX IF NOT EXISTS idx_deferred_user_status
  ON steward_deferred_prose (user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_deferred_thread
  ON steward_deferred_prose (thread_id, status);

-- Increment C: steward observables (facts about recorded rows).
-- No status, no author, no delivery fields by construction: a row
-- here is true while its fact holds and is deleted by recompute
-- when the fact stops holding. signal_key is the recompute
-- identity (scope + kind + identity fields), unique per user, so
-- an upsert preserves first_seen_at across passes. thread_id is
-- NULL for meeting-scoped rows (O1), which carry their meeting
-- identity in detail_json.
CREATE TABLE IF NOT EXISTS steward_observables (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  thread_id TEXT,
  kind TEXT NOT NULL,
  signal_key TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  detail_json TEXT NOT NULL DEFAULT '{}',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, signal_key)
);
CREATE INDEX IF NOT EXISTS idx_observables_user_thread
  ON steward_observables (user_id, thread_id, kind);
CREATE INDEX IF NOT EXISTS idx_observables_user_kind
  ON steward_observables (user_id, kind);

-- Increment A: per-user byte-offset read position into the
-- append-only activity log (see local_ai/narrative/sweep.py).
-- file_identity is "<st_dev>:<st_ino>"; a changed identity or a
-- file smaller than the stored offset invalidates the position
-- and forces a bounded full rescan.
CREATE TABLE IF NOT EXISTS steward_processing_position (
  user_id TEXT PRIMARY KEY,
  byte_offset INTEGER NOT NULL DEFAULT 0,
  file_identity TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

-- Increment D: delivery state for steward signals (the read
-- model's delivery axis, kept separate from verdict state).
-- signal_id is the reading id for readings, the observable
-- signal_key for observables (stable across recompute). Only
-- participating kinds ever get rows (steward/seat-authored
-- readings + observables); set_signal_delivery refuses the rest.
-- Rows for vanished signals are orphans: the read ignores them
-- (delivery state joins to existing signals only); thread
-- deletion cascades its signals' rows, and clear flows delete
-- directly-deleted readings'/observables' rows with them.
CREATE TABLE IF NOT EXISTS steward_signal_states (
  user_id TEXT NOT NULL,
  signal_kind TEXT NOT NULL,
  signal_id TEXT NOT NULL,
  delivery_status TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL DEFAULT 'visitor',
  PRIMARY KEY (user_id, signal_kind, signal_id)
);
CREATE INDEX IF NOT EXISTS idx_signal_states_user
  ON steward_signal_states (user_id, signal_kind);

-- Phase 1 (review wiring + branch contract): append-only coordination
-- records. Assessments are never updated (a fresh assessment
-- supersedes by recency); flags never adjudicate themselves;
-- verdicts are a log, not a mutable status. Additive only: old
-- databases gain these tables on open via CREATE TABLE IF NOT
-- EXISTS, and no existing table is altered.
CREATE TABLE IF NOT EXISTS steward_relevance_assessments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  branch_id TEXT NOT NULL,
  thread_id TEXT,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  relevant INTEGER NOT NULL DEFAULT 0,
  reasons_json TEXT NOT NULL DEFAULT '[]',
  inputs_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relevance_user_branch
  ON steward_relevance_assessments (user_id, branch_id, created_at);
CREATE TABLE IF NOT EXISTS steward_discrepancy_flags (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  assessment_id TEXT NOT NULL,
  branch_id TEXT NOT NULL,
  objection TEXT NOT NULL DEFAULT '',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flags_user_assessment
  ON steward_discrepancy_flags (user_id, assessment_id, created_at);
CREATE TABLE IF NOT EXISTS steward_review_verdicts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  item_kind TEXT NOT NULL,
  item_id TEXT NOT NULL,
  verdict TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verdicts_user_kind
  ON steward_review_verdicts (user_id, item_kind, created_at);

-- Phase 6 (diffusion schedule, literal): steward artifacts and
-- their versions. Versions are append-only: a rewrite inserts a
-- new row, never updates a predecessor, so every draft stays
-- retrievable. Content is the WHOLE draft at that version, never
-- a patch. Evidence is cited by thread_evidence row id only —
-- this module never writes evidence rows, so Tier-E records are
-- immutable by construction. Additive only: old databases gain
-- these tables on open via CREATE TABLE IF NOT EXISTS.
CREATE TABLE IF NOT EXISTS steward_artifacts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_user_thread
  ON steward_artifacts (user_id, thread_id, created_at);
CREATE TABLE IF NOT EXISTS steward_artifact_versions (
  id TEXT PRIMARY KEY,
  artifact_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  version_no INTEGER NOT NULL,
  content_json TEXT NOT NULL DEFAULT '{}',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  reading_ids_json TEXT NOT NULL DEFAULT '[]',
  lens_id TEXT,
  status TEXT NOT NULL DEFAULT 'proposed',
  user_authored_units REAL NOT NULL DEFAULT 0,
  user_edited_units REAL NOT NULL DEFAULT 0,
  synthesized_units REAL NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT 'steward',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifact_versions_artifact
  ON steward_artifact_versions (artifact_id, version_no);

-- Phase 7 (layer completion + rollout): correspondences,
-- oversight proposals, and reading reconsiderations. Additive
-- only: old databases gain these tables on open via CREATE
-- TABLE IF NOT EXISTS, and no existing table is altered.
-- Correspondences are NEVER evidence: their ids carry the
-- "corr-" prefix and no code path writes them into
-- thread_evidence; readings can only cite thread_evidence row
-- ids (audit invariant 1), so a correspondence can never be
-- cited as a fourth observation.
CREATE TABLE IF NOT EXISTS steward_correspondences (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  thread_ids_json TEXT NOT NULL DEFAULT '[]',
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  structural_tension TEXT NOT NULL DEFAULT '',
  proposed_relationship TEXT NOT NULL DEFAULT '',
  candidate_metaphor TEXT,
  mapping_json TEXT NOT NULL DEFAULT '{}',
  limitations TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'proposed',
  supersedes_id TEXT,
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_correspondences_user
  ON steward_correspondences (user_id, created_at);
CREATE TABLE IF NOT EXISTS steward_correspondence_responses (
  id TEXT PRIMARY KEY,
  correspondence_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  branch_id TEXT NOT NULL,
  response TEXT NOT NULL,
  expression TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (correspondence_id, branch_id)
);
CREATE INDEX IF NOT EXISTS idx_corr_responses_corr
  ON steward_correspondence_responses (correspondence_id, branch_id);
CREATE TABLE IF NOT EXISTS steward_oversight_proposals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  detail_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_oversight_user_thread
  ON steward_oversight_proposals (user_id, thread_id, created_at);
CREATE TABLE IF NOT EXISTS steward_reading_reconsiderations (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  reading_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'proposed',
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reconsiderations_reading
  ON steward_reading_reconsiderations (user_id, reading_id, created_at);

-- Steward D2 erasure (packet §§8.4/9.2, as reconciled through Rev 4):
-- the persistent rollback barrier. The tombstone is the operation's
-- content-free residue in this store: user id, the boundary T, the
-- operation id, and (filled in at completion) the same counts the
-- receipt carries — never content, never content identifiers.
-- The manifest is transaction-local eligibility attestation: rows
-- are written by a derivation funnel method inside its own write
-- transaction, from the admitted set that run's eligibility
-- evaluation produced, and deleted again before that transaction
-- commits — a manifest row never persists, is never visible to
-- another connection, and can never be borrowed by a later write.
-- The triggers below are the enforcement: while a tombstone stands
-- for a user, a derivation write to a covered table lands only
-- when its named dependencies were attested, in this same
-- transaction, by a manifest entry whose source_time is strictly
-- after the tombstone's erased_at. Rejection is RAISE(ABORT),
-- which surfaces as sqlite3.IntegrityError with
-- sqlite_errorname == 'SQLITE_CONSTRAINT_TRIGGER' and the message
-- 'steward erasure barrier'.
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

-- Evidence rows bind per record: the (ref_kind, ref_id) being
-- attached must itself be manifested with source_time > T. The
-- user is resolved through the owning thread (this table has no
-- user_id column).
CREATE TRIGGER IF NOT EXISTS trg_erasure_evidence_insert
BEFORE INSERT ON thread_evidence
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = (
      SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
    )
  )
  AND NOT EXISTS (
    SELECT 1 FROM steward_erasure_manifest m
    JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
    WHERE m.user_id = (
      SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
    )
      AND m.erased_at_seen = tb.erased_at
      AND m.source_kind = NEW.ref_kind
      AND m.source_id = NEW.ref_id
      AND m.source_time > tb.erased_at
  );
END;

-- Thread births bind compositionally: the outer gate is at least
-- one manifest entry for (user, T) in this transaction; the
-- founding evidence rows are bound per record by the evidence
-- trigger above, inside the same birth transaction.
CREATE TRIGGER IF NOT EXISTS trg_erasure_thread_insert
BEFORE INSERT ON narrative_threads
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
  );
END;

-- Readings bind through their cited evidence: every cited
-- thread_evidence row id must join to a manifested (ref_kind,
-- ref_id); a dangling id fails closed (the join finds nothing).
CREATE TRIGGER IF NOT EXISTS trg_erasure_reading_insert
BEFORE INSERT ON thread_readings
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = (
      SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
    )
  )
  AND EXISTS (
    SELECT 1 FROM json_each(NEW.evidence_refs_json) je
    WHERE NOT EXISTS (
      SELECT 1 FROM thread_evidence te
      JOIN steward_erasure_manifest m
        ON m.source_kind = te.ref_kind AND m.source_id = te.ref_id
      JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
      WHERE te.id = je.value
        AND m.user_id = (
          SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
        )
        AND m.erased_at_seen = tb.erased_at
        AND m.source_time > tb.erased_at
    )
  );
END;

-- Changes bind per family. (a) Evidence-citing changes: every
-- cited row id joins through thread_evidence to a manifested
-- source, exactly as readings. (b) Outgrown (absence) changes:
-- every thread_evidence row whose created_at equals the change's
-- absence_last_evidence_at must be manifested. (c) Reinterpreted
-- changes: a manifested successor-thread dependency entry, and
-- the successor must be a standing thread of the same user.
CREATE TRIGGER IF NOT EXISTS trg_erasure_change_insert
BEFORE INSERT ON thread_changes
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = (
      SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
    )
  )
  AND EXISTS (
    SELECT 1 FROM json_each(NEW.evidence_refs_json) je
    WHERE NOT EXISTS (
      SELECT 1 FROM thread_evidence te
      JOIN steward_erasure_manifest m
        ON m.source_kind = te.ref_kind AND m.source_id = te.ref_id
      JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
      WHERE te.id = je.value
        AND m.user_id = (
          SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
        )
        AND m.erased_at_seen = tb.erased_at
        AND m.source_time > tb.erased_at
    )
  );
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = (
      SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
    )
  )
  AND NEW.reason = 'outgrown'
  AND EXISTS (
    SELECT 1 FROM thread_evidence te
    WHERE te.thread_id = NEW.thread_id
      AND te.created_at = NEW.absence_last_evidence_at
      AND NOT EXISTS (
        SELECT 1 FROM steward_erasure_manifest m
        JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
        WHERE m.user_id = (
          SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
        )
          AND m.erased_at_seen = tb.erased_at
          AND m.source_kind = te.ref_kind
          AND m.source_id = te.ref_id
          AND m.source_time > tb.erased_at
      )
  );
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = (
      SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
    )
  )
  AND NEW.reason = 'reinterpreted'
  AND (
    NOT EXISTS (
      SELECT 1 FROM steward_erasure_manifest m
      JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
      WHERE m.user_id = (
        SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
      )
        AND m.erased_at_seen = tb.erased_at
        AND m.source_kind = 'thread'
        AND m.source_id = NEW.successor_thread_id
        AND m.source_time > tb.erased_at
    )
    OR NOT EXISTS (
      SELECT 1 FROM narrative_threads succ
      WHERE succ.id = NEW.successor_thread_id
        AND succ.user_id = (
          SELECT user_id FROM narrative_threads WHERE id = NEW.thread_id
        )
    )
  );
END;

-- Deferred-prose rows bind every ref they owe prose for: each
-- "kind:ref_id" element of evidence_refs_json must be manifested.
CREATE TRIGGER IF NOT EXISTS trg_erasure_deferred_insert
BEFORE INSERT ON steward_deferred_prose
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = NEW.user_id
  )
  AND EXISTS (
    SELECT 1 FROM json_each(NEW.evidence_refs_json) je
    WHERE NOT EXISTS (
      SELECT 1 FROM steward_erasure_manifest m
      JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
      WHERE m.user_id = NEW.user_id
        AND m.erased_at_seen = tb.erased_at
        AND m.source_kind = substr(je.value, 1, instr(je.value, ':') - 1)
        AND m.source_id = substr(je.value, instr(je.value, ':') + 1)
        AND m.source_time > tb.erased_at
    )
  );
END;

-- Observables bind their cited ids: each must resolve through a
-- manifested thread_evidence row of this user's threads, or to a
-- manifested thread dependency entry. Meeting-scoped rows
-- (thread_id IS NULL) additionally require the manifested meeting
-- dependency named by detail_json.meeting_key. Claims are never
-- manifested, so a claim-citing observable aborts mechanically.
CREATE TRIGGER IF NOT EXISTS trg_erasure_observable_insert
BEFORE INSERT ON steward_observables
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = NEW.user_id
  )
  AND (
    EXISTS (
      SELECT 1 FROM json_each(NEW.evidence_refs_json) je
      WHERE NOT (
        NEW.thread_id IS NULL
        AND je.value = json_extract(NEW.detail_json, '$.meeting_key')
      )
      AND NOT EXISTS (
        SELECT 1 FROM steward_erasure_manifest m
        JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
        WHERE m.user_id = NEW.user_id
          AND m.erased_at_seen = tb.erased_at
          AND m.source_time > tb.erased_at
          AND (
            (m.source_kind = 'thread' AND m.source_id = je.value)
            OR EXISTS (
              SELECT 1 FROM thread_evidence te
              WHERE te.id = je.value
                AND te.ref_kind = m.source_kind
                AND te.ref_id = m.source_id
                AND te.thread_id IN (
                  SELECT id FROM narrative_threads
                  WHERE user_id = NEW.user_id
                )
            )
          )
      )
    )
    OR (
      NEW.thread_id IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM steward_erasure_manifest m
        JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
        WHERE m.user_id = NEW.user_id
          AND m.erased_at_seen = tb.erased_at
          AND m.source_kind = 'meeting'
          AND m.source_id = json_extract(NEW.detail_json, '$.meeting_key')
          AND m.source_time > tb.erased_at
      )
    )
  );
END;

-- The recompute sync refreshes surviving rows in place; the same
-- binding applies to the refreshed row (BEFORE UPDATE).
CREATE TRIGGER IF NOT EXISTS trg_erasure_observable_update
BEFORE UPDATE ON steward_observables
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = NEW.user_id
  )
  AND (
    EXISTS (
      SELECT 1 FROM json_each(NEW.evidence_refs_json) je
      WHERE NOT (
        NEW.thread_id IS NULL
        AND je.value = json_extract(NEW.detail_json, '$.meeting_key')
      )
      AND NOT EXISTS (
        SELECT 1 FROM steward_erasure_manifest m
        JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
        WHERE m.user_id = NEW.user_id
          AND m.erased_at_seen = tb.erased_at
          AND m.source_time > tb.erased_at
          AND (
            (m.source_kind = 'thread' AND m.source_id = je.value)
            OR EXISTS (
              SELECT 1 FROM thread_evidence te
              WHERE te.id = je.value
                AND te.ref_kind = m.source_kind
                AND te.ref_id = m.source_id
                AND te.thread_id IN (
                  SELECT id FROM narrative_threads
                  WHERE user_id = NEW.user_id
                )
            )
          )
      )
    )
    OR (
      NEW.thread_id IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM steward_erasure_manifest m
        JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
        WHERE m.user_id = NEW.user_id
          AND m.erased_at_seen = tb.erased_at
          AND m.source_kind = 'meeting'
          AND m.source_id = json_extract(NEW.detail_json, '$.meeting_key')
          AND m.source_time > tb.erased_at
      )
    )
  );
END;

-- Steward D1 candidate mentions (packet Rev 1 §§3/4): the
-- registry's table family, inside this store under its existing
-- schema discipline. A candidate is an attributed recurrence of
-- the visitor's own words — never a person, identity hypothesis,
-- relationship assertion, or automatically promotable record.
-- The never-contain list (packet §3.3) is structural here: there
-- is no column for a resolved identity (except the post-act
-- citation promoted_person_ref), no relationship field, no
-- inferred attribute, no sameness link, and no confidence score.
-- user_id is NOT NULL on every table — the sighting's is
-- denormalized deliberately (D2 §9.2's correction).
CREATE TABLE IF NOT EXISTS steward_candidate_mentions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  surface_form TEXT NOT NULL,
  normalized_form TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'candidate',
  ask_state TEXT NOT NULL DEFAULT 'not_asked',
  mention_count INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT NOT NULL DEFAULT '',
  last_seen_at TEXT NOT NULL DEFAULT '',
  promoted_person_ref TEXT,
  promotion_intent_json TEXT NOT NULL DEFAULT '{}',
  user_label TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_mentions_user_form
  ON steward_candidate_mentions (user_id, normalized_form);
CREATE TABLE IF NOT EXISTS steward_candidate_sightings (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  ref_kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  normalized_form TEXT NOT NULL,
  surface_form TEXT NOT NULL,
  conversation_id TEXT NOT NULL DEFAULT '',
  seen_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (user_id, ref_kind, ref_id, normalized_form)
);
CREATE INDEX IF NOT EXISTS idx_candidate_sightings_user_form
  ON steward_candidate_sightings (user_id, normalized_form);
CREATE TABLE IF NOT EXISTS steward_candidate_membership (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  sighting_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  assigned_by TEXT NOT NULL DEFAULT 'capture',
  act_id TEXT,
  created_at TEXT NOT NULL,
  superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidate_membership_sighting
  ON steward_candidate_membership (sighting_id, superseded_at);
CREATE INDEX IF NOT EXISTS idx_candidate_membership_candidate
  ON steward_candidate_membership (candidate_id, superseded_at);
CREATE TABLE IF NOT EXISTS steward_candidate_acts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_acts_user
  ON steward_candidate_acts (user_id, created_at);

-- D1 joins the D2 barrier (packet §8.2 point 2): while a
-- tombstone stands, candidate-family derivation writes bind per
-- record exactly as thread_evidence does — the sighting cites
-- its source event on its face, so its insert requires a
-- manifest entry for that (ref_kind, ref_id) with source_time
-- strictly after the boundary; a membership link binds through
-- its sighting's cited source the same way; a candidate birth
-- binds compositionally, like a thread birth (at least one
-- manifest entry for (user, T) in this transaction — the
-- founding sighting's per-record binding does the real work).
-- Candidate UPDATEs (counts, timestamps) carry no source-derived
-- content and are not trigger-bound, as with observables'
-- non-content updates. Acts rows are user-act records, not
-- derivation writes, and have no trigger.
CREATE TRIGGER IF NOT EXISTS trg_erasure_sighting_insert
BEFORE INSERT ON steward_candidate_sightings
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
      AND m.source_kind = NEW.ref_kind
      AND m.source_id = NEW.ref_id
      AND m.source_time > tb.erased_at
  );
END;
CREATE TRIGGER IF NOT EXISTS trg_erasure_membership_insert
BEFORE INSERT ON steward_candidate_membership
BEGIN
  SELECT RAISE(ABORT, 'steward erasure barrier')
  WHERE EXISTS (
    SELECT 1 FROM steward_erasure_tombstones tb
    WHERE tb.user_id = NEW.user_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM steward_candidate_sightings s
    JOIN steward_erasure_manifest m
      ON m.source_kind = s.ref_kind AND m.source_id = s.ref_id
    JOIN steward_erasure_tombstones tb ON tb.user_id = m.user_id
    WHERE s.id = NEW.sighting_id
      AND m.user_id = NEW.user_id
      AND m.erased_at_seen = tb.erased_at
      AND m.source_time > tb.erased_at
  );
END;
CREATE TRIGGER IF NOT EXISTS trg_erasure_candidate_insert
BEFORE INSERT ON steward_candidate_mentions
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
  );
END;
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:24]}"


class ErasureBarrierRefusal(ValueError):
    """A derivation funnel refused a write under the erasure barrier.

    Raised when an erasure tombstone stands for the user and the
    write carries no eligibility manifest, or a manifest missing a
    dependency the write names (packet §9.2). A ValueError subclass
    so the derivation paths' existing store-refusal handling treats
    it as a decline; the SQLite trigger backstop raises
    sqlite3.IntegrityError ('steward erasure barrier') instead —
    the two signals are distinct by design (test 21).
    """


@contextmanager
def _atomic(conn: sqlite3.Connection) -> Iterator[None]:
    """Commit on clean exit, roll back on any failure.

    Used by the D2-plumbed funnel methods: an aborted write (in
    particular a trigger RAISE(ABORT)) must leave nothing behind —
    no partial rows and no manifest rows (packet §9.2: a manifest
    never commits). The store's documented atomicity for combined
    writes ("records + deferred row land together, or neither
    does") is what this implements.

    Gate B Increment 1: the commit/rollback resolve through the
    connection's boundary participation state (four-gap §1(c)).
    With no boundary standing they reach SQLite exactly as before;
    under a standing boundary the commit is suppressed (the
    boundary owner commits at its exit) and a rollback marks the
    boundary rollback-only instead of rolling back mid-step.
    """
    state = boundary_state_for(conn)
    try:
        yield
    except Exception:
        if state is not None:
            state.rollback(conn)
        else:
            conn.rollback()
        raise
    else:
        if state is not None:
            state.commit(conn)
        else:
            conn.commit()


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
        reason=row["reason"] if "reason" in row.keys() else None,
        successor_thread_id=(
            row["successor_thread_id"]
            if "successor_thread_id" in row.keys()
            else None
        ),
        absence_window_days=(
            row["absence_window_days"]
            if "absence_window_days" in row.keys()
            else None
        ),
        absence_last_evidence_at=(
            row["absence_last_evidence_at"]
            if "absence_last_evidence_at" in row.keys()
            else None
        ),
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


def _row_to_observable(row: sqlite3.Row) -> StewardObservable:
    return StewardObservable(
        id=row["id"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        kind=row["kind"],
        signal_key=row["signal_key"],
        evidence_refs=_loads(row["evidence_refs_json"], []),
        detail=_loads(row["detail_json"], {}),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        created_at=row["created_at"],
    )


def _row_to_dismissal(row: sqlite3.Row) -> StewardDismissal:
    return StewardDismissal(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        signature=row["signature"],
        created_at=row["created_at"],
    )


def _row_to_candidate(row: sqlite3.Row) -> CandidateMention:
    return CandidateMention(
        id=row["id"],
        user_id=row["user_id"],
        surface_form=row["surface_form"],
        normalized_form=row["normalized_form"],
        status=row["status"],
        ask_state=row["ask_state"],
        mention_count=row["mention_count"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        promoted_person_ref=row["promoted_person_ref"],
        promotion_intent=_loads(row["promotion_intent_json"], {}),
        user_label=row["user_label"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_sighting(row: sqlite3.Row) -> CandidateSighting:
    return CandidateSighting(
        id=row["id"],
        user_id=row["user_id"],
        ref_kind=row["ref_kind"],
        ref_id=row["ref_id"],
        normalized_form=row["normalized_form"],
        surface_form=row["surface_form"],
        conversation_id=row["conversation_id"],
        seen_at=row["seen_at"],
        created_at=row["created_at"],
    )


def _row_to_membership(row: sqlite3.Row) -> CandidateMembership:
    return CandidateMembership(
        id=row["id"],
        user_id=row["user_id"],
        sighting_id=row["sighting_id"],
        candidate_id=row["candidate_id"],
        assigned_by=row["assigned_by"],
        act_id=row["act_id"],
        created_at=row["created_at"],
        superseded_at=row["superseded_at"],
    )


def _row_to_candidate_act(row: sqlite3.Row) -> CandidateAct:
    return CandidateAct(
        id=row["id"],
        user_id=row["user_id"],
        kind=row["kind"],
        detail=_loads(row["detail_json"], {}),
        created_at=row["created_at"],
    )


def _row_to_artifact(row: sqlite3.Row) -> StewardArtifact:
    return StewardArtifact(
        id=row["id"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_artifact_version(row: sqlite3.Row) -> ArtifactVersion:
    return ArtifactVersion(
        id=row["id"],
        artifact_id=row["artifact_id"],
        user_id=row["user_id"],
        version_no=int(row["version_no"]),
        content=_loads(row["content_json"], {}),
        evidence_refs=_loads(row["evidence_refs_json"], []),
        reading_ids=_loads(row["reading_ids_json"], []),
        lens_id=row["lens_id"],
        status=row["status"],
        user_authored_units=float(row["user_authored_units"]),
        user_edited_units=float(row["user_edited_units"]),
        synthesized_units=float(row["synthesized_units"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


#: Increment D delivery lifecycle (proposal §3.7). Verdict state
#: lives on readings; delivery state lives here, never the twain
#: confused. ``not_applicable`` is not a stored value: it is what
#: the read model reports for kinds that do not participate.
DELIVERY_STATUSES: tuple[str, ...] = (
    "pending",
    "surfaced",
    "discussed",
    "dismissed",
)

#: Allowed delivery transitions (proposal §3.7). Same-state sets
#: are no-ops (idempotent re-mark). No transition out of
#: ``dismissed``; no backward transitions.
_DELIVERY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending": ("surfaced", "discussed", "dismissed"),
    "surfaced": ("discussed", "dismissed"),
    "discussed": ("dismissed",),
    "dismissed": (),
}

#: Card endorsement annotations (Story-First Phase 1A). An
#: endorsement is an ANNOTATION in the verdict log, never a
#: verdict: its rows carry this kind discriminator so no verdict
#: consumer (proposal precision, rollout coverage, the review
#: queue) can mistake one for a proposal verdict, and its stance
#: vocabulary is its own — endorsement is the visitor's stance
#: toward one reading version, with no state transition attached.
CARD_ENDORSEMENT_KIND = "card_endorsement"
CARD_ENDORSEMENT_STANCES: tuple[str, ...] = (
    "endorsed",
    "rejected",
    "unresolved",
)


def _decode_card_endorsement(raw: str | None) -> tuple[str, str]:
    """Decode a card-endorsement verdict-column value.

    The verdict log's row shape has no note column and Phase 1A
    adds no schema, so this kind stores a compact JSON object
    ``{"stance": ..., "note": ...}`` in the verdict column. A
    bare stance word is also accepted on read, for robustness.
    """
    text = (raw or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text, ""
        if isinstance(data, dict):
            return (
                str(data.get("stance") or ""),
                str(data.get("note") or ""),
            )
    return text, ""


class NarrativeStore:
    """SQLite-backed store for narrative threads and their records."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Gate B Increment 1: the boundary participation state
        # (four-gap §1(c)). The flow-invoked commit/rollback sites
        # route through it; with no boundary standing it passes
        # through, so non-flow behavior is untouched.
        self.boundary_state = BoundaryState("narrative")
        register_boundary_state(self._conn, self.boundary_state)
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # Steward D2: the erasure triggers parse JSON ref lists
            # with json_each/json_extract (packet §9.2). JSON1 is
            # part of this runtime's SQLite build (3.45.1); its
            # absence is build-blocking, never a silent degradation
            # of the barrier.
            try:
                self._conn.execute(
                    "SELECT json_extract('{\"a\": 1}', '$.a')"
                ).fetchone()
                self._conn.execute(
                    "SELECT value FROM json_each('[1]')"
                ).fetchall()
            except sqlite3.Error as exc:
                raise RuntimeError(
                    "SQLite JSON1 functions (json_each/json_extract) "
                    "are required by the steward erasure barrier and "
                    "are unavailable in this build"
                ) from exc
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
            # Increment B migration: databases created before B have
            # no suppression-provenance columns on the deferred-prose
            # table (CREATE TABLE IF NOT EXISTS does not add them).
            # Additive only; NULL reads back as "not suppressed" for
            # older rows. The suppressed row keeps its scope + key
            # on the row itself (Joshua's ruling: keep the why on
            # the note), never only in a run report.
            dfp_columns = {
                row[1]
                for row in self._conn.execute(
                    "PRAGMA table_info(steward_deferred_prose)"
                ).fetchall()
            }
            if "suppressed_scope" not in dfp_columns:
                self._conn.execute(
                    "ALTER TABLE steward_deferred_prose "
                    "ADD COLUMN suppressed_scope TEXT"
                )
            if "suppressed_key" not in dfp_columns:
                self._conn.execute(
                    "ALTER TABLE steward_deferred_prose "
                    "ADD COLUMN suppressed_key TEXT"
                )
            # Phase 3 migration: databases created before Phase 3
            # have no retirement/absence columns on thread_changes
            # (CREATE TABLE IF NOT EXISTS does not add them).
            # Additive only; NULL reads back as "no retirement
            # basis recorded" for older rows (no retired changes
            # could exist before Phase 3: no caller recorded them).
            chg_columns = {
                row[1]
                for row in self._conn.execute(
                    "PRAGMA table_info(thread_changes)"
                ).fetchall()
            }
            for _col, _type in (
                ("reason", "TEXT"),
                ("successor_thread_id", "TEXT"),
                ("absence_window_days", "INTEGER"),
                ("absence_last_evidence_at", "TEXT"),
            ):
                if _col not in chg_columns:
                    self._conn.execute(
                        f"ALTER TABLE thread_changes "
                        f"ADD COLUMN {_col} {_type}"
                    )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            unregister_boundary_state(self._conn)
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

    # -- erasure barrier plumbing (Steward D2, packet §9.2) ----------------
    #
    # A derivation funnel method that writes covered tables calls
    # _manifest_begin_locked at the top of its transaction and
    # _manifest_end_locked just before its commit. When no tombstone
    # stands for the user both are no-ops and the method behaves
    # exactly as it did before D2. When a tombstone stands, the
    # caller must pass the admitted set its eligibility evaluation
    # produced for THIS call's writes; the rows are written into
    # steward_erasure_manifest inside the transaction (where the
    # §9.2 triggers can see them), and deleted again before commit —
    # a manifest never persists and cannot be borrowed by another
    # transaction (test 21). Any failure rolls the whole transaction
    # back, manifest included.

    def _erasure_tombstone_locked(self, user_id: str) -> dict | None:
        """The user's erasure tombstone row, or None. Lock held."""
        row = self._conn.execute(
            "SELECT user_id, erased_at, operation_id, counts_json, "
            "created_at FROM steward_erasure_tombstones WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def _manifest_begin_locked(
        self,
        user_id: str,
        admitted_sources: Iterable[tuple[str, str, str]] | None,
    ) -> str | None:
        """Open this transaction's eligibility manifest.

        Returns the manifest run id, or None when no tombstone
        stands (barrier inert). Raises ErasureBarrierRefusal when a
        tombstone stands and no admitted set was supplied — a
        derivation write for an erased user without a contemporane-
        ous eligibility evaluation is refused at the funnel, before
        any row is written (the triggers are the backstop, not the
        first line).
        """
        tombstone = self._erasure_tombstone_locked(user_id)
        if tombstone is None:
            return None
        if admitted_sources is None:
            raise ErasureBarrierRefusal(
                "steward erasure barrier: derivation write for user "
                f"{user_id!r} refused — an erasure tombstone stands "
                f"(erased_at {tombstone['erased_at']}) and the write "
                "carries no eligibility manifest"
            )
        run_id = _new_id("mrun")
        for kind, ref_id, source_time in admitted_sources:
            self._conn.execute(
                "INSERT INTO steward_erasure_manifest (run_id, "
                "user_id, erased_at_seen, source_kind, source_id, "
                "source_time) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id, user_id, tombstone["erased_at"],
                    str(kind), str(ref_id), str(source_time),
                ),
            )
        return run_id

    def _manifest_end_locked(self, run_id: str | None) -> None:
        """Delete this transaction's manifest rows (pre-commit)."""
        if run_id is not None:
            self._conn.execute(
                "DELETE FROM steward_erasure_manifest WHERE run_id = ?",
                (run_id,),
            )

    def _manifest_require_locked(
        self,
        run_id: str | None,
        user_id: str,
        required: Iterable[tuple[str, str]],
    ) -> None:
        """Funnel-level binding check (packet §9.2): every required
        (source_kind, source_id) must be present in this
        transaction's manifest. No-op when the barrier is inert.
        The triggers re-verify at insert time; this check exists so
        the refusal names the missing dependency, and so bindings
        the triggers cannot express (e.g. the deferred-prose row's
        own manifest entry at completion) are enforced here."""
        if run_id is None:
            return
        present = {
            (row["source_kind"], row["source_id"])
            for row in self._conn.execute(
                "SELECT source_kind, source_id FROM "
                "steward_erasure_manifest WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        }
        missing = [
            f"{kind}:{ref_id}"
            for kind, ref_id in required
            if (kind, ref_id) not in present
        ]
        if missing:
            raise ErasureBarrierRefusal(
                "steward erasure barrier: derivation write for user "
                f"{user_id!r} refused — dependencies not attested by "
                "this run's eligibility evaluation: "
                + ", ".join(sorted(missing))
            )

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
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> NarrativeThread:
        """Create a thread and attach its founding evidence.

        ``scope`` is Part IX's optional broad label — stored when
        given, NULL when not; the store never requires one.
        ``progression`` is Part X's optional thread-local position:
        None (the default) records no local progression; a given
        position passes the same lens-binding validation readings
        use. Founding evidence passes the same tier gate as all
        evidence.

        ``admitted_sources`` is the Steward D2 eligibility manifest
        for this write (packet §9.2): (source_kind, source_id,
        source_time) triples attested by the caller's eligibility
        evaluation. It is consulted only when an erasure tombstone
        stands for the user; then every founding SourceRef must be
        attested, and a birth with no attested founding evidence is
        refused (see _manifest_begin_locked).
        """
        if origin not in THREAD_ORIGINS:
            raise ValueError(f"unknown thread origin: {origin!r}")
        weights = _validate_strand_weights(strand_weights)
        cast_rows = _validate_cast(cast)
        local_pos = (
            None if progression is None else _validate_progression(progression)
        )
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
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
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            if run_id is not None:
                if not admitted:
                    raise ErasureBarrierRefusal(
                        "steward erasure barrier: thread birth for "
                        f"user {user_id!r} refused — no attested "
                        "founding evidence under the erasure barrier"
                    )
                self._manifest_require_locked(
                    run_id,
                    user_id,
                    [
                        (ref.kind, ref.ref_id)
                        for ref in evidence_refs
                        if isinstance(ref, SourceRef)
                    ],
                )
            self._write_thread_rows(thread, local_pos, weights, cast_rows,
                                    evidence_refs, None, now)
            self._manifest_end_locked(run_id)
            row = self._conn.execute(
                "SELECT * FROM narrative_threads WHERE id = ?",
                (thread.id,),
            ).fetchone()
        return _row_to_thread(row)

    def _write_thread_rows(
        self,
        thread: NarrativeThread,
        local_pos,
        weights: dict,
        cast_rows: list,
        evidence_refs: Iterable[SourceRef | str],
        deferred: dict | None,
        now: str,
    ) -> None:
        """Insert a thread row + founding evidence (+ deferred row).

        Caller holds the lock; this does NOT commit, so callers can
        bundle the thread, its evidence, and a deferred-prose row
        into one atomic commit (increment A §7: records + deferred
        row must land together, or neither does). ``deferred`` is
        None for a plain birth, else a dict with kind,
        evidence_signature, evidence_refs (keys), evidence_texts.
        """
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
        if deferred is not None:
            self._insert_deferred_prose_locked(
                thread.user_id,
                thread.id,
                deferred["kind"],
                deferred["evidence_signature"],
                deferred["evidence_refs"],
                deferred["evidence_texts"],
            )

    def create_thread_with_deferred_prose(
        self,
        user_id: str,
        *,
        origin: str = "steward_proposal",
        title: str = "Untitled thread",
        evidence_refs: Iterable[SourceRef | str] = (),
        deferred_kind: str,
        evidence_signature: str,
        evidence_texts: list[dict] | None = None,
        strand_weights: dict | None = None,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> NarrativeThread:
        """Records-first birth (increment A §6): create a nascent
        thread, attach its founding evidence, and record the owed
        prose — all in ONE commit. The title is a working title:
        with no generation to propose one, the thread is born
        untitled and the deferred worker proposes a reading, not a
        retitle (retitling on prose completion is later work).
        ``evidence_texts`` are the verbatim texts the worker needs
        for its prompt (prompt inputs, not evidence rows).
        ``strand_weights`` is the founding cluster's aggregate
        (strand-key-keyed); None (the default) births the thread
        weightless, as before.
        """
        if origin not in THREAD_ORIGINS:
            raise ValueError(f"unknown thread origin: {origin!r}")
        if deferred_kind not in ("birth", "extension"):
            raise ValueError(f"unknown deferred kind: {deferred_kind!r}")
        weights = _validate_strand_weights(strand_weights)
        cast_rows = _validate_cast(None)
        now = _utcnow()
        thread = NarrativeThread(
            id=_new_id("thr"),
            user_id=user_id,
            title=title,
            status="nascent",
            scope=None,
            progression=None,
            strand_weights=weights,
            cast=cast_rows,
            aspiration_refs=[],
            origin=origin,
            created_at=now,
            updated_at=now,
        )
        evidence_refs = list(evidence_refs or ())
        evidence_keys = [
            f"{ref.kind}:{ref.ref_id}" if isinstance(ref, SourceRef) else str(ref)
            for ref in evidence_refs
        ]
        deferred = {
            "kind": deferred_kind,
            "evidence_signature": evidence_signature,
            "evidence_refs": evidence_keys,
            "evidence_texts": evidence_texts or [],
        }
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            if run_id is not None:
                if not admitted:
                    raise ErasureBarrierRefusal(
                        "steward erasure barrier: thread birth for "
                        f"user {user_id!r} refused — no attested "
                        "founding evidence under the erasure barrier"
                    )
                self._manifest_require_locked(
                    run_id,
                    user_id,
                    [
                        (ref.kind, ref.ref_id)
                        for ref in evidence_refs
                        if isinstance(ref, SourceRef)
                    ],
                )
            self._write_thread_rows(thread, None, weights, cast_rows,
                                    evidence_refs, deferred, now)
            self._manifest_end_locked(run_id)
            row = self._conn.execute(
                "SELECT * FROM narrative_threads WHERE id = ?",
                (thread.id,),
            ).fetchone()
        return _row_to_thread(row)

    def attach_evidence_with_deferred_prose(
        self,
        user_id: str,
        thread_id: str,
        evidence_refs: Iterable[SourceRef],
        *,
        deferred_kind: str = "extension",
        evidence_signature: str,
        evidence_texts: list[dict] | None = None,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> tuple[list[str], str]:
        """Records-first extension (increment A §6): attach new
        evidence to a live thread and record the owed prose — one
        commit. Returns (resolved evidence row ids, deferred row
        id). Dedup: if a deferred row already exists for this
        (user, thread, signature), no second row is created and the
        existing id is returned. The thread's updated_at is touched
        so the ignored-retention clock tracks last activity.
        """
        if deferred_kind not in ("birth", "extension"):
            raise ValueError(f"unknown deferred kind: {deferred_kind!r}")
        evidence_refs = list(evidence_refs)
        evidence_keys = [f"{ref.kind}:{ref.ref_id}" for ref in evidence_refs]
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            if run_id is not None:
                self._manifest_require_locked(
                    run_id,
                    user_id,
                    [(ref.kind, ref.ref_id) for ref in evidence_refs],
                )
            self._require_thread(user_id, thread_id)
            resolved, _ = self._attach_evidence(thread_id, evidence_refs)
            deferred_id = self._insert_deferred_prose_locked(
                user_id,
                thread_id,
                deferred_kind,
                evidence_signature,
                evidence_keys,
                evidence_texts or [],
            )
            self._touch_thread(thread_id)
            self._manifest_end_locked(run_id)
        return resolved, deferred_id

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
        limit: int | None = 100,
    ) -> list[NarrativeThread]:
        """The user's threads, oldest first. ``seat`` filters by cast
        standing (a seat in the thread's cast), in Python — thread
        counts per user are small and cast is JSON by design.
        ``limit=None`` is the explicit unbounded path (increment C's
        state scan uses it): the scan must never silently cap at
        100 threads, which would be a correctness bug, not a
        performance tradeoff."""
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
        return threads if limit is None else threads[:limit]

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

    def set_thread_strand_weights(
        self, user_id: str, thread_id: str, weights: dict | None
    ) -> NarrativeThread:
        """Replace a thread's strand weights with a recomputed aggregate.

        Used by derivation's extension path (founder ruling Q3): when
        new evidence extends a live thread, the thread's weights are
        recomputed from all attached evidence and written here. The
        value passes _validate_strand_weights — strand keys only,
        unknown keys refused. Passing None clears the weights back
        to {} (a thread with no weighed evidence is weightless,
        never invented).
        """
        validated = _validate_strand_weights(weights)
        with self._lock:
            self._require_thread(user_id, thread_id)
            self._conn.execute(
                "UPDATE narrative_threads SET strand_weights_json = ?, "
                "updated_at = ? WHERE id = ? AND user_id = ?",
                (
                    json.dumps(validated, ensure_ascii=False),
                    _utcnow(),
                    thread_id,
                    user_id,
                ),
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
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> ThreadEvidence:
        """Attach one evidence-tier record to a thread (deduped).

        The tier gate lives in _attach_evidence: offering a
        dramatization or interpretation ref here raises
        InadmissibleEvidenceError, whatever the caller intended.
        ``admitted_sources`` is the D2 eligibility manifest (§9.2),
        consulted only when an erasure tombstone stands.
        """
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            if run_id is not None:
                self._manifest_require_locked(
                    run_id, user_id, [(ref.kind, ref.ref_id)]
                )
            self._require_thread(user_id, thread_id)
            resolved, _ = self._attach_evidence(thread_id, [ref], note=note)
            self._manifest_end_locked(run_id)
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
        touch: bool = True,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> ThreadReading:
        """Store a proposed reading of a thread.

        INVARIANT 1: a reading with no evidence cannot be stored —
        empty refs raise, and every ref resolves through the tier
        gate, so 'evidence' here always means evidence-tier records
        actually attached to this thread.

        ``touch`` (increment C §7.4, specified but unexercised by
        narrowed C, which makes no propose_reading calls): when
        False, the thread's updated_at is left alone, so a
        steward-noticing reading neither delays prune nor breaks
        quiet. Default True preserves every existing caller.
        """
        if author not in SEAT_JURISDICTIONS and author not in READING_AUTHORS:
            raise ValueError(f"unknown reading author: {author!r}")
        reading_data = _validate_reading(reading)
        scale_list, primary = _validate_scales(scales, primary_scale)
        pos = _validate_progression(progression)
        evidence_refs = list(evidence_refs)
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            if run_id is not None:
                self._manifest_require_locked(
                    run_id,
                    user_id,
                    [
                        (ref.kind, ref.ref_id)
                        for ref in evidence_refs
                        if isinstance(ref, SourceRef)
                    ],
                )
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
            if touch:
                self._touch_thread(thread_id)
            self._manifest_end_locked(run_id)
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
        reason: str | None = None,
        successor_thread_id: str | None = None,
        absence_basis: dict | None = None,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> ThreadChange:
        """Record that a thread's story moved.

        INVARIANT 2 (the anti-manufacture rule): at least one cited
        ref must be NEW to the thread — evidence ids already attached
        and refs already attached do not count. A change asserted on
        only old evidence raises here, whatever called it.

        Phase 3 structural exception, narrow and verified: a
        ``retired`` change whose basis is structural rather than
        evidential may cite no new evidence, because the movement
        it records is not a new arrival:

        - ``outgrown``: ``absence_basis`` must carry ``window_days``
          (int > 0) and ``last_evidence_at`` (ISO timestamp). The
          store verifies the thread has at least one evidence row
          and that its most recent evidence predates now minus the
          window; otherwise it raises. The verified computation —
          window + last-evidence timestamp — is stored on the row,
          so the proposal is inspectable and falsifiable, not an
          invented event.
        - ``reinterpreted``: ``successor_thread_id`` must name a
          different thread of the same user. The successor link is
          the basis; both threads' readings are untouched.

        Every other retired reason (``completed``, ``abandoned``)
        and every non-retired kind still requires new evidence.
        ``reason``/``successor_thread_id``/``absence_basis`` on a
        non-retired kind raise.
        """
        if kind not in CHANGE_KINDS:
            raise ValueError(f"unknown thread change kind: {kind!r}")
        if kind != "retired" and (
            reason is not None
            or successor_thread_id is not None
            or absence_basis is not None
        ):
            raise ValueError(
                "reason/successor/absence_basis are only valid for "
                "retired changes"
            )
        structural_basis = False
        absence_window_days: int | None = None
        absence_last_evidence_at: str | None = None
        if kind == "retired":
            if reason not in RETIREMENT_REASONS:
                raise ValueError(
                    "a retired change requires a reason in "
                    f"{list(RETIREMENT_REASONS)}: {reason!r}"
                )
            if reason == "reinterpreted":
                if not successor_thread_id:
                    raise ValueError(
                        "a reinterpreted retirement requires "
                        "successor_thread_id"
                    )
                if successor_thread_id == thread_id:
                    raise ValueError(
                        "a thread cannot be its own successor"
                    )
            if reason == "outgrown":
                if not isinstance(absence_basis, dict):
                    raise ValueError(
                        "an outgrown retirement requires "
                        "absence_basis {window_days, last_evidence_at}"
                    )
                try:
                    absence_window_days = int(
                        absence_basis["window_days"]
                    )
                    absence_last_evidence_at = str(
                        absence_basis["last_evidence_at"]
                    )
                except (KeyError, TypeError, ValueError):
                    raise ValueError(
                        "absence_basis needs int window_days and "
                        "str last_evidence_at"
                    ) from None
                if absence_window_days <= 0:
                    raise ValueError("window_days must be positive")
            elif absence_basis is not None:
                raise ValueError(
                    "absence_basis is only valid for outgrown "
                    "retirements"
                )
            structural_basis = reason in ("outgrown", "reinterpreted")
        evidence_refs = list(evidence_refs)
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            if run_id is not None:
                required: list[tuple[str, str]] = [
                    (ref.kind, ref.ref_id)
                    for ref in evidence_refs
                    if isinstance(ref, SourceRef)
                ]
                if reason == "reinterpreted" and successor_thread_id:
                    required.append(("thread", successor_thread_id))
                self._manifest_require_locked(run_id, user_id, required)
            thread = self._require_thread(user_id, thread_id)
            if successor_thread_id is not None:
                self._require_thread(user_id, successor_thread_id)
            if reason == "outgrown":
                assert absence_window_days is not None
                assert absence_last_evidence_at is not None
                rows = self._conn.execute(
                    "SELECT created_at FROM thread_evidence "
                    "WHERE thread_id = ? ORDER BY created_at DESC",
                    (thread_id,),
                ).fetchall()
                if not rows:
                    raise ValueError(
                        "an outgrown retirement needs at least one "
                        "evidence row to cite as last confirmation"
                    )
                last_seen = rows[0]["created_at"]
                cutoff = (
                    datetime.now(timezone.utc)
                    - timedelta(days=absence_window_days)
                )
                try:
                    last_dt = datetime.fromisoformat(
                        last_seen.replace("Z", "+00:00")
                    )
                except ValueError:
                    raise ValueError(
                        "cannot verify absence: unparseable evidence "
                        f"timestamp {last_seen!r}"
                    ) from None
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if last_dt > cutoff:
                    raise ValueError(
                        "absence not verified: evidence arrived "
                        f"within the window (last {last_seen})"
                    )
                if absence_last_evidence_at != last_seen:
                    raise ValueError(
                        "absence_basis last_evidence_at does not "
                        "match the thread's most recent evidence "
                        f"({last_seen})"
                    )
            resolved, newly = self._attach_evidence(thread_id, evidence_refs)
            if not newly and not structural_basis:
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
                reason=reason,
                successor_thread_id=successor_thread_id,
                absence_window_days=absence_window_days,
                absence_last_evidence_at=absence_last_evidence_at,
            )
            self._conn.execute(
                "INSERT INTO thread_changes (id, thread_id, kind, "
                "evidence_refs_json, prior_reading_id, "
                "new_reading_id, status, created_at, reason, "
                "successor_thread_id, absence_window_days, "
                "absence_last_evidence_at) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id, record.thread_id, record.kind,
                    json.dumps(resolved, ensure_ascii=False),
                    record.prior_reading_id, record.new_reading_id,
                    record.status, record.created_at,
                    record.reason, record.successor_thread_id,
                    record.absence_window_days,
                    record.absence_last_evidence_at,
                ),
            )
            self._touch_thread(thread_id, change=True)
            self._manifest_end_locked(run_id)
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
        # Phase 4 (T2 — rejected fittings are durable): a fitting
        # whose lens + evidence set matches a REJECTED fitting on
        # this thread is refused, unless the caller names that
        # rejection in ``reopen_of`` (explicit user reopen) or the
        # evidence set is new. The rejected row itself is never
        # mutated: rejection stays recorded, and the new proposal
        # stands beside it. A reopen_of naming anything else (a
        # live, retired, or other-thread fitting, or a rejected
        # fitting with different lens/evidence) raises.
        reopen_of: str | None = None,
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
            # Phase 4 (T2): a rejected fitting is durable data, not
            # an obstacle to route around. Re-proposing the same
            # lens on the same evidence is refused unless the caller
            # names the rejection being reopened (reopen_of) — new
            # evidence needs no reopen. The raise rolls back the
            # evidence rows attached above, so a refused proposal
            # leaves no orphaned evidence behind.
            rejected = [
                _row_to_fitting(row)
                for row in self._conn.execute(
                    "SELECT * FROM lens_fittings WHERE thread_id = ? "
                    "AND status = 'rejected'",
                    (thread_id,),
                ).fetchall()
            ]
            new_evidence = set(resolved)
            matching = [
                fit
                for fit in rejected
                if fit.lens_id == lens_id
                and set(fit.evidence_refs or []) == new_evidence
            ]
            if matching and reopen_of not in {fit.id for fit in matching}:
                self._conn.rollback()
                raise ValueError(
                    "fitting was already rejected on this evidence; "
                    "re-propose with new evidence or reopen the "
                    "rejection explicitly via reopen_of"
                )
            if reopen_of is not None and reopen_of not in {
                fit.id for fit in matching
            }:
                self._conn.rollback()
                raise ValueError(
                    "reopen_of must name a rejected fitting on this "
                    "thread with the same lens and evidence set"
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

    # -- Phase 6: steward artifacts + versions (diffusion schedule) -----------

    def _validate_version_refs(
        self,
        user_id: str,
        thread_id: str,
        evidence_refs: Iterable[str],
        reading_ids: Iterable[str],
    ) -> tuple[list[str], list[str]]:
        """Citations must belong to this thread; nothing else is checked.

        Evidence refs are thread_evidence row ids (citations, never
        embedded text — the pass never writes evidence rows, so
        Tier-E records cannot be rewritten here). Reading ids are
        thread reading ids. Unknown or other-thread ids raise
        loudly; silent repair would let a draft cite state it
        never saw.
        """
        ev_ids = [str(r) for r in evidence_refs]
        rd_ids = [str(r) for r in reading_ids]
        with self._lock:
            for ev_id in ev_ids:
                row = self._conn.execute(
                    "SELECT id FROM thread_evidence "
                    "WHERE id = ? AND thread_id = ?",
                    (ev_id, thread_id),
                ).fetchone()
                if row is None:
                    raise ValueError(
                        f"unknown evidence for thread: {ev_id!r}"
                    )
            for rd_id in rd_ids:
                row = self._conn.execute(
                    "SELECT id FROM thread_readings "
                    "WHERE id = ? AND thread_id = ?",
                    (rd_id, thread_id),
                ).fetchone()
                if row is None:
                    raise ValueError(
                        f"unknown reading for thread: {rd_id!r}"
                    )
        return ev_ids, rd_ids

    def _validate_involvement_units(
        self, involvement: dict | None
    ) -> tuple[float, float, float]:
        """Per-version involvement split, same validation as the ledger."""
        units: dict[str, float] = {}
        for label in (
            "user_authored_units",
            "user_edited_units",
            "synthesized_units",
        ):
            value = (involvement or {}).get(label, 0.0)
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{label} is not a number: {value!r}") from None
            if number < 0:
                raise ValueError(f"{label} cannot be negative: {value!r}")
            units[label] = number
        return (
            units["user_authored_units"],
            units["user_edited_units"],
            units["synthesized_units"],
        )

    def _insert_version_locked(
        self,
        user_id: str,
        artifact_id: str,
        version_no: int,
        content: dict,
        evidence_refs: list[str],
        reading_ids: list[str],
        lens_id: str | None,
        units: tuple[float, float, float],
        created_by: str,
        now: str,
    ) -> ArtifactVersion:
        record = ArtifactVersion(
            id=_new_id("artv"),
            artifact_id=artifact_id,
            user_id=user_id,
            version_no=version_no,
            content=dict(content),
            evidence_refs=list(evidence_refs),
            reading_ids=list(reading_ids),
            lens_id=lens_id,
            status="proposed",
            user_authored_units=units[0],
            user_edited_units=units[1],
            synthesized_units=units[2],
            created_by=created_by,
            created_at=now,
        )
        self._conn.execute(
            "INSERT INTO steward_artifact_versions (id, artifact_id, "
            "user_id, version_no, content_json, evidence_refs_json, "
            "reading_ids_json, lens_id, status, user_authored_units, "
            "user_edited_units, synthesized_units, created_by, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id, record.artifact_id, record.user_id,
                record.version_no, json.dumps(record.content),
                json.dumps(record.evidence_refs),
                json.dumps(record.reading_ids), record.lens_id,
                record.status, record.user_authored_units,
                record.user_edited_units, record.synthesized_units,
                record.created_by, record.created_at,
            ),
        )
        return record

    def create_artifact(
        self,
        user_id: str,
        thread_id: str,
        *,
        title: str = "",
        content: dict | None = None,
        evidence_refs: Iterable[str] = (),
        reading_ids: Iterable[str] = (),
        lens_id: str | None = None,
        involvement: dict | None = None,
        created_by: str = "steward",
    ) -> tuple[StewardArtifact, ArtifactVersion]:
        """Start a schedule run: artifact row + version 1 (Draft step).

        The Draft conditioner is enforced here: at least one
        evidence citation is required — zero candidates means no
        draft, not an uncited one. Content is the WHOLE draft at
        this version, never a patch. The version's involvement
        split is also recorded on the ledger (subject "artifact"),
        so resolution rendering reads one current measure.
        """
        if not isinstance(content, dict):
            raise ValueError("artifact content must be a dict")
        ev_ids, rd_ids = self._validate_version_refs(
            user_id, thread_id, evidence_refs, reading_ids
        )
        if not ev_ids:
            raise ValueError(
                "artifact draft requires at least one evidence citation"
            )
        units = self._validate_involvement_units(involvement)
        now = _utcnow()
        with self._lock:
            self._require_thread(user_id, thread_id)
            artifact = StewardArtifact(
                id=_new_id("art"),
                user_id=user_id,
                thread_id=thread_id,
                title=title,
                created_at=now,
                updated_at=now,
            )
            self._conn.execute(
                "INSERT INTO steward_artifacts (id, user_id, thread_id, "
                "title, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    artifact.id, artifact.user_id, artifact.thread_id,
                    artifact.title, artifact.created_at, artifact.updated_at,
                ),
            )
            version = self._insert_version_locked(
                user_id, artifact.id, 1, content, ev_ids, rd_ids,
                lens_id, units, created_by, now,
            )
            self._conn.commit()
        self.record_involvement(
            user_id,
            subject_kind="artifact",
            subject_id=artifact.id,
            user_authored_units=units[0],
            user_edited_units=units[1],
            synthesized_units=units[2],
            note=f"schedule v{version.version_no}",
        )
        return artifact, version

    def get_artifact(
        self, user_id: str, artifact_id: str
    ) -> StewardArtifact | None:
        """One artifact, or None when it is not this user's."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_artifacts "
                "WHERE id = ? AND user_id = ?",
                (artifact_id, user_id),
            ).fetchone()
        return _row_to_artifact(row) if row is not None else None

    def artifacts_for(
        self, user_id: str, *, thread_id: str | None = None
    ) -> list[StewardArtifact]:
        """A user's artifacts, oldest first, optionally per thread."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if thread_id is not None:
            clauses.append("thread_id = ?")
            args.append(thread_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_artifacts WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        return [_row_to_artifact(r) for r in rows]

    def artifact_versions(
        self, user_id: str, artifact_id: str
    ) -> list[ArtifactVersion]:
        """Every version of one artifact, in version order.

        Predecessors stay retrievable after supersede or rejection:
        versions are append-only, never updated except for their
        own forward status transitions.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM steward_artifacts "
                "WHERE id = ? AND user_id = ?",
                (artifact_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown artifact: {artifact_id!r}")
            rows = self._conn.execute(
                "SELECT * FROM steward_artifact_versions "
                "WHERE artifact_id = ? ORDER BY version_no, id",
                (artifact_id,),
            ).fetchall()
        return [_row_to_artifact_version(r) for r in rows]

    def get_artifact_version(
        self, user_id: str, version_id: str
    ) -> ArtifactVersion | None:
        """One version, or None when it is not this user's."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_artifact_versions "
                "WHERE id = ? AND user_id = ?",
                (version_id, user_id),
            ).fetchone()
        return _row_to_artifact_version(row) if row is not None else None

    def artifact_status(self, user_id: str, artifact_id: str) -> str:
        """Derived schedule position: rendered | in_review | drafting.

        Derived from versions, never stored redundantly, so it
        cannot drift from version state. "rendered" iff an accepted
        version exists; else "in_review" iff a version is in
        review; else "drafting".
        """
        versions = self.artifact_versions(user_id, artifact_id)
        statuses = {v.status for v in versions}
        if "accepted" in statuses:
            return "rendered"
        if "in_review" in statuses:
            return "in_review"
        return "drafting"

    def propose_artifact_revision(
        self,
        user_id: str,
        artifact_id: str,
        *,
        content: dict | None = None,
        evidence_refs: Iterable[str] | None = None,
        reading_ids: Iterable[str] | None = None,
        lens_id: str | None = None,
        involvement: dict | None = None,
        created_by: str = "steward",
    ) -> ArtifactVersion:
        """Global revision pass: a whole-draft rewrite, versioned.

        The new version's content replaces the draft wholesale —
        it is never a patch and never merges with its predecessor.
        Defaults make the pass genuinely global: omitted
        evidence_refs become the thread's CURRENT evidence rows,
        omitted reading_ids become its CURRENT accepted readings,
        so the rewrite reconsiders the whole constellation, not a
        slice. Citing an accepted reading never mutates it; a
        change to accepted state goes through a new reading
        proposal, not through this row. The pass writes no
        evidence rows and no reading rows: Tier-E records and
        accepted readings are immutable here by construction.
        Unproposed alternatives are never stored (§6.7 default):
        each revision act records exactly one proposed version.
        """
        if not isinstance(content, dict):
            raise ValueError("artifact content must be a dict")
        artifact = self.get_artifact(user_id, artifact_id)
        if artifact is None:
            raise ValueError(f"unknown artifact: {artifact_id!r}")
        # Defaults are read BEFORE the write lock: evidence_for /
        # readings_for take the store lock themselves (plain,
        # non-reentrant), so calling them under it would deadlock.
        if evidence_refs is None:
            evidence_refs = [
                r.id
                for r in self.evidence_for(user_id, artifact.thread_id)
            ]
        if reading_ids is None:
            reading_ids = [
                r.id
                for r in self.readings_for(
                    user_id, artifact.thread_id, status="accepted"
                )
            ]
        ev_ids, rd_ids = self._validate_version_refs(
            user_id, artifact.thread_id, evidence_refs, reading_ids
        )
        if not ev_ids:
            raise ValueError(
                "artifact revision requires at least one evidence citation"
            )
        units = self._validate_involvement_units(involvement)
        now = _utcnow()
        with self._lock:
            max_no = self._conn.execute(
                "SELECT MAX(version_no) FROM steward_artifact_versions "
                "WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()[0]
            version_no = (max_no or 0) + 1
            version = self._insert_version_locked(
                user_id, artifact_id, version_no, content, ev_ids,
                rd_ids, lens_id, units, created_by, now,
            )
            self._conn.execute(
                "UPDATE steward_artifacts SET updated_at = ? "
                "WHERE id = ?",
                (now, artifact_id),
            )
            self._conn.commit()
        self.record_involvement(
            user_id,
            subject_kind="artifact",
            subject_id=artifact_id,
            user_authored_units=units[0],
            user_edited_units=units[1],
            synthesized_units=units[2],
            note=f"schedule v{version.version_no}",
        )
        return version

    def _set_artifact_version_status(
        self, user_id: str, version_id: str, new_status: str
    ) -> ArtifactVersion:
        """One forward version transition, or a loud ValueError.

        Gate enforcement lives here: only the transitions in
        _ARTIFACT_VERSION_TRANSITIONS exist, and only the owning
        user may move a version. A rejected or superseded version
        never advances again.
        """
        if new_status not in ARTIFACT_VERSION_STATUSES:
            raise ValueError(f"unknown version status: {new_status!r}")
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_artifact_versions "
                "WHERE id = ? AND user_id = ?",
                (version_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown version: {version_id!r}")
            version = _row_to_artifact_version(row)
            allowed = _ARTIFACT_VERSION_TRANSITIONS[version.status]
            if new_status not in allowed:
                raise ValueError(
                    f"version {version_id!r} cannot move "
                    f"{version.status!r} -> {new_status!r}"
                )
            self._conn.execute(
                "UPDATE steward_artifact_versions SET status = ? "
                "WHERE id = ?",
                (new_status, version_id),
            )
            self._conn.commit()
        return self.get_artifact_version(user_id, version_id)  # type: ignore[return-value]

    def submit_artifact_version_for_review(
        self, user_id: str, version_id: str
    ) -> ArtifactVersion:
        """Review-step entry gate: proposed → in_review only.

        Entering review is what makes a version a pending review
        item; a merely proposed version is not verdictable. This
        is the gate the schedule's review step enforces.
        """
        return self._set_artifact_version_status(
            user_id, version_id, "in_review"
        )

    def accept_artifact_version(
        self, user_id: str, version_id: str
    ) -> ArtifactVersion:
        """Accept one in-review version; supersede any prior accepted.

        The accepted version becomes the artifact's deliverable;
        the superseded predecessor keeps its row and content,
        retrievable, never destroyed. Only the review layer calls
        this (review.apply_verdict, transition-then-log); direct
        callers must still pass the in_review gate.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_artifact_versions "
                "WHERE id = ? AND user_id = ?",
                (version_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown version: {version_id!r}")
            version = _row_to_artifact_version(row)
            if version.status != "in_review":
                raise ValueError(
                    f"version {version_id!r} cannot move "
                    f"{version.status!r} -> 'accepted'"
                )
            prior = self._conn.execute(
                "SELECT id FROM steward_artifact_versions "
                "WHERE artifact_id = ? AND status = 'accepted'",
                (version.artifact_id,),
            ).fetchall()
            for prior_row in prior:
                self._conn.execute(
                    "UPDATE steward_artifact_versions SET status = "
                    "'superseded' WHERE id = ?",
                    (prior_row["id"],),
                )
            self._conn.execute(
                "UPDATE steward_artifact_versions SET status = "
                "'accepted' WHERE id = ?",
                (version_id,),
            )
            self._conn.commit()
        return self.get_artifact_version(user_id, version_id)  # type: ignore[return-value]

    def reject_artifact_version(
        self, user_id: str, version_id: str
    ) -> ArtifactVersion:
        """Reject one in-review version; its row stays, terminal."""
        return self._set_artifact_version_status(
            user_id, version_id, "rejected"
        )

    def render_artifact(
        self, user_id: str, artifact_id: str
    ) -> dict | None:
        """The rendered deliverable — or None when nothing is accepted.

        Rendering is a pure read over store state, not a state
        change: an unaccepted revision can never become standing
        state through this function, because there is nothing to
        render until a version carries an accepted verdict. The
        deliverable carries its tier, lens, and involvement on
        itself, so any downstream reader can check what produced
        the telling. Blend appears here only as labeled provenance.
        """
        artifact = self.get_artifact(user_id, artifact_id)
        if artifact is None:
            raise ValueError(f"unknown artifact: {artifact_id!r}")
        versions = self.artifact_versions(user_id, artifact_id)
        accepted = [v for v in versions if v.status == "accepted"]
        if not accepted:
            return None
        version = accepted[-1]
        fitted = [
            f
            for f in self.fittings_for(user_id, artifact.thread_id)
            if f.status == "accepted"
        ]
        lens = None
        if fitted:
            fit = fitted[-1]
            lens = {
                "lens_id": fit.lens_id,
                "proposed_by": fit.proposed_by,
                "decided_at": fit.decided_at,
            }
        return {
            "artifact_id": artifact.id,
            "thread_id": artifact.thread_id,
            "title": artifact.title,
            "version_no": version.version_no,
            "content": dict(version.content),
            "evidence_refs": list(version.evidence_refs or []),
            "reading_ids": list(version.reading_ids or []),
            "lens": lens,
            "draft_lens_id": version.lens_id,
            "involvement": {
                "user_authored_units": version.user_authored_units,
                "user_edited_units": version.user_edited_units,
                "synthesized_units": version.synthesized_units,
                "user_share": version.user_share,
            },
            "provenance": (
                {
                    "blend": {
                        "user_sourced": version.user_share,
                        "base_model_fill": (
                            1 - version.user_share
                            if version.user_share is not None
                            else None
                        ),
                        "label": "provenance: user-sourced vs "
                        "base-model fill — not resolution, "
                        "not fidelity",
                    },
                    "version_id": version.id,
                }
                if version.user_share is not None
                else None
            ),
        }

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

    def has_dismissal_kind(self, user_id: str, *, kind: str) -> bool:
        """Does the user have any dismissal row of this kind standing?

        Increment B: the ambiguity existence check — one indexed
        SELECT, used when an offer's subject key is unknown or
        coarse and a subject decline would make it ambiguous.
        """
        if kind not in DISMISSAL_KINDS:
            raise ValueError(f"unknown dismissal kind: {kind!r}")
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM steward_dismissals WHERE user_id = ? "
                "AND kind = ? LIMIT 1",
                (user_id, kind),
            ).fetchone()
        return row is not None

    def clear_dismissal(
        self, user_id: str, *, kind: str, signature: str
    ) -> bool:
        """Clear exactly one dismissal row (a visitor lift).

        Clearing is a user act and is never performed by
        derivation (derivation only consults). Deletes exactly
        the matching row; True if a row was deleted. Scoped
        exactly: clearing one kind + signature never clears
        another regime or scope.
        """
        if kind not in DISMISSAL_KINDS:
            raise ValueError(f"unknown dismissal kind: {kind!r}")
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM steward_dismissals WHERE user_id = ? "
                "AND kind = ? AND signature = ?",
                (user_id, kind, signature),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    # -- deferred prose (increment A) ----------------------------------------

    # -- observables (increment C) --------------------------------------

    def observables_for(
        self, user_id: str, *, kind: str | None = None
    ) -> list[StewardObservable]:
        """All of the user's observable rows, oldest first."""
        if kind is not None and kind not in OBSERVABLE_KINDS:
            raise ValueError(f"unknown observable kind: {kind!r}")
        with self._lock:
            if kind is None:
                rows = self._conn.execute(
                    "SELECT * FROM steward_observables WHERE user_id = ? "
                    "ORDER BY created_at, id",
                    (user_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM steward_observables WHERE user_id = ? "
                    "AND kind = ? ORDER BY created_at, id",
                    (user_id, kind),
                ).fetchall()
        return [_row_to_observable(r) for r in rows]

    def observables_for_thread(
        self, user_id: str, thread_id: str
    ) -> list[StewardObservable]:
        """The thread's observable rows (thread-scoped only)."""
        with self._lock:
            self._require_thread(user_id, thread_id)
            rows = self._conn.execute(
                "SELECT * FROM steward_observables WHERE user_id = ? "
                "AND thread_id = ? ORDER BY created_at, id",
                (user_id, thread_id),
            ).fetchall()
        return [_row_to_observable(r) for r in rows]

    def meeting_observables_for(
        self, user_id: str
    ) -> list[StewardObservable]:
        """The user's meeting-scoped (NULL thread) observable rows."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_observables WHERE user_id = ? "
                "AND thread_id IS NULL ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
        return [_row_to_observable(r) for r in rows]

    def _sync_observables_locked(
        self,
        user_id: str,
        desired: list[dict],
        *,
        thread_id: str | None,
        meeting_scoped: bool,
    ) -> tuple[int, int, int]:
        """Recompute-sync one scope's observables, one transaction.

        ``desired`` rows are dicts with kind, signal_key,
        evidence_refs (non-empty), and detail. Rows whose fact
        still holds keep their id and first_seen_at and refresh
        last_seen_at; new facts insert; facts that stopped holding
        delete. Writes touch ONLY the observables table — never a
        thread clock, so C observing quiet cannot break quiet.
        Returns (written, refreshed, removed). Caller holds the lock.
        """
        for row in desired:
            if row["kind"] not in OBSERVABLE_KINDS:
                raise ValueError(f"unknown observable kind: {row['kind']!r}")
            if not row.get("evidence_refs"):
                raise ValueError(
                    "an observable cannot be stored without evidence refs "
                    "(invariant: no observable without evidence)"
                )
            if meeting_scoped and row.get("thread_id") is not None:
                raise ValueError(
                    "meeting-scoped sync takes NULL-thread rows only"
                )
            if not meeting_scoped and row.get("thread_id") != thread_id:
                raise ValueError(
                    "thread sync rows must carry the synced thread_id"
                )
        if meeting_scoped:
            existing = self._conn.execute(
                "SELECT * FROM steward_observables WHERE user_id = ? "
                "AND thread_id IS NULL",
                (user_id,),
            ).fetchall()
        else:
            existing = self._conn.execute(
                "SELECT * FROM steward_observables WHERE user_id = ? "
                "AND thread_id = ?",
                (user_id, thread_id),
            ).fetchall()
        by_key = {(r["kind"], r["signal_key"]): r for r in existing}
        wanted_keys = set()
        written = refreshed = 0
        now = _utcnow()
        for row in desired:
            key = (row["kind"], row["signal_key"])
            wanted_keys.add(key)
            if key in by_key:
                old = by_key[key]
                self._conn.execute(
                    "UPDATE steward_observables SET evidence_refs_json = ?, "
                    "detail_json = ?, last_seen_at = ? WHERE id = ?",
                    (
                        json.dumps(list(row["evidence_refs"]), ensure_ascii=False),
                        json.dumps(row.get("detail") or {}, ensure_ascii=False),
                        now,
                        old["id"],
                    ),
                )
                refreshed += 1
            else:
                self._conn.execute(
                    "INSERT INTO steward_observables (id, user_id, "
                    "thread_id, kind, signal_key, evidence_refs_json, "
                    "detail_json, first_seen_at, last_seen_at, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _new_id("obs"),
                        user_id,
                        row.get("thread_id"),
                        row["kind"],
                        row["signal_key"],
                        json.dumps(list(row["evidence_refs"]), ensure_ascii=False),
                        json.dumps(row.get("detail") or {}, ensure_ascii=False),
                        now,
                        now,
                        now,
                    ),
                )
                written += 1
        removed = 0
        for key, old in by_key.items():
            if key not in wanted_keys:
                self._conn.execute(
                    "DELETE FROM steward_observables WHERE id = ?",
                    (old["id"],),
                )
                removed += 1
        return written, refreshed, removed

    def sync_thread_observables(
        self,
        user_id: str,
        thread_id: str,
        desired: list[dict],
        *,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> tuple[int, int, int]:
        """Recompute-sync one thread's observables (one transaction).

        ``admitted_sources`` is the D2 eligibility manifest (§9.2),
        consulted only when an erasure tombstone stands and the
        sync would write rows; a deletion-only sync (empty desired)
        needs no manifest — no covered insert or update occurs.
        """
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        with self._lock, _atomic(self._conn):
            run_id = (
                self._manifest_begin_locked(user_id, admitted)
                if desired
                else None
            )
            self._require_thread(user_id, thread_id)
            out = self._sync_observables_locked(
                user_id, desired, thread_id=thread_id, meeting_scoped=False
            )
            self._manifest_end_locked(run_id)
        return out

    def sync_meeting_observables(
        self,
        user_id: str,
        desired: list[dict],
        *,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> tuple[int, int, int]:
        """Recompute-sync the user's meeting-scoped observables (O1).

        ``admitted_sources``: see sync_thread_observables.
        """
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        with self._lock, _atomic(self._conn):
            run_id = (
                self._manifest_begin_locked(user_id, admitted)
                if desired
                else None
            )
            out = self._sync_observables_locked(
                user_id, desired, thread_id=None, meeting_scoped=True
            )
            self._manifest_end_locked(run_id)
        return out

    def delete_observables_for_user(self, user_id: str) -> int:
        """Hard-delete ALL of the user's observable rows (clear path)."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM steward_observables WHERE user_id = ?",
                (user_id,),
            )
            self._conn.commit()
        return cursor.rowcount

    def _insert_deferred_prose_locked(
        self,
        user_id: str,
        thread_id: str,
        kind: str,
        evidence_signature: str,
        evidence_refs: list[str],
        evidence_texts: list[dict],
    ) -> str:
        """Insert a deferred-prose row, or return the existing one.

        Caller holds the lock and owns the commit: this is always
        part of a combined write (records + deferred row, one
        commit), never a standalone write. Dedup is by
        (user, thread, evidence signature); the UNIQUE constraint
        backs the check. ``evidence_texts`` are prompt inputs
        (verbatim texts), not evidence rows.
        """
        existing = self._conn.execute(
            "SELECT id FROM steward_deferred_prose WHERE user_id = ? "
            "AND thread_id = ? AND evidence_signature = ?",
            (user_id, thread_id, evidence_signature),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        row_id = _new_id("dfp")
        self._conn.execute(
            "INSERT INTO steward_deferred_prose (id, user_id, "
            "thread_id, kind, evidence_signature, evidence_refs_json, "
            "evidence_texts_json, created_at, attempts, last_attempt_at, "
            "status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 'pending')",
            (
                row_id, user_id, thread_id, kind, evidence_signature,
                json.dumps(evidence_refs, ensure_ascii=False),
                json.dumps(evidence_texts, ensure_ascii=False),
                _utcnow(),
            ),
        )
        return row_id

    def deferred_prose_for(
        self,
        user_id: str,
        *,
        status: str | None = None,
    ) -> list[dict]:
        """Deferred-prose rows for a user, optionally filtered."""
        with self._lock:
            if status is None:
                rows = self._conn.execute(
                    "SELECT * FROM steward_deferred_prose "
                    "WHERE user_id = ? ORDER BY created_at, id",
                    (user_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM steward_deferred_prose "
                    "WHERE user_id = ? AND status = ? "
                    "ORDER BY created_at, id",
                    (user_id, status),
                ).fetchall()
        return [dict(r) for r in rows]

    def deferred_prose_for_thread(
        self,
        user_id: str,
        thread_id: str,
        *,
        statuses: tuple[str, ...] | None = None,
    ) -> list[dict]:
        """Deferred-prose rows for one thread, optionally filtered."""
        with self._lock:
            if statuses is None:
                rows = self._conn.execute(
                    "SELECT * FROM steward_deferred_prose "
                    "WHERE user_id = ? AND thread_id = ? "
                    "ORDER BY created_at, id",
                    (user_id, thread_id),
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in statuses)
                rows = self._conn.execute(
                    "SELECT * FROM steward_deferred_prose "
                    "WHERE user_id = ? AND thread_id = ? AND status IN "
                    f"({placeholders}) ORDER BY created_at, id",
                    (user_id, thread_id, *statuses),
                ).fetchall()
        return [dict(r) for r in rows]

    def claim_deferred_prose(
        self,
        user_id: str,
        row_id: str,
    ) -> dict | None:
        """Claim a pending row for rendering (a lease, not a state).

        pending → rendering, attempts +1, last_attempt_at = now, in
        one commit. Returns the claimed row, or None when the row
        is not pending (already claimed, done, or gone). The lease
        is released by release_stale_deferred_prose after
        STEWARD_DEFERRED_LEASE_SECONDS; a crashed render therefore
        returns to pending instead of being lost.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE steward_deferred_prose SET status = 'rendering', "
                "attempts = attempts + 1, last_attempt_at = ? "
                "WHERE id = ? AND user_id = ? AND status = 'pending'",
                (_utcnow(), row_id, user_id),
            )
            if cursor.rowcount != 1:
                self._conn.commit()
                return None
            row = self._conn.execute(
                "SELECT * FROM steward_deferred_prose WHERE id = ?",
                (row_id,),
            ).fetchone()
            self._conn.commit()
        return dict(row) if row is not None else None

    def release_stale_deferred_prose(self, lease_seconds: int) -> int:
        """Return rendering rows past their lease to pending."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)
        ).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE steward_deferred_prose SET status = 'pending' "
                "WHERE status = 'rendering' AND last_attempt_at IS NOT "
                "NULL AND last_attempt_at < ?",
                (cutoff,),
            )
            self._conn.commit()
        return cursor.rowcount

    def release_deferred_prose(
        self,
        user_id: str,
        row_id: str,
    ) -> bool:
        """Release a claimed (rendering) row back to pending.

        Used when a render attempt fails cleanly (generation
        raised and was caught): the worker knows the attempt is
        over, so the row retries on the next pass instead of
        waiting out the lease. Only a process crash mid-render —
        where no one releases — holds the lease until expiry.
        Returns False when the row is not rendering for this user.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE steward_deferred_prose SET status = 'pending' "
                "WHERE id = ? AND user_id = ? AND status = 'rendering'",
                (row_id, user_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def mark_deferred_prose_done(
        self,
        user_id: str,
        row_id: str,
    ) -> bool:
        """Mark a claimed (rendering) row done without a reading.

        Used when the worker's render yields no usable prose (a
        NONE judgment or malformed output): the attempt is settled
        rather than retried forever, and the thread + evidence
        persist — a later extension may still propose a reading.
        Returns False when the row is not rendering for this user.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE steward_deferred_prose SET status = 'done' "
                "WHERE id = ? AND user_id = ? AND status = 'rendering'",
                (row_id, user_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def mark_deferred_prose_suppressed(
        self,
        user_id: str,
        row_id: str,
        *,
        scope: str,
        key: str,
    ) -> bool:
        """Settle a claimed (rendering) row as suppressed by decline
        (increment B §6.3) — a distinct terminal outcome, NOT done
        and NOT deleted.

        In ONE transaction for a rendering row: status →
        'suppressed_by_decline'; evidence_texts_json → cleared
        (verbatim prompt copies no longer serve a purpose once the
        proposal will never render); evidence_refs_json RETAINED
        (refs are provenance keys, not verbatim text); and the
        matched refusal scope + key recorded on the row itself
        (suppressed_scope / suppressed_key), so the why stays
        queryable on the note rather than only in a run report.
        The thread + evidence already landed STAY landed.
        Returns False when the row is not rendering for this user.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE steward_deferred_prose SET status = "
                "'suppressed_by_decline', evidence_texts_json = '[]', "
                "suppressed_scope = ?, suppressed_key = ? "
                "WHERE id = ? AND user_id = ? AND status = 'rendering'",
                (scope, key, row_id, user_id),
            )
            self._conn.commit()
        return cursor.rowcount == 1

    def propose_reading_and_complete_deferred(
        self,
        user_id: str,
        thread_id: str,
        deferred_id: str,
        *,
        author: str,
        reading: dict | None = None,
        evidence_refs: Iterable[SourceRef | str] = (),
        scales: Iterable[str] | None = None,
        primary_scale: str | None = None,
        progression: ProgressionPosition | dict | None = None,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> ThreadReading | None:
        """Worker completion (increment A §6.2): propose a reading
        AND mark the deferred row done — in ONE transaction.

        Completion guard: if a reading already covers the deferred
        evidence (crash between reading commit and row-done commit
        in an older layout, or a double claim), the row is marked
        done WITHOUT rendering a duplicate — reading existence is
        the idempotency guard on the completion side. Returns the
        new reading, or None when the row was already covered (or
        the deferred row is gone / not rendering for this user).
        """
        if author not in SEAT_JURISDICTIONS and author not in READING_AUTHORS:
            raise ValueError(f"unknown reading author: {author!r}")
        reading_data = _validate_reading(reading)
        scale_list, primary = _validate_scales(scales, primary_scale)
        pos = _validate_progression(progression)
        evidence_refs = list(evidence_refs)
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        outcome: ThreadReading | None = None
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            if run_id is not None:
                # Completion binding (packet §9.2): the completion
                # manifests every ref it cites AND the deferred row
                # itself, at the row's resolved provenance time —
                # the funnel refuses a completion whose manifest
                # lacks the deferred entry.
                self._manifest_require_locked(
                    run_id,
                    user_id,
                    [
                        (ref.kind, ref.ref_id)
                        for ref in evidence_refs
                        if isinstance(ref, SourceRef)
                    ]
                    + [("deferred_prose", deferred_id)],
                )
            self._require_thread(user_id, thread_id)
            deferred = self._conn.execute(
                "SELECT * FROM steward_deferred_prose WHERE id = ? "
                "AND user_id = ? AND thread_id = ?",
                (deferred_id, user_id, thread_id),
            ).fetchone()
            if deferred is None or deferred["status"] != "rendering":
                self._manifest_end_locked(run_id)
                return None
            resolved, _ = self._attach_evidence(thread_id, evidence_refs)
            if not resolved:
                raise ValueError(
                    "a reading cannot be stored without evidence refs "
                    "(invariant: no reading without at least one "
                    "evidence-tier reference)"
                )
            resolved_set = set(resolved)
            already_covered = False
            for existing in self._conn.execute(
                "SELECT evidence_refs_json FROM thread_readings "
                "WHERE thread_id = ?",
                (thread_id,),
            ).fetchall():
                try:
                    covered = set(json.loads(existing["evidence_refs_json"]))
                except (json.JSONDecodeError, TypeError):
                    continue
                if resolved_set <= covered:
                    already_covered = True
                    break
            if already_covered:
                self._conn.execute(
                    "UPDATE steward_deferred_prose SET status = 'done' "
                    "WHERE id = ?",
                    (deferred_id,),
                )
                self._manifest_end_locked(run_id)
                return None
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
            self._conn.execute(
                "UPDATE steward_deferred_prose SET status = 'done' "
                "WHERE id = ?",
                (deferred_id,),
            )
            self._touch_thread(thread_id)
            self._manifest_end_locked(run_id)
            outcome = record
        return outcome

    # -- sweep cursor (increment A) ------------------------------------------

    def get_processing_position(self, user_id: str) -> dict | None:
        """A user's byte-offset read position, or None (never swept)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, byte_offset, file_identity, updated_at "
                "FROM steward_processing_position WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def set_processing_position(
        self,
        user_id: str,
        byte_offset: int,
        file_identity: str,
    ) -> None:
        """Advance a user's read position (its own later commit).

        Cursor-last (§7): this is NEVER bundled into a record
        commit, so a cursor commit failure cannot roll back records
        and a record commit failure cannot advance the cursor.
        """
        with self._lock:
            self._conn.execute(
                "INSERT INTO steward_processing_position (user_id, "
                "byte_offset, file_identity, updated_at) VALUES "
                "(?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "byte_offset = excluded.byte_offset, "
                "file_identity = excluded.file_identity, "
                "updated_at = excluded.updated_at",
                (user_id, int(byte_offset), file_identity, _utcnow()),
            )
            self.boundary_state.commit(self._conn)

    def processing_position_users(self) -> list[str]:
        """User ids with a stored read position (sweep enumeration)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id FROM steward_processing_position"
            ).fetchall()
        return [row["user_id"] for row in rows]

    # -- hard deletion (increment A retention) -------------------------------

    def delete_thread(self, user_id: str, thread_id: str) -> bool:
        """Hard-delete a thread and its owned rows (increment A §1.8:
        DELETE means real removal, not retire-and-hide).

        Removes the thread row, its evidence, readings, changes,
        deferred-prose rows, lens fittings, observables, Phase 6
        artifacts + versions, and containment links on either side. Phase 1 rows follow the
        same rule: verdict rows for the thread's items, relevance
        assessments for the thread, and flags on those assessments
        are deleted with it (NULL-thread assessments are not
        thread-owned and survive). Involvement measures are
        measures ABOUT a subject, not the subject's records, and
        are left untouched. Meeting-scoped (NULL thread)
        observables do NOT cascade here — every clause is
        thread_id = ?, so O1 rows are deleted directly by the
        clear operations, never by thread deletion.
        Returns False when the thread does not belong to this user.
        """
        with self._lock:
            try:
                self._require_thread(user_id, thread_id)
            except ValueError:
                return False
            # Increment D cascade contract (§3.7): delivery rows for
            # this thread's readings + observables go with the
            # thread. Runs BEFORE the owned-row deletes below, so
            # the subqueries still see them. Meeting-scoped (NULL
            # thread) observables are untouched here.
            self._conn.execute(
                "DELETE FROM steward_signal_states WHERE user_id = ? "
                "AND ((signal_kind = 'reading' AND signal_id IN "
                "(SELECT id FROM thread_readings WHERE thread_id = ?)) "
                "OR (signal_kind = 'observable' AND signal_id IN "
                "(SELECT signal_key FROM steward_observables "
                "WHERE thread_id = ?)))",
                (user_id, thread_id, thread_id),
            )
            # Phase 1 cascade contract: verdict rows follow their
            # items, and relevance assessments + flags follow
            # their thread. Runs BEFORE the owned-row deletes
            # below, so the subqueries still see them.
            # NULL-thread assessments are not thread-owned and
            # survive (they record a branch-level decision, not a
            # thread's content).
            # Phase 7 cascade contract: a correspondence cites
            # threads by id, so deleting a cited thread orphans
            # it — correspondences citing this thread (and their
            # seat responses) go with the thread, and their
            # verdict rows follow. Correspondences citing only
            # surviving threads are untouched. Runs BEFORE the
            # verdict delete below, so the doomed ids are known
            # while their rows still exist.
            doomed_corr: list[str] = []
            for corr_row in self._conn.execute(
                "SELECT id, thread_ids_json FROM "
                "steward_correspondences WHERE user_id = ?",
                (user_id,),
            ).fetchall():
                try:
                    cited = json.loads(corr_row["thread_ids_json"] or "[]")
                except (ValueError, TypeError):
                    cited = []
                if thread_id in cited:
                    doomed_corr.append(corr_row["id"])
            if doomed_corr:
                placeholders = ", ".join("?" for _ in doomed_corr)
                self._conn.execute(
                    "DELETE FROM steward_correspondence_responses "
                    f"WHERE correspondence_id IN ({placeholders})",
                    doomed_corr,
                )
                self._conn.execute(
                    "DELETE FROM steward_correspondences "
                    f"WHERE id IN ({placeholders})",
                    doomed_corr,
                )
            self._conn.execute(
                "DELETE FROM steward_review_verdicts WHERE user_id = ? "
                "AND ((item_kind = 'birth' AND item_id = ?) "
                "OR (item_kind = 'reading' AND item_id IN "
                "(SELECT id FROM thread_readings WHERE thread_id = ?)) "
                "OR (item_kind = 'change' AND item_id IN "
                "(SELECT id FROM thread_changes WHERE thread_id = ?)) "
                "OR (item_kind = 'fitting' AND item_id IN "
                "(SELECT id FROM lens_fittings WHERE thread_id = ?)) "
                "OR (item_kind = 'oversight' AND item_id IN "
                "(SELECT id FROM steward_oversight_proposals "
                "WHERE thread_id = ?)) "
                "OR (item_kind = 'reconsideration' AND item_id IN "
                "(SELECT id FROM steward_reading_reconsiderations "
                "WHERE thread_id = ?)) "
                "OR (item_kind = 'revision' AND item_id IN "
                "(SELECT id FROM steward_artifact_versions WHERE "
                "artifact_id IN (SELECT id FROM steward_artifacts "
                "WHERE thread_id = ?))))",
                (
                    user_id, thread_id, thread_id, thread_id,
                    thread_id, thread_id, thread_id, thread_id,
                ),
            )
            if doomed_corr:
                placeholders = ", ".join("?" for _ in doomed_corr)
                self._conn.execute(
                    "DELETE FROM steward_review_verdicts "
                    "WHERE user_id = ? AND item_kind = "
                    "'correspondence' AND item_id IN "
                    f"({placeholders})",
                    [user_id, *doomed_corr],
                )
            self._conn.execute(
                "DELETE FROM steward_discrepancy_flags WHERE user_id = ? "
                "AND assessment_id IN (SELECT id FROM "
                "steward_relevance_assessments WHERE thread_id = ?)",
                (user_id, thread_id),
            )
            self._conn.execute(
                "DELETE FROM steward_relevance_assessments "
                "WHERE user_id = ? AND thread_id = ?",
                (user_id, thread_id),
            )
            for table, clause in (
                ("thread_evidence", "thread_id = ?"),
                ("thread_readings", "thread_id = ?"),
                ("thread_changes", "thread_id = ?"),
                ("steward_deferred_prose", "thread_id = ?"),
                ("lens_fittings", "thread_id = ?"),
                ("steward_observables", "thread_id = ?"),
                # Phase 7: oversight proposals and
                # reconsiderations are thread-owned rows, so
                # they cascade with the thread. (Correspondences
                # citing the thread were removed above, with
                # their responses, because they cite by id list
                # rather than a thread_id column.)
                ("steward_oversight_proposals", "thread_id = ?"),
                ("steward_reading_reconsiderations", "thread_id = ?"),
                # Phase 6: artifact versions go before their
                # artifacts; both are thread-owned rows, so they
                # cascade with the thread. Involvement measures
                # are measures ABOUT a subject and survive, as
                # before.
                (
                    "steward_artifact_versions",
                    "artifact_id IN (SELECT id FROM steward_artifacts "
                    "WHERE thread_id = ?)",
                ),
                ("steward_artifacts", "thread_id = ?"),
            ):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE {clause}",
                    (thread_id,),
                )
            self._conn.execute(
                "DELETE FROM thread_links WHERE parent_thread_id = ? "
                "OR child_thread_id = ?",
                (thread_id, thread_id),
            )
            self._conn.execute(
                "DELETE FROM narrative_threads WHERE id = ? AND user_id = ?",
                (thread_id, user_id),
            )
            self.boundary_state.commit(self._conn)
        return True

    # -- deletion preview + user-material clearing (increment B §9) -----

    def deletion_preview(
        self, user_id: str, *, operation: str
    ) -> dict:
        """Compute, BEFORE any deletion, exactly what an operation
        would remove — the warn-first content (increments B §9,
        C §8.4).

        ``operation`` is "routine_clear" or "full_delete". Both
        cover the user's steward-proposal threads (origin
        steward_proposal, any status) and their owned rows
        (readings, changes, deferred prose, observables,
        containment links on either side), PLUS all of the user's
        observable rows (thread-scoped rows on preserved threads
        and meeting-scoped O1 rows, deleted directly) and the
        proposed readings on preserved (non-steward-proposal)
        threads. They differ on verdict-state readings on
        preserved threads and on decline rows: a routine clear
        PRESERVES both (rule A, Joshua's ruling: a verdict is a
        visitor act, and routine clear clears steward material,
        not visitor acts; deleting a no would silently re-enable
        declined offers); a full deletion REMOVES both (hard
        removal throughout — "delete = gone"). Verdict-state
        readings on wholesale-deleted threads cascade with their
        thread under EITHER operation and are counted separately
        (``accepted_readings_on_deleted_threads`` — the name is
        the proposal's; the count covers every verdict state),
        so that loss is named, not hidden in a thread count.
        Involvement measures are left untouched by both (they
        are measures ABOUT a subject, per delete_thread).
        Meetings and claims are never deleted by either
        operation (O1's provenance survives; only the O1
        derivation row goes). The preview names thread ids +
        titles, reading/change/deferred counts, links touched,
        observable counts split thread-scoped / meeting-scoped,
        proposed vs verdict-state reading counts on preserved
        threads (with the preserved reading ids, so clear acts
        on exactly what was previewed), and — for full deletion
        — the decline rows by kind, or an explicit preserved
        statement for routine clear. E renders this preview as
        the warning and gates confirmation on it; the content
        requirements here are B's + C's, the rendering is E's
        work. The preview is a point-in-time inventory, not a
        lock: material added between preview and clear is not
        covered by it.
        """
        if operation not in ("routine_clear", "full_delete"):
            raise ValueError(f"unknown deletion operation: {operation!r}")
        threads = [
            t for t in self.threads_for(user_id, limit=None)
            if t.origin == "steward_proposal"
        ]
        wholesale_ids = {t.id for t in threads}
        reading_count = 0
        change_count = 0
        deferred_count = 0
        links: dict[str, dict] = {}
        verdict_on_deleted = 0
        for thread in threads:
            readings = self.readings_for(user_id, thread.id)
            reading_count += len(readings)
            verdict_on_deleted += sum(
                1 for r in readings if r.status != "proposed"
            )
            change_count += len(self.changes_for(user_id, thread.id))
            deferred_count += len(
                self.deferred_prose_for_thread(user_id, thread.id)
            )
            for link in self.links_for(user_id, thread.id):
                links[link.id] = {
                    "id": link.id,
                    "parent_thread_id": link.parent_thread_id,
                    "child_thread_id": link.child_thread_id,
                }
        preserved_proposed_ids: list[str] = []
        preserved_verdict_ids: list[str] = []
        judgment_proposed = 0
        judgment_verdict = 0
        for thread in self.threads_for(user_id, limit=None):
            if thread.id in wholesale_ids:
                continue
            for reading in self.readings_for(user_id, thread.id):
                if reading.status == "proposed":
                    preserved_proposed_ids.append(reading.id)
                else:
                    preserved_verdict_ids.append(reading.id)
                if isinstance(reading.reading, dict) and (
                    "judgment_kind" in reading.reading
                ):
                    if reading.status == "proposed":
                        judgment_proposed += 1
                    else:
                        judgment_verdict += 1
        observables = self.observables_for(user_id)
        observable_thread_scoped = sum(
            1 for o in observables if o.thread_id is not None
        )
        observable_meeting_scoped = sum(
            1 for o in observables if o.thread_id is None
        )
        # Steward D1 (packet §8.2 point 4): candidate mentions are
        # steward material — BOTH operations remove the whole
        # family, named here so the warning shows them.
        candidate_count = len(self.candidates_for(user_id))
        candidate_sighting_count = len(self.sightings_for(user_id))
        declines = self.dismissals_for(user_id)
        by_kind: dict[str, int] = {}
        for row in declines:
            by_kind[row.kind] = by_kind.get(row.kind, 0) + 1
        return {
            "operation": operation,
            "thread_ids": [t.id for t in threads],
            "threads": [{"id": t.id, "title": t.title} for t in threads],
            "reading_count": reading_count,
            "change_count": change_count,
            "deferred_count": deferred_count,
            "links_touched": sorted(links.values(), key=lambda d: d["id"]),
            "observable_count": len(observables),
            "observable_thread_scoped_count": observable_thread_scoped,
            "observable_meeting_scoped_count": observable_meeting_scoped,
            "candidate_mention_count": candidate_count,
            "candidate_sighting_count": candidate_sighting_count,
            "observable_ids": [o.id for o in observables],
            "proposed_readings_on_preserved_count": len(
                preserved_proposed_ids
            ),
            "verdict_readings_on_preserved_count": len(
                preserved_verdict_ids
            ),
            "preserved_proposed_reading_ids": preserved_proposed_ids,
            "preserved_verdict_reading_ids": preserved_verdict_ids,
            "judgment_readings_proposed": judgment_proposed,
            "judgment_readings_verdict_state": judgment_verdict,
            "accepted_readings_on_deleted_threads": verdict_on_deleted,
            "declines": {
                "preserved": operation == "routine_clear",
                "total": len(declines),
                "by_kind": by_kind,
            },
        }

    def clear_user_material(
        self,
        user_id: str,
        *,
        operation: str,
        preview: dict | None = None,
    ) -> dict:
        """Perform a routine clear or a full deletion (increments
        B §9, C §8.4 + rule A) — storage-level only; no UI here.

        Takes the preview it acts on (computed here when not
        supplied), so the warning shown is the warning acted on.
        Routine clear deletes the preview's steward-proposal
        threads (via delete_thread, so owned rows and links go
        with them), ALL of the user's observable rows (directly —
        thread-scoped rows on preserved threads and meeting-scoped
        O1 rows; rows on wholesale threads already cascaded),
        and the preview's proposed readings on preserved threads,
        and PRESERVES verdict-state readings on preserved threads
        and decline rows (rule A). Full deletion deletes the
        same, PLUS the preview's verdict-state readings on
        preserved threads, PLUS the user's decline rows (both
        regimes, hard removal). Phase 1 verdict rows follow their
        items exactly (deleted with directly-deleted readings,
        cascaded with wholesale threads via delete_thread);
        assessments and flags follow their threads via
        delete_thread and otherwise survive clear as decision
        records, like involvement measures. Clear is NOT suppression: cleared
        observables may be re-derived on the next pass if their
        facts still hold. Returns a report with the operation,
        the preview acted on, deleted thread ids, and the
        deleted observable / reading / decline counts.
        """
        if operation not in ("routine_clear", "full_delete"):
            raise ValueError(f"unknown deletion operation: {operation!r}")
        if preview is None:
            preview = self.deletion_preview(user_id, operation=operation)
        deleted_threads: list[str] = []
        for thread_id in preview.get("thread_ids", []):
            if self.delete_thread(user_id, thread_id):
                deleted_threads.append(thread_id)
        deleted_observables = self.delete_observables_for_user(user_id)
        # Steward D1 (packet §8.2 point 4): candidates are steward
        # material and delete with it under BOTH operations —
        # routine clear included (the Q3 disclosure says so, in
        # the consent text itself). Dismissals — visitor acts,
        # including candidate declines — are preserved by routine
        # clear exactly as other dismissals are, and removed by
        # full delete with the rest of the rail below.
        deleted_candidates = self._delete_candidate_family(user_id)
        # Increment D: readings deleted directly here (not via
        # delete_thread) and observables deleted wholesale above
        # leave orphan delivery rows unless cleaned with them.
        # Delivery rows for recomputed-away observables are the
        # remaining orphan source (tracked cleanup, §8.3); the
        # read ignores orphans.
        with self._lock:
            self._conn.execute(
                "DELETE FROM steward_signal_states WHERE user_id = ? "
                "AND signal_kind = 'observable'",
                (user_id,),
            )
            self._conn.commit()
        with self._lock:
            proposed_ids = preview.get(
                "preserved_proposed_reading_ids", []
            )
            deleted_proposed = 0
            if proposed_ids:
                placeholders = ", ".join("?" for _ in proposed_ids)
                cursor = self._conn.execute(
                    "DELETE FROM thread_readings WHERE id IN "
                    f"({placeholders}) AND thread_id IN (SELECT id "
                    "FROM narrative_threads WHERE user_id = ?)",
                    (*proposed_ids, user_id),
                )
                deleted_proposed = cursor.rowcount
                self._conn.execute(
                    "DELETE FROM steward_signal_states "
                    "WHERE user_id = ? AND signal_kind = 'reading' "
                    f"AND signal_id IN ({placeholders})",
                    (user_id, *proposed_ids),
                )
                # Phase 1: verdict rows follow their items — a
                # verdict on a deleted proposed reading goes with
                # it; verdicts on preserved readings survive
                # (rule A: a verdict is a visitor act).
                self._conn.execute(
                    "DELETE FROM steward_review_verdicts "
                    "WHERE user_id = ? AND item_kind = 'reading' "
                    f"AND item_id IN ({placeholders})",
                    (user_id, *proposed_ids),
                )
            deleted_verdict = 0
            if operation == "full_delete":
                verdict_ids = preview.get(
                    "preserved_verdict_reading_ids", []
                )
                if verdict_ids:
                    placeholders = ", ".join("?" for _ in verdict_ids)
                    cursor = self._conn.execute(
                        "DELETE FROM thread_readings WHERE id IN "
                        f"({placeholders}) AND thread_id IN (SELECT id "
                        "FROM narrative_threads WHERE user_id = ?)",
                        (*verdict_ids, user_id),
                    )
                    deleted_verdict = cursor.rowcount
                    self._conn.execute(
                        "DELETE FROM steward_signal_states "
                        "WHERE user_id = ? AND signal_kind = 'reading' "
                        f"AND signal_id IN ({placeholders})",
                        (user_id, *verdict_ids),
                    )
                    # Phase 1: verdict rows follow their items —
                    # full deletion removes the verdict-state
                    # readings, so their verdict rows go too.
                    self._conn.execute(
                        "DELETE FROM steward_review_verdicts "
                        "WHERE user_id = ? AND item_kind = 'reading' "
                        f"AND item_id IN ({placeholders})",
                        (user_id, *verdict_ids),
                    )
            self._conn.commit()
        deleted_declines = 0
        if operation == "full_delete":
            with self._lock:
                cursor = self._conn.execute(
                    "DELETE FROM steward_dismissals WHERE user_id = ?",
                    (user_id,),
                )
                # Phase 7: sweep the layer-completion tables by
                # user on full delete (thread deletion above
                # already cascades thread-owned rows and cited
                # correspondences; this covers any orphan).
                for table in (
                    "steward_correspondences",
                    "steward_correspondence_responses",
                    "steward_oversight_proposals",
                    "steward_reading_reconsiderations",
                ):
                    self._conn.execute(
                        f"DELETE FROM {table} WHERE user_id = ?",
                        (user_id,),
                    )
                self._conn.commit()
            deleted_declines = cursor.rowcount
        return {
            "operation": operation,
            "preview": preview,
            "deleted_thread_ids": deleted_threads,
            "deleted_observable_count": deleted_observables,
            "deleted_candidate_count": deleted_candidates["candidates"],
            "deleted_candidate_sighting_count": deleted_candidates[
                "sightings"
            ],
            "deleted_proposed_reading_count": deleted_proposed,
            "deleted_verdict_reading_count": deleted_verdict,
            "deleted_decline_count": deleted_declines,
        }

    def _delete_candidate_family(self, user_id: str) -> dict[str, int]:
        """Delete the user's whole candidate-mention family
        (mentions, sightings, membership links, acts) in one
        transaction. The clear operations' candidate step
        (Steward D1, packet §8.2 point 4); Scope S erasure
        reaches the same tables through _ERASURE_USER_TABLES."""
        out = {"candidates": 0, "sightings": 0, "membership": 0, "acts": 0}
        with self._lock, _atomic(self._conn):
            for table, key in (
                ("steward_candidate_membership", "membership"),
                ("steward_candidate_acts", "acts"),
                ("steward_candidate_sightings", "sightings"),
                ("steward_candidate_mentions", "candidates"),
            ):
                cursor = self._conn.execute(
                    f"DELETE FROM {table} WHERE user_id = ?",
                    (user_id,),
                )
                out[key] = cursor.rowcount
        return out

    def erase_user_material(
        self,
        user_id: str,
        *,
        erased_at: str | None = None,
        operation_id: str = "",
        log_path: str | Path | None = None,
    ) -> dict:
        """Full-record erasure of the user's narrative material
        (Steward D2, packet §6.2.1) — a THIRD operation beside
        routine clear and full delete, which keep their current
        semantics byte-for-byte.

        Deletes ALL of the user's threads regardless of origin
        (including user-declared and discovery threads, and
        verdict-state readings routine clear would preserve) via
        the delete_thread cascade, then user-wide deletes of every
        remaining §2.3 row family: involvement measures, dismissals
        (both regimes), all deferred prose, all observables
        (including meeting-scoped), all signal states, relevance
        assessments INCLUDING NULL-thread rows and their flags,
        verdict rows, correspondences + responses, oversight
        proposals, reconsiderations, links, artifacts + versions.
        Writes the §4 erasure tombstone (first writer wins: the
        wired flow writes it first, at the operation record's T)
        and advances the processing position to end-of-log, so a
        surviving log cannot silently resurrect the record on the
        next pass (the eligibility filter is the second line, not
        a substitute for the watermark). Consent flags are neither
        read nor written here — gate and watermark are independent
        conditions.

        The inventory is computed fresh with no thread cap (the
        preview path's limit=None fix, §6.2.1) and is counts-only:
        no thread ids or titles leave this method, and no preview
        is persisted anywhere (§4). Returns the executed counts
        (recount difference), the standing tombstone, and whether
        the position advanced.
        """
        before = self.erasure_recount(user_id)
        threads = self.threads_for(user_id, limit=None)
        deleted_threads = 0
        for thread in threads:
            if self.delete_thread(user_id, thread.id):
                deleted_threads += 1
        with self._lock, _atomic(self._conn):
            # User-wide sweep of everything the cascade cannot
            # reach (NULL-thread rows, user-keyed families) plus an
            # orphan sweep of thread-keyed tables whose thread is
            # gone (any user's cascade leaves none, but an
            # interrupted earlier erase might).
            for table in _ERASURE_USER_TABLES:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE user_id = ?",
                    (user_id,),
                )
            for table in _ERASURE_THREAD_KEYED_TABLES:
                self._conn.execute(
                    f"DELETE FROM {table} WHERE thread_id NOT IN "
                    "(SELECT id FROM narrative_threads)",
                )
            self._conn.execute(
                "DELETE FROM steward_artifact_versions WHERE "
                "artifact_id NOT IN (SELECT id FROM steward_artifacts)",
            )
            tombstone = self._erasure_tombstone_locked(user_id)
            if tombstone is None:
                self._conn.execute(
                    "INSERT INTO steward_erasure_tombstones (user_id, "
                    "erased_at, operation_id, counts_json, created_at) "
                    "VALUES (?, ?, ?, '{}', ?)",
                    (
                        user_id,
                        erased_at or _utcnow(),
                        operation_id,
                        _utcnow(),
                    ),
                )
                tombstone = self._erasure_tombstone_locked(user_id)
        after = self.erasure_recount(user_id)
        per_table = {
            table: before.get(table, 0) - after.get(table, 0)
            for table in before
            if table != "total"
        }
        # Watermark: advance the read position to end-of-log
        # (cursor discipline preserved — this is its own commit,
        # after the deletion commits, via set_processing_position).
        position_advanced = False
        try:
            if log_path is None:
                from local_ai.activity import _activity_log_path

                log_file = Path(_activity_log_path())
            else:
                log_file = Path(log_path)
            stat = log_file.stat()
            self.set_processing_position(
                user_id,
                stat.st_size,
                f"{stat.st_dev}:{stat.st_ino}",
            )
            position_advanced = True
        except OSError:
            # No log to watermark against; the eligibility filter
            # still guards any later rescan. Reported, not hidden.
            position_advanced = False
        return {
            "threads_deleted": deleted_threads,
            "rows_deleted": before["total"] - after["total"],
            "per_table": per_table,
            "recount_after": after,
            "tombstone": tombstone,
            "position_advanced": position_advanced,
        }

    # -- erasure (Steward D2, packet §§6.2/8.2/9.4/9.5) --------------------

    def get_erasure_tombstone(self, user_id: str) -> dict | None:
        """The user's erasure tombstone (content-free residue), or
        None when no erasure stands for them in this store."""
        with self._lock:
            return self._erasure_tombstone_locked(user_id)

    def write_erasure_tombstone(
        self, user_id: str, erased_at: str, operation_id: str = ""
    ) -> dict:
        """Write the tombstone if none stands (first writer wins).

        The boundary is fixed by the first write — the signed
        operation record's T, written by the wired flow before any
        content step (§8.2 step 2) or recovered by the barrier-
        integrity check (§9.4). A standing tombstone is returned
        unchanged; reconciliation to a different T is a separate,
        explicit act (rewrite_erasure_tombstone) taken only under
        the operation record's authority.
        """
        with self._lock, _atomic(self._conn):
            existing = self._erasure_tombstone_locked(user_id)
            if existing is None:
                self._conn.execute(
                    "INSERT INTO steward_erasure_tombstones (user_id, "
                    "erased_at, operation_id, counts_json, created_at) "
                    "VALUES (?, ?, ?, '{}', ?)",
                    (user_id, erased_at, operation_id, _utcnow()),
                )
                existing = self._erasure_tombstone_locked(user_id)
        return existing

    def rewrite_erasure_tombstone(
        self, user_id: str, erased_at: str, operation_id: str = ""
    ) -> dict:
        """Reconcile the tombstone to the operation record's T.

        Only the wired flow's pre-step and the barrier-integrity
        recovery call this, and only against a signature-verified
        operation record (§9.4): a timestamp is never chosen here,
        only copied from the authoritative record.
        """
        with self._lock, _atomic(self._conn):
            self._conn.execute(
                "INSERT INTO steward_erasure_tombstones (user_id, "
                "erased_at, operation_id, counts_json, created_at) "
                "VALUES (?, ?, ?, '{}', ?) ON CONFLICT(user_id) DO "
                "UPDATE SET erased_at = excluded.erased_at, "
                "operation_id = excluded.operation_id",
                (user_id, erased_at, operation_id, _utcnow()),
            )
            row = self._erasure_tombstone_locked(user_id)
        return row

    def set_erasure_tombstone_counts(
        self, user_id: str, counts: dict[str, int]
    ) -> None:
        """Record the executed counts on the tombstone (§4 residue:
        the tombstone carries the same counts the receipt carries)."""
        with self._lock, _atomic(self._conn):
            self._conn.execute(
                "UPDATE steward_erasure_tombstones SET counts_json = ? "
                "WHERE user_id = ?",
                (json.dumps(counts, ensure_ascii=False), user_id),
            )

    def vacuum(self) -> None:
        """VACUUM the database (packet §8.2 step 5: file hygiene —
        reclaimed pages stop carrying deleted bytes in THIS file;
        never evidence about backups or other media)."""
        with self._lock:
            # Routed like every flow-invoked site (Gate B Inc 1
            # §3.4) — and never suppressed in practice: VACUUM runs
            # outside any boundary, as today, so the routing passes
            # through.
            self.boundary_state.commit(self._conn)
            self._conn.execute("VACUUM")

    def erasure_recount(self, user_id: str) -> dict[str, int]:
        """Independent recount of everything the erase covers.

        Counts the user's rows in every table §2.3 names, thread-
        keyed tables counted through the user's threads. Used by
        the wired flow's verification step (§§8.2/9.5): a store is
        verified when this recount is zero outside the permitted
        residue (the tombstone and the processing-position row are
        not counted here at all).
        """
        counts: dict[str, int] = {}
        with self._lock:
            counts["narrative_threads"] = self._conn.execute(
                "SELECT COUNT(*) FROM narrative_threads WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
            for table in _ERASURE_THREAD_KEYED_TABLES:
                counts[table] = self._conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE thread_id IN "
                    "(SELECT id FROM narrative_threads WHERE user_id = ?)",
                    (user_id,),
                ).fetchone()[0]
            for table in _ERASURE_USER_TABLES:
                counts[table] = self._conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?",
                    (user_id,),
                ).fetchone()[0]
        counts["total"] = sum(counts.values())
        return counts

    def delete_rows_for_audit(
        self,
        user_id: str,
        *,
        reading_ids: Iterable[str] = (),
        change_ids: Iterable[str] = (),
        deferred_ids: Iterable[str] = (),
        observable_ids: Iterable[str] = (),
    ) -> dict[str, int]:
        """Delete individually named derived rows (the §9.5 audit's
        mop-up). Scoped to the user's own rows; delivery-state rows
        for deleted readings/observables go with them, mirroring
        the clear operations' hygiene. Returns per-family counts.
        """
        out = {"readings": 0, "changes": 0, "deferred": 0, "observables": 0}
        reading_ids = list(reading_ids)
        change_ids = list(change_ids)
        deferred_ids = list(deferred_ids)
        observable_ids = list(observable_ids)
        with self._lock, _atomic(self._conn):
            if reading_ids:
                ph = ", ".join("?" for _ in reading_ids)
                cur = self._conn.execute(
                    f"DELETE FROM thread_readings WHERE id IN ({ph}) "
                    "AND thread_id IN (SELECT id FROM narrative_threads "
                    "WHERE user_id = ?)",
                    (*reading_ids, user_id),
                )
                out["readings"] = cur.rowcount
                self._conn.execute(
                    "DELETE FROM steward_signal_states WHERE user_id = ? "
                    "AND signal_kind = 'reading' AND signal_id IN "
                    f"({ph})",
                    (user_id, *reading_ids),
                )
            if change_ids:
                ph = ", ".join("?" for _ in change_ids)
                cur = self._conn.execute(
                    f"DELETE FROM thread_changes WHERE id IN ({ph}) "
                    "AND thread_id IN (SELECT id FROM narrative_threads "
                    "WHERE user_id = ?)",
                    (*change_ids, user_id),
                )
                out["changes"] = cur.rowcount
            if deferred_ids:
                ph = ", ".join("?" for _ in deferred_ids)
                cur = self._conn.execute(
                    f"DELETE FROM steward_deferred_prose WHERE id IN "
                    f"({ph}) AND user_id = ?",
                    (*deferred_ids, user_id),
                )
                out["deferred"] = cur.rowcount
            if observable_ids:
                ph = ", ".join("?" for _ in observable_ids)
                doomed_keys = [
                    row["signal_key"]
                    for row in self._conn.execute(
                        f"SELECT signal_key FROM steward_observables "
                        f"WHERE id IN ({ph}) AND user_id = ?",
                        (*observable_ids, user_id),
                    ).fetchall()
                ]
                cur = self._conn.execute(
                    f"DELETE FROM steward_observables WHERE id IN "
                    f"({ph}) AND user_id = ?",
                    (*observable_ids, user_id),
                )
                out["observables"] = cur.rowcount
                if doomed_keys:
                    kph = ", ".join("?" for _ in doomed_keys)
                    self._conn.execute(
                        "DELETE FROM steward_signal_states WHERE "
                        "user_id = ? AND signal_kind = 'observable' "
                        f"AND signal_id IN ({kph})",
                        (user_id, *doomed_keys),
                    )
        return out

    # -- candidate mentions (Steward D1, packet Rev 1 §§3/5) ---------------
    #
    # Recognition is not identification: these methods keep an
    # attributed recurrence of the visitor's own words and nothing
    # more. Capture is the only writer in the first scope, and it
    # confers exactly one standing — ``candidate``. No method here
    # reads or writes VE, resolves an identity, or transitions a
    # standing; ``retired`` is reachable only through
    # retire_candidate, a user-act surface the delivery scope owns.

    def capture_sightings(
        self,
        user_id: str,
        sightings: Iterable[dict[str, Any]],
        *,
        admitted_sources: Iterable[tuple[str, str, str]] | None = None,
    ) -> dict[str, int]:
        """Accumulate one batch of mention sightings (packet §5).

        The derivation funnel for candidate capture: one call per
        batch, inside the store lock, in one transaction. Each
        input dict carries ``ref_kind`` / ``ref_id`` (the source
        event citation), ``normalized_form`` / ``surface_form``,
        ``conversation_id``, and ``seen_at`` (the event's own
        timestamp). Per form, in order:

        - a standing candidate dismissal over the form (§6.3's
          rail, signature = the normalized form) writes NOTHING —
          no sighting, no candidate;
        - a form whose sole claimant is ``confirmed`` or
          ``promoted`` is spoken for and writes nothing (§5.3
          rule 1; fulfilled, not dismissed);
        - the sighting insert is insert-or-ignore on
          ``UNIQUE (user_id, ref_kind, ref_id, normalized_form)``
          — the sighting row is capture's coverage record, so a
          reprocessed event (live-after-sweep, crash rescan)
          writes nothing and its assignment is never re-evaluated
          (§5.2 as revised; assignment lives in the membership
          link, outside the key);
        - a newly written sighting is routed fresh (§5.3): zero
          claimants → a new candidate is created and linked;
          exactly one → linked to it; two or more → written
          UNLINKED (the holding pool: counted nowhere, eligible
          for nothing, until a user act links it).

        ``mention_count`` / ``first_seen_at`` / ``last_seen_at``
        are refreshed by recount over current links in the same
        transaction — the count is defined over links (§3.4),
        never trusted as an increment.

        ``admitted_sources`` is the D2 eligibility manifest for
        this call (packet §8.2 point 2): consulted only when an
        erasure tombstone stands; then every sighting's source
        event must be attested, and the §9.2 triggers re-verify
        at insert time.
        """
        admitted = (
            list(admitted_sources) if admitted_sources is not None else None
        )
        report = {
            "sightings_written": 0,
            "sightings_duplicate": 0,
            "sightings_unlinked": 0,
            "forms_dismissed": 0,
            "forms_spoken_for": 0,
            "candidates_created": 0,
        }
        now = _utcnow()
        with self._lock, _atomic(self._conn):
            run_id = self._manifest_begin_locked(user_id, admitted)
            for sighting in sightings:
                ref_kind = str(sighting["ref_kind"])
                ref_id = str(sighting["ref_id"])
                form = str(sighting["normalized_form"])
                if run_id is not None:
                    self._manifest_require_locked(
                        run_id, user_id, [(ref_kind, ref_id)]
                    )
                dismissed = self._conn.execute(
                    "SELECT 1 FROM steward_dismissals WHERE user_id = ? "
                    "AND kind = 'candidate_mention' AND signature = ?",
                    (user_id, form),
                ).fetchone()
                if dismissed is not None:
                    report["forms_dismissed"] += 1
                    continue
                claimants = self._candidate_claimants_locked(user_id, form)
                if len(claimants) == 1 and claimants[0].status in (
                    "confirmed",
                    "promoted",
                ):
                    report["forms_spoken_for"] += 1
                    continue
                sighting_id = _new_id("sgt")
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO steward_candidate_sightings "
                    "(id, user_id, ref_kind, ref_id, normalized_form, "
                    "surface_form, conversation_id, seen_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sighting_id,
                        user_id,
                        ref_kind,
                        ref_id,
                        form,
                        str(sighting["surface_form"]),
                        str(sighting.get("conversation_id") or ""),
                        str(sighting.get("seen_at") or ""),
                        now,
                    ),
                )
                if cursor.rowcount == 0:
                    report["sightings_duplicate"] += 1
                    continue
                report["sightings_written"] += 1
                if len(claimants) >= 2:
                    report["sightings_unlinked"] += 1
                    continue
                if not claimants:
                    candidate = CandidateMention(
                        id=_new_id("cand"),
                        user_id=user_id,
                        surface_form=str(sighting["surface_form"]),
                        normalized_form=form,
                        created_at=now,
                        updated_at=now,
                    )
                    self._conn.execute(
                        "INSERT INTO steward_candidate_mentions (id, "
                        "user_id, surface_form, normalized_form, status, "
                        "ask_state, mention_count, first_seen_at, "
                        "last_seen_at, promoted_person_ref, "
                        "promotion_intent_json, user_label, created_at, "
                        "updated_at) VALUES (?, ?, ?, ?, 'candidate', "
                        "'not_asked', 0, '', '', NULL, '{}', NULL, ?, ?)",
                        (
                            candidate.id,
                            user_id,
                            candidate.surface_form,
                            form,
                            now,
                            now,
                        ),
                    )
                    report["candidates_created"] += 1
                else:
                    candidate = claimants[0]
                self._conn.execute(
                    "INSERT INTO steward_candidate_membership (id, "
                    "user_id, sighting_id, candidate_id, assigned_by, "
                    "act_id, created_at, superseded_at) VALUES "
                    "(?, ?, ?, ?, 'capture', NULL, ?, NULL)",
                    (_new_id("mbr"), user_id, sighting_id, candidate.id, now),
                )
                self._refresh_candidate_locked(user_id, candidate.id, now)
            self._manifest_end_locked(run_id)
        return report

    def _candidate_claimants_locked(
        self, user_id: str, normalized_form: str
    ) -> list[CandidateMention]:
        """The form's claimants, evaluated fresh (packet §5.3):
        the non-retired candidates whose normalized form equals
        the form, plus non-retired candidates holding a
        user-authored alias for it (an ``alias`` acts row naming
        the form and the candidate). An alias routes only while
        it is the form's sole claimant — that is this evaluation's
        output, not a stored flag. Lock held."""
        by_id: dict[str, CandidateMention] = {}
        rows = self._conn.execute(
            "SELECT * FROM steward_candidate_mentions WHERE user_id = ? "
            "AND normalized_form = ? AND status != 'retired' "
            "ORDER BY created_at, id",
            (user_id, normalized_form),
        ).fetchall()
        for row in rows:
            candidate = _row_to_candidate(row)
            by_id[candidate.id] = candidate
        alias_rows = self._conn.execute(
            "SELECT c.* FROM steward_candidate_acts a "
            "JOIN steward_candidate_mentions c "
            "ON c.id = json_extract(a.detail_json, '$.candidate_id') "
            "WHERE a.user_id = ? AND a.kind = 'alias' "
            "AND json_extract(a.detail_json, '$.form') = ? "
            "AND c.user_id = ? AND c.status != 'retired' "
            "ORDER BY c.created_at, c.id",
            (user_id, normalized_form, user_id),
        ).fetchall()
        for row in alias_rows:
            candidate = _row_to_candidate(row)
            by_id.setdefault(candidate.id, candidate)
        return list(by_id.values())

    def _refresh_candidate_locked(
        self, user_id: str, candidate_id: str, now: str
    ) -> None:
        """Recompute a candidate's count and seen-span by recount
        over its CURRENT links (packet §3.4: the count is defined
        over links, asserted by recount, never incremented).
        Lock held, inside the caller's transaction."""
        self._conn.execute(
            "UPDATE steward_candidate_mentions SET "
            "mention_count = (SELECT COUNT(*) FROM "
            "steward_candidate_membership m WHERE m.candidate_id = ? "
            "AND m.superseded_at IS NULL), "
            "first_seen_at = COALESCE((SELECT MIN(s.seen_at) FROM "
            "steward_candidate_membership m JOIN "
            "steward_candidate_sightings s ON s.id = m.sighting_id "
            "WHERE m.candidate_id = ? AND m.superseded_at IS NULL), ''), "
            "last_seen_at = COALESCE((SELECT MAX(s.seen_at) FROM "
            "steward_candidate_membership m JOIN "
            "steward_candidate_sightings s ON s.id = m.sighting_id "
            "WHERE m.candidate_id = ? AND m.superseded_at IS NULL), ''), "
            "updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (candidate_id, candidate_id, candidate_id, now, candidate_id,
             user_id),
        )

    def candidates_for(self, user_id: str) -> list[CandidateMention]:
        """All of the user's candidates, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_candidate_mentions "
                "WHERE user_id = ? ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
        return [_row_to_candidate(r) for r in rows]

    def get_candidate(
        self, user_id: str, candidate_id: str
    ) -> CandidateMention | None:
        """One candidate, or None — a candidate owned by another
        user reads as absent (the store's ownership discipline)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_candidate_mentions "
                "WHERE id = ? AND user_id = ?",
                (candidate_id, user_id),
            ).fetchone()
        return _row_to_candidate(row) if row is not None else None

    def sightings_for(self, user_id: str) -> list[CandidateSighting]:
        """All of the user's sightings, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_candidate_sightings "
                "WHERE user_id = ? ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
        return [_row_to_sighting(r) for r in rows]

    def sightings_for_candidate(
        self, user_id: str, candidate_id: str
    ) -> list[CandidateSighting]:
        """The candidate's CURRENTLY LINKED sightings (superseded
        assignments are history, not membership), by event time."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.* FROM steward_candidate_sightings s "
                "JOIN steward_candidate_membership m "
                "ON m.sighting_id = s.id AND m.superseded_at IS NULL "
                "WHERE s.user_id = ? AND m.candidate_id = ? "
                "ORDER BY s.seen_at, s.id",
                (user_id, candidate_id),
            ).fetchall()
        return [_row_to_sighting(r) for r in rows]

    def unlinked_sightings_for(
        self, user_id: str
    ) -> list[CandidateSighting]:
        """The holding pool (packet §5.3 rule 4): sightings with
        no current membership link. They count toward no
        candidate and feed no eligibility computation."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.* FROM steward_candidate_sightings s "
                "WHERE s.user_id = ? AND NOT EXISTS ("
                "SELECT 1 FROM steward_candidate_membership m "
                "WHERE m.sighting_id = s.id "
                "AND m.superseded_at IS NULL) "
                "ORDER BY s.created_at, s.id",
                (user_id,),
            ).fetchall()
        return [_row_to_sighting(r) for r in rows]

    def membership_for_sighting(
        self, user_id: str, sighting_id: str
    ) -> list[CandidateMembership]:
        """A sighting's full assignment history — current and
        superseded links, oldest first (packet §3.4: provenance
        is reconstructible from links + acts, never rewritten)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_candidate_membership "
                "WHERE user_id = ? AND sighting_id = ? "
                "ORDER BY created_at, id",
                (user_id, sighting_id),
            ).fetchall()
        return [_row_to_membership(r) for r in rows]

    def candidate_acts_for(self, user_id: str) -> list[CandidateAct]:
        """All of the user's candidate acts-log rows."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_candidate_acts "
                "WHERE user_id = ? ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
        return [_row_to_candidate_act(r) for r in rows]

    def retire_candidate(self, user_id: str, candidate_id: str) -> bool:
        """Retire a candidate (a user act's store primitive —
        packet §6.3; the delivery scope owns the surfaces that
        call this; capture never does). Sightings and links are
        untouched: retirement changes standing, not provenance.
        True when a standing candidate was retired."""
        now = _utcnow()
        with self._lock, _atomic(self._conn):
            cursor = self._conn.execute(
                "UPDATE steward_candidate_mentions SET status = "
                "'retired', updated_at = ? WHERE id = ? AND user_id = ? "
                "AND status != 'retired'",
                (now, candidate_id, user_id),
            )
        return cursor.rowcount == 1

    def delete_candidates_for_audit(
        self,
        user_id: str,
        *,
        sighting_ids: Iterable[str] = (),
        candidate_ids: Iterable[str] = (),
    ) -> dict[str, int]:
        """Delete individually named candidate-family rows (the
        §9.5 provenance audit's mop-up, packet §8.2 point 3).
        Scoped to the user's own rows. Deleting a sighting
        deletes its membership links; deleting a candidate
        deletes its links and the acts rows that name it (the
        acts log is provenance OF the registry — under erasure
        verification it follows the records it governed)."""
        out = {"sightings": 0, "candidates": 0, "membership": 0, "acts": 0}
        sighting_ids = list(sighting_ids)
        candidate_ids = list(candidate_ids)
        with self._lock, _atomic(self._conn):
            if sighting_ids:
                ph = ", ".join("?" for _ in sighting_ids)
                cur = self._conn.execute(
                    "DELETE FROM steward_candidate_membership "
                    f"WHERE user_id = ? AND sighting_id IN ({ph})",
                    (user_id, *sighting_ids),
                )
                out["membership"] += cur.rowcount
                cur = self._conn.execute(
                    "DELETE FROM steward_candidate_sightings "
                    f"WHERE user_id = ? AND id IN ({ph})",
                    (user_id, *sighting_ids),
                )
                out["sightings"] = cur.rowcount
            if candidate_ids:
                ph = ", ".join("?" for _ in candidate_ids)
                cur = self._conn.execute(
                    "DELETE FROM steward_candidate_membership "
                    f"WHERE user_id = ? AND candidate_id IN ({ph})",
                    (user_id, *candidate_ids),
                )
                out["membership"] += cur.rowcount
                for candidate_id in candidate_ids:
                    cur = self._conn.execute(
                        "DELETE FROM steward_candidate_acts WHERE "
                        "user_id = ? AND detail_json LIKE ?",
                        (user_id, f"%{candidate_id}%"),
                    )
                    out["acts"] += cur.rowcount
                cur = self._conn.execute(
                    "DELETE FROM steward_candidate_mentions "
                    f"WHERE user_id = ? AND id IN ({ph})",
                    (user_id, *candidate_ids),
                )
                out["candidates"] = cur.rowcount
        return out

    # -- increment D: snapshot read + delivery state ------------------------

    def snapshot_for_read(self, user_id: str) -> dict:
        """One consistent read of everything the D read model serves.

        Increment D (proposal §4.6): ALL narrative-store reads for
        one response happen under ONE acquisition of the store lock,
        via raw SELECTs here — never by calling the lock-acquiring
        list methods (the lock is a plain non-reentrant
        threading.Lock; re-entering it would deadlock). The caller
        (read_model) assembles envelopes from this snapshot with
        pure Python: no further store calls, so consultation,
        content, and totals cohere. The snapshot is detached rows,
        safe to use after the connection closes. No writes of any
        kind: no clock touches, no cursor moves, no delivery
        transitions.

        Returns a dict with keys: threads, evidence, readings,
        changes, observables, dismissals, suppressed (deferred-prose
        rows settled as suppressed_by_decline), delivery
        ({(kind, signal_id): status}).
        """
        with self._lock:
            thread_rows = self._conn.execute(
                "SELECT * FROM narrative_threads WHERE user_id = ? "
                "ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
            thread_ids = [r["id"] for r in thread_rows]
            if thread_ids:
                placeholders = ", ".join("?" for _ in thread_ids)
                evidence_rows = self._conn.execute(
                    "SELECT * FROM thread_evidence WHERE thread_id IN "
                    f"({placeholders}) ORDER BY created_at, id",
                    thread_ids,
                ).fetchall()
                reading_rows = self._conn.execute(
                    "SELECT * FROM thread_readings WHERE thread_id IN "
                    f"({placeholders}) ORDER BY created_at, id",
                    thread_ids,
                ).fetchall()
                change_rows = self._conn.execute(
                    "SELECT * FROM thread_changes WHERE thread_id IN "
                    f"({placeholders}) ORDER BY created_at, id",
                    thread_ids,
                ).fetchall()
            else:
                evidence_rows = []
                reading_rows = []
                change_rows = []
            observable_rows = self._conn.execute(
                "SELECT * FROM steward_observables WHERE user_id = ? "
                "ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
            dismissal_rows = self._conn.execute(
                "SELECT * FROM steward_dismissals WHERE user_id = ? "
                "ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
            suppressed_rows = self._conn.execute(
                "SELECT * FROM steward_deferred_prose WHERE user_id = ? "
                "AND status = 'suppressed_by_decline' "
                "ORDER BY created_at, id",
                (user_id,),
            ).fetchall()
            delivery_rows = self._conn.execute(
                "SELECT * FROM steward_signal_states WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {
            "threads": [_row_to_thread(r) for r in thread_rows],
            "evidence": [_row_to_evidence(r) for r in evidence_rows],
            "readings": [_row_to_reading(r) for r in reading_rows],
            "changes": [_row_to_change(r) for r in change_rows],
            "observables": [_row_to_observable(r) for r in observable_rows],
            "dismissals": [_row_to_dismissal(r) for r in dismissal_rows],
            "suppressed": [dict(r) for r in suppressed_rows],
            "delivery": {
                (r["signal_kind"], r["signal_id"]): r["delivery_status"]
                for r in delivery_rows
            },
        }

    def set_signal_delivery(
        self,
        user_id: str,
        *,
        signal_kind: str,
        signal_id: str,
        delivery_status: str,
        updated_by: str = "visitor",
    ) -> dict:
        """Record one delivery transition (increment D §3.7).

        This is the ONLY writer of delivery state, and it is NOT
        called by the read model or the route — E's actions (and
        later H's dialogue markers) call it. Participation is
        enforced: readings participate only when steward- or
        seat-authored (user-authored readings have nothing to
        deliver to their author); observables always participate;
        every other kind raises ValueError, as do unknown signals,
        cross-user signals, unknown statuses, backward transitions,
        and any transition out of dismissed. Same-state sets are
        idempotent no-ops. Returns the stored row as a dict.
        """
        if delivery_status not in DELIVERY_STATUSES:
            raise ValueError(f"unknown delivery status: {delivery_status!r}")
        with self._lock:
            if signal_kind == "reading":
                row = self._conn.execute(
                    "SELECT r.* FROM thread_readings r JOIN "
                    "narrative_threads t ON t.id = r.thread_id "
                    "WHERE r.id = ? AND t.user_id = ?",
                    (signal_id, user_id),
                ).fetchone()
                if row is None:
                    raise ValueError(f"unknown reading: {signal_id!r}")
                if row["author"] == "user":
                    raise ValueError(
                        "user-authored readings do not participate "
                        "in delivery tracking"
                    )
            elif signal_kind == "observable":
                row = self._conn.execute(
                    "SELECT * FROM steward_observables "
                    "WHERE signal_key = ? AND user_id = ?",
                    (signal_id, user_id),
                ).fetchone()
                if row is None:
                    raise ValueError(f"unknown observable: {signal_id!r}")
            else:
                raise ValueError(
                    f"signal kind does not participate in delivery "
                    f"tracking: {signal_kind!r}"
                )
            existing = self._conn.execute(
                "SELECT delivery_status FROM steward_signal_states "
                "WHERE user_id = ? AND signal_kind = ? AND signal_id = ?",
                (user_id, signal_kind, signal_id),
            ).fetchone()
            if existing is not None:
                current = existing["delivery_status"]
                if (
                    delivery_status != current
                    and delivery_status
                    not in _DELIVERY_TRANSITIONS[current]
                ):
                    raise ValueError(
                        f"illegal delivery transition: {current!r} -> "
                        f"{delivery_status!r}"
                    )
            now = _utcnow()
            self._conn.execute(
                "INSERT INTO steward_signal_states "
                "(user_id, signal_kind, signal_id, delivery_status, "
                "updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, signal_kind, signal_id) DO UPDATE "
                "SET delivery_status = excluded.delivery_status, "
                "updated_at = excluded.updated_at, "
                "updated_by = excluded.updated_by",
                (
                    user_id,
                    signal_kind,
                    signal_id,
                    delivery_status,
                    now,
                    updated_by,
                ),
            )
            self._conn.commit()
            stored = self._conn.execute(
                "SELECT * FROM steward_signal_states "
                "WHERE user_id = ? AND signal_kind = ? AND signal_id = ?",
                (user_id, signal_kind, signal_id),
            ).fetchone()
        return dict(stored)

    # -- Phase 1: relevance assessments, discrepancy flags, review verdicts --
    # Append-only records. Assessments are never updated; a fresh
    # assessment supersedes by recency. Flags never adjudicate
    # themselves. Verdicts are a log. Nothing here transitions a
    # proposal row — review.py owns verdict-to-transition mapping.

    def record_relevance_assessment(
        self,
        user_id: str,
        branch_id: str,
        *,
        thread_id: str | None = None,
        evidence_refs: Iterable[str] = (),
        relevant: bool = False,
        reasons: Iterable[str] = (),
        inputs: dict | None = None,
    ) -> RelevanceAssessment:
        """Store one deterministic relevance assessment, append-only."""
        now = _utcnow()
        record = RelevanceAssessment(
            id=_new_id("asm"),
            user_id=user_id,
            branch_id=branch_id,
            thread_id=thread_id,
            evidence_refs=[str(r) for r in evidence_refs],
            relevant=bool(relevant),
            reasons=[str(r) for r in reasons],
            inputs=dict(inputs or {}),
            created_at=now,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO steward_relevance_assessments "
                "(id, user_id, branch_id, thread_id, evidence_refs_json, "
                "relevant, reasons_json, inputs_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    user_id,
                    branch_id,
                    thread_id,
                    json.dumps(record.evidence_refs),
                    1 if record.relevant else 0,
                    json.dumps(record.reasons),
                    json.dumps(record.inputs),
                    now,
                ),
            )
            self._conn.commit()
        return record

    def assessments_for(
        self,
        user_id: str,
        *,
        branch_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 100,
    ) -> list[RelevanceAssessment]:
        """Assessments for a user, newest first."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if branch_id is not None:
            clauses.append("branch_id = ?")
            args.append(branch_id)
        if thread_id is not None:
            clauses.append("thread_id = ?")
            args.append(thread_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_relevance_assessments WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC, id DESC LIMIT ?",
                [*args, limit],
            ).fetchall()
        return [
            RelevanceAssessment(
                id=row["id"],
                user_id=row["user_id"],
                branch_id=row["branch_id"],
                thread_id=row["thread_id"],
                evidence_refs=_loads(row["evidence_refs_json"], []),
                relevant=bool(row["relevant"]),
                reasons=_loads(row["reasons_json"], []),
                inputs=_loads(row["inputs_json"], {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def record_discrepancy_flag(
        self,
        user_id: str,
        assessment_id: str,
        branch_id: str,
        *,
        objection: str = "",
        evidence_refs: Iterable[str] = (),
    ) -> DiscrepancyFlag:
        """Record a flag-only discrepancy objection.

        The referenced assessment must exist for this user; the
        assessment row itself is never modified, so the original
        assessment is preserved alongside the objection. The flag
        changes no shared evidence and starts (and stays, in
        Phase 1) ``open``: there is no adjudication workflow.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM steward_relevance_assessments "
                "WHERE id = ? AND user_id = ?",
                (assessment_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"unknown relevance assessment for user: {assessment_id!r}"
                )
            now = _utcnow()
            record = DiscrepancyFlag(
                id=_new_id("flg"),
                user_id=user_id,
                assessment_id=assessment_id,
                branch_id=branch_id,
                objection=objection,
                evidence_refs=[str(r) for r in evidence_refs],
                status="open",
                created_at=now,
            )
            self._conn.execute(
                "INSERT INTO steward_discrepancy_flags "
                "(id, user_id, assessment_id, branch_id, objection, "
                "evidence_refs_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    user_id,
                    assessment_id,
                    branch_id,
                    objection,
                    json.dumps(record.evidence_refs),
                    "open",
                    now,
                ),
            )
            self._conn.commit()
        return record

    def flags_for(
        self,
        user_id: str,
        *,
        assessment_id: str | None = None,
        branch_id: str | None = None,
    ) -> list[DiscrepancyFlag]:
        """Flags for a user, oldest first."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if assessment_id is not None:
            clauses.append("assessment_id = ?")
            args.append(assessment_id)
        if branch_id is not None:
            clauses.append("branch_id = ?")
            args.append(branch_id)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_discrepancy_flags WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        return [
            DiscrepancyFlag(
                id=row["id"],
                user_id=row["user_id"],
                assessment_id=row["assessment_id"],
                branch_id=row["branch_id"],
                objection=row["objection"],
                evidence_refs=_loads(row["evidence_refs_json"], []),
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def record_review_verdict(
        self,
        user_id: str,
        item_kind: str,
        item_id: str,
        verdict: str,
    ) -> ReviewVerdict:
        """Append one review verdict to the log.

        ``verdict`` follows the claim-verdict vocabulary: accepted,
        rejected, or unresolved (explicit not-deciding, recorded
        rather than silently skipped). Unresolved never transitions
        proposal state — review.py records it and stops there.
        """
        if item_kind not in (
            "birth", "reading", "change", "fitting", "revision",
            # Phase 7: oversight, correspondence, and
            # reconsideration proposals route through the same
            # review machinery (review.py ITEM_KINDS must match).
            "oversight", "correspondence", "reconsideration",
        ):
            raise ValueError(f"unknown review item kind: {item_kind!r}")
        if verdict not in ("accepted", "rejected", "unresolved"):
            raise ValueError(f"unknown review verdict: {verdict!r}")
        now = _utcnow()
        record = ReviewVerdict(
            id=_new_id("vrd"),
            user_id=user_id,
            item_kind=item_kind,
            item_id=item_id,
            verdict=verdict,
            created_at=now,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO steward_review_verdicts "
                "(id, user_id, item_kind, item_id, verdict, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    user_id,
                    item_kind,
                    item_id,
                    verdict,
                    now,
                ),
            )
            self._conn.commit()
        return record

    def verdicts_for(
        self,
        user_id: str,
        *,
        item_kind: str | None = None,
    ) -> list[ReviewVerdict]:
        """Verdict log for a user, oldest first."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if item_kind is not None:
            clauses.append("item_kind = ?")
            args.append(item_kind)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_review_verdicts WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        return [
            ReviewVerdict(
                id=row["id"],
                user_id=row["user_id"],
                item_kind=row["item_kind"],
                item_id=row["item_id"],
                verdict=row["verdict"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # -- card endorsement annotations (Phase 1A) ----------------------
    #
    # A dedicated dispatch path, structurally isolated from the
    # verdict path: these methods never call accept_reading /
    # reject_reading, never write thread_readings or
    # narrative_threads, and never move standing_reading_id. An
    # endorsement records the visitor's stance toward ONE reading
    # version; organic revision of that reading neither moves nor
    # removes the annotation (design Rev 6 §1: currency and
    # endorsement read disjoint inputs).

    def record_card_endorsement(
        self,
        user_id: str,
        reading_id: str,
        stance: str,
        note: str = "",
    ) -> dict:
        """Append one card endorsement annotation to the verdict log.

        The row carries ``item_kind = "card_endorsement"`` (see
        ``CARD_ENDORSEMENT_KIND``), the reading id as its item, and
        the stance + note encoded in the verdict column (see
        ``_decode_card_endorsement``). Raises ``ValueError`` for an
        unknown stance or a reading the user does not own.
        """
        if stance not in CARD_ENDORSEMENT_STANCES:
            raise ValueError(
                f"unknown card endorsement stance: {stance!r}"
            )
        with self._lock:
            row = self._conn.execute(
                "SELECT r.id FROM thread_readings r JOIN "
                "narrative_threads t ON t.id = r.thread_id "
                "WHERE r.id = ? AND t.user_id = ?",
                (reading_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown reading: {reading_id!r}")
            now = _utcnow()
            record_id = _new_id("vrd")
            self._conn.execute(
                "INSERT INTO steward_review_verdicts "
                "(id, user_id, item_kind, item_id, verdict, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    user_id,
                    CARD_ENDORSEMENT_KIND,
                    reading_id,
                    json.dumps(
                        {"stance": stance, "note": note or ""},
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
            self._conn.commit()
        return {
            "id": record_id,
            "user_id": user_id,
            "reading_id": reading_id,
            "stance": stance,
            "note": note or "",
            "created_at": now,
        }

    def card_endorsements_for(
        self, user_id: str, reading_id: str
    ) -> list[dict]:
        """Endorsement annotations on one reading version, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_review_verdicts WHERE "
                "user_id = ? AND item_kind = ? AND item_id = ? "
                "ORDER BY created_at, id",
                (user_id, CARD_ENDORSEMENT_KIND, reading_id),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            stance, note = _decode_card_endorsement(row["verdict"])
            out.append(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "reading_id": row["item_id"],
                    "stance": stance,
                    "note": note,
                    "created_at": row["created_at"],
                }
            )
        return out

    def proposal_precision(self, user_id: str) -> dict:
        """Proposal-precision metric from the verdict log (Phase 1).

        Precision = accepted / (accepted + rejected) over
        review-layer verdicts, per proposal kind and overall.
        Unresolved verdicts are recorded but excluded from both
        numerator and denominator — not deciding is not a
        rejection. With zero decided verdicts, precision is None
        (no data), never 0.

        The metric's inputs are verdict counts ONLY. Flags,
        disagreements, and cross-branch agreement are not inputs
        and cannot move it, so it cannot reward interpretive
        convergence (addendum I5).
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT item_kind, verdict, COUNT(*) AS n "
                "FROM steward_review_verdicts WHERE user_id = ? "
                "AND verdict IN ('accepted', 'rejected') "
                "GROUP BY item_kind, verdict",
                (user_id,),
            ).fetchall()
        per_kind: dict[str, dict] = {}
        total_accepted = 0
        total_rejected = 0
        for kind in (
            "birth", "reading", "change", "fitting", "revision",
            # Phase 7: the new proposal kinds count in precision
            # exactly like the old ones — verdicts on steward
            # proposals, never flags or agreement.
            "oversight", "correspondence", "reconsideration",
        ):
            accepted = 0
            rejected = 0
            for row in rows:
                if row["item_kind"] != kind:
                    continue
                if row["verdict"] == "accepted":
                    accepted = row["n"]
                elif row["verdict"] == "rejected":
                    rejected = row["n"]
            total = accepted + rejected
            per_kind[kind] = {
                "accepted": accepted,
                "rejected": rejected,
                "decided": total,
                "precision": (accepted / total) if total else None,
            }
            total_accepted += accepted
            total_rejected += rejected
        total = total_accepted + total_rejected
        return {
            "per_kind": per_kind,
            "overall": {
                "accepted": total_accepted,
                "rejected": total_rejected,
                "decided": total,
                "precision": (total_accepted / total) if total else None,
            },
        }

    # -- Phase 7: correspondences, oversight, reconsiderations ----------

    def create_correspondence(
        self,
        user_id: str,
        *,
        thread_ids: list[str],
        evidence_refs: list[str],
        structural_tension: str,
        proposed_relationship: str,
        candidate_metaphor: str | None = None,
        mapping: dict | None = None,
        limitations: str = "",
        supersedes_id: str | None = None,
    ) -> Correspondence:
        """Insert one proposed correspondence row.

        Validation of the §3 evidence rules (refs resolve to
        real thread_evidence rows spanning >= 2 threads) lives
        in correspondence.propose_correspondence; this writer
        only enforces row-level invariants: non-empty tension
        and relationship, and a supersedes target that exists
        and is not already terminal (it becomes superseded).
        The row is structure, never evidence: its id carries
        the "corr-" prefix and no path writes it into
        thread_evidence.
        """
        if not structural_tension or not proposed_relationship:
            raise ValueError(
                "a correspondence needs a structural tension and "
                "a proposed relationship"
            )
        with self._lock:
            if supersedes_id is not None:
                old = self._conn.execute(
                    "SELECT status FROM steward_correspondences "
                    "WHERE id = ? AND user_id = ?",
                    (supersedes_id, user_id),
                ).fetchone()
                if old is None:
                    raise ValueError(
                        f"unknown correspondence to supersede: "
                        f"{supersedes_id!r}"
                    )
                if old["status"] in ("rejected", "superseded"):
                    raise ValueError(
                        "a rejected or superseded correspondence "
                        "cannot be superseded again"
                    )
            now = _utcnow()
            record = Correspondence(
                id=_new_id("corr"),
                user_id=user_id,
                thread_ids=list(thread_ids),
                evidence_refs=list(evidence_refs),
                structural_tension=structural_tension,
                proposed_relationship=proposed_relationship,
                candidate_metaphor=candidate_metaphor,
                mapping=dict(mapping or {}),
                limitations=limitations,
                status="proposed",
                supersedes_id=supersedes_id,
                created_at=now,
            )
            self._conn.execute(
                "INSERT INTO steward_correspondences (id, user_id, "
                "thread_ids_json, evidence_refs_json, "
                "structural_tension, proposed_relationship, "
                "candidate_metaphor, mapping_json, limitations, "
                "status, supersedes_id, created_at, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    record.id, user_id,
                    json.dumps(record.thread_ids),
                    json.dumps(record.evidence_refs),
                    structural_tension, proposed_relationship,
                    candidate_metaphor,
                    json.dumps(record.mapping),
                    limitations, "proposed", supersedes_id, now,
                ),
            )
            if supersedes_id is not None:
                self._conn.execute(
                    "UPDATE steward_correspondences SET status = "
                    "'superseded', decided_at = ? WHERE id = ? "
                    "AND user_id = ?",
                    (now, supersedes_id, user_id),
                )
            self._conn.commit()
        return record

    def get_correspondence(
        self, user_id: str, correspondence_id: str
    ) -> Correspondence | None:
        """One correspondence row, or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_correspondences WHERE id = ? "
                "AND user_id = ?",
                (correspondence_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return Correspondence(
            id=row["id"], user_id=row["user_id"],
            thread_ids=json.loads(row["thread_ids_json"] or "[]"),
            evidence_refs=json.loads(row["evidence_refs_json"] or "[]"),
            structural_tension=row["structural_tension"],
            proposed_relationship=row["proposed_relationship"],
            candidate_metaphor=row["candidate_metaphor"],
            mapping=json.loads(row["mapping_json"] or "{}"),
            limitations=row["limitations"],
            status=row["status"],
            supersedes_id=row["supersedes_id"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
        )

    def correspondences_for(
        self, user_id: str, *, status: str | None = None
    ) -> list[Correspondence]:
        """Correspondences for a user, oldest first."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM steward_correspondences WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        out = []
        for row in rows:
            corr = self.get_correspondence(user_id, row["id"])
            if corr is not None:
                out.append(corr)
        return out

    def set_correspondence_status(
        self, user_id: str, correspondence_id: str, status: str
    ) -> Correspondence:
        """Move a correspondence through its §3 lifecycle.

        proposed -> user_accepted | rejected | superseded;
        user_accepted -> superseded. rejected and superseded
        are terminal. Only user verdicts (via review.py) move a
        correspondence to user_accepted/rejected; seat
        responses never call this.
        """
        from .models import CORRESPONDENCE_STATUSES

        if status not in CORRESPONDENCE_STATUSES:
            raise ValueError(f"unknown correspondence status: {status!r}")
        with self._lock:
            # Inline row fetch: get_correspondence takes the
            # store lock, and this lock is a plain Lock —
            # re-entering it would deadlock (see the lock's
            # own comment at init).
            row = self._conn.execute(
                "SELECT status FROM steward_correspondences "
                "WHERE id = ? AND user_id = ?",
                (correspondence_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"unknown correspondence: {correspondence_id!r}"
                )
            current_status = row["status"]
            allowed = {
                "proposed": ("user_accepted", "rejected", "superseded"),
                "user_accepted": ("superseded",),
                "rejected": (),
                "superseded": (),
            }[current_status]
            if status not in allowed and status != current_status:
                raise ValueError(
                    f"correspondence cannot move {current_status!r} "
                    f"-> {status!r}"
                )
            now = _utcnow()
            self._conn.execute(
                "UPDATE steward_correspondences SET status = ?, "
                "decided_at = ? WHERE id = ? AND user_id = ?",
                (
                    status,
                    now if status != "proposed" else None,
                    correspondence_id, user_id,
                ),
            )
            self._conn.commit()
        updated = self.get_correspondence(user_id, correspondence_id)
        assert updated is not None
        return updated

    def record_correspondence_response(
        self,
        user_id: str,
        correspondence_id: str,
        branch_id: str,
        response: str,
        expression: str = "",
    ) -> CorrespondenceResponse:
        """One seat's response to a correspondence (addendum §3).

        One row per (correspondence, branch): a seat revising
        its response replaces its own row. The response never
        moves the correspondence's status — only a user verdict
        does. A translate response without its own expression
        is refused: translation must carry the seat's own
        imagery, not an empty adoption of the steward's words.
        """
        from .models import CORRESPONDENCE_RESPONSES

        if response not in CORRESPONDENCE_RESPONSES:
            raise ValueError(
                f"unknown correspondence response: {response!r}"
            )
        if response == "translate" and not expression:
            raise ValueError(
                "a translate response must carry the seat's own "
                "expression"
            )
        with self._lock:
            # Inline existence check: get_correspondence takes
            # the store lock, and re-entering this plain Lock
            # would deadlock.
            exists = self._conn.execute(
                "SELECT id FROM steward_correspondences "
                "WHERE id = ? AND user_id = ?",
                (correspondence_id, user_id),
            ).fetchone()
            if exists is None:
                raise ValueError(
                    f"unknown correspondence: {correspondence_id!r}"
                )
            now = _utcnow()
            existing = self._conn.execute(
                "SELECT id FROM steward_correspondence_responses "
                "WHERE correspondence_id = ? AND branch_id = ?",
                (correspondence_id, branch_id),
            ).fetchone()
            if existing is not None:
                self._conn.execute(
                    "UPDATE steward_correspondence_responses SET "
                    "response = ?, expression = ?, created_at = ? "
                    "WHERE id = ?",
                    (response, expression, now, existing["id"]),
                )
                record_id = existing["id"]
            else:
                record_id = _new_id("cresp")
                self._conn.execute(
                    "INSERT INTO steward_correspondence_responses "
                    "(id, correspondence_id, user_id, branch_id, "
                    "response, expression, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        record_id, correspondence_id, user_id,
                        branch_id, response, expression, now,
                    ),
                )
            self._conn.commit()
        return CorrespondenceResponse(
            id=record_id,
            correspondence_id=correspondence_id,
            user_id=user_id,
            branch_id=branch_id,
            response=response,
            expression=expression,
            created_at=now,
        )

    def responses_for(
        self, user_id: str, correspondence_id: str
    ) -> list[CorrespondenceResponse]:
        """Seat responses to one correspondence, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_correspondence_responses "
                "WHERE correspondence_id = ? AND user_id = ? "
                "ORDER BY created_at, id",
                (correspondence_id, user_id),
            ).fetchall()
        return [
            CorrespondenceResponse(
                id=row["id"],
                correspondence_id=row["correspondence_id"],
                user_id=row["user_id"],
                branch_id=row["branch_id"],
                response=row["response"],
                expression=row["expression"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_oversight_proposal(
        self,
        user_id: str,
        thread_id: str,
        kind: str,
        reason: str = "",
        detail: dict | None = None,
    ) -> OversightProposal:
        """Insert one oversight proposal, or return the existing
        proposed one for the same (thread, kind).

        Dedupe is load-bearing for oversight: a detector that
        re-fires on unchanged state must not stack identical
        proposals in the review queue. A decided (confirmed /
        dismissed) proposal does not block a fresh one — new
        state may warrant a new observation.
        """
        from .models import OVERSIGHT_KINDS

        if kind not in OVERSIGHT_KINDS:
            raise ValueError(f"unknown oversight kind: {kind!r}")
        with self._lock:
            self._require_thread(user_id, thread_id)
            existing = self._conn.execute(
                "SELECT * FROM steward_oversight_proposals "
                "WHERE user_id = ? AND thread_id = ? AND kind = ? "
                "AND status = 'proposed' ORDER BY created_at, id "
                "LIMIT 1",
                (user_id, thread_id, kind),
            ).fetchone()
            if existing is not None:
                return OversightProposal(
                    id=existing["id"], user_id=user_id,
                    thread_id=thread_id, kind=kind,
                    reason=existing["reason"],
                    detail=json.loads(existing["detail_json"] or "{}"),
                    status="proposed",
                    created_at=existing["created_at"],
                )
            now = _utcnow()
            record = OversightProposal(
                id=_new_id("ovp"),
                user_id=user_id,
                thread_id=thread_id,
                kind=kind,
                reason=reason,
                detail=dict(detail or {}),
                status="proposed",
                created_at=now,
            )
            self._conn.execute(
                "INSERT INTO steward_oversight_proposals (id, "
                "user_id, thread_id, kind, reason, detail_json, "
                "status, created_at, decided_at) VALUES (?, ?, ?, "
                "?, ?, ?, 'proposed', ?, NULL)",
                (
                    record.id, user_id, thread_id, kind, reason,
                    json.dumps(record.detail), now,
                ),
            )
            self._conn.commit()
        return record

    def oversight_proposals_for(
        self,
        user_id: str,
        *,
        thread_id: str | None = None,
        status: str | None = None,
    ) -> list[OversightProposal]:
        """Oversight proposals for a user, oldest first."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if thread_id is not None:
            clauses.append("thread_id = ?")
            args.append(thread_id)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_oversight_proposals WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        return [
            OversightProposal(
                id=row["id"], user_id=row["user_id"],
                thread_id=row["thread_id"], kind=row["kind"],
                reason=row["reason"],
                detail=json.loads(row["detail_json"] or "{}"),
                status=row["status"],
                created_at=row["created_at"],
                decided_at=row["decided_at"],
            )
            for row in rows
        ]

    def set_oversight_status(
        self, user_id: str, proposal_id: str, status: str
    ) -> OversightProposal:
        """Decide an oversight proposal (review verdicts only).

        proposed -> confirmed | dismissed. Confirming an
        oversight proposal changes NO thread, reading, or
        branch state: oversight never commands. The confirmed
        row is a confirmed observation the user may act on,
        nothing more. Terminal states refuse further moves.
        """
        from .models import OVERSIGHT_PROPOSAL_STATUSES

        if status not in OVERSIGHT_PROPOSAL_STATUSES:
            raise ValueError(
                f"unknown oversight status: {status!r}"
            )
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_oversight_proposals "
                "WHERE id = ? AND user_id = ?",
                (proposal_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"unknown oversight proposal: {proposal_id!r}"
                )
            if row["status"] != "proposed" and status != row["status"]:
                raise ValueError(
                    f"oversight proposal cannot move "
                    f"{row['status']!r} -> {status!r}"
                )
            now = _utcnow()
            self._conn.execute(
                "UPDATE steward_oversight_proposals SET status = ?, "
                "decided_at = ? WHERE id = ? AND user_id = ?",
                (
                    status,
                    now if status != "proposed" else None,
                    proposal_id, user_id,
                ),
            )
            self._conn.commit()
        updated = self.oversight_proposals_for(user_id)
        for proposal in updated:
            if proposal.id == proposal_id:
                return proposal
        raise ValueError(f"unknown oversight proposal: {proposal_id!r}")

    def propose_reading_reconsideration(
        self, user_id: str, reading_id: str, reason: str = ""
    ) -> ReadingReconsideration:
        """Open candidate-for-reconsideration status (I3) on a
        previously ACCEPTED reading.

        The reading row is never touched: its status stays
        "accepted" and its content and evidence_refs are
        byte-identical before and after. Only this separate
        row records the candidacy. Proposing reconsideration
        of a non-accepted reading is a category error (there
        is nothing standing to reconsider) and raises. An
        already-proposed candidacy for the same reading is
        returned instead of duplicated.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM thread_readings WHERE id = ? "
                "AND thread_id IN (SELECT id FROM narrative_threads "
                "WHERE user_id = ?)",
                (reading_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"unknown reading for user: {reading_id!r}"
                )
            if row["status"] != "accepted":
                raise ValueError(
                    "only an accepted reading can gain "
                    "candidate-for-reconsideration status "
                    f"(reading status is {row['status']!r})"
                )
            existing = self._conn.execute(
                "SELECT * FROM steward_reading_reconsiderations "
                "WHERE user_id = ? AND reading_id = ? AND "
                "status = 'proposed' ORDER BY created_at, id LIMIT 1",
                (user_id, reading_id),
            ).fetchone()
            if existing is not None:
                return ReadingReconsideration(
                    id=existing["id"], user_id=user_id,
                    reading_id=reading_id,
                    thread_id=existing["thread_id"],
                    reason=existing["reason"],
                    status="proposed",
                    created_at=existing["created_at"],
                )
            now = _utcnow()
            record = ReadingReconsideration(
                id=_new_id("rcn"),
                user_id=user_id,
                reading_id=reading_id,
                thread_id=row["thread_id"],
                reason=reason,
                status="proposed",
                created_at=now,
            )
            self._conn.execute(
                "INSERT INTO steward_reading_reconsiderations (id, "
                "user_id, reading_id, thread_id, reason, status, "
                "created_at, decided_at) VALUES (?, ?, ?, ?, ?, "
                "'proposed', ?, NULL)",
                (
                    record.id, user_id, reading_id,
                    row["thread_id"], reason, now,
                ),
            )
            self._conn.commit()
        return record

    def reconsiderations_for(
        self,
        user_id: str,
        *,
        reading_id: str | None = None,
        status: str | None = None,
    ) -> list[ReadingReconsideration]:
        """Reconsiderations for a user, oldest first."""
        clauses = ["user_id = ?"]
        args: list[Any] = [user_id]
        if reading_id is not None:
            clauses.append("reading_id = ?")
            args.append(reading_id)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steward_reading_reconsiderations "
                "WHERE " + " AND ".join(clauses)
                + " ORDER BY created_at, id",
                args,
            ).fetchall()
        return [
            ReadingReconsideration(
                id=row["id"], user_id=row["user_id"],
                reading_id=row["reading_id"],
                thread_id=row["thread_id"],
                reason=row["reason"],
                status=row["status"],
                created_at=row["created_at"],
                decided_at=row["decided_at"],
            )
            for row in rows
        ]

    def set_reconsideration_status(
        self, user_id: str, reconsideration_id: str, status: str
    ) -> ReadingReconsideration:
        """Decide a reconsideration candidacy (review verdicts only).

        proposed -> affirmed | dismissed. Affirming keeps the
        reading accepted and open for revision; it does not
        revise, retire, or reaffirm the reading by itself —
        those are downstream outcomes through the existing
        reading-proposal and retirement flows. Dismissing
        clears the candidacy; the reading stands as before.
        Terminal states refuse further moves.
        """
        from .models import RECONSIDERATION_STATUSES

        if status not in RECONSIDERATION_STATUSES:
            raise ValueError(
                f"unknown reconsideration status: {status!r}"
            )
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM steward_reading_reconsiderations "
                "WHERE id = ? AND user_id = ?",
                (reconsideration_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(
                    "unknown reconsideration: "
                    f"{reconsideration_id!r}"
                )
            if row["status"] != "proposed" and status != row["status"]:
                raise ValueError(
                    f"reconsideration cannot move "
                    f"{row['status']!r} -> {status!r}"
                )
            now = _utcnow()
            self._conn.execute(
                "UPDATE steward_reading_reconsiderations SET "
                "status = ?, decided_at = ? WHERE id = ? "
                "AND user_id = ?",
                (
                    status,
                    now if status != "proposed" else None,
                    reconsideration_id, user_id,
                ),
            )
            self._conn.commit()
        for item in self.reconsiderations_for(user_id):
            if item.id == reconsideration_id:
                return item
        raise ValueError(
            f"unknown reconsideration: {reconsideration_id!r}"
        )
