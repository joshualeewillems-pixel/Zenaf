"""Keystone meeting engine — the first-meeting conversation, as a stage machine.

A meeting is a guided conversation between the user and ONE council seat,
run against the script in local_ai/council/meetings.py. Beats:

  opening   (scripted) → encounter (one question, live reply)
            → readback  (one tentative impression, live)
            → orientation (ONLY where the script carries one — the
              Conductor's, today: what was pulled from the conversation,
              where it shows up, how the system works. The tutorials are
              distributed per seat; see meetings.SEAT_FEATURE_FOCUS)
            → reveal    (scripted) → keystone task marked Done

State lives in its own small store (stage, question pointer, the read-back
claim and the user's response to it). The transcript lives in the shared
ConversationStore under conversation_id "meeting-{seat}-{keystone}", so
hydration and rendering reuse the skeleton's machinery — a meeting is a
conversation, not a new kind of object.

Rules the engine enforces (Joshua's design, not preferences):
  - The Conductor is met first. Until its keystone 1 completes, no other
    seat's first meeting can begin (the attention markers encode the same
    order on the tree).
  - A seat with no written script has no meeting yet — the engine refuses
    honestly instead of improvising one.
  - Keystones run in chain order: keystone N's meeting requires N-1 Done.
    (Only keystone 1 is written in this build.)
  - The read-back is stored on the meeting record as an UNFILED first
    impression, verbatim, with the user's response verbatim. Nothing here
    writes a training signal; filing it belongs to the review flow.
  - Meetings are resumable: state is server-side, so leaving mid-meeting
    loses nothing, and beginning again picks up at the current beat.

The character's live beats go through the shared voice-reply builder with
the script's frame as extra instructions — the meeting never forks the
voice. Scripted beats are appended verbatim in the base voice (this is the
canonical character; the user's echo is a different side of the switch).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from local_ai.council import meetings as MT
from local_ai.council.archetypes import stock_archetype_ids
from local_ai.vision_execution import keystone_seeding
from local_ai.vision_execution import models as ve_models
from local_ai.vision_execution import service as ve

from .reply import generate_voice_reply
from .store import ConversationStore

GenerateFn = Callable[..., str]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data" / "conversations"
DEFAULT_DB_PATH = DATA_DIR / "meetings.db"

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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, archetype_id, keystone_index)
);
"""

#: Plain strand names the read-back's bookkeeping line may cite.
_STRAND_NAMES = ("Voice", "Logic", "Eye", "Ear", "Hands", "Heart", "Compass")

#: Orientation acknowledgments — the user signaling "understood, go on"
#: rather than asking something. Anything else in the orientation beat is
#: treated as a question and answered from the script's facts block.
_ACK_TOKENS = {
    "ok", "okay", "got it", "thanks", "thank you", "yes", "yeah", "yep",
    "makes sense", "understood", "cool", "great", "sure", "fine",
    "alright", "all right", "go on", "continue", "ready",
}

#: Acknowledgment phrases for _is_acknowledgment's containment check.
_ACK_PHRASES = (
    "sounds good", "sounds great", "looks good", "all good", "makes sense",
    "got it", "thank you", "thanks", "understood", "go on", "okay", "ok",
    "yes", "yeah", "yep", "sure", "cool", "great", "fine", "alright",
    "all right", "continue", "ready", "perfect", "nice",
)

#: Words that turn a short reply into something other than an ack.
_ACK_CONTRASTS = ("but", "except", "however", "actually", "though")


def _is_acknowledgment(message: str) -> bool:
    """Human-shaped ack detection (the first live run's lesson: exact
    token matching sent "Ok sounds good" down the question path, where
    the framed answer improvised a second introduction). A short,
    question-free reply containing an ack phrase — and no contrast
    word — is an acknowledgment; anything else is treated as a
    question and answered from the script's facts."""
    norm = " ".join((message or "").strip().lower().strip(".! ").split())
    if not norm or "?" in norm:
        return False
    if norm in _ACK_TOKENS:
        return True
    words = norm.split()
    if len(words) > 6:
        return False
    if any(c in words for c in _ACK_CONTRASTS):
        return False
    return any(phrase in norm for phrase in _ACK_PHRASES)


def _excerpt(text: str, limit: int) -> str:
    """A word-boundary excerpt for inline display; the full text stays
    on the meeting record and in review."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut < limit // 2:
        cut = limit
    return text[:cut].rstrip(" ,;:") + "…"

#: Short answers that mean "ask me a different one" rather than an answer.
#: Exact-match after normalization — a substantive "no, because…" is an
#: answer, not a pass.
_PASS_TOKENS = {
    "pass", "skip", "next", "next question", "another question",
    "different question", "idk", "i don't know", "not sure", "nope",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def conversation_id_for(archetype_id: str, keystone_index: int) -> str:
    return f"meeting-{archetype_id}-{keystone_index}"


class MeetingError(ValueError):
    """A meeting rule refusal (maps to 409 in the route layer)."""


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
            # Additive migration for stores created before the read-back
            # carried strand attribution.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(meetings)")}
            if "readback_strands" not in cols:
                self._conn.execute(
                    "ALTER TABLE meetings ADD COLUMN readback_strands "
                    "TEXT NOT NULL DEFAULT '[]'"
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
        allowed = {"stage", "status", "question_idx", "readback_claim", "readback_response", "readback_strands"}
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


def _is_pass(message: str) -> bool:
    norm = " ".join((message or "").strip().lower().strip(".! ").split())
    return norm in _PASS_TOKENS


class MeetingService:
    def __init__(
        self,
        conversation_store: ConversationStore,
        meeting_store: MeetingStore,
        generate_fn: GenerateFn | None = None,
    ) -> None:
        self.conversations = conversation_store
        self.meetings = meeting_store
        self._generate_fn = generate_fn

    # -- guards ---------------------------------------------------------------

    def _check_beginnable(self, user_id: str, archetype_id: str, keystone_index: int) -> MT.MeetingScript:
        arch_id = (archetype_id or "").strip().lower()
        if arch_id not in stock_archetype_ids():
            raise ValueError(f"Unknown seat: {archetype_id!r}")
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
        entry = keystone_seeding.ENTRY_SEAT_REF
        if keystone_index == 1 and arch_id != entry:
            entry_tasks = _seat_keystone_tasks(user_id, entry)
            if not entry_tasks or entry_tasks[0].get("status") != "Done":
                raise MeetingError(
                    "The Weaver opens the council — meet them first. The "
                    "others will introduce themselves in their own time."
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
        return {
            "archetype_id": arch_id,
            "keystone_index": keystone_index,
            "conversation_id": cid,
            "status": status,
            "stage": stage,
            "has_script": script is not None,
            # The reveal payload: who was met, and the demeanor the first
            # meeting unlocks. Only meaningful once complete — before that
            # the frontend shows neither (earned, not announced).
            "character": script.character if script else None,
            "demeanor": script.demeanor if (script and status == "complete") else None,
            "messages": self.conversations.history(user_id, cid, limit=100),
        }

    # -- the beats ---------------------------------------------------------------

    def _say(self, user_id: str, cid: str, archetype_id: str, body: str) -> dict[str, Any]:
        return self.conversations.append_message(
            user_id, cid, archetype_id, "voice", body, mode="base", context={"meeting": True}
        )

    def start(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        """Begin (or resume) a meeting. A fresh start delivers the scripted
        opening and the first question. A resume returns current state —
        the transcript carries what was already said, nothing repeats."""
        arch_id = (archetype_id or "").strip().lower()
        script = self._check_beginnable(user_id, arch_id, keystone_index)
        cid = conversation_id_for(arch_id, keystone_index)

        if self._keystone_done(user_id, arch_id, keystone_index):
            row = self.meetings.get(user_id, arch_id, keystone_index)
            if row is None:
                row = self.meetings.create(user_id, arch_id, keystone_index)
            self.meetings.update(user_id, arch_id, keystone_index, stage="complete", status="complete")
            return self.state(user_id, arch_id, keystone_index)

        row = self.meetings.get(user_id, arch_id, keystone_index)
        if row is not None:
            if row["status"] != "active":
                self.meetings.update(user_id, arch_id, keystone_index, status="active")
            return self.state(user_id, arch_id, keystone_index)

        self.meetings.create(user_id, arch_id, keystone_index)
        self.conversations.ensure_conversation(user_id, cid, kind="meeting")
        for paragraph in script.opening:
            self._say(user_id, cid, arch_id, paragraph)
        self._say(user_id, cid, arch_id, script.questions[0])
        return self.state(user_id, arch_id, keystone_index)

    def turn(self, user_id: str, archetype_id: str, message: str, keystone_index: int = 1) -> dict[str, Any]:
        """One user turn inside an active meeting. Raises MeetingError when
        no meeting is in progress, ValueError on bad input."""
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
            user_id, cid, arch_id, "user", message, mode="base", context={"meeting": True}
        )

        if row["stage"] == "encounter":
            self._encounter_beat(user_id, arch_id, keystone_index, script, row, message)
        elif row["stage"] == "readback":
            self._readback_response_beat(user_id, arch_id, keystone_index, script, row, message)
        elif row["stage"] == "orientation":
            self._orientation_beat(user_id, arch_id, keystone_index, script, message)
        else:  # a completed-stage row that isn't status=complete: treat as done
            raise MeetingError("This meeting has already reached its close.")
        return self.state(user_id, arch_id, keystone_index)

    def _history_for_reply(self, user_id: str, cid: str) -> list[dict[str, str]]:
        rows = self.conversations.history(user_id, cid, limit=30)
        return [{"role": m["role"], "content": m["body"]} for m in rows]

    def _encounter_beat(self, user_id: str, arch_id: str, keystone_index: int,
                        script: MT.MeetingScript, row: dict[str, Any], message: str) -> None:
        cid = conversation_id_for(arch_id, keystone_index)
        q_idx = int(row["question_idx"])

        if _is_pass(message):
            if q_idx + 1 < len(script.questions):
                self.meetings.update(user_id, arch_id, keystone_index, question_idx=q_idx + 1)
                self._say(user_id, cid, arch_id, script.questions[q_idx + 1])
                return
            # Bank exhausted with nothing answered: the read-back reflects
            # the choosing-not-to-answer itself. Fall through to read-back
            # with the pass as the latest user turn.
            claim, strands = self._readback(user_id, arch_id, script)
            self.meetings.update(
                user_id, arch_id, keystone_index, stage="readback",
                readback_claim=claim, readback_strands=json.dumps(strands),
            )
            self._say(user_id, cid, arch_id, claim)
            return

        # Substantive answer: live engagement, then the read-back.
        history = self._history_for_reply(user_id, cid)
        reply = generate_voice_reply(
            user_id, arch_id, message, history[:-1],
            mode="base", generate_fn=self._generate_fn,
            extra_instructions=script.encounter_frame,
        )
        self._say(user_id, cid, arch_id, reply.reply)

        claim, strands = self._readback(user_id, arch_id, script)
        self.meetings.update(
            user_id, arch_id, keystone_index, stage="readback",
            readback_claim=claim, readback_strands=json.dumps(strands),
        )
        self._say(user_id, cid, arch_id, claim)

    def _readback(self, user_id: str, arch_id: str, script: MT.MeetingScript) -> tuple[str, list[str]]:
        """Generate the read-back; split off its 'Strands:' bookkeeping
        line. Returns (display claim, strand names). A missing or garbled
        trailer degrades to no strands — the meeting never breaks on it."""
        cid = conversation_id_for(arch_id, script.keystone_index)
        history = self._history_for_reply(user_id, cid)
        # The builder appends the current user turn itself, so hand it the
        # transcript with the last user message lifted out as the input —
        # everything else (including the encounter reply just given) stays
        # as context, in order.
        last_user_idx = max(
            (i for i, m in enumerate(history) if m["role"] == "user"), default=None
        )
        if last_user_idx is None:
            return "", []
        last_user = history[last_user_idx]
        prior = history[:last_user_idx] + history[last_user_idx + 1:]
        reply = generate_voice_reply(
            user_id, arch_id, last_user.get("content", ""), prior,
            mode="base", generate_fn=self._generate_fn,
            extra_instructions=script.readback_frame,
        )
        text = reply.reply.strip()
        strands: list[str] = []
        lines = text.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if not stripped:
                continue
            if stripped.lower().startswith("strands:"):
                cited = [s.strip() for s in stripped.split(":", 1)[1].split(",")]
                strands = [s for s in cited if s in _STRAND_NAMES][:2]
                text = "\n".join(lines[:i]).strip()
            break
        return text, strands

    # -- orientation (only scripts that carry one — today, the Conductor) ------

    def _has_orientation(self, script: MT.MeetingScript) -> bool:
        return bool(script.orientation_intro or script.pulled_item_template)

    def _readback_response_beat(self, user_id: str, arch_id: str, keystone_index: int,
                                script: MT.MeetingScript, row: dict[str, Any], message: str) -> None:
        # The user's response to the impression is part of the record —
        # verbatim, uninterpreted. Filing it is the review flow's job.
        self.meetings.update(user_id, arch_id, keystone_index, readback_response=message)
        if self._has_orientation(script):
            self._deliver_orientation(user_id, arch_id, keystone_index, script)
            self.meetings.update(user_id, arch_id, keystone_index, stage="orientation")
        else:
            self._do_reveal(user_id, arch_id, keystone_index, script)

    def _deliver_orientation(self, user_id: str, arch_id: str, keystone_index: int,
                             script: MT.MeetingScript) -> None:
        cid = conversation_id_for(arch_id, keystone_index)
        row = self.meetings.get(user_id, arch_id, keystone_index) or {}
        for paragraph in script.orientation_intro:
            self._say(user_id, cid, arch_id, paragraph)
        if script.pulled_item_template:
            self._say(
                user_id, cid, arch_id,
                script.pulled_item_template.format(
                    claim=_excerpt(row.get("readback_claim") or "", 160),
                    response=_excerpt(row.get("readback_response") or "", 120),
                ),
            )
        if script.pulled_where_template:
            try:
                strands = json.loads(row.get("readback_strands") or "[]")
            except Exception:
                strands = []
            if len(strands) == 1:
                phrase = f"the {strands[0]} strand"
            elif len(strands) >= 2:
                phrase = f"the {strands[0]} and {strands[1]} strands"
            else:
                phrase = "the strands it was heard under"
            self._say(
                user_id, cid, arch_id,
                script.pulled_where_template.format(strands=phrase),
            )
        for paragraph in script.orientation:
            self._say(user_id, cid, arch_id, paragraph)

    def _orientation_beat(self, user_id: str, arch_id: str, keystone_index: int,
                          script: MT.MeetingScript, message: str) -> None:
        cid = conversation_id_for(arch_id, keystone_index)
        if not _is_acknowledgment(message) and not _is_pass(message):
            # A real question about how the system works: one framed
            # answer from the script's facts, then the meeting proceeds.
            history = self._history_for_reply(user_id, cid)
            frame = script.orientation_frame
            if script.orientation_facts:
                frame = f"{frame}\n\n{script.orientation_facts}"
            reply = generate_voice_reply(
                user_id, arch_id, message, history[:-1],
                mode="base", generate_fn=self._generate_fn,
                extra_instructions=frame,
            )
            self._say(user_id, cid, arch_id, reply.reply)
        self._do_reveal(user_id, arch_id, keystone_index, script)

    def _do_reveal(self, user_id: str, arch_id: str, keystone_index: int,
                   script: MT.MeetingScript) -> None:
        cid = conversation_id_for(arch_id, keystone_index)
        for paragraph in script.reveal:
            self._say(user_id, cid, arch_id, paragraph)

        tasks = _seat_keystone_tasks(user_id, arch_id)
        if len(tasks) >= keystone_index:
            task = tasks[keystone_index - 1]
            if task.get("status") != "Done":
                ve.update_task(task["id"], ve_models.TaskUpdate(status="Done"), user_id)
        self.meetings.update(user_id, arch_id, keystone_index, stage="complete", status="complete")

    def pause(self, user_id: str, archetype_id: str, keystone_index: int = 1) -> dict[str, Any]:
        arch_id = (archetype_id or "").strip().lower()
        row = self.meetings.get(user_id, arch_id, keystone_index)
        if row is not None and row["status"] == "active":
            self.meetings.update(user_id, arch_id, keystone_index, status="paused")
        return self.state(user_id, arch_id, keystone_index)
