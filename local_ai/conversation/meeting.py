"""Keystone meeting service — the host of the encounter runtime.

A meeting is a conversation between the user and ONE council seat.
Since the Fellowship Runtime (P3, Joshua 2026-10-23), the conversation
itself runs on OBJECTIVES, not a stage sequence: the encounter runtime
(local_ai/conversation/encounter.py) holds the character's narrative
objectives, answers the user's move before any agenda, and closes on
conditions — the impression offered and genuinely answered, or the
graceful ceiling. This service is the runtime's host and adapter:

  - the guards (who may be met, in what order — the rules below),
  - the stores (meeting state in its own small store; the transcript
    in the shared ConversationStore under "meeting-{seat}-{keystone}",
    so hydration and rendering reuse the skeleton's machinery — a
    meeting is a conversation, not a new kind of object),
  - the hands the runtime borrows (say / generate / store), and
  - the single completion chokepoint: reveal, keystone task Done,
    and the impression filed into the review queue exactly once.

The `stage` column survives as the derived position label the API has
always surfaced (encounter / readback / orientation / complete); the
runtime derives it from encounter state — position is the interface's
view, objectives are the engine's.

Rules the service enforces (Joshua's design, not preferences):
  - The Conductor is met first. Until its keystone 1 completes, no other
    seat's first meeting can begin (the attention markers encode the same
    order on the tree).
  - A seat with no written script has no meeting yet — the engine refuses
    honestly instead of improvising one. Building is not availability:
    a written-but-unreleased first meeting (RELEASED_FIRST_MEETING_SEATS
    in meetings.py) is refused as the last guard in _check_beginnable,
    after the seed / script / chain / entry checks, so no transcript,
    generation, or reveal can happen for it. `start` is the single
    entry: `turn` and `restart` both require a row only `start` creates.
  - Keystones run in chain order: keystone N's meeting requires N-1 Done.
    (Only keystone 1 is written in this build.)
  - The read-back is stored on the meeting record verbatim, with the
    user's response verbatim. The user's reply to the read-back is
    classified three ways — acknowledgment / correction / other. A
    CORRECTION replaces the stored impression with the corrected
    understanding (the record the impression-filing reads); an
    acknowledgment or any other reply leaves the impression
    standing exactly as spoken. When the meeting completes, the
    impression is filed into the review queue as a pending claim, where
    it waits, word for word — filing writes no training signal; only
    the user's verdict on the claim does.
  - Meetings are resumable: state is server-side, so leaving mid-meeting
    loses nothing, and beginning again picks up where the encounter
    stands.
  - A COMPLETED meeting can be met again (restart): the prior run —
    transcript plus the verbatim read-back impression — is
    archived in the meeting store, never deleted; the meeting resets to
    not-started and the seat's keystone task returns to its seeded
    status, so the face the meeting revealed re-locks until the new run
    completes. An in-progress meeting is never restartable — it can be
    paused and resumed instead.

The character's live beats go through the shared voice-reply builder with
the encounter's frame as extra instructions — the meeting never forks the
voice. Scripted beats are appended verbatim in the base voice (this is the
canonical character; the user's echo is a different side of the switch).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from local_ai.council import capabilities as CAP
from local_ai.council import meetings as MT
from local_ai.council.archetypes import PLAIN_TO_KEY, stock_archetype_ids
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as ve

from . import encounter as ENC
from .encounter import (
    EncounterRuntime,
    EncounterState,
    _classify_readback_reply,
    _is_acknowledgment,
    _is_pass,
)
from .reply import generate_voice_reply
from .store import (
    ConversationIntegrityError,
    ConversationStore,
    ConversationWriteRefused,
    OpeningIntegrityConflict,
    TransactionStateError,
)

GenerateFn = Callable[..., str]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "conversations"
DEFAULT_DB_PATH = DATA_DIR / "meetings.db"

#: D5 recovery sweep (2026-11-07): a meeting's conversation must have
#: been quiet this many days before the sweep files its affirmed
#: impression. A live conversation is left alone — the close path
#: files it when it completes.
AFFIRMATION_RECOVERY_QUIET_DAYS = 7

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
  user_id TEXT NOT NULL,
  archetype_id TEXT NOT NULL,
  keystone_index INTEGER NOT NULL,
  stage TEXT NOT NULL DEFAULT 'encounter',
  status TEXT NOT NULL DEFAULT 'active',
  question_idx INTEGER NOT NULL DEFAULT 0,
  readback_claim TEXT NOT NULL DEFAULT '',
  readback_response TEXT NOT NULL DEFAULT '',
  readback_strands TEXT NOT NULL DEFAULT '[]',
  readback_original_claim TEXT NOT NULL DEFAULT '',
  readback_seat_outcome TEXT NOT NULL DEFAULT '',
  readback_visitor_response TEXT NOT NULL DEFAULT '',
  state_json TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, archetype_id, keystone_index)
);
CREATE TABLE IF NOT EXISTS meeting_archives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  archetype_id TEXT NOT NULL,
  keystone_index INTEGER NOT NULL,
  transcript_json TEXT NOT NULL DEFAULT '[]',
  readback_claim TEXT NOT NULL DEFAULT '',
  readback_response TEXT NOT NULL DEFAULT '',
  readback_strands TEXT NOT NULL DEFAULT '[]',
  readback_original_claim TEXT NOT NULL DEFAULT '',
  readback_seat_outcome TEXT NOT NULL DEFAULT '',
  readback_visitor_response TEXT NOT NULL DEFAULT '',
  meeting_created_at TEXT NOT NULL DEFAULT '',
  archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meeting_encounters (
  run_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  archetype_id TEXT NOT NULL,
  keystone_index INTEGER NOT NULL,
  run_number INTEGER NOT NULL,
  predecessor_run_id TEXT,
  predecessor_link_kind TEXT NOT NULL DEFAULT 'witnessed',
  conversation_id TEXT NOT NULL,
  transcript_source TEXT NOT NULL DEFAULT 'live',
  transcript_json TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'creating',
  stage TEXT NOT NULL DEFAULT 'encounter',
  state_json TEXT NOT NULL DEFAULT '',
  state_schema_version TEXT NOT NULL DEFAULT 'unknown',
  state_writer_ref TEXT NOT NULL DEFAULT 'unknown',
  archive_commit TEXT NOT NULL DEFAULT 'unknown',
  readback_claim TEXT NOT NULL DEFAULT '',
  readback_response TEXT NOT NULL DEFAULT '',
  readback_strands TEXT NOT NULL DEFAULT '[]',
  readback_original_claim TEXT NOT NULL DEFAULT '',
  readback_seat_outcome TEXT NOT NULL DEFAULT '',
  readback_visitor_response TEXT NOT NULL DEFAULT '',
  message_count INTEGER NOT NULL DEFAULT 0,
  verification_status TEXT NOT NULL DEFAULT 'unverified',
  verification_detail_json TEXT NOT NULL DEFAULT '[]',
  verification_checked_at TEXT,
  task_id TEXT,
  finalized_at TEXT,
  opening_expected INTEGER NOT NULL DEFAULT 0,
  opening_script_id TEXT,
  opening_script_version TEXT,
  opening_paragraphs_json TEXT,
  legacy_group_key TEXT,
  legacy_possible_duplicate INTEGER NOT NULL DEFAULT 0,
  run_id_provenance TEXT NOT NULL DEFAULT 'generated',
  created_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE (user_id, archetype_id, keystone_index, run_number),
  UNIQUE (user_id, archetype_id, keystone_index, predecessor_run_id)
);
CREATE INDEX IF NOT EXISTS idx_encounters_key_run
  ON meeting_encounters (user_id, archetype_id, keystone_index, run_number);
CREATE TABLE IF NOT EXISTS meet_again_requests (
  user_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  predecessor_run_id TEXT NOT NULL,
  successor_run_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, request_id),
  UNIQUE (user_id, successor_run_id)
);
CREATE INDEX IF NOT EXISTS idx_meet_again_requests_predecessor
  ON meet_again_requests (user_id, predecessor_run_id);
"""

#: The deterministic heuristics that guard the state-critical
#: transitions (read-back reply classification, acknowledgment and
#: pass detection, the strands-trailer split, excerpts) live in
#: encounter.py with the runtime that uses them; the private names
#: are re-exported above for the callers that grew up importing
#: them from here.



def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def conversation_id_for(archetype_id: str, keystone_index: int) -> str:
    return f"meeting-{archetype_id}-{keystone_index}"


#: Per-run / per-key locks (non-destructive Meet Again, Slice 2).
#: The meeting service is constructed fresh per request, so no
#: instance-level lock can cover a run: the registry is module-level,
#: keyed by ``run:<run_id>`` for a single encounter and by
#: ``key:<user_id>:<archetype_id>:<keystone_index>`` for creation of
#: the next run of one key. RLock: a turn holds its run's lock while
#: the runtime closes through _do_reveal, which takes the same lock
#: again. One small lock object per run — the same order as the
#: encounter rows themselves; the registry is never pruned (a run's
#: lock must stay the same object for the run's life).
_RUN_LOCKS: dict[str, threading.RLock] = {}
_RUN_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.RLock:
    with _RUN_LOCKS_GUARD:
        lock = _RUN_LOCKS.get(key)
        if lock is None:
            # RLock, not Lock: a turn holds its run's lock while the
            # runtime closes through _do_reveal, which takes the same
            # lock again in the same thread. A plain Lock here deadlocks
            # the ceiling close (found by the ceiling test hanging in
            # _do_reveal's _resolve_encounter — the lock was already
            # held by the enclosing turn).
            lock = threading.RLock()
            _RUN_LOCKS[key] = lock
        return lock


def _new_run_id() -> str:
    """A fresh encounter run id (uuid4 hex, proposal §1)."""
    return uuid.uuid4().hex


def _opening_digest(paragraphs: list[str]) -> str:
    """The opening script version: first 16 hex of sha256 of the
    joined opening paragraphs (proposal §3.3)."""
    return hashlib.sha256("\n".join(paragraphs).encode("utf-8")).hexdigest()[:16]


def _run_key_for_encounter(
    encounter: dict[str, Any] | None, meetings_row: dict[str, Any] | None = None
) -> str:
    """The claim-identity key for one run (the ``_file_impression``
    run_key). New runs are keyed by their run_id; a run that predates
    encounters keeps its created_at-derived key, so a re-filing of the
    same run finds its existing claim instead of filing a second one
    and superseding its own standing claim:
    - provenance 'generated' -> the run_id.
    - provenance 'generated-migration' -> the meetings row's created_at.
    - provenance 'legacy-record' -> the legacy group key (the archive
      row's meeting_created_at, the original run's created_at).
    - no encounter -> the meetings row's created_at (legacy path)."""
    if encounter is None:
        created = (meetings_row or {}).get("created_at") or ""
        return re.sub(r"[^0-9A-Za-z]", "", created) or "run"
    provenance = encounter.get("run_id_provenance") or "generated"
    if provenance == "generated":
        return encounter["run_id"]
    if provenance == "legacy-record":
        created = encounter.get("legacy_group_key") or ""
        return re.sub(r"[^0-9A-Za-z]", "", created) or "run"
    created = (
        (meetings_row or {}).get("created_at")
        or encounter.get("created_at")
        or ""
    )
    return re.sub(r"[^0-9A-Za-z]", "", created) or "run"


class MeetingError(ValueError):
    """A meeting rule refusal (maps to 409 in the route layer).

    ``code`` is the stable machine-readable refusal (``encounter_finalized``,
    ``encounter_in_progress``, ...); ``run_id`` names the encounter the
    refusal is about, when there is one. Both are carried on the
    exception so the route layer can return them without re-deriving
    them; a MeetingError without a code keeps today's plain-string detail."""

    def __init__(self, message: str, code: str | None = None,
                 run_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.run_id = run_id


class MeetingValidationError(ValueError):
    """A Meet Again validation refusal (maps to 422 in the route layer):
    ``predecessor_required`` (no predecessor_run_id in the body),
    ``predecessor_unknown`` (no such run for the key). Carries the
    stable code so the route layer can return it without re-deriving it."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class MeetingNotFoundError(ValueError):
    """No encounter ever existed for the key (maps to 404 in the route
    layer): a Meet Again with nothing to meet again from. Distinct
    from ``predecessor_unknown`` (422) — that is a run id that matches
    no encounter for a key that HAS encounters."""

    def __init__(self, message: str, code: str = "encounter_not_found"):
        super().__init__(message)
        self.code = code


#: Written-but-unreleased first meetings (Fellowship
#: conversational-agency build, 2026-10-28): script existence alone
#: would otherwise make a meeting begin-able once its seat's
#: keystone chain is seeded and the entry seat's first meeting is
#: complete (see _check_beginnable), so a written script needs an
#: explicit begin refusal until its release decision. Building an
#: encounter does NOT make it available. Removing an entry here
#: is the whole release mechanism — no gate, keystone, or unlock
#: semantics change for any other seat, and no other path can
#: start a meeting: turn/complete/restart all refuse without an
#: active/completed row, and only start creates one.
#: The Maverick was released in the all-six release (Joshua's
#: availability verdict, 2026-10-29); the set is empty and
#: retained as the mechanism, not removed.
_UNRELEASED_MEETINGS: frozenset[tuple[str, int]] = frozenset()


class MeetingStore:
    """SQLite-backed meeting state. Strictly per-user rows."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            # Additive migrations for stores created before later
            # columns landed (strand attribution; encounter state).
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(meetings)")}
            if "readback_strands" not in cols:
                self._conn.execute(
                    "ALTER TABLE meetings ADD COLUMN readback_strands "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            if "state_json" not in cols:
                self._conn.execute(
                    "ALTER TABLE meetings ADD COLUMN state_json "
                    "TEXT NOT NULL DEFAULT ''"
                )
            for column in (
                "readback_original_claim",
                "readback_seat_outcome",
                "readback_visitor_response",
            ):
                if column not in cols:
                    self._conn.execute(
                        f"ALTER TABLE meetings ADD COLUMN {column} "
                        "TEXT NOT NULL DEFAULT ''"
                    )
            # The archives table has no migration block of its own
            # yet; existing databases get the same three columns.
            archive_cols = {
                r[1] for r in self._conn.execute("PRAGMA table_info(meeting_archives)")
            }
            for column in (
                "readback_original_claim",
                "readback_seat_outcome",
                "readback_visitor_response",
            ):
                if column not in archive_cols:
                    self._conn.execute(
                        f"ALTER TABLE meeting_archives ADD COLUMN {column} "
                        "TEXT NOT NULL DEFAULT ''"
                    )
            # Non-destructive Meet Again (Slice 2): the meetings row is
            # the latest-encounter pointer — `run_id` names the
            # encounter it points at, `conversation_id` that
            # encounter's conversation. Additive, guarded.
            for column, ddl in (
                ("run_id", "ALTER TABLE meetings ADD COLUMN run_id TEXT"),
                (
                    "conversation_id",
                    "ALTER TABLE meetings ADD COLUMN conversation_id TEXT",
                ),
            ):
                if column not in cols:
                    self._conn.execute(ddl)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get(self, user_id: str, archetype_id: str, keystone_index: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meetings WHERE user_id = ? AND archetype_id = ? "
                "AND keystone_index = ?",
                (user_id, archetype_id, keystone_index),
            ).fetchone()
        return dict(row) if row else None

    def list_active(self, user_id: str) -> list[dict[str, Any]]:
        """All of the user's still-active meetings, oldest first.

        D5 (2026-11-07): the recovery sweep's input — the sweep needs
        every active meeting to find affirmed-but-unfiled impressions,
        not one row at a time.

        Non-destructive Meet Again (Slice 2): the active set is the
        in-progress ENCOUNTERS, one row per key, in encounter shape
        (carrying run_id + conversation_id) — UNION the meetings rows
        with status 'active' that have NO encounter row yet (an
        unmigrated / un-materialized meeting), in meetings-row shape
        with conversation_id filled in (the stored column, or the
        legacy shared id). The sweep reads the encounter rows' run_id
        for the claim identity and the conversation id for the quiet
        check; the meetings-row entries carry run_id None and are
        materialized by the caller before any claim work."""
        with self._lock:
            enc_rows = self._conn.execute(
                "SELECT * FROM meeting_encounters WHERE user_id = ? AND "
                "status = 'in_progress' ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
            enc_keys = {
                (r["archetype_id"], r["keystone_index"]) for r in enc_rows
            }
            m_rows = self._conn.execute(
                "SELECT * FROM meetings WHERE user_id = ? AND "
                "status = 'active' ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        out: list[dict[str, Any]] = [_encounter_dict(r) for r in enc_rows]
        for r in m_rows:
            key = (r["archetype_id"], r["keystone_index"])
            if key in enc_keys:
                continue
            d = dict(r)
            if not d.get("conversation_id"):
                d["conversation_id"] = conversation_id_for(
                    d["archetype_id"], d["keystone_index"]
                )
            out.append(d)
        out.sort(key=lambda d: d.get("created_at") or "")
        return out

    def create(self, user_id: str, archetype_id: str, keystone_index: int) -> dict[str, Any]:
        now = _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO meetings (user_id, archetype_id, "
                "keystone_index, stage, status, question_idx, created_at, "
                "updated_at) VALUES (?, ?, ?, 'encounter', 'active', 0, ?, ?)",
                (user_id, archetype_id, keystone_index, now, now),
            )
            self._conn.commit()
        return self.get(user_id, archetype_id, keystone_index)  # type: ignore[return-value]

    def update(self, user_id: str, archetype_id: str, keystone_index: int, **fields: Any) -> dict[str, Any]:
        # The pointer columns (run_id / conversation_id) are
        # updatable: the meetings row points at the latest encounter,
        # and the pointer moves on Meet Again / materialization. The
        # key (user, archetype, keystone) is never updatable.
        allowed = {"stage", "status", "question_idx", "readback_claim", "readback_response", "readback_strands", "readback_original_claim", "readback_seat_outcome", "readback_visitor_response", "state_json", "run_id", "conversation_id"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            with self._lock:
                self._conn.execute(
                    f"UPDATE meetings SET {cols}, updated_at = ? WHERE user_id = ? "
                    "AND archetype_id = ? AND keystone_index = ?",
                    (*sets.values(), _utcnow(), user_id, archetype_id, keystone_index),
                )
                self._conn.commit()
        return self.get(user_id, archetype_id, keystone_index)  # type: ignore[return-value]

    def store_impression(self, user_id: str, archetype_id: str, keystone_index: int,
                         claim: str, strands: list[str]) -> None:
        """Store an impression: the claim and strands are always
        written; the original text is written only the first time
        (set-if-empty), at offer time, and never overwritten — a
        later revision replaces the claim but leaves the original
        standing, so the filing can carry both. Read + conditional
        write under one lock (the store's lock is a plain Lock, so
        this does its own SQL rather than calling update())."""
        with self._lock:
            row = self._conn.execute(
                "SELECT readback_original_claim FROM meetings WHERE user_id = ? "
                "AND archetype_id = ? AND keystone_index = ?",
                (user_id, archetype_id, keystone_index),
            ).fetchone()
            original = (row[0] if row else "") or ""
            if original:
                self._conn.execute(
                    "UPDATE meetings SET readback_claim = ?, readback_strands = ?, "
                    "updated_at = ? WHERE user_id = ? AND archetype_id = ? "
                    "AND keystone_index = ?",
                    (claim, json.dumps(strands), _utcnow(),
                     user_id, archetype_id, keystone_index),
                )
            else:
                self._conn.execute(
                    "UPDATE meetings SET readback_claim = ?, readback_strands = ?, "
                    "readback_original_claim = ?, updated_at = ? WHERE user_id = ? "
                    "AND archetype_id = ? AND keystone_index = ?",
                    (claim, json.dumps(strands), claim, _utcnow(),
                     user_id, archetype_id, keystone_index),
                )
            self._conn.commit()

    def met_seats(self, user_id: str) -> list[str]:
        """Archetype ids whose FIRST meeting (keystone 1) is complete
        for this user — the naming rule's met set (amendment E).
        Read from the ENCOUNTERS, never the meetings rows (amendment
        §1): a seat counts when ANY completed encounter exists for its
        first meeting. A begun-but-incomplete meeting does not count:
        the name unlocks at completion, when the card says so."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT archetype_id FROM meeting_encounters "
                "WHERE user_id = ? AND keystone_index = 1 "
                "AND status = 'complete'",
                (user_id,),
            ).fetchall()
        return [row[0] for row in rows]

    def meetings_for(self, user_id: str) -> list[dict[str, Any]]:
        """All live meeting rows for the user (increment C's O1
        scan reads stage/status/readback fields from these dicts;
        archived runs are separate records and are not scanned —
        O1 is about the live meeting's recorded response field)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM meetings WHERE user_id = ? "
                "ORDER BY created_at, archetype_id, keystone_index",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # -- archives (prior runs, preserved verbatim) ------------------------------

    def archive_run(
        self,
        user_id: str,
        archetype_id: str,
        keystone_index: int,
        row: dict[str, Any],
        transcript: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Preserve a completed run before a restart resets it: the full
        transcript plus the read-back impression and the user's response,
        verbatim — exactly as the live record held them. (The run's
        review claim, filed at completion, is a separate record:
        archiving never touches it. It is superseded only later, when
        a new run completes and files its own claim — restart and
        archiving alone supersede nothing.)"""
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO meeting_archives (user_id, archetype_id, "
                "keystone_index, transcript_json, readback_claim, "
                "readback_response, readback_strands, readback_original_claim, "
                "readback_seat_outcome, readback_visitor_response, meeting_created_at, "
                "archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    archetype_id,
                    keystone_index,
                    json.dumps(transcript, ensure_ascii=True),
                    row.get("readback_claim") or "",
                    row.get("readback_response") or "",
                    row.get("readback_strands") or "[]",
                    row.get("readback_original_claim") or "",
                    row.get("readback_seat_outcome") or "",
                    row.get("readback_visitor_response") or "",
                    row.get("created_at") or "",
                    _utcnow(),
                ),
            )
            self._conn.commit()
            archive_id = cur.lastrowid
        return self.get_archive(user_id, archive_id)  # type: ignore[return-value]

    def get_archive(self, user_id: str, archive_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meeting_archives WHERE user_id = ? AND id = ?",
                (user_id, archive_id),
            ).fetchone()
        return _archive_dict(row) if row else None

    def list_archives(
        self, user_id: str, archetype_id: str, keystone_index: int
    ) -> list[dict[str, Any]]:
        """Every archived run of this meeting, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM meeting_archives WHERE user_id = ? AND "
                "archetype_id = ? AND keystone_index = ? ORDER BY id ASC",
                (user_id, archetype_id, keystone_index),
            ).fetchall()
        return [_archive_dict(r) for r in rows]

    # -- encounters (one row per run; the meeting is a succession) ----------

    def get_encounter(self, user_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meeting_encounters WHERE user_id = ? AND run_id = ?",
                (user_id, run_id),
            ).fetchone()
        return _encounter_dict(row) if row else None

    def get_latest_encounter(
        self, user_id: str, archetype_id: str, keystone_index: int
    ) -> dict[str, Any] | None:
        """The highest-run_number encounter for the key, or None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meeting_encounters WHERE user_id = ? "
                "AND archetype_id = ? AND keystone_index = ? "
                "ORDER BY run_number DESC LIMIT 1",
                (user_id, archetype_id, keystone_index),
            ).fetchone()
        return _encounter_dict(row) if row else None

    def list_encounters(
        self, user_id: str, archetype_id: str, keystone_index: int
    ) -> list[dict[str, Any]]:
        """Every encounter for the key, run_number ascending (the lineage)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM meeting_encounters WHERE user_id = ? "
                "AND archetype_id = ? AND keystone_index = ? "
                "ORDER BY run_number ASC",
                (user_id, archetype_id, keystone_index),
            ).fetchall()
        return [_encounter_dict(r) for r in rows]

    def distinct_meeting_keys(self, user_id: str) -> list[tuple[str, int]]:
        """Every (archetype_id, keystone_index) the user has a meetings
        row or an encounter row for — the recovery sweep's key input."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT archetype_id, keystone_index FROM meetings "
                "WHERE user_id = ? UNION SELECT archetype_id, "
                "keystone_index FROM meeting_encounters WHERE user_id = ?",
                (user_id, user_id),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def distinct_user_ids(self) -> list[str]:
        """Every user with a meetings row or an encounter row — the
        recovery sweep's input."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT user_id FROM meetings "
                "UNION SELECT DISTINCT user_id FROM meeting_encounters"
            ).fetchall()
        return [r[0] for r in rows]

    def create_encounter(self, **fields: Any) -> dict[str, Any]:
        """Insert one encounter row. The caller supplies run_id,
        user_id, archetype_id, keystone_index, run_number and
        conversation_id, plus any other Appendix A column; the rest
        take their defaults. ``verification_detail`` /
        ``opening_paragraphs`` take lists and are serialized (the
        same as update_encounter). A duplicate run_number /
        predecessor for the key raises IntegrityError — the caller
        re-reads the latest encounter instead of creating a second run."""
        fields = _serialize_encounter_lists(dict(fields))
        fields.setdefault("created_at", _utcnow())
        fields.setdefault("status", "creating")
        cols = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO meeting_encounters ({cols}) VALUES ({placeholders})",
                tuple(fields.values()),
            )
            self._conn.commit()
        return self.get_encounter(fields["user_id"], fields["run_id"])  # type: ignore[return-value]

    def get_meet_again_request(
        self, user_id: str, request_id: str
    ) -> dict[str, Any] | None:
        """The recorded Meet Again request for (user_id, request_id) —
        the request's identity (proposal §5, AC15/AC19). A retry with
        the same request_id finds this row first and returns the
        existing successor instead of creating a second run."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meet_again_requests WHERE user_id = ? AND request_id = ?",
                (user_id, request_id),
            ).fetchone()
        return dict(row) if row else None

    def get_successor(
        self, user_id: str, predecessor_run_id: str
    ) -> dict[str, Any] | None:
        """The encounter (if any) whose predecessor is the given run —
        the one-successor-per-predecessor rule (AC19). A stale
        predecessor (or a concurrent creation that won) returns this
        instead of creating a second successor."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM meeting_encounters WHERE user_id = ? "
                "AND predecessor_run_id = ? ORDER BY run_number ASC LIMIT 1",
                (user_id, predecessor_run_id),
            ).fetchone()
        return _encounter_dict(row) if row else None

    def create_encounter_with_request(
        self, encounter_fields: dict[str, Any], request: dict[str, Any]
    ) -> dict[str, Any]:
        """Insert an encounter row AND its meet-again request record in
        one BEGIN IMMEDIATE transaction on meetings.db. A crash between
        them would leave a successor with no request identity, and a
        retry would create a duplicate run — the two rows are one
        atomic fact. A duplicate request_id (a concurrent retry that
        won) or a duplicate run_number raises IntegrityError; the
        caller re-reads the request / the latest encounter."""
        fields = _serialize_encounter_lists(dict(encounter_fields))
        fields.setdefault("created_at", _utcnow())
        fields.setdefault("status", "creating")
        cols = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    f"INSERT INTO meeting_encounters ({cols}) VALUES ({placeholders})",
                    tuple(fields.values()),
                )
                self._conn.execute(
                    "INSERT INTO meet_again_requests "
                    "(user_id, request_id, predecessor_run_id, successor_run_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        request["user_id"],
                        request["request_id"],
                        request["predecessor_run_id"],
                        request["successor_run_id"],
                        request.get("created_at") or _utcnow(),
                    ),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    try:
                        self._conn.execute("ROLLBACK")
                    except Exception:
                        pass
                raise
        return self.get_encounter(fields["user_id"], fields["run_id"])  # type: ignore[return-value]

    def migrate_to_encounters(
        self, conversations: Any, task_id_for: Any
    ) -> dict[str, Any]:
        """Run the §4.3 migration (Steps 2–5) on the databases this
        store is opened on. Step 1 (additive schema) is already
        applied by __init__ (the _SCHEMA creates the tables; the
        guarded ALTERs add the columns).

        Step 2 — archive rows become encounter rows, in `archived_at`
        order: `legacy-unverified`, `legacy_group_key` = shared
        `meeting_created_at`, distinct record identities,
        `predecessor_link_kind = 'reconstructed'`. The identity
        evidence rule (§4.1 I6): an archive row whose
        `meeting_created_at` group key is unique within the key's
        archive rows qualifies for `run_id_provenance =
        'generated-migration'`; a row in a duplicate group gets
        `'legacy-record'` (and `legacy_possible_duplicate = 1`).
        An archive encounter's conversation id is run-specific
        (its transcript is read from `transcript_json`, never from
        messages) so its fence row cannot collide with the live
        run's grandfathered shared id.
        Step 3 — the live row becomes an encounter row (`run_number`
        k+1, `verification_status = 'unverified'`, `transcript_source
        = 'live'`, the grandfathered shared conversation id). A
        pre-existing materialized row (lazy materialization, S2) is
        ADOPTED — its run_number is moved to k+1 and its predecessor
        set to the last archive encounter — never duplicated.
        Step 4 — the meetings row is re-pointed at the live encounter.
        Step 5 — verify per key (the gates) and report.
        Step 6 — live messages are untouched (nothing here moves a
        message). `meeting_archives` is retained as-is; no rows are
        deleted, no columns dropped, no values relabelled. No
        migrated row is promoted to `read_consistency_verified`
        (archive rows stay `legacy-unverified`; live rows stay
        `unverified` until a check runs). No recorded opening is
        backfilled for a legacy row (a row with no recorded opening
        fails closed, never completes from the live script).

        `task_id_for(user_id, archetype_id, keystone_index)` resolves
        the seeded keystone task id (or None). The migration is
        idempotent: re-running it adopts existing encounter rows and
        only fills gaps. Returns a report
        {keys: [...per-key...], verified: bool, failures: [...]}."""
        report: dict[str, Any] = {"keys": [], "verified": True, "failures": []}
        for user_id in self.distinct_user_ids():
            for arch_id, keystone_index in self.distinct_meeting_keys(user_id):
                key_report: dict[str, Any] = {
                    "user_id": user_id,
                    "archetype_id": arch_id,
                    "keystone_index": keystone_index,
                    "archives_migrated": 0,
                    "archives_adopted": 0,
                    "live": None,
                    "fences": 0,
                    "failures": [],
                }
                report["keys"].append(key_report)
                shared_cid = conversation_id_for(arch_id, keystone_index)
                # The live message count, recorded before anything is
                # written (Step 5 compares it after — Step 6).
                live_msg_before = conversations.count_messages(user_id, shared_cid)
                # --- Step 2: archive rows -------------------------------
                archives = self.list_archives(user_id, arch_id, keystone_index)
                archives.sort(key=lambda a: (a.get("archived_at") or "", a["id"]))
                groups: dict[str, list[dict[str, Any]]] = {}
                for a in archives:
                    groups.setdefault(a.get("meeting_created_at") or "", []).append(a)
                existing = self.list_encounters(user_id, arch_id, keystone_index)
                existing_archive = [
                    e for e in existing if e.get("transcript_source") == "archive"
                ]
                live_pre = next(
                    (e for e in existing if e.get("transcript_source") == "live"),
                    None,
                )
                # A live/materialized row occupies a run_number in the
                # archive range (it was created as run 1 before the
                # archives were migrated). Move it to k+1 FIRST — the
                # final archive count is known upfront (len(archives))
                # — so its old number is free for the archive rows
                # and its final number (k+1) cannot collide with them.
                # (run_number is an identity field, outside
                # update_encounter's allow-list, so this is a direct
                # migration UPDATE.)
                if live_pre is not None:
                    with self._lock:
                        self._conn.execute(
                            "UPDATE meeting_encounters SET run_number = ? "
                            "WHERE user_id = ? AND run_id = ?",
                            (len(archives) + 1, user_id, live_pre["run_id"]),
                        )
                        self._conn.commit()
                max_run = max(
                    (e["run_number"] for e in existing_archive), default=0
                )
                prev_archive: dict[str, Any] | None = (
                    max(existing_archive, key=lambda e: e["run_number"])
                    if existing_archive else None
                )
                for a in archives:
                    group = groups[a.get("meeting_created_at") or ""]
                    # Already migrated? Match by group key + transcript
                    # (the archive dict carries the parsed `transcript`
                    # list — `transcript_json` was popped by
                    # _archive_dict — so compare parsed forms).
                    a_transcript = a.get("transcript") or []

                    def _enc_transcript(e: dict[str, Any]) -> list:
                        try:
                            t = json.loads(e.get("transcript_json") or "[]")
                            return t if isinstance(t, list) else []
                        except Exception:
                            return []

                    already = next(
                        (
                            e for e in existing_archive
                            if e.get("legacy_group_key") == a.get("meeting_created_at")
                            and _enc_transcript(e) == a_transcript
                        ),
                        None,
                    )
                    if already is not None:
                        key_report["archives_adopted"] += 1
                        prev_archive = already
                        continue
                    if not isinstance(a_transcript, list):
                        key_report["failures"].append(
                            f"archive {a['id']}: malformed transcript_json"
                        )
                        continue
                    transcript = a_transcript
                    run_id = _new_run_id()
                    max_run += 1
                    fields: dict[str, Any] = {
                        "run_id": run_id,
                        "user_id": user_id,
                        "archetype_id": arch_id,
                        "keystone_index": keystone_index,
                        "run_number": max_run,
                        "predecessor_run_id": (
                            prev_archive["run_id"] if prev_archive else None
                        ),
                        "predecessor_link_kind": (
                            "reconstructed" if prev_archive else "witnessed"
                        ),
                        "conversation_id": f"{shared_cid}-{run_id}",
                        "transcript_source": "archive",
                        "transcript_json": json.dumps(
                            transcript, ensure_ascii=True
                        ),
                        "status": "complete",
                        "stage": "complete",
                        "state_json": "",
                        "readback_claim": a.get("readback_claim") or "",
                        "readback_response": a.get("readback_response") or "",
                        "readback_strands": a.get("readback_strands") or "[]",
                        "readback_original_claim": a.get("readback_original_claim") or "",
                        "readback_seat_outcome": a.get("readback_seat_outcome") or "",
                        "readback_visitor_response": a.get("readback_visitor_response") or "",
                        "message_count": len(transcript),
                        "verification_status": "legacy-unverified",
                        "legacy_group_key": a.get("meeting_created_at") or "",
                        "legacy_possible_duplicate": 1 if len(group) > 1 else 0,
                        "run_id_provenance": (
                            "generated-migration" if len(group) == 1 else "legacy-record"
                        ),
                        "created_at": a.get("meeting_created_at") or a.get("archived_at") or "",
                        "completed_at": a.get("archived_at") or "",
                        "finalized_at": a.get("archived_at") or "",
                        "task_id": task_id_for(user_id, arch_id, keystone_index),
                    }
                    enc = self.create_encounter(**fields)
                    prev_archive = enc
                    key_report["archives_migrated"] += 1
                # --- Step 3: the live row -------------------------------
                mrow = self.get(user_id, arch_id, keystone_index)
                live_enc: dict[str, Any] | None = None
                if mrow is not None:
                    archive_count = len(
                        [e for e in self.list_encounters(user_id, arch_id, keystone_index)
                         if e.get("transcript_source") == "archive"]
                    )
                    live_existing = next(
                        (
                            e for e in self.list_encounters(user_id, arch_id, keystone_index)
                            if e.get("transcript_source") == "live"
                        ),
                        None,
                    )
                    last_archive = (
                        max(
                            [e for e in self.list_encounters(user_id, arch_id, keystone_index)
                             if e.get("transcript_source") == "archive"],
                            key=lambda e: e["run_number"],
                        )
                        if archive_count else None
                    )
                    if live_existing is not None:
                        # Adopt the materialized row: it was already
                        # moved to k+1 in Step 2a, so only its
                        # predecessor binds here (to the last archive
                        # encounter) and its message_count syncs from
                        # the live messages (materialization never set
                        # it), so Step 5's count gate passes.
                        # (predecessor is an identity field, outside
                        # update_encounter's allow-list, so the bind
                        # is a direct migration UPDATE.)
                        with self._lock:
                            self._conn.execute(
                                "UPDATE meeting_encounters SET "
                                "predecessor_run_id = ?, predecessor_link_kind = ? "
                                "WHERE user_id = ? AND run_id = ?",
                                (
                                    last_archive["run_id"] if last_archive else None,
                                    "reconstructed" if last_archive else "witnessed",
                                    user_id, live_existing["run_id"],
                                ),
                            )
                            self._conn.commit()
                        self.update_encounter(
                            user_id, live_existing["run_id"],
                            message_count=conversations.count_messages(
                                user_id, live_existing["conversation_id"]
                            ),
                        )
                        live_enc = self.get_encounter(user_id, live_existing["run_id"])
                        key_report["live"] = "adopted"
                    else:
                        live_msg = conversations.count_messages(user_id, shared_cid)
                        live_enc = self.create_encounter(
                            run_id=_new_run_id(),
                            user_id=user_id,
                            archetype_id=arch_id,
                            keystone_index=keystone_index,
                            run_number=archive_count + 1,
                            predecessor_run_id=(
                                last_archive["run_id"] if last_archive else None
                            ),
                            predecessor_link_kind=(
                                "reconstructed" if last_archive else "witnessed"
                            ),
                            conversation_id=shared_cid,
                            transcript_source="live",
                            status=(
                                "complete" if mrow.get("status") == "complete"
                                else "in_progress"
                            ),
                            stage=mrow.get("stage") or "encounter",
                            state_json=mrow.get("state_json") or "",
                            readback_claim=mrow.get("readback_claim") or "",
                            readback_response=mrow.get("readback_response") or "",
                            readback_strands=mrow.get("readback_strands") or "[]",
                            readback_original_claim=mrow.get("readback_original_claim") or "",
                            readback_seat_outcome=mrow.get("readback_seat_outcome") or "",
                            readback_visitor_response=mrow.get("readback_visitor_response") or "",
                            message_count=live_msg,
                            verification_status="unverified",
                            run_id_provenance="generated-migration",
                            created_at=mrow.get("created_at") or "",
                            completed_at=(
                                mrow.get("updated_at") or ""
                                if mrow.get("status") == "complete" else ""
                            ),
                            finalized_at=(
                                mrow.get("updated_at") or ""
                                if mrow.get("status") == "complete" else ""
                            ),
                            task_id=task_id_for(user_id, arch_id, keystone_index),
                        )
                        key_report["live"] = "created"
                    # --- Step 4: re-point the meetings row -------------
                    self.update(
                        user_id, arch_id, keystone_index,
                        run_id=live_enc["run_id"],
                        conversation_id=live_enc["conversation_id"],
                    )
                # --- Fences (I5) ----------------------------------------
                for enc in self.list_encounters(user_id, arch_id, keystone_index):
                    conversations.ensure_fence(user_id, enc["conversation_id"])
                    key_report["fences"] += 1
                    if enc["status"] == "complete":
                        conversations.close_fence(
                            user_id, enc["conversation_id"], enc["run_id"]
                        )
                # --- Step 5: verify -------------------------------------
                encounters = self.list_encounters(user_id, arch_id, keystone_index)
                expected = len(archives) + (1 if mrow is not None else 0)
                if len(encounters) != expected:
                    key_report["failures"].append(
                        f"encounter count {len(encounters)} != archive {len(archives)} + live {1 if mrow is not None else 0}"
                    )
                if conversations.count_messages(user_id, shared_cid) != live_msg_before:
                    key_report["failures"].append("live message count changed")
                for enc in encounters:
                    if enc.get("transcript_source") == "archive":
                        try:
                            n = len(json.loads(enc.get("transcript_json") or "[]"))
                        except Exception:
                            n = -1
                        if enc.get("message_count") != n:
                            key_report["failures"].append(
                                f"archive run {enc['run_id']}: message_count {enc.get('message_count')} != transcript {n}"
                            )
                        if not enc.get("legacy_group_key"):
                            key_report["failures"].append(
                                f"archive run {enc['run_id']}: legacy_group_key missing"
                            )
                        group = groups.get(enc.get("legacy_group_key") or "", [])
                        want_dup = 1 if len(group) > 1 else 0
                        if enc.get("legacy_possible_duplicate") != want_dup:
                            key_report["failures"].append(
                                f"archive run {enc['run_id']}: legacy_possible_duplicate wrong"
                            )
                    else:
                        live_now = conversations.count_messages(
                            user_id, enc["conversation_id"]
                        )
                        if enc.get("message_count") != live_now:
                            key_report["failures"].append(
                                f"live run {enc['run_id']}: message_count {enc.get('message_count')} != live {live_now}"
                            )
                    fence = conversations.get_fence_state(user_id, enc["conversation_id"])
                    want = "closed" if enc["status"] == "complete" else "open"
                    if fence != want:
                        key_report["failures"].append(
                            f"run {enc['run_id']}: fence {fence} != {want}"
                        )
                if key_report["failures"]:
                    report["verified"] = False
                    report["failures"].extend(
                        f"{user_id}/{arch_id}/{keystone_index}: {f}"
                        for f in key_report["failures"]
                    )
        return report

    def update_encounter(
        self, user_id: str, run_id: str, **fields: Any
    ) -> dict[str, Any] | None:
        """Update one encounter row (allow-list; identity fields are
        never updated). ``verification_detail`` / ``opening_paragraphs``
        take lists and are serialized. Returns the row, or None when
        the run does not exist."""
        fields = _serialize_encounter_lists(dict(fields))
        allowed = {
            "status", "stage", "state_json", "state_schema_version",
            "state_writer_ref", "archive_commit", "readback_claim",
            "readback_response", "readback_strands",
            "readback_original_claim", "readback_seat_outcome",
            "readback_visitor_response", "message_count",
            "verification_status", "verification_detail_json",
            "verification_checked_at", "task_id", "finalized_at",
            "completed_at", "opening_expected", "opening_script_id",
            "opening_script_version", "opening_paragraphs_json",
            "legacy_group_key", "legacy_possible_duplicate",
            "transcript_json", "transcript_source", "predecessor_run_id",
            "predecessor_link_kind",
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return self.get_encounter(user_id, run_id)
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._lock:
            self._conn.execute(
                f"UPDATE meeting_encounters SET {cols} "
                "WHERE user_id = ? AND run_id = ?",
                (*sets.values(), user_id, run_id),
            )
            self._conn.commit()
        return self.get_encounter(user_id, run_id)

    def finalize_encounter(
        self, user_id: str, run_id: str, message_count: int | None = None,
        verification_status: str | None = None,
        verification_detail: dict[str, Any] | None = None,
        verification_checked_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically complete one encounter (proposal §3.1 step 6).

        One BEGIN IMMEDIATE transaction on meetings.db: the encounter
        flips to complete (finalized_at / completed_at set), its six
        read-back fields + state_json sync from the meetings row (the
        host writes those there during the encounter), and the meetings
        row mirrors the completion — but only while it still points at
        this run (a successor already owns the pointer once a Meet
        Again has run). When a read-consistency check result is given,
        its status + checked_at are written and its detail entry is
        APPENDED to verification_detail_json (the history is
        append-only — a failed check never overwrites a prior passing
        record). Idempotent: an already-finalized encounter returns
        its row unchanged. Returns the encounter row, or None when
        the run does not exist."""
        now = _utcnow()
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                enc = self._conn.execute(
                    "SELECT * FROM meeting_encounters "
                    "WHERE user_id = ? AND run_id = ?",
                    (user_id, run_id),
                ).fetchone()
                if enc is None:
                    self._conn.execute("ROLLBACK")
                    return None
                if enc["finalized_at"]:
                    self._conn.execute("ROLLBACK")
                    return _encounter_dict(enc)
                mrow = self._conn.execute(
                    "SELECT * FROM meetings WHERE user_id = ? "
                    "AND archetype_id = ? AND keystone_index = ?",
                    (user_id, enc["archetype_id"], enc["keystone_index"]),
                ).fetchone()
                sets: dict[str, Any] = {
                    "status": "complete",
                    "stage": "complete",
                    "finalized_at": now,
                    "completed_at": enc["completed_at"] or now,
                }
                if mrow is not None:
                    for col in (
                        "state_json", "readback_claim", "readback_response",
                        "readback_strands", "readback_original_claim",
                        "readback_seat_outcome", "readback_visitor_response",
                    ):
                        sets[col] = mrow[col]
                if message_count is not None:
                    sets["message_count"] = message_count
                if verification_status is not None:
                    sets["verification_status"] = verification_status
                    sets["verification_checked_at"] = (
                        verification_checked_at or now
                    )
                    if verification_detail is not None:
                        try:
                            history = json.loads(
                                enc["verification_detail_json"] or "[]"
                            )
                        except Exception:
                            history = []
                        if not isinstance(history, list):
                            history = []
                        history.append(verification_detail)
                        sets["verification_detail_json"] = json.dumps(
                            history, ensure_ascii=True
                        )
                cols = ", ".join(f"{k} = ?" for k in sets)
                self._conn.execute(
                    f"UPDATE meeting_encounters SET {cols} "
                    "WHERE user_id = ? AND run_id = ?",
                    (*sets.values(), user_id, run_id),
                )
                if mrow is not None and (
                    mrow["run_id"] is None or mrow["run_id"] == run_id
                ):
                    self._conn.execute(
                        "UPDATE meetings SET status = 'complete', "
                        "stage = 'complete', run_id = ?, "
                        "conversation_id = ?, updated_at = ? "
                        "WHERE user_id = ? AND archetype_id = ? "
                        "AND keystone_index = ?",
                        (
                            run_id, enc["conversation_id"], now,
                            user_id, enc["archetype_id"], enc["keystone_index"],
                        ),
                    )
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    try:
                        self._conn.execute("ROLLBACK")
                    except Exception:
                        pass
                raise
        return self.get_encounter(user_id, run_id)


def _serialize_encounter_lists(fields: dict[str, Any]) -> dict[str, Any]:
    """Serialize an encounter row's list-valued columns to their
    ``*_json`` storage form (the same rule update_encounter applies):
    ``opening_paragraphs`` -> ``opening_paragraphs_json``,
    ``verification_detail`` -> ``verification_detail_json``."""
    if "verification_detail" in fields:
        fields["verification_detail_json"] = json.dumps(
            fields.pop("verification_detail"), ensure_ascii=True
        )
    if "opening_paragraphs" in fields:
        fields["opening_paragraphs_json"] = json.dumps(
            fields.pop("opening_paragraphs"), ensure_ascii=True
        )
    return fields


def _encounter_dict(row: sqlite3.Row) -> dict[str, Any]:
    """An encounter row as the API shape: the JSON columns parsed to
    lists (``opening_paragraphs`` / ``verification_detail``), the raw
    ``*_json`` keys dropped."""
    out = dict(row)
    try:
        out["opening_paragraphs"] = json.loads(
            out.pop("opening_paragraphs_json") or "null"
        )
    except Exception:
        out["opening_paragraphs"] = None
    try:
        out["verification_detail"] = json.loads(
            out.pop("verification_detail_json") or "[]"
        )
    except Exception:
        out["verification_detail"] = []
    return out


def _archive_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    try:
        out["transcript"] = json.loads(out.pop("transcript_json") or "[]")
    except Exception:
        out["transcript"] = []
    try:
        out["readback_strands"] = json.loads(out.get("readback_strands") or "[]")
    except Exception:
        out["readback_strands"] = []
    return out


def _seat_keystone_tasks(user_id: str, archetype_id: str) -> list[dict[str, Any]]:
    """The seat's keystone tasks in chain order (1→4). [] when unseeded."""
    initiative = keystone_seeding.find_keystone_initiative(user_id)
    if initiative is None:
        return []
    tasks: list[dict[str, Any]] = []
    for project in ve.list_projects(user_id):
        if project.get("initiative_id") != initiative["id"]:
            continue
        tasks.extend(ve.list_tasks(user_id, project_id=project["id"]))
    mine = [t for t in tasks if t.get("seat_ref") == archetype_id]
    return keystone_seeding._chain_order(mine)


class _MeetingHost:
    """The encounter runtime's hands, lent by the meeting service
    (encounter.EncounterHost): speech goes to the meeting's
    conversation, generation goes through the shared voice-reply
    builder with the runtime's frame, storage goes to the meeting
    record, and closing goes through the service's single completion
    chokepoint."""

    def __init__(self, service: "MeetingService", user_id: str, arch_id: str,
                 keystone_index: int, script: MT.MeetingScript,
                 fellowship_reference: str = "",
                 decoupled_recognition: bool = False,
                 conversation_id: str | None = None) -> None:
        self._svc = service
        self._user_id = user_id
        self._arch_id = arch_id
        self._keystone_index = keystone_index
        self._script = script
        self._fellowship_reference = fellowship_reference
        self._decoupled_recognition = decoupled_recognition
        # The encounter's own conversation (run-specific); the legacy
        # shared id only when no encounter exists yet.
        self._cid = conversation_id or conversation_id_for(arch_id, keystone_index)

    def say(self, body: str) -> None:
        self._svc._say(self._user_id, self._cid, self._arch_id, body)

    def generate(self, frame: str) -> str:
        try:
            return self._svc._generate_framed(
                self._user_id, self._arch_id, self._keystone_index, frame,
                fellowship_reference=self._fellowship_reference,
                conversation_id=self._cid,
            )
        except Exception:
            # A provider failure degrades to the runtime's fallback
            # anchors; a meeting never breaks mid-sentence on it.
            logger.exception("meeting generation failed; degrading to fallback")
            return ""

    def store_impression(self, claim: str, strands: list[str]) -> None:
        self._svc.meetings.store_impression(
            self._user_id, self._arch_id, self._keystone_index,
            claim, strands,
        )

    def store_response(self, text: str) -> None:
        self._svc.meetings.update(
            self._user_id, self._arch_id, self._keystone_index,
            readback_response=text,
        )

    def store_dimensions(self, seat_outcome: str, visitor_response: str) -> None:
        """Record both dimensions of the read-back outcome on the
        row — the seat's interpretation and the visitor's response.
        The response turn writes these on every path, so the filing
        and the training boundary read structure, not prose. The
        fail-safe is the only writer of (unjudged, unresolved)."""
        self._svc.meetings.update(
            self._user_id, self._arch_id, self._keystone_index,
            readback_seat_outcome=seat_outcome,
            readback_visitor_response=visitor_response,
        )

    def close(self, wrap_line: str) -> None:
        self._svc._do_reveal(
            self._user_id, self._arch_id, self._keystone_index,
            self._script, wrap_line=wrap_line,
            silent_close=self._decoupled_recognition,
        )


def _is_ceiling_filed(row: dict[str, Any]) -> bool:
    """Whether this run's impression was filed by the ceiling wrap
    without ever being answered — the longest user turn is evidence
    the impression was formed from, not an answer to it (verdict
    amendment 5). The encounter state's `impression_answered` says
    so directly when the runtime ran: present and False means the
    response turn never ran. Present and True means a genuine
    answer. Absent or unparseable (a legacy pre-runtime row) means
    a genuine answer: the ceiling wrap is a runtime feature, so a
    row that predates the runtime only ever stored genuine answers."""
    try:
        state = json.loads(row.get("state_json") or "")
    except Exception:
        return False
    if not isinstance(state, dict) or "impression_answered" not in state:
        return False
    return state.get("impression_answered") is False


#: Normative paragraph (readiness amendment §A): what the
#: read-consistency check does and does not establish. Carried into
#: the implementation's documentation and into any user-facing copy
#: that describes the verification badge (the encounter detail
#: response serves it as ``verification_note``).
READ_CONSISTENCY_NORMATIVE = (
    "The read-consistency check performs two independent paged reads of the same "
    "SQLite records (the live `messages` rows for the encounter's conversation id, "
    "in `id` order) and compares them on count, `id` sequence, and order; it "
    "confirms the six read-back fields are present and the `state_json` parses "
    "with its version context. A passing check establishes that the two reads "
    "agree and that the recorded transcript is internally consistent at the time "
    "of the check. It does **not** establish that no earlier messages are missing "
    "relative to any external ground truth — there is no external ground truth for "
    "a live conversation — nor that the transcript matches any record outside the "
    "live rows, nor absolute completeness. A record can be preserved without being "
    "read-consistency-verified, and it must never be represented as verified merely "
    "because preservation was attempted."
)


class MeetingService:
    def __init__(
        self,
        conversation_store: ConversationStore,
        meeting_store: MeetingStore,
        generate_fn: GenerateFn | None = None,
        agent_store_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.conversations = conversation_store
        self.meetings = meeting_store
        self._generate_fn = generate_fn
        # user_id -> AgentStore for filing meeting impressions into the
        # review queue; None builds the default-path store per user,
        # the same store the intake routes read.
        self._agent_store_factory = agent_store_factory

    def close(self) -> None:
        """Close both stores (the sweep's open-query-close discipline)."""
        self.conversations.close()
        self.meetings.close()

    @staticmethod
    def _translate_store_error(
        exc: Exception, run_id: str | None = None
    ) -> None:
        """Translate a conversation-store refusal into the meeting
        service's error vocabulary: a write refusal becomes a
        MeetingError (409, carrying its stable code); an integrity /
        transaction failure becomes a RuntimeError (502). Always
        raises; never returns."""
        if isinstance(exc, ConversationWriteRefused):
            raise MeetingError(
                str(exc), code=exc.code, run_id=exc.run_id or run_id
            ) from exc
        if isinstance(exc, OpeningIntegrityConflict):
            raise MeetingError(
                str(exc), code=exc.code, run_id=exc.run_id or run_id
            ) from exc
        if isinstance(exc, (ConversationIntegrityError, TransactionStateError)):
            raise RuntimeError(str(exc)) from exc
        raise exc

    # -- encounters -----------------------------------------------------------

    def _resolve_encounter(
        self, user_id: str, arch_id: str, keystone_index: int
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(latest encounter, meetings row) for a key.

        When no encounter row exists but a meetings row does, the
        encounter is lazily materialized from the meetings row (the
        migration's Step 3, applied on read): run 1, provenance
        'generated-migration', transcript_source 'live', the
        conversation id from the meetings row (or the legacy shared
        id), status from the meetings row, the fence created (open for
        an active meeting, closed for a completed one), and the
        meetings row pointed at the new run. When neither exists,
        (None, None)."""
        enc = self.meetings.get_latest_encounter(user_id, arch_id, keystone_index)
        mrow = self.meetings.get(user_id, arch_id, keystone_index)
        if enc is not None:
            return enc, mrow
        if mrow is None:
            return None, None
        return self._materialize_encounter(user_id, arch_id, keystone_index, mrow), mrow

    def _materialize_encounter(
        self, user_id: str, arch_id: str, keystone_index: int,
        mrow: dict[str, Any],
    ) -> dict[str, Any]:
        """Create the run-1 encounter row for a meetings row that
        predates encounters. Under the per-key lock; a concurrent
        materialization that wins returns the existing row instead.
        The opening is NOT recorded here — it predates the encounter
        record (opening_expected stays 0); a row with no recorded
        opening is never completed from the live script."""
        key = f"key:{user_id}:{arch_id}:{keystone_index}"
        with _lock_for(key):
            existing = self.meetings.get_latest_encounter(
                user_id, arch_id, keystone_index
            )
            if existing is not None:
                return existing
            run_id = _new_run_id()
            cid = (mrow.get("conversation_id") or "") or conversation_id_for(
                arch_id, keystone_index
            )
            status = mrow.get("status") or "active"
            enc_status = "complete" if status == "complete" else "in_progress"
            tasks = _seat_keystone_tasks(user_id, arch_id)
            task = tasks[keystone_index - 1] if len(tasks) >= keystone_index else None
            now = _utcnow()
            enc = self.meetings.create_encounter(
                run_id=run_id,
                user_id=user_id,
                archetype_id=arch_id,
                keystone_index=keystone_index,
                run_number=1,
                conversation_id=cid,
                transcript_source="live",
                run_id_provenance="generated-migration",
                status=enc_status,
                stage=mrow.get("stage") or "encounter",
                state_json=mrow.get("state_json") or "",
                readback_claim=mrow.get("readback_claim") or "",
                readback_response=mrow.get("readback_response") or "",
                readback_strands=mrow.get("readback_strands") or "[]",
                readback_original_claim=mrow.get("readback_original_claim") or "",
                readback_seat_outcome=mrow.get("readback_seat_outcome") or "",
                readback_visitor_response=mrow.get("readback_visitor_response") or "",
                task_id=(task or {}).get("id"),
                created_at=mrow.get("created_at") or now,
                completed_at=mrow.get("updated_at") if enc_status == "complete" else None,
                finalized_at=now if enc_status == "complete" else None,
            )
            # The fence: a completed meeting's conversation is closed
            # to writes; an active one's is open.
            self.conversations.ensure_conversation(user_id, cid, kind="meeting")
            if enc_status == "complete":
                self.conversations.close_fence(user_id, cid, run_id)
            self.meetings.update(
                user_id, arch_id, keystone_index,
                run_id=run_id, conversation_id=cid,
            )
            return enc

    def _create_encounter(
        self, user_id: str, arch_id: str, keystone_index: int,
        predecessor: dict[str, Any] | None = None,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create the next encounter row for a key (run_number = latest
        + 1, or 1), in status 'creating'. The caller records the
        opening and flips it to in_progress. A concurrent creation
        that wins the race raises IntegrityError on the unique
        run_number — the caller re-reads the latest encounter
        instead of creating a second run. When ``request`` is given
        (a Meet Again), the encounter row and the request record are
        inserted in one transaction, so a crash between them can never
        leave a successor with no request identity."""
        latest = self.meetings.get_latest_encounter(user_id, arch_id, keystone_index)
        run_number = (latest["run_number"] + 1) if latest else 1
        run_id = _new_run_id()
        tasks = _seat_keystone_tasks(user_id, arch_id)
        task = tasks[keystone_index - 1] if len(tasks) >= keystone_index else None
        fields: dict[str, Any] = {
            "run_id": run_id,
            "user_id": user_id,
            "archetype_id": arch_id,
            "keystone_index": keystone_index,
            "run_number": run_number,
            "conversation_id": f"meeting-{arch_id}-{keystone_index}-{run_id}",
            "transcript_source": "live",
            "run_id_provenance": "generated",
            "status": "creating",
            "task_id": (task or {}).get("id"),
        }
        if predecessor is not None:
            fields["predecessor_run_id"] = predecessor["run_id"]
            fields["predecessor_link_kind"] = "witnessed"
        if request is not None:
            # The request record names the successor it created.
            request = dict(request)
            request["successor_run_id"] = run_id
            return self.meetings.create_encounter_with_request(fields, request)
        return self.meetings.create_encounter(**fields)

    def _record_opening(
        self, encounter: dict[str, Any], script: MT.MeetingScript
    ) -> list[str]:
        """Record the opening identity on a creating encounter
        (proposal §3.3): opening_script_id, opening_script_version
        (first 16 hex of sha256 of the joined paragraphs),
        opening_paragraphs_json, opening_expected. Returns the
        recorded paragraphs."""
        definition = ENC.get_definition(script)
        paragraphs = list(definition.opening)
        self.meetings.update_encounter(
            encounter["user_id"], encounter["run_id"],
            opening_script_id=f"{encounter['archetype_id']}:{encounter['keystone_index']}",
            opening_script_version=_opening_digest(paragraphs),
            opening_paragraphs=paragraphs,
            opening_expected=len(paragraphs),
        )
        return paragraphs

    def _speak_opening(
        self, user_id: str, encounter: dict[str, Any], paragraphs: list[str]
    ) -> list[dict[str, Any]]:
        """Speak the recorded opening, insert-if-absent per paragraph
        (corrections §3): a re-run returns the existing messages,
        never duplicates. Each paragraph carries its identity
        ``opening:{run_id}:{index}`` and its (index, total) context."""
        cid = encounter["conversation_id"]
        arch_id = encounter["archetype_id"]
        run_id = encounter["run_id"]
        total = len(paragraphs)
        out: list[dict[str, Any]] = []
        for i, paragraph in enumerate(paragraphs):
            out.append(self._say(
                user_id, cid, arch_id, paragraph,
                message_key=f"opening:{run_id}:{i}",
                context={
                    "meeting": True,
                    "opening_index": i,
                    "opening_total": total,
                },
            ))
        return out

    # -- guards ---------------------------------------------------------------

    def _check_beginnable(self, user_id: str, archetype_id: str, keystone_index: int) -> MT.MeetingScript:
        arch_id = (archetype_id or "").strip().lower()
        if arch_id not in stock_archetype_ids():
            raise ValueError(f"Unknown seat: {archetype_id!r}")
        if (arch_id, keystone_index) in _UNRELEASED_MEETINGS:
            raise MeetingError(
                "That meeting is written but not open yet — it will "
                "get its own conversation when its turn comes, "
                "nothing improvised."
            )
        if keystone_seeding.find_keystone_initiative(user_id) is None:
            raise MeetingError(
                "Your council hasn't been seeded yet — the meetings arrive "
                "with the 'Meet your council' initiative."
            )
        script = MT.get_script(arch_id, keystone_index)
        if script is None:
            raise MeetingError(
                "That meeting isn't written yet. It will get its own "
                "conversation when its turn comes — nothing improvised."
            )
        # Build-only hold (Fellowship conversational-agency build):
        # a written meeting in MT.HELD_FIRST_MEETINGS is built, not
        # available. This check changes nothing for any other seat
        # or keystone — it fires only for held entries — and it
        # runs before the entry-seat guard, so a held meeting is
        # refused on its own terms, not by proxy. Lifting it is a
        # one-line removal from that set, under Joshua's separate
        # availability verdict. No meeting row can exist for a
        # held meeting (begin is the only row creator), so turn /
        # complete / restart are unreachable for it as well.
        if (arch_id, keystone_index) in MT.HELD_FIRST_MEETINGS:
            raise MeetingError(
                "That meeting is built but not yet open to visitors — "
                "it will open when its turn comes."
            )
        tasks = _seat_keystone_tasks(user_id, arch_id)
        if len(tasks) < keystone_index:
            raise MeetingError("That keystone isn't part of this seat's chain.")
        # Chain order: earlier keystones complete first.
        for i in range(keystone_index - 1):
            if tasks[i].get("status") != "Done":
                raise MeetingError(
                    f"One meeting at a time — '{tasks[i].get('title')}' comes first."
                )
        # The Conductor opens the council: every other seat's FIRST meeting
        # waits until the entry seat's first meeting is complete.
        # STICKY (Joshua's rule, 2026-10-30: "Once it's open it should
        # stay open"): a seat whose begin door has become available
        # stays beginnable even if the entry seat's task later returns
        # to Todo (Weaver restart / Reopen toggle) — otherwise the lit
        # door would lead to a refusal, which is not "open". The
        # availability sets above (released / held / unreleased),
        # the script check, and the chain check are untouched; only
        # this entry condition consults the sticky record.
        entry = keystone_seeding.ENTRY_SEAT_REF
        if keystone_index == 1 and arch_id != entry:
            entry_tasks = _seat_keystone_tasks(user_id, entry)
            if not entry_tasks or entry_tasks[0].get("status") != "Done":
                if not keystone_seeding.seat_unlocked(user_id, arch_id):
                    raise MeetingError(
                        "The Weaver opens the council — meet them first. The "
                        "others will introduce themselves in their own time."
                    )
        # BUILDING IS NOT AVAILABILITY, last guard: a written script
        # alone never opens a seat to visitors. Only seats in
        # RELEASED_FIRST_MEETING_SEATS may begin a first meeting; a
        # written-but-unreleased seat is refused here, so no
        # transcript, generation, or reveal can happen for it. The
        # guard sits after the seed / script / chain / entry checks
        # so every earlier refusal keeps its original message and
        # the Conductor (released) is untouched.
        if keystone_index == 1 and arch_id not in MT.RELEASED_FIRST_MEETING_SEATS:
            raise MeetingError(
                "That seat's first meeting isn't open to visitors yet — "
                "it is written, not released. It will open in its own "
                "time; nothing is improvised in the meantime."
            )
        return script

    def _keystone_done(self, user_id: str, archetype_id: str, keystone_index: int) -> bool:
        tasks = _seat_keystone_tasks(user_id, archetype_id)
        return len(tasks) >= keystone_index and tasks[keystone_index - 1].get("status") == "Done"

    # -- state ------------------------------------------------------------------

    def state(self, user_id: str, archetype_id: str, keystone_index: int = 1,
              run_id: str | None = None) -> dict[str, Any]:
        """Where this meeting stands, for the frontend. Never raises on
        unseeded/unwritten — it reports, the begin action refuses.

        Reads the LATEST encounter by default (or the named run when
        ``run_id`` is given — a historical revisit, read-only). Status
        comes from the encounter: creating / active (in_progress) /
        complete; a paused meeting reads its paused state from the
        meetings-row mirror. The demeanor unlocks when ANY completed
        encounter exists for this key (amendment §1) — a later run
        never re-locks the face the first meeting revealed.
        ``run_id`` names the encounter in the payload; ``read_only``
        is true for a completed encounter or a revisit of a run that
        is not the latest."""
        arch_id = (archetype_id or "").strip().lower()
        script = MT.get_script(arch_id, keystone_index)
        done = False
        try:
            done = self._keystone_done(user_id, arch_id, keystone_index)
        except Exception:
            done = False
        if run_id is not None:
            enc = self.meetings.get_encounter(user_id, run_id)
            mrow = self.meetings.get(user_id, arch_id, keystone_index)
            if (
                enc is None
                or enc["archetype_id"] != arch_id
                or enc["keystone_index"] != keystone_index
            ):
                # Unknown run for this key: fall back to the latest.
                enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
                run_id = None
        else:
            enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
        if enc is None:
            status = "complete" if done else "not_started"
            stage = "complete" if done else None
            cid = conversation_id_for(arch_id, keystone_index)
            completion_offered = False
            pending_discarded = ""
            read_only = False
            enc_run_id = None
            any_complete = done
        else:
            cid = enc["conversation_id"]
            enc_run_id = enc["run_id"]
            if enc["status"] == "complete":
                status = "complete"
            elif enc["status"] == "creating":
                status = "creating"
            elif (mrow or {}).get("status") == "paused":
                status = "paused"
            else:
                status = "active"
            stage = enc["stage"]
            completion_offered = False
            pending_discarded = ""
            try:
                enc_state = self._hydrate_state(enc, mrow)
                completion_offered = bool(
                    enc_state.completion_offered and status in ("active", "paused"))
                pending_discarded = enc_state.pending_impression_discarded or ""
            except Exception:
                pass
            latest = self.meetings.get_latest_encounter(
                user_id, arch_id, keystone_index
            )
            read_only = enc["status"] == "complete" or (
                latest is not None and latest["run_id"] != enc["run_id"]
            )
            if enc["status"] == "complete":
                any_complete = True
            else:
                encounters = self.meetings.list_encounters(
                    user_id, arch_id, keystone_index
                )
                any_complete = any(
                    e["status"] == "complete" for e in encounters
                )
        return {
            "archetype_id": arch_id,
            "keystone_index": keystone_index,
            "conversation_id": cid,
            "run_id": enc_run_id,
            "read_only": read_only,
            "status": status,
            "stage": stage,
            "completion_offered": completion_offered,
            "pending_impression_discarded": pending_discarded,
            "has_script": script is not None,
            # The reveal payload: who was met, and the demeanor the first
            # meeting unlocks. Only meaningful once complete — before that
            # the frontend shows neither (earned, not announced).
            "character": script.character if script else None,
            "demeanor": script.demeanor if (script and any_complete) else None,
            "messages": self.conversations.history(user_id, cid, limit=100),
        }

    # -- speech ------------------------------------------------------------------

    def _say(self, user_id: str, cid: str, archetype_id: str, body: str,
             message_key: str | None = None,
             context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Speak one voice message into a meeting conversation.

        ``message_key`` is the durable identity for scripted speech
        (corrections §3.3): an opening paragraph or a reveal paragraph
        carries ``opening:{run_id}:{index}`` / ``reveal:{run_id}:{index}``,
        so a re-run returns the existing message instead of speaking
        twice. Unkeyed speech (live runtime lines) is unchanged."""
        try:
            return self.conversations.append_message(
                user_id, cid, archetype_id, "voice", body, mode="base",
                context=context if context is not None else {"meeting": True},
                message_key=message_key,
                via_meeting=True,
            )
        except (
            ConversationWriteRefused, ConversationIntegrityError,
            TransactionStateError, OpeningIntegrityConflict,
        ) as exc:
            self._translate_store_error(exc)

    def _resume_creating_encounter(
        self, user_id: str, encounter: dict[str, Any], script: MT.MeetingScript
    ) -> dict[str, Any]:
        """Resume an encounter stuck in 'creating': re-attempt the
        recorded opening (insert-if-absent) and flip to in_progress.
        Fails closed — the encounter stays as it is — when the opening
        was never recorded or its recorded paragraphs do not match
        their recorded version (a digest mismatch means the record
        itself is untrustworthy, never the live script)."""
        paragraphs = encounter.get("opening_paragraphs")
        version = encounter.get("opening_script_version")
        if not paragraphs or not version:
            raise MeetingError(
                "This meeting's opening was never recorded, so its "
                "creation cannot be resumed safely — the encounter "
                "stays as it is.",
                code="opening_unrecorded",
                run_id=encounter["run_id"],
            )
        if _opening_digest(paragraphs) != version:
            raise MeetingError(
                "This meeting's recorded opening does not match its "
                "recorded version — the encounter stays as it is.",
                code="opening_integrity_conflict",
                run_id=encounter["run_id"],
            )
        self.conversations.ensure_conversation(
            user_id, encounter["conversation_id"], kind="meeting"
        )
        self._speak_opening(user_id, encounter, paragraphs)
        self.meetings.update_encounter(
            user_id, encounter["run_id"], status="in_progress"
        )
        return self.state(
            user_id, encounter["archetype_id"], encounter["keystone_index"]
        )

    def start(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        """Begin (or resume) a meeting. A fresh start delivers the
        encounter's opening — the script's authored introduction
        (the Weaver's is four bubbles, delivered verbatim) — and
        the encounter begins. A resume returns current state: the
        transcript carries what was already said, nothing repeats.

        The encounter is the unit: a start resumes the latest
        in-progress encounter, returns the completed state for a
        completed one (Meet Again opens the next run — start never
        re-opens a finished run), and creates run 1 only when no
        encounter and no meetings row exist. A Done keystone task with
        an in-progress successor resumes the successor; a Done task
        with a completed latest encounter backfills the impression.
        The per-key lock serializes concurrent starts for one key."""
        arch_id = (archetype_id or "").strip().lower()
        script = self._check_beginnable(user_id, arch_id, keystone_index)
        key = f"key:{user_id}:{arch_id}:{keystone_index}"
        with _lock_for(key):
            self.recover_incomplete_encounters(user_id, arch_id, keystone_index)

            if self._keystone_done(user_id, arch_id, keystone_index):
                enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
                if enc is None:
                    # The task is Done but no meeting record exists:
                    # create the row and materialize a completed
                    # encounter for it.
                    self.meetings.create(user_id, arch_id, keystone_index)
                    self.meetings.update(
                        user_id, arch_id, keystone_index,
                        stage="complete", status="complete",
                    )
                    enc, mrow = self._resolve_encounter(
                        user_id, arch_id, keystone_index
                    )
                if enc["status"] == "in_progress":
                    # A successor is live: the Done task belongs to
                    # the predecessor. Resume the successor.
                    return self.state(user_id, arch_id, keystone_index)
                if enc["status"] == "creating":
                    return self._resume_creating_encounter(user_id, enc, script)
                # The latest encounter is complete: backfill the
                # impression (idempotent per run) and return the
                # completed state.
                self._file_impression(user_id, arch_id, keystone_index, script)
                return self.state(user_id, arch_id, keystone_index)

            enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
            if enc is not None:
                if enc["status"] == "complete":
                    return self.state(user_id, arch_id, keystone_index)
                if enc["status"] == "creating":
                    return self._resume_creating_encounter(user_id, enc, script)
                if (mrow or {}).get("status") == "paused":
                    self.meetings.update(
                        user_id, arch_id, keystone_index, status="active"
                    )
                return self.state(user_id, arch_id, keystone_index)

            # Fresh start: run 1. The meetings row is the pointer;
            # the encounter owns the conversation.
            self.meetings.create(user_id, arch_id, keystone_index)
            enc = self._create_encounter(user_id, arch_id, keystone_index)
            initial_state = EncounterState().to_json()
            self.meetings.update(
                user_id, arch_id, keystone_index,
                run_id=enc["run_id"], conversation_id=enc["conversation_id"],
                state_json=initial_state,
            )
            self.meetings.update_encounter(
                user_id, enc["run_id"], state_json=initial_state
            )
            self.conversations.ensure_conversation(
                user_id, enc["conversation_id"], kind="meeting"
            )
            paragraphs = self._record_opening(enc, script)
            self._speak_opening(user_id, enc, paragraphs)
            self.meetings.update_encounter(
                user_id, enc["run_id"], status="in_progress"
            )
            return self.state(user_id, arch_id, keystone_index)

    def meet_again(
        self, user_id: str, arch_id: str, keystone_index: int = 1,
        predecessor_run_id: str | None = None, request_id: str | None = None,
    ) -> dict[str, Any]:
        """Open the next encounter after a completed one (proposal §5).

        Identity-first (corrections §2, AC15/AC19): the (user_id,
        request_id) record IS the request's identity. A retry with the
        same request_id returns the existing successor
        (``successor_exists: true``); the same request_id for a
        DIFFERENT predecessor is a ``request_identity_conflict`` (409).
        The predecessor must exist and be complete: no encounter ever
        existed for the key -> 404; the run id matches no encounter
        for the key -> 422 ``predecessor_unknown``; the predecessor is
        not complete -> 409 ``encounter_in_progress``. The successor
        leaves the predecessor byte-identical (AC1) and carries
        run_number + 1 with the predecessor bound explicitly (AC19).
        A crash during creation leaves a 'creating' successor; a
        retry resumes it (the recorded opening is replayed, never
        re-recorded). Returns {encounter, state, resumed,
        successor_exists}. The per-key lock serializes concurrent
        Meet Again calls for one key."""
        arch_id = (arch_id or "").strip().lower()
        if arch_id not in stock_archetype_ids():
            raise ValueError(f"Unknown seat: {arch_id!r}")
        script = MT.get_script(arch_id, keystone_index)
        if script is None:
            raise MeetingError("That meeting isn't written yet.")
        if not (predecessor_run_id or "").strip():
            raise MeetingValidationError(
                "A predecessor run is required — Meet Again opens the next "
                "run after a completed one.",
                code="predecessor_required",
            )
        predecessor_run_id = (predecessor_run_id or "").strip()
        request_id = (request_id or "").strip()
        key = f"key:{user_id}:{arch_id}:{keystone_index}"
        with _lock_for(key):
            # Identity-first: a retry returns the existing successor.
            existing = self.meetings.get_meet_again_request(user_id, request_id)
            if existing is not None:
                if existing["predecessor_run_id"] != predecessor_run_id:
                    raise MeetingError(
                        "This request id was already used for a different "
                        "predecessor — a request id identifies one Meet Again.",
                        code="request_identity_conflict",
                    )
                successor = self.meetings.get_encounter(
                    user_id, existing["successor_run_id"]
                )
                if successor is None:
                    # The request record exists but its successor row
                    # does not — an integrity failure, never silently
                    # re-created.
                    raise ConversationIntegrityError(
                        "meet-again request references a missing successor "
                        f"run {existing['successor_run_id']!r}"
                    )
                if successor["status"] == "creating":
                    # A crash during creation: resume it (the recorded
                    # opening is replayed, never re-recorded).
                    self._resume_creating_encounter(user_id, successor, script)
                    successor = self.meetings.get_encounter(
                        user_id, existing["successor_run_id"]
                    )
                return {
                    "encounter": successor,
                    "state": self.state(user_id, arch_id, keystone_index),
                    "resumed": True,
                    "successor_exists": True,
                }

            # The predecessor must exist and be complete.
            pred = self.meetings.get_encounter(user_id, predecessor_run_id)
            if pred is None or pred["archetype_id"] != arch_id or pred["keystone_index"] != keystone_index:
                if self.meetings.get_latest_encounter(user_id, arch_id, keystone_index) is None:
                    raise MeetingNotFoundError(
                        "No encounter ever existed for this meeting — "
                        "begin one first, then meet again."
                    )
                raise MeetingValidationError(
                    f"Unknown predecessor run: {predecessor_run_id!r}.",
                    code="predecessor_unknown",
                )
            if pred["status"] != "complete":
                raise MeetingError(
                    "This meeting is still in progress — meet again once "
                    "it has reached its close.",
                    code="encounter_in_progress",
                    run_id=pred["run_id"],
                )

            # A successor already exists for this predecessor (a stale
            # predecessor, or a concurrent creation that won): return
            # it — exactly one successor per predecessor (AC19). The
            # successor's request record belongs to the creation that
            # made it (UNIQUE successor_run_id); an adopter does not
            # record a second one — a retry re-runs this check and
            # returns the same successor.
            existing_successor = self.meetings.get_successor(
                user_id, predecessor_run_id
            )
            if existing_successor is not None:
                return {
                    "encounter": existing_successor,
                    "state": self.state(user_id, arch_id, keystone_index),
                    "resumed": True,
                    "successor_exists": True,
                }

            # Create the successor (encounter row + request record in
            # one transaction) and deliver its opening.
            try:
                enc = self._create_encounter(
                    user_id, arch_id, keystone_index, predecessor=pred,
                    request={
                        "user_id": user_id,
                        "request_id": request_id,
                        "predecessor_run_id": predecessor_run_id,
                    },
                )
            except sqlite3.IntegrityError:
                # A concurrent creation won the race between the
                # successor check and this insert (the UNIQUE
                # predecessor constraint enforces one successor per
                # predecessor). Re-read and adopt it.
                existing = self.meetings.get_meet_again_request(user_id, request_id)
                if existing is not None:
                    successor = self.meetings.get_encounter(
                        user_id, existing["successor_run_id"]
                    )
                    return {
                        "encounter": successor,
                        "state": self.state(user_id, arch_id, keystone_index),
                        "resumed": True,
                        "successor_exists": True,
                    }
                latest = self.meetings.get_latest_encounter(
                    user_id, arch_id, keystone_index
                )
                if latest is not None and latest.get("predecessor_run_id") == predecessor_run_id:
                    return {
                        "encounter": latest,
                        "state": self.state(user_id, arch_id, keystone_index),
                        "resumed": True,
                        "successor_exists": True,
                    }
                raise
            initial_state = EncounterState().to_json()
            self.meetings.update(
                user_id, arch_id, keystone_index,
                run_id=enc["run_id"], conversation_id=enc["conversation_id"],
                state_json=initial_state,
            )
            self.meetings.update_encounter(
                user_id, enc["run_id"], state_json=initial_state
            )
            self.conversations.ensure_conversation(
                user_id, enc["conversation_id"], kind="meeting"
            )
            paragraphs = self._record_opening(enc, script)
            self._speak_opening(user_id, enc, paragraphs)
            self.meetings.update_encounter(
                user_id, enc["run_id"], status="in_progress"
            )
            return {
                "encounter": self.meetings.get_encounter(user_id, enc["run_id"]),
                "state": self.state(user_id, arch_id, keystone_index),
                "resumed": False,
                "successor_exists": False,
            }

    def list_encounters(
        self, user_id: str, arch_id: str, keystone_index: int = 1
    ) -> list[dict[str, Any]]:
        """Every encounter for the key, run_number ascending (the
        lineage). Each carries ``identity_kind`` (from
        run_id_provenance), ``read_only`` (a completed encounter is
        read-only), and ``lineage_label`` — ``"follows (archive
        order)"`` for a reconstructed (legacy) link, ``"follows"``
        for a witnessed one, None for the first run."""
        encounters = self.meetings.list_encounters(user_id, arch_id, keystone_index)
        out: list[dict[str, Any]] = []
        for enc in encounters:
            e = dict(enc)
            e["identity_kind"] = enc.get("run_id_provenance") or "generated"
            e["read_only"] = enc["status"] == "complete"
            # The fence state, so the frontend can distinguish an
            # in-progress encounter from one interrupted during
            # completion (fence closed, not finalized).
            e["fence_state"] = self.conversations.get_fence_state(
                user_id, enc["conversation_id"]
            )
            if enc.get("predecessor_link_kind") == "reconstructed":
                e["lineage_label"] = "follows (archive order)"
            elif enc.get("predecessor_run_id"):
                e["lineage_label"] = "follows"
            else:
                e["lineage_label"] = None
            out.append(e)
        return out

    def get_encounter_detail(
        self, user_id: str, run_id: str, limit: int = 100, offset: int = 0
    ) -> dict[str, Any] | None:
        """One encounter + its transcript, owner-scoped (another
        user's run_id returns None -> 404 at the route). A completed
        encounter is read-only. A live encounter's transcript is
        paged from its conversation (bound, default 100); an archive
        encounter's transcript is paged in memory from its
        transcript_json (same bound)."""
        enc = self.meetings.get_encounter(user_id, run_id)
        if enc is None:
            return None
        limit = max(1, min(int(limit or 100), 200))
        offset = max(0, int(offset or 0))
        if enc.get("transcript_source") == "archive":
            try:
                transcript = json.loads(enc.get("transcript_json") or "[]")
            except Exception:
                transcript = []
            if not isinstance(transcript, list):
                transcript = []
            total = len(transcript)
            messages = transcript[offset:offset + limit]
        else:
            messages = self.conversations.history(
                user_id, enc["conversation_id"], limit=limit, offset=offset
            )
            total = self.conversations.count_messages(user_id, enc["conversation_id"])
        return {
            "encounter": dict(
                enc,
                read_only=enc["status"] == "complete",
                fence_state=self.conversations.get_fence_state(
                    user_id, enc["conversation_id"]
                ),
            ),
            "messages": messages,
            "total": total,
            "read_only": enc["status"] == "complete",
            # What the verification badge does and does not establish
            # (readiness amendment §A) — carried into user-facing copy.
            "verification_note": READ_CONSISTENCY_NORMATIVE,
        }

    def turn(self, user_id: str, archetype_id: str, message: str, keystone_index: int = 1) -> dict[str, Any]:
        """One user turn inside an active meeting. The encounter
        runtime runs the turn — the user's move first, the character's
        objectives behind it — and this service persists the outcome.
        Raises MeetingError when no meeting is in progress, ValueError
        on bad input. A turn to a completed encounter is refused with
        ``encounter_finalized`` (409): the encounter is complete, its
        last stored message is its last word, and no retry is
        attempted — Meet Again opens the next run. The per-run lock
        serializes concurrent turns on one run."""
        arch_id = (archetype_id or "").strip().lower()
        if arch_id not in stock_archetype_ids():
            raise ValueError(f"Unknown seat: {archetype_id!r}")
        if not (message or "").strip():
            raise ValueError("Message is empty.")
        enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
        if enc is None:
            raise MeetingError("No meeting is in progress with this seat — begin one first.")
        if enc["status"] == "complete":
            raise MeetingError(
                "This meeting has reached its close — its last stored "
                "message is its last word. Meet again to open a new run.",
                code="encounter_finalized",
                run_id=enc["run_id"],
            )
        if enc["status"] == "creating":
            script = MT.get_script(arch_id, keystone_index)
            if script is None:
                raise MeetingError("That meeting isn't written yet.")
            self._resume_creating_encounter(user_id, enc, script)
            enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
        script = MT.get_script(arch_id, keystone_index)
        if script is None:  # state without a script shouldn't exist; be honest
            raise MeetingError("That meeting isn't written yet.")
        with _lock_for(f"run:{enc['run_id']}"):
            if (mrow or {}).get("status") == "paused":
                self.meetings.update(user_id, arch_id, keystone_index, status="active")
                mrow = self.meetings.get(user_id, arch_id, keystone_index)

            cid = enc["conversation_id"]
            try:
                self.conversations.append_message(
                    user_id, cid, arch_id, "user", message, mode="base",
                    context={"meeting": True}, via_meeting=True,
                )
            except (
                ConversationWriteRefused, ConversationIntegrityError,
                TransactionStateError, OpeningIntegrityConflict,
            ) as exc:
                self._translate_store_error(exc, run_id=enc["run_id"])

            enc_state = self._hydrate_state(enc, mrow)
            if enc_state.closed:
                raise MeetingError("This meeting has already reached its close.")
            definition = ENC.get_definition(script)
            # The naming rule needs the met set: completed first meetings
            # only (see MeetingStore.met_seats). The definition is frozen,
            # so replace rather than mutate. Same pattern for capability
            # context (demonstration spec §6): re-resolved per turn from
            # the visitor's actual state, so a consent-gated capability
            # is never implied usable to a visitor who has not consented.
            definition = dataclasses.replace(
                definition,
                met_seats=tuple(self.meetings.met_seats(user_id)),
                capability_context=CAP.first_meeting_block(
                    arch_id, CAP.resolve_visitor_state(user_id)),
            )
            host = _MeetingHost(
                self, user_id, arch_id, keystone_index, script,
                fellowship_reference=definition.fellowship_reference,
                decoupled_recognition=definition.decoupled_recognition,
                conversation_id=cid,
            )
            new_q_idx = EncounterRuntime(definition).handle_turn(
                host, enc_state, message, int((mrow or {}).get("question_idx") or 0)
            )
            stage = ENC.derived_stage(enc_state)
            state_json = enc_state.to_json()
            self.meetings.update_encounter(
                user_id, enc["run_id"], state_json=state_json, stage=stage
            )
            self.meetings.update(
                user_id, arch_id, keystone_index,
                question_idx=new_q_idx, state_json=state_json, stage=stage,
            )
            return self.state(user_id, arch_id, keystone_index)

    @staticmethod
    def _hydrate_state(
        row: dict[str, Any], meetings_row: dict[str, Any] | None = None
    ) -> EncounterState:
        """The encounter state for a meeting row. Rows begun before
        the encounter runtime carry no state_json; their position is
        reconstructed from the columns the old engine already kept —
        the read-back claim/response and the stage label — so an
        in-progress meeting survives the engine change honestly.

        The read-back columns are read from the meetings row when
        one is given: the host writes them there during the encounter
        (the encounter row's copy syncs only at finalize), so the
        meetings row is the live source for whether an impression was
        offered and answered. A read-back the meetings row records
        but the encounter state doesn't is a legacy (pre-runtime)
        impression — the recognition floor is waived for it, never
        for one the runtime itself has run."""
        state = EncounterState.from_json(row.get("state_json"))
        source = meetings_row if meetings_row is not None else row
        if row.get("state_json") and not (source.get("readback_claim") or "").strip():
            return state
        if (source.get("readback_claim") or "").strip():
            if not state.impression_offered:
                # Legacy (pre-runtime) impression: the runtime never
                # offered it, so the recognition floor is waived.
                state.impression_offered = True
                state.impression_text = source["readback_claim"]
                state.floor_waived = True
                try:
                    state.impression_strands = json.loads(
                        source.get("readback_strands") or "[]"
                    )
                except Exception:
                    state.impression_strands = []
        if (source.get("readback_response") or "").strip():
            state.impression_answered = True
            state.response_recorded = True
        if source.get("stage") == "orientation":
            state.pause_delivered = True
            # The orientation stage was only ever reachable after
            # the read-back was answered, in both engines — the
            # adaptive runtime reads it as the post-recognition
            # phase, so an in-flight meeting is never stranded.
            state.impression_answered = True
        return state

    def _history_for_reply(self, user_id: str, cid: str) -> list[dict[str, str]]:
        rows = self.conversations.history(user_id, cid, limit=30)
        return [{"role": m["role"], "content": m["body"]} for m in rows]

    def _generate_framed(self, user_id: str, arch_id: str, keystone_index: int,
                         frame: str, fellowship_reference: str = "",
                         conversation_id: str | None = None) -> str:
        """Run one live beat against the transcript: the last user message
        is lifted out as the reply builder's input, everything else stays
        as context, in order. Returns the raw reply text.
        `fellowship_reference` is the seat's slice of the shared
        Fellowship knowledge, carried as an uncapped meeting-scoped
        prompt section (see reply.build_voice_prompt) — "" means no
        reference has been written for this seat yet, and the prompt
        is byte-identical to before (mechanism only, no content).
        `conversation_id` is the encounter's own conversation; the
        legacy shared id only when no encounter exists yet."""
        cid = conversation_id or conversation_id_for(arch_id, keystone_index)
        history = self._history_for_reply(user_id, cid)
        last_user_idx = max(
            (i for i, m in enumerate(history) if m["role"] == "user"), default=None
        )
        if last_user_idx is None:
            return ""
        last_user = history[last_user_idx]
        prior = history[:last_user_idx] + history[last_user_idx + 1:]
        reply = generate_voice_reply(
            user_id, arch_id, last_user.get("content", ""), prior,
            mode="base", generate_fn=self._generate_fn,
            extra_instructions=frame,
            fellowship_reference=fellowship_reference or None,
            # Meetings run under the evidence/expression separation
            # (Joshua's ruling, 2026-10-23): the character synthesizes
            # in her own words; exact quotes live in the evidence.
            # canonical=False keeps the legacy assembly (ordinary
            # turns use the canonical renderer); no quote-weaving
            # instruction exists on any path anymore (removed
            # 2026-11-02, Step 2).
            canonical=False,
            timing_label="meeting",
        )
        return reply.reply

    def _read_consistency_check(
        self, user_id: str, encounter: dict[str, Any],
        meetings_row: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]]:
        """The completion read-consistency check (readiness amendment
        §A, AC5/AC16): two independent paged reads of the encounter's
        transcript (the live `messages` rows for its conversation id,
        in `id` order) must agree on count, `id` sequence, and order;
        the six read-back fields must be present on the meetings row;
        `state_json` must parse. Returns (status, detail_entry) —
        `read_consistency_verified` or `read_consistency_failed`.
        A failure NEVER blocks completion (the encounter is still
        marked complete; a successor is still creatable) — it is
        recorded, and the detail history is append-only, so a failed
        check never overwrites a prior passing record. See
        READ_CONSISTENCY_NORMATIVE for what the check does and does
        not establish."""
        cid = encounter["conversation_id"]
        checked_at = _utcnow()

        def _read_all() -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            offset = 0
            while True:
                page = self.conversations.history(
                    user_id, cid, limit=200, offset=offset
                )
                rows.extend(page)
                if len(page) < 200:
                    break
                offset += len(page)
            return rows

        failures: list[str] = []
        try:
            first = _read_all()
            second = _read_all()
        except Exception as exc:  # noqa: BLE001 — the check records, never raises
            failures.append(f"read_error: {exc}")
            first, second = [], []
        first_ids = [m["id"] for m in first]
        second_ids = [m["id"] for m in second]
        if len(first) != len(second):
            failures.append(
                f"count_mismatch: first={len(first)} second={len(second)}"
            )
        if first_ids != second_ids:
            failures.append("id_sequence_mismatch")
        mrow = meetings_row or {}
        for col in (
            "readback_claim", "readback_response", "readback_strands",
            "readback_original_claim", "readback_seat_outcome",
            "readback_visitor_response",
        ):
            if mrow.get(col) is None:
                failures.append(f"readback_field_missing: {col}")
        raw_state = encounter.get("state_json") or ""
        if raw_state:
            try:
                state = json.loads(raw_state)
                if not isinstance(state, dict):
                    failures.append("state_json_not_an_object")
            except Exception:
                failures.append("state_json_unparseable")
        status = (
            "read_consistency_failed" if failures else "read_consistency_verified"
        )
        detail = {
            "checked_at": checked_at,
            "result": status,
            "count": len(first),
            "id_range": [first_ids[0], first_ids[-1]] if first_ids else [None, None],
            "failures": failures,
            "note": READ_CONSISTENCY_NORMATIVE,
        }
        return status, detail

    def _do_reveal(self, user_id: str, arch_id: str, keystone_index: int,
                   script: MT.MeetingScript, wrap_line: str = "",
                   silent_close: bool = False) -> None:
        """The completion chokepoint (the runtime's `close`): the
        reveal, the keystone task Done, and the impression filed —
        every path that finishes a meeting funnels through here, so
        the filing happens exactly once per run. A ceiling close
        speaks its wrap line first ("I've kept you long enough").
        `silent_close` (decoupled recognition, no-scripting build,
        2026-10-29): no scripted speech at all — neither the wrap
        line nor the reveal paragraphs. The recognition moment
        already introduced the character live, and the completion
        card marks the close; the task Done, event, and filing
        below still run exactly as before.

        The corrected order (proposal §3.1): (1) reveal dialogue via
        _say, each paragraph carrying its durable identity
        (``reveal:{run_id}:{index}`` — the wrap line is index 0, the
        script's reveal paragraphs 1..n — so a re-run returns the
        existing messages, never speaks twice); (2) keystone task
        Done; (3) the completed-meeting event; (4) the impression
        filed; (5) the write fence closed; (6) atomic
        finalize_encounter (incl. the meetings-row mirror in the same
        transaction). A crash between (5) and (6) is healed by
        recover_incomplete_encounters (CR-B5); a crash during (1)
        re-runs the reveal insert-if-absent (CR-B1/B2). Completing an
        already-complete encounter is a no-op (the reveal is never
        spoken twice). The per-run lock serializes concurrent closes
        of one run."""
        enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
        if enc is None:
            raise MeetingError(
                "There's no meeting in progress to complete — this seat "
                "hasn't been met yet."
            )
        with _lock_for(f"run:{enc['run_id']}"):
            if enc["status"] == "complete":
                return
            run_id = enc["run_id"]
            cid = enc["conversation_id"]
            if not silent_close:
                if wrap_line:
                    self._say(user_id, cid, arch_id, wrap_line,
                              message_key=f"reveal:{run_id}:0")
                for i, paragraph in enumerate(script.reveal):
                    self._say(user_id, cid, arch_id, paragraph,
                              message_key=f"reveal:{run_id}:{i + 1}")

            tasks = _seat_keystone_tasks(user_id, arch_id)
            if len(tasks) >= keystone_index:
                task = tasks[keystone_index - 1]
                if task.get("status") != "Done":
                    ve.update_task(task["id"], ve_models.TaskUpdate(status="Done"), user_id)
            # Fellowship Runtime P1: the completed meeting is a
            # shared-reality event, emitted at this same single chokepoint
            # (guarded inside _emit_meeting_completed — it can never break
            # the close, and its derivation only produces observations).
            # A recovery re-run skips the emit when the impression is
            # already filed: the emit precedes the filing, so a filed
            # claim proves the emit ran — re-emitting would duplicate
            # the event. (The narrow window between the emit and the
            # filing can still duplicate it once; see the build report.)
            if not self._impression_claim_exists(
                user_id, arch_id, keystone_index, script, enc, mrow
            ):
                self._emit_meeting_completed(
                    user_id, arch_id, keystone_index, conversation_id=cid
                )
            self._file_impression(user_id, arch_id, keystone_index, script)
            # (5) the fence closes before the finalize: a crash here
            # leaves CR-B5 (fence closed, finalized_at NULL), healed by
            # the recovery rule, never by re-running the reveal.
            try:
                fence_result = self.conversations.close_fence(user_id, cid, run_id)
            except TransactionStateError as exc:
                self._translate_store_error(exc, run_id=run_id)
            if fence_result == "missing":
                raise ConversationIntegrityError(
                    f"no fence row for meeting conversation {cid!r}; "
                    "refusing to finalize an encounter whose writes "
                    "were never fenced"
                )
            if fence_result == "closed-by-other-run":
                raise ConversationIntegrityError(
                    f"fence for meeting conversation {cid!r} was closed "
                    "by another run; refusing to finalize"
                )
            # (6) the completion read-consistency check (AC5/AC16):
            # the fence is closed, so the transcript is stable for
            # the two reads. A failure is recorded, never a block —
            # the encounter still completes.
            verification_status, verification_detail = self._read_consistency_check(
                user_id, enc, mrow
            )
            # (7) atomic finalize (incl. the meetings-row mirror).
            message_count = self.conversations.count_messages(user_id, cid)
            self.meetings.finalize_encounter(
                user_id, run_id, message_count=message_count,
                verification_status=verification_status,
                verification_detail=verification_detail,
                verification_checked_at=verification_detail["checked_at"],
            )

    def _emit_meeting_completed(self, user_id: str, arch_id: str, keystone_index: int,
                                conversation_id: str | None = None) -> None:
        """Record the completed meeting as a fellowship event.

        Evidence is the user's verbatim read-back answer (their words
        about the impression) when the run stored one; otherwise the
        observation will cite the meeting itself by reference. Guarded
        like _file_impression: failures are logged, never raised.
        The entity is the encounter's own conversation."""
        try:
            from local_ai.fellowship.events import emit_event

            row = self.meetings.get(user_id, arch_id, keystone_index) or {}
            emit_event(
                kind="meeting_completed",
                user_id=user_id,
                entity_type="meeting",
                entity_id=conversation_id
                or conversation_id_for(arch_id, keystone_index),
                evidence_text=(row.get("readback_response") or ""),
                summary=(
                    f"First meeting completed with the {arch_id} voice "
                    f"(keystone {keystone_index})."
                ),
                payload={
                    "archetype_id": arch_id,
                    "keystone_index": keystone_index,
                },
            )
        except Exception:
            logger.exception("fellowship: meeting-completed event failed")


    def _build_meeting_impression_claim(
        self, user_id: str, arch_id: str, keystone_index: int,
        script: MT.MeetingScript, run_key: str, filed_via: str = "",
    ):
        """The meeting_impression claim for one run (or None when the
        run has no read-back to file). The claim id carries the
        run_key, so one run's filing is idempotent and a new run's
        filing is distinct — the D5 sweep and the _do_reveal emit
        guard compute the same id through here."""
        row = self.meetings.get(user_id, arch_id, keystone_index)
        if not row or not (row.get("readback_claim") or "").strip():
            return None
        from local_ai.agent_intake import review_claims

        try:
            strand_names = json.loads(row.get("readback_strands") or "[]")
        except Exception:
            strand_names = []
        strand_keys = [PLAIN_TO_KEY[n] for n in strand_names if n in PLAIN_TO_KEY]
        return review_claims.build_meeting_impression_claim(
            agent_id=conversation_id_for(arch_id, keystone_index),
            seat_name=script.character,
            readback_claim=row.get("readback_claim") or "",
            readback_response=row.get("readback_response") or "",
            strand_keys=strand_keys,
            run_key=run_key,
            readback_original_claim=row.get("readback_original_claim") or "",
            readback_seat_outcome=row.get("readback_seat_outcome") or "",
            readback_visitor_response=row.get("readback_visitor_response") or "",
            ceiling_filed=_is_ceiling_filed(row),
            filed_via=filed_via,
        )

    def _impression_claim_exists(
        self, user_id: str, arch_id: str, keystone_index: int,
        script: MT.MeetingScript,
        encounter: dict[str, Any] | None,
        meetings_row: dict[str, Any] | None,
    ) -> bool:
        """Whether this run's meeting_impression claim already exists
        in the review queue. The emit precedes the filing, so a filed
        claim proves the emit ran — a recovery re-run of _do_reveal
        skips the emit on that evidence. A store failure reads as
        'not filed' (the emit then runs; a duplicate event is the
        lesser harm)."""
        claim = self._build_meeting_impression_claim(
            user_id, arch_id, keystone_index, script,
            _run_key_for_encounter(encounter, meetings_row),
        )
        if claim is None:
            return False
        from local_ai.agent_intake.store import AgentStore

        store = (
            self._agent_store_factory(user_id)
            if self._agent_store_factory is not None
            else AgentStore(user_id=user_id)
        )
        agent_id = conversation_id_for(arch_id, keystone_index)
        try:
            return any(c.id == claim.id for c in store.get_claims(agent_id))
        except Exception:
            return False

    def _file_impression(self, user_id: str, arch_id: str, keystone_index: int,
                         script: MT.MeetingScript,
                         filed_via: str = "") -> None:
        """File the completed meeting's read-back impression as a review
        claim — the orientation's promise ("the full text of both waits
        in your review, word for word"), kept.

        One "meeting_impression" claim under a ConnectedAgent anchored
        to the meeting's transcript id ("meeting-{seat}-{keystone}"),
        carrying the full read-back and the user's verbatim answer.
        Nothing trains: the claim sits pending like every other claim
        until the user rules on it, and the verdict is what writes the
        training signal (under the read-back's strands, via the normal
        claim-feedback machinery).

        Idempotent per run: the claim id carries the run's key
        (run_id for a new run, the created_at-derived key for a run
        that predates encounters — see _run_key_for_encounter), and an
        existing claim is never re-saved (save_claims is INSERT OR
        REPLACE — re-saving would reset its verdict). A replay is a
        new run with a new claim, and filing that new claim
        SUPERSEDES every prior meeting_impression claim for the same
        agent (Fellowship supersede rule, 2026-10-28): the old rows
        stay in history with their prior verdicts recorded in their
        detail (review_claims.supersede_claim), but only the new claim
        stands — exactly one standing meeting_impression claim per
        seat+visitor. Restart ALONE does not supersede: the prior claim
        stays standing until a new run completes and files. Re-filing
        the SAME run (is_new false) supersedes nothing, including
        itself. Supersede writes no training signal. Filing must never
        break a meeting's close, so failures are logged, not raised.
        """
        try:
            enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
            row = self.meetings.get(user_id, arch_id, keystone_index)
            if not row or not (row.get("readback_claim") or "").strip():
                return
            from local_ai.agent_intake.schema import (
                ConnectedAgent,
                MomentClaim,
                SortResult,
                StrandClaim,
            )
            from local_ai.agent_intake.store import AgentStore

            store = (
                self._agent_store_factory(user_id)
                if self._agent_store_factory is not None
                else AgentStore(user_id=user_id)
            )
            agent_id = conversation_id_for(arch_id, keystone_index)
            try:
                strand_names = json.loads(row.get("readback_strands") or "[]")
            except Exception:
                strand_names = []
            strand_keys = [PLAIN_TO_KEY[n] for n in strand_names if n in PLAIN_TO_KEY]
            run_key = _run_key_for_encounter(enc, mrow)
            claim = self._build_meeting_impression_claim(
                user_id, arch_id, keystone_index, script, run_key,
                filed_via=filed_via,
            )
            if claim is None:
                return
            existing = store.get_claims(agent_id)
            is_new = claim.id not in {c.id for c in existing}

            # The meeting as a reviewable source: its transcript is the
            # agent's material; the read-back's own strand attribution
            # is its sort (which is also what places it under the seat's
            # review group). Refreshed per run — the claim ids keep each
            # run's filing distinct.
            history_cid = (enc or {}).get("conversation_id") or agent_id
            history = self.conversations.history(user_id, history_cid, limit=200)
            examples = [
                f"{'USER' if m.get('role') == 'user' else 'ASSISTANT'}: {m.get('body') or ''}"
                for m in history
            ]
            sort = SortResult(
                primary_strand=strand_keys[0] if strand_keys else "",
                claims=[
                    StrandClaim(
                        strand=k,
                        score=1.0,
                        reasoning="Named by the seat's read-back in its first meeting.",
                    )
                    for k in strand_keys
                ],
                strand_weights={k: 1.0 for k in strand_keys},
                kind="undecided",
                confidence=1.0,
                needs_probing=False,
                moments=(
                    [
                        MomentClaim(
                            strand=strand_keys[0],
                            quote=claim.evidence,
                            inference=claim.inference,
                        )
                    ]
                    if strand_keys
                    else []
                ),
            )
            agent = store.get(agent_id)
            if agent is None:
                agent = ConnectedAgent(
                    id=agent_id,
                    name=f"First meeting — {script.character}",
                    source_platform="meeting",
                    description=(
                        f"{script.character}'s first meeting with you — the "
                        "read-back impression it formed, filed for your review."
                    ),
                    instructions=None,
                    examples=examples,
                    sort=sort,
                    status="pending_review",
                    created_at=row.get("created_at") or _utcnow(),
                    mining_state="skipped",
                )
            else:
                agent.examples = examples
                agent.sort = sort
                agent.status = "pending_review"
            store.save(agent)
            if is_new:
                # Supersede (2026-10-28 decision): a genuinely new
                # filing replaces every prior meeting_impression claim
                # for this agent as the standing one. Only claims of
                # this type, only this agent, never the new claim
                # itself, never an already-superseded row — and never
                # on a same-run re-filing, which never reaches here.
                # Other claim types (strand, kind, mined, ...) are
                # untouched: supersede is scoped to meeting impressions.
                priors = [
                    c
                    for c in existing
                    if c.claim_type == "meeting_impression"
                    and c.id != claim.id
                    and c.status != "superseded"
                ]
                superseded = [
                    review_claims.supersede_claim(c, claim.id) for c in priors
                ]
                if superseded:
                    store.save_claims(agent_id, superseded)
                store.save_claims(agent_id, [claim])
            else:
                # D5 staleness rule (2026-11-07): the same run's
                # impression was filed once and the meeting's row has
                # since changed (a revised read-back, a later
                # affirmation). If the stored claim is still pending —
                # no verdict recorded — refresh its inference, evidence
                # and detail in place, under the same claim id. A ruled
                # claim is never touched here; the verdict stands. The
                # visitor's own note on the claim is preserved.
                existing_claim = next(
                    (c for c in existing if c.id == claim.id), None
                )
                if (
                    existing_claim is not None
                    and existing_claim.status == "pending"
                    and claim.inference != existing_claim.inference
                ):
                    claim.user_note = existing_claim.user_note
                    store.save_claims(agent_id, [claim])
        except Exception:
            logger.exception("meeting impression filing failed")

    def recover_affirmed_impressions(self, user_id: str) -> list[str]:
        """Recovery sweep (D5, 2026-11-07): file affirmed-but-unfiled
        impressions from meetings that are still active.

        The close path files an impression when the meeting completes,
        but a meeting that never completes — still active, the visitor
        long gone — leaves an affirmed impression with no claim. This
        sweep finds those rows and files them through the same
        _file_impression path the close uses, with
        filed_via="affirmation_recovery" so the claim's detail says
        how it got there.

        A row qualifies only when the meeting is still active, its
        read-back is non-empty, the visitor's response is 'affirmed',
        and the meeting's conversation has been quiet for
        AFFIRMATION_RECOVERY_QUIET_DAYS — a live conversation is left
        alone; the close path will file it when it completes. If a
        claim already exists for the run, the sweep does nothing
        (filing is idempotent per run). A row whose claim is stale —
        filed once, the row's read-back since revised — is refreshed
        by _file_impression's pending-only update rule, and is
        reported as filed only when the claim did not exist before.

        Manual invocation only: the maintenance script under
        ~/workspace/maintenance/. No schedule, no Review-queue
        trigger. Returns the claim ids filed, so the sweep is
        auditable from its own output. Failures are logged per row,
        never raised — one bad row must not lose the rest."""
        from local_ai.agent_intake.store import AgentStore

        filed: list[str] = []
        try:
            rows = self.meetings.list_active(user_id)
        except Exception:
            logger.exception("affirmation recovery: listing meetings failed")
            return filed
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=AFFIRMATION_RECOVERY_QUIET_DAYS
        )
        for row in rows:
            try:
                arch_id = (row.get("archetype_id") or "").strip().lower()
                keystone_index = int(row.get("keystone_index") or 1)
                # The read-back fields live on the meetings row (the
                # host writes them there during the encounter); the
                # encounter row's copy syncs only at finalize.
                mrow = self.meetings.get(user_id, arch_id, keystone_index) or row
                if not (mrow.get("readback_claim") or "").strip():
                    continue
                if (mrow.get("readback_visitor_response") or "").strip() != "affirmed":
                    continue
                if not self._meeting_quiet_since(user_id, row, cutoff):
                    continue
                script = MT.get_script(arch_id, keystone_index)
                if script is None:
                    logger.warning(
                        "affirmation recovery: no script for %s keystone %s",
                        arch_id, keystone_index,
                    )
                    continue
                agent_id = conversation_id_for(arch_id, keystone_index)
                enc, _ = self._resolve_encounter(user_id, arch_id, keystone_index)
                # The claim id, computed through the same builder
                # _file_impression uses, so the pre-check matches the
                # filing exactly.
                claim = self._build_meeting_impression_claim(
                    user_id, arch_id, keystone_index, script,
                    _run_key_for_encounter(enc, mrow),
                    filed_via="affirmation_recovery",
                )
                if claim is None:
                    continue
                claim_id = claim.id
                store = (
                    self._agent_store_factory(user_id)
                    if self._agent_store_factory is not None
                    else AgentStore(user_id=user_id)
                )
                if any(c.id == claim_id for c in store.get_claims(agent_id)):
                    continue
                self._file_impression(
                    user_id, arch_id, keystone_index, script,
                    filed_via="affirmation_recovery",
                )
                if any(c.id == claim_id for c in store.get_claims(agent_id)):
                    logger.info(
                        "affirmation recovery: filed %s from meeting %s keystone %s",
                        claim_id, arch_id, keystone_index,
                    )
                    filed.append(claim_id)
            except Exception:
                logger.exception(
                    "affirmation recovery: row %s keystone %s failed",
                    row.get("archetype_id"), row.get("keystone_index"),
                )
        return filed

    def recover_incomplete_encounters(
        self, user_id: str, archetype_id: str | None = None,
        keystone_index: int | None = None,
    ) -> list[dict[str, Any]]:
        """Heal encounters left incomplete by a crash (proposal §3.4,
        CR-B1…CR-B6). Scoped to one key when archetype_id is given;
        otherwise every key the user has a meetings row or encounter
        row for. Returns one record per key examined. Failures are
        logged per key, never raised — one bad key must not lose the
        rest, and a recovery that cannot heal fails closed (the
        encounter stays as it is, with the reason recorded).

        Per key, the latest encounter:
        - 'creating' -> resume creation (the recorded opening is
          re-attempted insert-if-absent, then the flip; a missing
          recorded opening or a digest mismatch fails closed).
        - in_progress + fence closed + finalized_at NULL (CR-B5) ->
          complete the finalize from the already-recorded artifacts
          (the reveal, the task Done, the impression): never re-run
          _do_reveal, never re-speak.
        - in_progress + fence open + reveal-keyed messages (CR-B1/B2)
          -> re-run _do_reveal with the wrap line read back from the
          transcript (the ``reveal:{run_id}:0`` message, or "" when
          the close spoke no wrap); the reveal re-attempts
          insert-if-absent and the emit is skipped when the
          impression is already filed.
        - in_progress + fence open + no reveal messages -> an ordinary
          active encounter; nothing to do.
        - complete -> nothing to do."""
        if archetype_id is not None:
            keys = [(archetype_id.strip().lower(), keystone_index or 1)]
        else:
            keys = self.meetings.distinct_meeting_keys(user_id)
        records: list[dict[str, Any]] = []
        for arch_id, key_idx in keys:
            try:
                enc, _mrow = self._resolve_encounter(user_id, arch_id, key_idx)
                if enc is None:
                    records.append({
                        "run_id": None, "archetype_id": arch_id,
                        "keystone_index": key_idx, "action": "no_encounter",
                    })
                    continue
                base = {
                    "run_id": enc["run_id"], "archetype_id": arch_id,
                    "keystone_index": key_idx,
                }
                if enc["status"] == "complete":
                    records.append({**base, "action": "unchanged",
                                    "detail": "already complete"})
                    continue
                if enc["status"] == "creating":
                    script = MT.get_script(arch_id, key_idx)
                    if script is None:
                        records.append({**base, "action": "failed",
                                        "detail": "no script for this meeting"})
                        continue
                    try:
                        self._resume_creating_encounter(user_id, enc, script)
                    except MeetingError as exc:
                        records.append({**base, "action": "failed",
                                        "detail": str(exc)})
                        continue
                    records.append({**base, "action": "creation_resumed"})
                    continue
                # in_progress
                fence = self.conversations.get_fence_state(
                    user_id, enc["conversation_id"]
                )
                if fence == "closed" and not enc.get("finalized_at"):
                    # CR-B5: the fence closed but the finalize never
                    # ran — complete it from the recorded artifacts.
                    # The completion check runs here too (a failure is
                    # recorded, never a block).
                    mrow = self.meetings.get(
                        user_id, enc["archetype_id"], enc["keystone_index"]
                    )
                    verification_status, verification_detail = (
                        self._read_consistency_check(user_id, enc, mrow)
                    )
                    message_count = self.conversations.count_messages(
                        user_id, enc["conversation_id"]
                    )
                    self.meetings.finalize_encounter(
                        user_id, enc["run_id"], message_count=message_count,
                        verification_status=verification_status,
                        verification_detail=verification_detail,
                        verification_checked_at=verification_detail["checked_at"],
                    )
                    records.append({**base, "action": "finalized_cr_b5"})
                    continue
                if fence == "closed":
                    records.append({**base, "action": "unchanged",
                                    "detail": "fence closed, finalized"})
                    continue
                if fence is None:
                    # A missing fence on a meeting conversation is an
                    # integrity error, not a state to heal — the
                    # migration establishes it; the recovery refuses.
                    records.append({**base, "action": "failed",
                                    "detail": "missing fence row"})
                    continue
                reveal = self.conversations.messages_by_key_prefix(
                    user_id, enc["conversation_id"], f"reveal:{enc['run_id']}:"
                )
                if not reveal:
                    records.append({**base, "action": "unchanged",
                                    "detail": "active, no interrupted close"})
                    continue
                wrap = next(
                    (
                        m["body"]
                        for m in reveal
                        if m.get("message_key") == f"reveal:{enc['run_id']}:0"
                    ),
                    "",
                )
                script = MT.get_script(arch_id, key_idx)
                if script is None:
                    records.append({**base, "action": "failed",
                                    "detail": "no script for this meeting"})
                    continue
                self._do_reveal(
                    user_id, arch_id, key_idx, script,
                    wrap_line=wrap, silent_close=False,
                )
                records.append({**base, "action": "reveal_replayed"})
            except Exception as exc:
                logger.exception(
                    "encounter recovery: %s keystone %s failed",
                    arch_id, key_idx,
                )
                records.append({
                    "run_id": None, "archetype_id": arch_id,
                    "keystone_index": key_idx, "action": "failed",
                    "detail": str(exc),
                })
        return records

    def _meeting_quiet_since(self, user_id: str, row: dict[str, Any],
                             cutoff: datetime) -> bool:
        """True when the meeting's conversation has no message newer
        than `cutoff` — or no messages at all. A message whose
        timestamp cannot be parsed fails closed: not quiet. The
        conversation id comes from the row (an encounter row carries
        its own); the legacy shared id is only the fallback."""
        agent_id = (row.get("conversation_id") or "") or conversation_id_for(
            (row.get("archetype_id") or "").strip().lower(),
            int(row.get("keystone_index") or 1),
        )
        try:
            history = self.conversations.history(user_id, agent_id, limit=1)
        except Exception:
            logger.exception("affirmation recovery: history read failed")
            return False
        if not history:
            return True
        created = (history[0].get("created_at") or "").strip()
        try:
            last = datetime.fromisoformat(created)
        except Exception:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return last <= cutoff

    def pause(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        arch_id = (archetype_id or "").strip().lower()
        enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
        # Paused is a meetings-row mirror state, not an encounter
        # lifecycle state: the encounter stays in_progress, and the
        # next turn flips the mirror back to active.
        if (
            enc is not None
            and enc["status"] == "in_progress"
            and (mrow or {}).get("status") == "active"
        ):
            self.meetings.update(user_id, arch_id, keystone_index, status="paused")
        return self.state(user_id, arch_id, keystone_index)

    def complete(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        """Complete the meeting at the visitor's word.

        Until now a meeting could only reach its close through the
        encounter runtime's own verdict — a visitor who said "we're
        done here" and was answered "Done" could still find the meeting
        sitting active, with no way to complete it and therefore no way
        to meet again (restart refuses anything not complete). This is
        the visitor's own close action: it funnels through the same
        completion chokepoint as the runtime's close (_do_reveal), so
        the character's authored closing words are spoken, the keystone
        task marks Done, the completed-meeting event emits, and any
        read-back impression files — exactly as a runtime close would.

        Deliberately NOT gated on recognition: a meeting that never
        produced an impression (a poking-around visitor, a short
        exchange) still ends cleanly, filing nothing — _file_impression
        is a no-op without a read-back. Completing an already-complete
        meeting returns its state unchanged (the reveal is never
        spoken twice). Nothing here trains — same invariant as the
        rest of the engine.

        Pending-impression rule (Fellowship shared foundation,
        2026-10-28 — this REPLACES the audit's deliver-or-discard
        alternative): a held (pending) impression is DISCARDED
        explicitly on this voluntary end, with an auditable reason
        logged and recorded on the meeting's state — never spoken,
        never filed, never an accepted claim. If nothing is pending,
        behavior is unchanged.

        Restart-claims rule (Fellowship supersede decision,
        2026-10-28 — this REPLACES the shared foundation's open
        "restart-claims handling is UNCHANGED" note): when a new run
        completes and files its impression, the filing SUPERSEDES
        every prior meeting_impression claim for the seat — old rows
        stay in history with their prior verdicts recorded, only the
        new claim stands. Restart alone supersedes nothing, and a
        discarded pending impression is never filed and never
        supersedes anything: discard and supersede are distinct rules
        for distinct states (never-delivered vs previously filed).
        """
        arch_id = (archetype_id or "").strip().lower()
        if arch_id not in stock_archetype_ids():
            raise ValueError(f"Unknown seat: {archetype_id!r}")
        script = MT.get_script(arch_id, keystone_index)
        if script is None:
            raise MeetingError(
                "That meeting isn't written yet. It will get its own "
                "conversation when its turn comes — nothing improvised."
            )
        enc, mrow = self._resolve_encounter(user_id, arch_id, keystone_index)
        if enc is None:
            if self._keystone_done(user_id, arch_id, keystone_index):
                return self.state(user_id, arch_id, keystone_index)
            raise MeetingError(
                "There's no meeting in progress to complete — this seat "
                "hasn't been met yet."
            )
        if enc["status"] == "complete":
            return self.state(user_id, arch_id, keystone_index)
        if enc["status"] == "creating":
            return self._resume_creating_encounter(user_id, enc, script)
        # Explicit discard (see docstring): the held read must not
        # strand in the completed row's state_json as an orphan, and
        # must not be spoken or filed on the way out. The discard
        # reason is persisted on the state, so it stays inspectable
        # after the meeting completes. Written to the encounter row
        # (and the meetings-row mirror).
        enc_state = self._hydrate_state(enc, mrow)
        if enc_state.impression_pending_text:
            logger.info(
                "meeting: discarding pending impression on voluntary "
                "manual complete (POST /meeting/complete); held text "
                "length=%d, never spoken, never filed",
                len(enc_state.impression_pending_text),
            )
            enc_state.impression_pending_text = ""
            enc_state.impression_pending_strands = []
            enc_state.impression_held_at_pursuit = 0
            enc_state.pending_impression_discarded = (
                "visitor completed the meeting manually "
                "(POST /meeting/complete)"
            )
            self.meetings.update_encounter(
                user_id, enc["run_id"], state_json=enc_state.to_json()
            )
            self.meetings.update(
                user_id, arch_id, keystone_index,
                state_json=enc_state.to_json(),
            )
        # Manual Complete funnels through the same chokepoint, with
        # the same silence for decoupled definitions (no scripted
        # reveal on a visitor-initiated close either).
        definition = ENC.get_definition(script)
        self._do_reveal(user_id, arch_id, keystone_index, script,
                        silent_close=definition.decoupled_recognition)
        return self.state(user_id, arch_id, keystone_index)
