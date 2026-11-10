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
import json
import logging
import re
import sqlite3
import threading
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
from .store import ConversationStore

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
"""

#: The deterministic heuristics that guard the state-critical
#: transitions (read-back reply classification, acknowledgment and
#: pass detection, the strands-trailer split, excerpts) live in
#: encounter.py with the runtime that uses them; the private names
#: are re-exported above for the callers that grew up importing
#: them from here.

#: The status seeded keystone tasks start with: keystone_seeding creates
#: them through TaskCreate without a status, so the model's default is the
#: seed state. Restart returns a completed meeting's task to exactly this.
_SEEDED_TASK_STATUS = "Todo"



def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def conversation_id_for(archetype_id: str, keystone_index: int) -> str:
    return f"meeting-{archetype_id}-{keystone_index}"


class MeetingError(ValueError):
    """A meeting rule refusal (maps to 409 in the route layer)."""


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
        not one row at a time."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM meetings WHERE user_id = ? AND "
                "status = 'active' ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

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
        allowed = {"stage", "status", "question_idx", "readback_claim", "readback_response", "readback_strands", "readback_original_claim", "readback_seat_outcome", "readback_visitor_response", "state_json"}
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

    def delete(self, user_id: str, archetype_id: str, keystone_index: int) -> None:
        """Remove the live meeting row. Only ever called by restart, AFTER
        the run has been archived and verified complete — the record
        survives in the archive."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM meetings WHERE user_id = ? AND archetype_id = ? "
                "AND keystone_index = ?",
                (user_id, archetype_id, keystone_index),
            )
            self._conn.commit()

    def met_seats(self, user_id: str) -> list[str]:
        """Archetype ids whose FIRST meeting (keystone 1) is complete
        for this user — the naming rule's met set (amendment E):
        character names may be used for these seats, roles for all
        others. A begun-but-incomplete meeting does not count: the
        name unlocks at completion, when the card says so."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT archetype_id FROM meetings WHERE user_id = ? "
                "AND keystone_index = 1 AND status = 'complete'",
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
                 decoupled_recognition: bool = False) -> None:
        self._svc = service
        self._user_id = user_id
        self._arch_id = arch_id
        self._keystone_index = keystone_index
        self._script = script
        self._fellowship_reference = fellowship_reference
        self._decoupled_recognition = decoupled_recognition
        self._cid = conversation_id_for(arch_id, keystone_index)

    def say(self, body: str) -> None:
        self._svc._say(self._user_id, self._cid, self._arch_id, body)

    def generate(self, frame: str) -> str:
        try:
            return self._svc._generate_framed(
                self._user_id, self._arch_id, self._keystone_index, frame,
                fellowship_reference=self._fellowship_reference,
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

    def state(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        """Where this meeting stands, for the frontend. Never raises on
        unseeded/unwritten — it reports, the begin action refuses."""
        arch_id = (archetype_id or "").strip().lower()
        cid = conversation_id_for(arch_id, keystone_index)
        row = self.meetings.get(user_id, arch_id, keystone_index)
        done = False
        try:
            done = self._keystone_done(user_id, arch_id, keystone_index)
        except Exception:
            done = False
        if row is None:
            status = "complete" if done else "not_started"
            stage = "complete" if done else None
        else:
            status = row["status"]
            stage = row["stage"]
        script = MT.get_script(arch_id, keystone_index)
        # Controller-visible completion signal (Fellowship shared
        # foundation, 2026-10-28): True while the character has
        # named the Complete action and the record is still active
        # — the frontend renders its hint + primary Complete action
        # from this. `pending_impression_discarded` carries the
        # auditable discard reason after a voluntary end ("" =
        # nothing discarded). Neither is meaningful once complete
        # except the discard record, which stays inspectable.
        completion_offered = False
        pending_discarded = ""
        if row is not None:
            try:
                enc = self._hydrate_state(row)
                completion_offered = bool(
                    enc.completion_offered and status in ("active", "paused"))
                pending_discarded = enc.pending_impression_discarded or ""
            except Exception:
                pass
        return {
            "archetype_id": arch_id,
            "keystone_index": keystone_index,
            "conversation_id": cid,
            "status": status,
            "stage": stage,
            "completion_offered": completion_offered,
            "pending_impression_discarded": pending_discarded,
            "has_script": script is not None,
            # The reveal payload: who was met, and the demeanor the first
            # meeting unlocks. Only meaningful once complete — before that
            # the frontend shows neither (earned, not announced).
            "character": script.character if script else None,
            "demeanor": script.demeanor if (script and status == "complete") else None,
            "messages": self.conversations.history(user_id, cid, limit=100),
        }

    # -- speech ------------------------------------------------------------------

    def _say(self, user_id: str, cid: str, archetype_id: str, body: str) -> dict[str, Any]:
        return self.conversations.append_message(
            user_id, cid, archetype_id, "voice", body, mode="base", context={"meeting": True},
            via_meeting=True,
        )

    def start(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        """Begin (or resume) a meeting. A fresh start delivers the
        encounter's opening — the script's authored introduction
        (the Weaver's is four bubbles, delivered verbatim) — and
        the encounter begins. A resume
        returns current state: the transcript carries what was already
        said, nothing repeats."""
        arch_id = (archetype_id or "").strip().lower()
        script = self._check_beginnable(user_id, arch_id, keystone_index)
        cid = conversation_id_for(arch_id, keystone_index)

        if self._keystone_done(user_id, arch_id, keystone_index):
            row = self.meetings.get(user_id, arch_id, keystone_index)
            if row is None:
                row = self.meetings.create(user_id, arch_id, keystone_index)
            self.meetings.update(user_id, arch_id, keystone_index, stage="complete", status="complete")
            # A meeting completed before impressions were filed (or one
            # whose filing was missed) backfills here — the filing is
            # idempotent per run, so this is a no-op once filed.
            self._file_impression(user_id, arch_id, keystone_index, script)
            return self.state(user_id, arch_id, keystone_index)

        row = self.meetings.get(user_id, arch_id, keystone_index)
        if row is not None:
            if row["status"] != "active":
                self.meetings.update(user_id, arch_id, keystone_index, status="active")
            return self.state(user_id, arch_id, keystone_index)

        self.meetings.create(user_id, arch_id, keystone_index)
        self.conversations.ensure_conversation(user_id, cid, kind="meeting")
        definition = ENC.get_definition(script)
        self.meetings.update(
            user_id, arch_id, keystone_index,
            state_json=EncounterState().to_json(),
        )
        for paragraph in definition.opening:
            self._say(user_id, cid, arch_id, paragraph)
        return self.state(user_id, arch_id, keystone_index)

    def turn(self, user_id: str, archetype_id: str, message: str, keystone_index: int = 1) -> dict[str, Any]:
        """One user turn inside an active meeting. The encounter
        runtime runs the turn — the user's move first, the character's
        objectives behind it — and this service persists the outcome.
        Raises MeetingError when no meeting is in progress, ValueError
        on bad input."""
        arch_id = (archetype_id or "").strip().lower()
        if arch_id not in stock_archetype_ids():
            raise ValueError(f"Unknown seat: {archetype_id!r}")
        if not (message or "").strip():
            raise ValueError("Message is empty.")
        row = self.meetings.get(user_id, arch_id, keystone_index)
        if row is None or row["status"] == "complete":
            raise MeetingError("No meeting is in progress with this seat — begin one first.")
        script = MT.get_script(arch_id, keystone_index)
        if script is None:  # state without a script shouldn't exist; be honest
            raise MeetingError("That meeting isn't written yet.")
        if row["status"] != "active":
            self.meetings.update(user_id, arch_id, keystone_index, status="active")
            row = self.meetings.get(user_id, arch_id, keystone_index)  # type: ignore[assignment]

        cid = conversation_id_for(arch_id, keystone_index)
        self.conversations.append_message(
            user_id, cid, arch_id, "user", message, mode="base", context={"meeting": True},
            via_meeting=True,
        )

        enc_state = self._hydrate_state(row)
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
        )
        new_q_idx = EncounterRuntime(definition).handle_turn(
            host, enc_state, message, int(row["question_idx"])
        )
        self.meetings.update(
            user_id, arch_id, keystone_index,
            question_idx=new_q_idx,
            state_json=enc_state.to_json(),
            stage=ENC.derived_stage(enc_state),
        )
        return self.state(user_id, arch_id, keystone_index)

    @staticmethod
    def _hydrate_state(row: dict[str, Any]) -> EncounterState:
        """The encounter state for a meeting row. Rows begun before
        the encounter runtime carry no state_json; their position is
        reconstructed from the columns the old engine already kept —
        the read-back claim/response and the stage label — so an
        in-progress meeting survives the engine change honestly."""
        state = EncounterState.from_json(row.get("state_json"))
        if row.get("state_json"):
            return state
        if (row.get("readback_claim") or "").strip():
            state.impression_offered = True
            state.impression_text = row["readback_claim"]
            # The recognition floor (the Weaver pattern) did not
            # exist when this meeting's impression was offered: the
            # recognition completes under the contract the meeting
            # began with, so the floor is waived for this row —
            # never for one the runtime itself has run.
            state.floor_waived = True
            try:
                state.impression_strands = json.loads(row.get("readback_strands") or "[]")
            except Exception:
                state.impression_strands = []
        if (row.get("readback_response") or "").strip():
            state.impression_answered = True
            state.response_recorded = True
        if row.get("stage") == "orientation":
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
                         frame: str, fellowship_reference: str = "") -> str:
        """Run one live beat against the transcript: the last user message
        is lifted out as the reply builder's input, everything else stays
        as context, in order. Returns the raw reply text.
        `fellowship_reference` is the seat's slice of the shared
        Fellowship knowledge, carried as an uncapped meeting-scoped
        prompt section (see reply.build_voice_prompt) — "" means no
        reference has been written for this seat yet, and the prompt
        is byte-identical to before (mechanism only, no content)."""
        cid = conversation_id_for(arch_id, keystone_index)
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
        below still run exactly as before."""
        cid = conversation_id_for(arch_id, keystone_index)
        if not silent_close:
            if wrap_line:
                self._say(user_id, cid, arch_id, wrap_line)
            for paragraph in script.reveal:
                self._say(user_id, cid, arch_id, paragraph)

        tasks = _seat_keystone_tasks(user_id, arch_id)
        if len(tasks) >= keystone_index:
            task = tasks[keystone_index - 1]
            if task.get("status") != "Done":
                ve.update_task(task["id"], ve_models.TaskUpdate(status="Done"), user_id)
        self.meetings.update(user_id, arch_id, keystone_index, stage="complete", status="complete")
        # Fellowship Runtime P1: the completed meeting is a
        # shared-reality event, emitted at this same single chokepoint
        # (guarded inside _emit_meeting_completed — it can never break
        # the close, and its derivation only produces observations).
        self._emit_meeting_completed(user_id, arch_id, keystone_index)
        self._file_impression(user_id, arch_id, keystone_index, script)

    def _emit_meeting_completed(self, user_id: str, arch_id: str, keystone_index: int) -> None:
        """Record the completed meeting as a fellowship event.

        Evidence is the user's verbatim read-back answer (their words
        about the impression) when the run stored one; otherwise the
        observation will cite the meeting itself by reference. Guarded
        like _file_impression: failures are logged, never raised.
        """
        try:
            from local_ai.fellowship.events import emit_event

            row = self.meetings.get(user_id, arch_id, keystone_index) or {}
            emit_event(
                kind="meeting_completed",
                user_id=user_id,
                entity_type="meeting",
                entity_id=conversation_id_for(arch_id, keystone_index),
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

        Idempotent per run: the claim id carries the run's creation
        time, and an existing claim is never re-saved (save_claims is
        INSERT OR REPLACE — re-saving would reset its verdict). A
        replay is a new run with a new claim, and filing that new claim
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
            row = self.meetings.get(user_id, arch_id, keystone_index)
            if not row or not (row.get("readback_claim") or "").strip():
                return
            from local_ai.agent_intake import review_claims
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
            run_key = re.sub(r"[^0-9A-Za-z]", "", row.get("created_at") or "") or "run"
            claim = review_claims.build_meeting_impression_claim(
                agent_id=agent_id,
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
            existing = store.get_claims(agent_id)
            is_new = claim.id not in {c.id for c in existing}

            # The meeting as a reviewable source: its transcript is the
            # agent's material; the read-back's own strand attribution
            # is its sort (which is also what places it under the seat's
            # review group). Refreshed per run — the claim ids keep each
            # run's filing distinct.
            history = self.conversations.history(user_id, agent_id, limit=200)
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
        from local_ai.agent_intake import review_claims
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
                if not (row.get("readback_claim") or "").strip():
                    continue
                if (row.get("readback_visitor_response") or "").strip() != "affirmed":
                    continue
                if not self._meeting_quiet_since(user_id, row, cutoff):
                    continue
                arch_id = (row.get("archetype_id") or "").strip().lower()
                keystone_index = int(row.get("keystone_index") or 1)
                script = MT.get_script(arch_id, keystone_index)
                if script is None:
                    logger.warning(
                        "affirmation recovery: no script for %s keystone %s",
                        arch_id, keystone_index,
                    )
                    continue
                agent_id = conversation_id_for(arch_id, keystone_index)
                try:
                    strand_names = json.loads(row.get("readback_strands") or "[]")
                except Exception:
                    strand_names = []
                strand_keys = [
                    PLAIN_TO_KEY[n] for n in strand_names if n in PLAIN_TO_KEY
                ]
                run_key = (
                    re.sub(r"[^0-9A-Za-z]", "", row.get("created_at") or "") or "run"
                )
                # The claim id, computed through the same builder
                # _file_impression uses, so the pre-check matches the
                # filing exactly.
                claim_id = review_claims.build_meeting_impression_claim(
                    agent_id=agent_id,
                    seat_name=script.character,
                    readback_claim=row.get("readback_claim") or "",
                    readback_response=row.get("readback_response") or "",
                    strand_keys=strand_keys,
                    run_key=run_key,
                    readback_original_claim=row.get("readback_original_claim") or "",
                    readback_seat_outcome=row.get("readback_seat_outcome") or "",
                    readback_visitor_response=row.get("readback_visitor_response") or "",
                    ceiling_filed=_is_ceiling_filed(row),
                    filed_via="affirmation_recovery",
                ).id
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

    def _meeting_quiet_since(self, user_id: str, row: dict[str, Any],
                             cutoff: datetime) -> bool:
        """True when the meeting's conversation has no message newer
        than `cutoff` — or no messages at all. A message whose
        timestamp cannot be parsed fails closed: not quiet."""
        agent_id = conversation_id_for(
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

    def restart(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        """Meet again: reset a COMPLETED meeting so it can be run fresh.

        The prior run's FULL transcript (every message row,
        in original order, verified complete against the live rows)
        plus the read-back impression is archived in the meeting store
        before anything is reset — archived and verified, never deleted
        unverified. The seat's keystone task returns
        to the status it was seeded with, which also re-locks the face
        the first meeting revealed (PR #186's face_revealed reads the
        same task store) until the new run completes.

        Refusals are honest: no meeting on record, a meeting still in
        progress (pause/resume serves that), or a seat whose meeting
        isn't written yet. Restart alone does NOT supersede the prior
        run's filed claim: it stays standing until a new run completes
        and files its own impression. Nothing here trains — same
        invariant as the rest of the engine."""
        arch_id = (archetype_id or "").strip().lower()
        if arch_id not in stock_archetype_ids():
            raise ValueError(f"Unknown seat: {archetype_id!r}")
        script = MT.get_script(arch_id, keystone_index)
        if script is None:
            raise MeetingError(
                "That meeting isn't written yet. It will get its own "
                "conversation when its turn comes — nothing improvised."
            )
        row = self.meetings.get(user_id, arch_id, keystone_index)
        if row is None:
            raise MeetingError(
                "There's no finished meeting to meet again — this seat "
                "hasn't been met yet."
            )
        if row["status"] != "complete":
            raise MeetingError(
                "This meeting is still in progress — it waits where you "
                "left it and can be resumed. Meeting again is for a "
                "meeting that has reached its close."
            )

        cid = conversation_id_for(arch_id, keystone_index)
        # Archive the FULL transcript in bounded 200-row pages, then
        # verify it against the live rows before anything is deleted.
        # Any failure aborts the restart with every live row and the
        # live meeting row intact, so the meeting stays restartable.
        pages: list[list[dict[str, Any]]] = []
        offset = 0
        while True:
            page = self.conversations.history(user_id, cid, limit=200, offset=offset)
            pages.append(page)
            if len(page) < 200:
                break
            offset += 200
        transcript: list[dict[str, Any]] = []
        for page in reversed(pages):
            transcript.extend(page)
        count = self.conversations.count_messages(user_id, cid)
        ids = self.conversations.message_ids(user_id, cid)
        if len(transcript) != count or [m["id"] for m in transcript] != ids:
            raise MeetingError(
                "The prior run could not be archived completely — its live "
                "transcript was left untouched. Meet again to retry."
            )
        self.meetings.archive_run(user_id, arch_id, keystone_index, row, transcript)
        self.conversations.clear_conversation(user_id, cid)
        self.meetings.delete(user_id, arch_id, keystone_index)

        # Revert the keystone task through the same VE service layer the
        # completion path writes through (_do_reveal), back to the exact
        # status seeded keystone tasks start with.
        tasks = _seat_keystone_tasks(user_id, arch_id)
        if len(tasks) >= keystone_index:
            task = tasks[keystone_index - 1]
            if task.get("status") != _SEEDED_TASK_STATUS:
                ve.update_task(
                    task["id"],
                    ve_models.TaskUpdate(status=_SEEDED_TASK_STATUS),
                    user_id,
                )
        return self.state(user_id, arch_id, keystone_index)

    def pause(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        arch_id = (archetype_id or "").strip().lower()
        row = self.meetings.get(user_id, arch_id, keystone_index)
        if row is not None and row["status"] == "active":
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
        row = self.meetings.get(user_id, arch_id, keystone_index)
        if row is None:
            if self._keystone_done(user_id, arch_id, keystone_index):
                return self.state(user_id, arch_id, keystone_index)
            raise MeetingError(
                "There's no meeting in progress to complete — this seat "
                "hasn't been met yet."
            )
        if row["status"] == "complete":
            return self.state(user_id, arch_id, keystone_index)
        if row["status"] not in ("active", "paused"):
            raise MeetingError(
                "This meeting can't be completed from where it stands."
            )
        # Explicit discard (see docstring): the held read must not
        # strand in the completed row's state_json as an orphan, and
        # must not be spoken or filed on the way out. The discard
        # reason is persisted on the state, so it stays inspectable
        # after the meeting completes.
        enc_state = self._hydrate_state(row)
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
