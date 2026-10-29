"""Encounter runtime — first meetings as stateful characters, not scripts.

Doctrine (Joshua, 2026-10-23 — the Fellowship Runtime): an introduction
is an ENCOUNTER with a philosophically coherent character who holds
narrative OBJECTIVES, not a sequence of dialogue bubbles the user is
walked through. This module is that runtime. The meeting service
(local_ai/conversation/meeting.py) is its first host: it owns the
stores, the keystone guards, and the completion chokepoint, and lends
the runtime its hands (say / generate / file) through a small host
protocol. Only the Conductor's keystone 1 is defined so far — the
proving ground, not a special case.

The rules the runtime runs by:

  - Minimal scripted opening: character, environment, invitation.
    A few short bubbles, delivered verbatim, then the character
    waits and the user is participating — the rest of the old
    scripted opening survives as bench anchors and
    prepared context, not as a monologue delivered at the door.
  - Objectives, never announced: each objective is a predicate over
    the encounter state (transcript-derived counters and flags),
    checked after every turn. An objective can be satisfied by
    whatever the user volunteers — an offer to help the Weaver build
    IS encounter material, because it shows how the user relates to
    someone else's unfinished work. Objectives are the frame's only
    agenda: every live objective's guidance rides the generation
    frame as a standing hope, and the user's contributions — not
    the objectives — determine the conversational trajectory.
  - The user's move comes first. Recognition of the move (answer /
    question / offer / joke / disagreement / direction-change) lives
    INSIDE the character's generation call — frame instructions plus
    prepared context, never a separate classifier call on the reply
    path (two-speed law: the fast path is prepared context + ONE
    generation call per user turn, worst case). The deterministic
    shapes below are routing safety nets only: they decide which
    frame runs, conservatively — an unrecognized move is treated as
    conversation, never as agenda-advance.
  - Deterministic heuristics survive ONLY where a misread has durable
    consequences: the reply to the read-back (a correction REVISES
    the stored impression; completion FILES it). Those two state
    transitions keep the phrase classifiers this module carries.
  - Closing is on RECOGNITION, not position — and never while a
    thread hangs. The reveal fires once the impression has been
    offered AND genuinely answered (agree, correct, reject, or
    argue — recognition is not agreement), and the conversation's
    open-door evaluation says nothing is left hanging. That
    evaluation is semantic: it rides the turn's single generation
    as a stripped bookkeeping trailer, with a deterministic
    estimate only when the model omits the trailer. Until both
    hold, the encounter is ordinary conversation: she always
    answers, and no thread is closed over. At the turn ceiling
    (open middle only) the character wraps gracefully ("I've kept
    you long enough") and the impression still files exactly
    once, through the host's existing chokepoint.
  - The world is a runtime input: frames draw on the seat's
    jurisdiction record (P0) and the environmental registry
    (meetings.SEAT_ENVIRONMENT); allusions surface at most one per
    turn, only when the conversation passes near a fixture, and are
    logged in the encounter state against the debt registry
    (meetings.WEAVER_ALLUSIONS) — traces are debts, and the state is
    where the runtime keeps its side of the ledger. The old
    workshop pause lives here now: its paragraphs are cues in the
    same pool — available context the conversation may pass near,
    never a block delivered because a flag flipped. The pulled-item
    accounting that once quoted the record in dialogue is retired
    entirely; that bookkeeping belongs to the interface layer.
  - Scripted lines survive as fallback anchors: if generation fails
    or returns nothing, the character says the definition's fallback
    line and the encounter state does not advance — degradation is
    honest, never a silent skip.
  - MEANINGFUL recognition, not merely sufficient (the Weaver
    pattern, Joshua 2026-10-23 — his live test of the adaptivity
    fix ended the meeting after two user turns: an impression
    offered at the first opportunity and answered with an
    affirmation). An authored definition may therefore carry two
    structural guards, both formalized as objective predicates over
    state (see check_objectives), never as turn counters in the
    close path: an IMPRESSION GATE (the read is not offerable until
    a named objective — the shared-work exchange — was satisfied on
    a PRIOR turn, so a turn-one impression is structurally
    impossible), and a CLOSE FLOOR (an answered impression closes
    the meeting only when at least one of the named floor
    objectives is also satisfied: the user's own material was taken
    up, or a pursuit exchange followed it). The ceiling backstop
    bypasses both — a wrap is a rescue, not a recognition claim.
    Rows hydrated from pre-runtime storage whose impression was
    already on the table carry floor_waived: their recognition
    completes under the contract the meeting began with, and no
    in-flight meeting is stranded by the new floor.
  - Three intentions (Joshua, 2026-10-24 — supersedes the retired
    tutorial-beat mechanism, its guidance tiers, pivot, and close
    gate): a first meeting is organized by (1) be yourself —
    converse naturally from the character, philosophy, and
    jurisdiction, engaging with what the visitor actually brings;
    (2) let the visitor discover who you are — what matters to
    you, why you wanted to meet, what distinguishes your
    perspective; (3) show one real thing within your scope,
    explained concretely when relevant. These are intentions, not
    speeches, turns, or a checklist: they overlap, emerge in any
    order, and being yourself governs — never interrupt a
    meaningful exchange to teach or to introduce yourself. "One
    thing" is intentional: the meeting is not responsible for
    teaching every feature. The ceiling wrap is unchanged — a
    rescue, not a recognition claim.
  - Evidence and expression are separate layers (Joshua's ruling,
    2026-10-23): the user's exact words live in the evidence —
    stored verbatim, filed with the claim, shown in review with
    provenance. The character's dialogue is her own synthesis in
    her own register: no frame on this path requires quotation, no
    generation is fed the weave instruction, and any [[u]] markup
    a model emits anyway is stripped before her words are spoken
    or stored. Quote-splicing is a structure, not a style — it
    dies here.

Nothing here trains anything. The impression files through the host
into the review queue, anchored to the user's verbatim words, and
only a verdict on it writes a signal — the transparency mechanics
stay in the review interface, out of the character's dialogue.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace as _dc_replace
from typing import Protocol

from local_ai.council import capabilities as CAP
from local_ai.council import jurisdictions as JX
from local_ai.council import meetings as MT
from local_ai.council import steward_records as _steward_records

from .weave import strip_weave_markers

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deterministic heuristics — safety nets for state-critical transitions.
#
# These phrase classifiers decide only two durable things: whether the
# user's reply to the read-back REVISES the stored impression, and the
# small routings where a wrong guess would corrupt state (a "pass" is
# navigation, not material). Everything else about reading the user's
# move belongs to the character's generation call.
# ---------------------------------------------------------------------------

#: Plain strand names the read-back's bookkeeping line may cite.
STRAND_NAMES = ("Voice", "Logic", "Eye", "Ear", "Hands", "Heart", "Compass")

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

#: Correction signals for the read-back reply: the user amending the
#: impression rather than accepting it or changing the subject. Matched
#: against the normalized reply (phrases as substrings, plus a leading
#: negation); acknowledgment is checked FIRST, so an ack carrying a
#: contrast word (which _is_acknowledgment already rejects) reaches
#: this check and can still classify as a correction via "actually" /
#: "except" / "however" / "though".
_CORRECTION_PHRASES = (
    "actually", "except", "however", "though", "instead", "rather",
    "not quite", "not really", "more like", "that's wrong", "that is wrong",
    "you got it wrong", "you've got it wrong", "not how i", "not how it",
    "i meant", "what i meant", "i mean,", "let me correct", "correction",
    "the opposite", "it's the other", "it is the other",
)


def _classify_readback_reply(message: str) -> str:
    """Three-way classification of the user's reply to the read-back:
    "ack" (the impression stands, agreed), "correction" (the user is
    amending it — the stored impression gets replaced), or "other"
    (neither — the impression stands as the character's own)."""
    if _is_acknowledgment(message):
        return "ack"
    norm = " ".join((message or "").strip().lower().strip(".! ").split())
    if not norm:
        return "other"
    if norm in ("no problem", "no worries", "no complaints"):
        return "ack"
    if norm == "no" or norm.startswith(("no ", "no,", "no —", "no -", "nope")):
        return "correction"
    if any(phrase in norm for phrase in _CORRECTION_PHRASES):
        return "correction"
    words = norm.split()
    if "but" in words:
        return "correction"
    return "other"


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


#: Short answers that mean "ask me a different one" rather than an answer.
#: Exact-match after normalization — a substantive "no, because…" is an
#: answer, not a pass.
_PASS_TOKENS = {
    "pass", "skip", "next", "next question", "another question",
    "different question", "idk", "i don't know", "not sure", "nope",
}


def _is_pass(message: str) -> bool:
    norm = " ".join((message or "").strip().lower().strip(".! ").split())
    return norm in _PASS_TOKENS


def split_strands_trailer(text: str) -> tuple[str, list[str]]:
    """Split a generated read-back's 'Strands:' bookkeeping line off
    its display text. A missing or garbled trailer degrades to no
    strands — the meeting never breaks on it."""
    text = (text or "").strip()
    strands: list[str] = []
    lines = text.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.lower().startswith("strands:"):
            cited = [s.strip() for s in stripped.split(":", 1)[1].split(",")]
            strands = [s for s in cited if s in STRAND_NAMES][:2]
            text = "\n".join(lines[:i]).strip()
        break
    return text, strands


# ---------------------------------------------------------------------------
# The open-door trailer — the semantic thread judgment that rides the
# turn's single generation (refinement, Joshua 2026-10-23).
#
# Whether the encounter may close is a judgment about MEANING: the
# user's last message may leave a thread hanging (a question awaiting
# its answer, an offer on the table, a disagreement they are still
# pressing) or may settle the conversation. Phrase matching cannot
# decide that honestly, and a short acknowledgment is not automatic
# proof of an ending — so the character makes the call inside the
# generation she is already producing, ending her reply with one
# bookkeeping line the runtime strips before anything is spoken. No
# extra call is spent; the trailer rides the existing one. When the
# model omits the trailer, the runtime falls back to the
# deterministic estimate below — an estimate, labeled as such.
# ---------------------------------------------------------------------------

_THREAD_TRAILER_RE = re.compile(r"\[\[thread:(open|settled)\]\]")

#: Appended to the frames of every turn whose generation carries the
#: open-door judgment (the impression-response turn and every
#: post-recognition turn).
_THREAD_TRAILER_INSTRUCTION = (
    "\n\nAfter everything else (including any 'Strands:' line), end "
    "with exactly one final line, on its own: [[thread:open]] if "
    "their last message leaves something genuinely hanging — a "
    "question still awaiting its answer, an offer on the table, a "
    "new topic they have opened, a disagreement they are still "
    "pressing — or [[thread:settled]] if nothing is left hanging "
    "and the meeting could gracefully end here. That line is "
    "bookkeeping for the system, never part of what you say to them."
)

#: Appended alongside the trailer instruction in the recognition
#: phase: recognition does not require agreement (refinement,
#: Joshua 2026-10-23).
_RECOGNITION_NOTE = (
    "\n\nTheir answer to your impression — whatever its valence: "
    "agreement, correction, thoughtful rejection, uncertainty, "
    "disagreement — completes the recognition in itself. Do not "
    "argue them toward your reading, do not soften a rejection "
    "into assent, and do not reframe their words more flatteringly "
    "than they said them. A rejection leaves your impression "
    "standing as your own read, with their answer standing beside "
    "it; the disagreement is part of the record, not a problem to "
    "smooth over."
)


# ---------------------------------------------------------------------------
# Standing dialogue rules (2026-10-24 amendments C and E, slimmed
# 2026-10-24): direct questions about Zenaf, and two-tier naming
# for other seats. Both notes are one line each. The naming note
# rides every generation path; the Zenaf note rides the
# conversational Q&A paths (_turn_frame, engage path). Correction
# and impression movements are impression-focused by design, so
# they carry the naming note only — a Zenaf question bundled with
# a correction is answered on the next conversational turn, when
# the standing note is in frame.
# ---------------------------------------------------------------------------

#: Character name per seat role (archetype id). Roles are public
#: vocabulary; character names unlock seat by seat, when met.
_SEAT_CHARACTER_NAMES = {
    "mentor": "Gardener",
    "champion": "Firebrand",
    "guardian": "Bear",
    "maverick": "Fox",
    "ambassador": "Crane",
    "conductor": "Weaver",
    "skeptic": "Raven",
}


def _naming_note(definition: EncounterDefinition) -> str:
    """Two-tier naming (amendment E) as one line: roles before
    meeting, character names after, seat by seat. The met list is
    state, not a paragraph — the model reads it, it does not need
    it explained."""
    met = [a for a in definition.met_seats
           if a in _SEAT_CHARACTER_NAMES]
    if met:
        met_text = ", ".join(
            f"{_SEAT_CHARACTER_NAMES[a]} ({a})" for a in met)
        return "Other seats: roles until met. Met: " + met_text + "."
    return "Other seats: roles until met. None met yet."


#: Standing responsibility (amendment C), one line: direct
#: questions about Zenaf get concrete answers first. No detector:
#: the line covers every phrasing, and a small regex vocabulary
#: can only re-state it for the phrasings it happens to match.
_ZENAF_QUESTION_NOTE = (
    "If the visitor asks about Zenaf, answer plainly first — "
    "what it is, what it does, what they can do with it — and "
    "say plainly what is planned rather than available. Then "
    "return to their material."
)


def split_thread_trailer(text: str) -> tuple[str, str | None]:
    """Split the open-door bookkeeping trailer off a generated reply:
    a line '[[thread:open]]' or '[[thread:settled]]' the frame asks
    for and the user never sees. Returns (display_text, verdict) —
    verdict None when the model didn't comply, and the caller falls
    back to the deterministic estimate."""
    verdict: str | None = None
    kept: list[str] = []
    for line in (text or "").split("\n"):
        match = _THREAD_TRAILER_RE.fullmatch(line.strip())
        if match:
            verdict = match.group(1)
            continue
        kept.append(line)
    body = "\n".join(kept).strip()
    if verdict is None:
        # A trailer glued to the last spoken line still counts —
        # and still never reaches the user.
        glued = re.search(r"\s*\[\[thread:(open|settled)\]\]\s*$", body)
        if glued:
            verdict = glued.group(1)
            body = body[:glued.start()].strip()
    return body, verdict


def _fallback_thread_verdict(message: str) -> str:
    """The deterministic open-door ESTIMATE, used only when the
    generation carried no trailer: a question, an offer, a direction
    change, or substantive new material reads as a thread still
    open; a pure acknowledgment or pass reads as settled. It is a
    safety net for model noncompliance, not the mechanism — the
    semantic judgment rides the generation whenever one ran."""
    move = detect_move(message)
    if move in ("question", "offer", "direction"):
        return "open"
    if "?" in (message or ""):
        return "open"
    if move in ("ack", "pass"):
        return "settled"
    if len((message or "").strip()) >= SUBSTANCE_MIN_USER_CHARS:
        return "open"
    return "settled"


# ---------------------------------------------------------------------------
# Move shapes — deterministic routing for which frame runs.
#
# Deliberately shallow: these shapes catch the moves whose routing is
# unambiguous (offers, explicit questions, subject changes, passes) and
# let everything else fall to "substantive" or "conversation". They do
# NOT interpret the user — the character does that, in her generation
# call. A misroute here defers the agenda; it never advances it wrongly.
# ---------------------------------------------------------------------------

_OFFER_PHRASES = (
    "can i help", "want a hand", "let me help", "i can help", "i'll help",
    "i will help", "need a hand", "give you a hand", "lend a hand",
    "help you with", "help with that", "want me to hold", "shall i hold",
    "i could hold", "let me hold", "happy to help", "can i hold",
)

_DIRECTION_PHRASES = (
    "change the subject", "different topic", "talk about something else",
    "let's talk about something else", "never mind", "forget the instrument",
    "forget it", "move on", "skip the question",
)

_JOKE_MARKERS = ("haha", "lol", "😂", "🤣", "just kidding", "jk,")

_GREETING_TOKENS = {
    "hi", "hello", "hey", "morning", "good morning", "good afternoon",
    "good evening", "yo", "hiya",
}

#: Completion-intent vocabulary (Fellowship shared foundation,
#: 2026-10-28): explicit finish phrasings ONLY — a narrow list, so
#: an ordinary "bye" or a topical "done with this" is not swept in.
#: Checked BEFORE the "?" rule, so "we're done here?" classifies as
#: completion intent, not as a question. The signal NEVER auto-closes:
#: it routes to the explicit confirmation action (the character
#: naming the Complete action while the record stays honestly
#: active, and the controller-visible `completion_offered` signal),
#: and only the offered-path + affirmation sequence — or the
#: visitor's explicit UI Complete action — closes the meeting.
#: There is deliberately NO deterministic second-utterance rule:
#: a bare utterance count never closes anything (see
#: _is_completion_confirmation and the confirmation branch in
#: handle_turn).
_COMPLETION_PHRASES = (
    "we're done", "we are done", "that's all", "i have to go",
    "i've got to go", "i gotta go", "i need to go", "i must go",
    "complete this meeting", "complete the meeting", "end the meeting",
    "finish this meeting", "let's wrap up", "lets wrap up",
    "time to wrap up",
)

#: The frame instruction appended on the completion-offer turn. It
#: tells the character to name the Complete action explicitly while
#: keeping words and record in agreement: the meeting is NOT over
#: until the visitor confirms, and it stays open if they move on.
_COMPLETION_PATH_INSTRUCTION = (
    "The visitor has just said they want to finish. Say plainly, "
    "in your own words, that they can tap 'Complete this meeting' "
    "below to end it — and say plainly that the meeting is still "
    "open until they do. Never state or imply that the meeting is "
    "already over, and never close it yourself in words."
)


def _is_completion_confirmation(message: str) -> bool:
    """Is this turn the visitor confirming a completion path that
    was already offered? True for a restated completion intent, or
    for a short affirmation (ack) while `completion_offered` is set.
    A bare utterance count is never enough: without the offered
    path already standing, this returns False for affirmations —
    the caller checks the offered flag first. A new topic, a
    question, or any other move is not a confirmation, and the
    offered path lapses instead (see handle_turn)."""
    if detect_move(message) == "completion":
        return True
    return _is_acknowledgment(message)


def detect_move(message: str) -> str:
    """The deterministic shape of the user's turn, for frame routing:
    "pass" | "offer" | "direction" | "joke" | "completion" |
    "question" | "ack" | "greeting" | "substantive". Reading the
    move's MEANING is the character's job, in generation; this only
    picks the frame."""
    raw = (message or "").strip()
    norm = " ".join(raw.lower().strip(".! ").split())
    if not norm:
        return "substantive"
    if _is_pass(raw):
        return "pass"
    if any(p in norm for p in _OFFER_PHRASES):
        return "offer"
    if any(p in norm for p in _DIRECTION_PHRASES):
        return "direction"
    if any(m in raw.lower() for m in _JOKE_MARKERS):
        return "joke"
    if any(p in norm for p in _COMPLETION_PHRASES):
        return "completion"
    if "?" in raw:
        return "question"
    if norm in _GREETING_TOKENS:
        return "greeting"
    if _is_acknowledgment(raw):
        return "ack"
    return "substantive"


# ---------------------------------------------------------------------------
# Definitions — what an encounter IS, as data.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Objective:
    """One narrative objective of an encounter. `satisfied_when` is the
    predicate in words (for reviewers); the runtime evaluates it over
    EncounterState in check_objectives, keyed by `id`. Objectives are
    server-side state only — they are never woven into generation
    frames (slim-prompt rule, 2026-10-24): the character is never
    told an objective exists, as bookkeeping or as guidance."""

    id: str
    description: str
    satisfied_when: str


@dataclass(frozen=True)
class AllusionCue:
    """One environmental trace the runtime may surface: the locked line,
    the fixture it belongs to (from SEAT_ENVIRONMENT), and the words in
    the user's speech that mean the conversation is passing near it."""

    seat: str
    text: str
    fixture: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class EncounterDefinition:
    """An encounter, per (seat, keystone): a minimal scripted opening,
    a set of objectives, the frames the character generates within,
    and the scripted anchors that survive as fallbacks. Built from a
    MeetingScript (meetings.py) plus, for authored encounters, the
    objective set and bench material below."""

    archetype_id: str
    keystone_index: int
    character: str
    #: Delivered verbatim at start — a few short bubbles (character,
    #: environment, invitation), then the character waits.
    opening: tuple[str, ...]
    #: The encounter's question bank: [0] is the invitation inside the
    #: opening; the rest are branches a pass can offer, never a
    #: checklist to complete.
    question_bank: tuple[str, ...]
    objectives: tuple[Objective, ...]
    #: The substantive-answer call: ONE generation producing the engaged
    #: reply and the first impression as two movements, split on the
    #: delimiter line the frame specifies.
    engage_frame: str
    #: The conversational call: initiative, questions, jokes, detours —
    #: the character responds to the move; the agenda waits.
    turn_frame: str
    #: The impression alone (pass-exhaustion and ceiling paths).
    impression_frame: str
    correction_frame: str
    impression_reply_frame: str
    orientation_frame: str
    orientation_facts: str
    #: The workshop pause (scripts that carry one), RETIRED as a
    #: delivered beat (adaptivity fix, 2026-10-23): its paragraphs
    #: are no longer spoken as a block when the impression is
    #: answered. The body paragraphs live on as available context —
    #: proximity cues in the allusion pool (see build_definition /
    #: build_weaver_k1_definition). The fields stay for data compat.
    pause_intro: tuple[str, ...]
    pause_body: tuple[str, ...]
    #: RETIRED from spoken dialogue entirely: quoting the record
    #: back at the user is system explanation, and system
    #: explanation belongs to the interface layer (the completion
    #: card, the review queue). Kept as data fields for compat;
    #: the runtime never formats or speaks them.
    pulled_item_template: str
    pulled_where_template: str
    #: Verbatim close, delivered by the host when conditions are met.
    reveal: tuple[str, ...]
    #: Said once, before the reveal, when the close is the ceiling's.
    wrap_line: str
    #: Said when a generation fails or returns nothing: honest
    #: degradation; the encounter state does not advance.
    fallback_line: str
    allusion_pool: tuple[AllusionCue, ...] = ()
    #: The impression gate (the Weaver pattern): the objective id
    #: that must already be satisfied — as of a PRIOR turn's
    #: check_objectives — before an impression may be offered on the
    #: engage path or the pass path. "" = no gate (the generic
    #: shape). The ceiling wrap offers a fresh impression ONLY when
    #: the gate is satisfied (no-manufacture rule, Fellowship shared
    #: foundation 2026-10-28); a held (pending) read, which was
    #: gate-checked at generation, still speaks at the wrap.
    impression_gate_objective: str = ""
    #: Fellowship reference (shared foundation, 2026-10-28): the
    #: seat's slice of the shared Fellowship knowledge, carried as a
    #: meeting-scoped prompt section OUTSIDE the capped frame (see
    #: reply.build_voice_prompt `fellowship_reference`). "" = no
    #: reference written yet — the placement mechanism is live, the
    #: canonical reference text is a later phase (it needs Joshua's
    #: verdict as canonical text) and is never improvised here.
    fellowship_reference: str = ""
    #: The close floor (the Weaver pattern): objective ids of which
    #: at least one must be satisfied for a settled verdict to close
    #: the meeting after recognition. Empty = no floor. Legacy
    #: hydration may waive it per-state (floor_waived).
    close_floor_objectives: tuple[str, ...] = ()
    #: Seats the visitor has already met (completed first meetings),
    #: as archetype ids — set by the meeting service per turn, never
    #: by the script. The naming rule (role before meeting, character
    #: name after, seat by seat) reads this list; empty means no
    #: other seat has been met yet, so every reference uses a role.
    met_seats: tuple[str, ...] = ()
    #: Capability context for this seat's first meeting
    #: (demonstration spec §6): the seat's own registry slice plus
    #: the one shared intention line, rendered from
    #: local_ai/council/capabilities.py — never hardcoded here. Set
    #: at definition build; the meeting service re-resolves it per
    #: turn from the visitor's actual state, like met_seats. "" =
    #: no slice (unknown seat). Impression, correction, reply, and
    #: orientation frames never carry it: the read-back grounds only
    #: in the user's substantive material.
    capability_context: str = ""


# ---------------------------------------------------------------------------
# State — the encounter as the runtime remembers it.
# ---------------------------------------------------------------------------

#: The substance floor for "the user has brought their own undertaking
#: into the room": a real answer, not a token one.
SUBSTANCE_MIN_USER_CHARS = 40

#: The graceful ceiling: past this many user turns, the character wraps
#: ("I've kept you long enough") rather than letting the first meeting
#: ramble. RETAINED TEMPORARILY (Fellowship shared foundation,
#: 2026-10-28) as a resource/runaway safeguard ONLY — never a
#: narrative endpoint — and it manufactures nothing: when no gate
#: was satisfied, a ceiling close files nothing (see _wrap_turn).
#: The resource-limit replacement is proposed, not built, in the
#: PR description for this change (ceiling investigation).
TURN_CEILING = 12


@dataclass
class EncounterState:
    user_turns: int = 0
    engagements: int = 0
    offers_engaged: int = 0
    user_chars: int = 0
    longest_user_turn: str = ""
    #: The recognition floor's trackers (the Weaver pattern). They
    #: are transcript-derived counters like the ones above; the
    #: objectives read them, the close path never counts turns.
    #: material_turn: the user_turns value of the first user message
    #: at substance (≥ SUBSTANCE_MIN_USER_CHARS), 0 = their own
    #: material has not surfaced yet. pursuit_turns: turns AFTER the
    #: material surfaced in which the conversation followed it (any
    #: non-pass, non-bare-ack move) — plus, once recognition has
    #: happened, any further non-pass turn: a user who answered the
    #: impression and stayed to talk again has taken the thread up,
    #: and the floor must never hold a willing user hostage.
    #: substantive_turns: substantive-move turns across all phases.
    material_turn: int = 0
    pursuit_turns: int = 0
    substantive_turns: int = 0
    #: Set ONLY by legacy hydration (meeting.py): the row predates
    #: the runtime and its impression was already on the table when
    #: the runtime first saw the meeting, so the close floor is
    #: waived for it — the recognition completes under the contract
    #: the meeting began with.
    floor_waived: bool = False
    satisfied: dict[str, bool] = field(default_factory=dict)
    impression_offered: bool = False
    impression_answered: bool = False
    impression_answer_kind: str = ""
    impression_text: str = ""
    impression_strands: list[str] = field(default_factory=list)
    #: A generated impression held back by the sequencing rule
    #: (2026-10-24 screenshot fix): its generation's reply ended
    #: in a question, so speaking the impression in the same breath
    #: would orphan that question. The held impression is the only
    #: impression that may speak until delivered; delivery happens
    #: after the first later reply that does not end in a question.
    impression_pending_text: str = ""
    impression_pending_strands: list[str] = field(default_factory=list)
    #: Fellowship shared foundation (2026-10-28) — completion path
    #: state, persisted in state_json and surfaced by the meeting
    #: API so the frontend can render the hint + primary Complete
    #: action: True from the turn the character names the Complete
    #: action until the visitor confirms, moves on (lapse), or the
    #: meeting closes. Never, on its own, a close: closing requires
    #: the offered-path + affirmation sequence, or the explicit UI
    #: Complete action.
    completion_offered: bool = False
    #: Auditable discard record (2026-10-28): when a held (pending)
    #: impression is discarded on a voluntary end instead of being
    #: spoken or filed, this carries the reason ("" = nothing
    #: discarded). The discard is also logged; the held text itself
    #: is cleared, never spoken, never filed, never an accepted
    #: claim. Ceiling wraps are NOT voluntary ends: a gate-earned
    #: held read still speaks at the wrap (see _wrap_turn).
    pending_impression_discarded: str = ""
    response_recorded: bool = False
    #: Legacy field, kept for state hydration: rows written by the
    #: P3 runtime (or the stage engine before it) may carry it. The
    #: adaptive runtime never sets it — it maps to the
    #: post-recognition phase (see derived_stage / handle_turn).
    pause_delivered: bool = False
    #: Cue keys already surfaced: fellowship seats for allusions,
    #: "pause:N" for retired-pause paragraphs — one ledger, so the
    #: same fixture can never surface twice by either path.
    allusions_used: list[str] = field(default_factory=list)
    closed: bool = False

    def to_json(self) -> str:
        return json.dumps({
            "user_turns": self.user_turns,
            "engagements": self.engagements,
            "offers_engaged": self.offers_engaged,
            "user_chars": self.user_chars,
            "longest_user_turn": self.longest_user_turn,
            "material_turn": self.material_turn,
            "pursuit_turns": self.pursuit_turns,
            "substantive_turns": self.substantive_turns,
            "floor_waived": self.floor_waived,
            "satisfied": self.satisfied,
            "impression_offered": self.impression_offered,
            "impression_answered": self.impression_answered,
            "impression_answer_kind": self.impression_answer_kind,
            "impression_text": self.impression_text,
            "impression_strands": self.impression_strands,
            "impression_pending_text": self.impression_pending_text,
            "impression_pending_strands": self.impression_pending_strands,
            "completion_offered": self.completion_offered,
            "pending_impression_discarded": self.pending_impression_discarded,
            "response_recorded": self.response_recorded,
            "pause_delivered": self.pause_delivered,
            "allusions_used": self.allusions_used,
            "closed": self.closed,
        })

    @classmethod
    def from_json(cls, raw: str | None) -> "EncounterState":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except Exception:
            return cls()
        if not isinstance(data, dict):
            return cls()
        state = cls()
        for key in (
            "user_turns", "engagements", "offers_engaged", "user_chars",
            "longest_user_turn", "material_turn", "pursuit_turns",
            "substantive_turns", "floor_waived",
            "satisfied", "impression_offered",
            "impression_answered", "impression_answer_kind",
            "impression_text", "impression_strands",
            "impression_pending_text", "impression_pending_strands",
            "completion_offered", "pending_impression_discarded",
            "response_recorded",
            "pause_delivered", "allusions_used",
            "closed",
        ):
            if key in data:
                setattr(state, key, data[key])
        return state


def check_objectives(definition: EncounterDefinition, state: EncounterState) -> None:
    """Evaluate every objective's predicate over the state. Predicates
    are keyed by objective id; an id the runtime doesn't know is never
    satisfied by accident (it stays the author's note, not a claim)."""
    for obj in definition.objectives:
        if state.satisfied.get(obj.id):
            continue
        ok = False
        if obj.id == "engaged_exchange":
            ok = state.engagements >= 1
        elif obj.id == "shared_work_exchange":
            # The shared work has begun: a substantive engagement
            # with the material her invitation opened, or an offer
            # of help received — either way, she and the user are
            # working the same thing together.
            ok = state.engagements >= 1 or state.offers_engaged >= 1
        elif obj.id == "offer_of_help_received":
            ok = state.offers_engaged >= 1
        elif obj.id == "pursuit_exchange":
            # The conversation has TAKEN UP the user's material:
            # either an exchange followed its surfacing (the
            # character asked, the user told — tracked structurally
            # in handle_turn), or substantive engagement has simply
            # accumulated across the meeting.
            ok = (state.pursuit_turns >= 1
                  or state.substantive_turns >= 3)
        elif obj.id == "own_undertaking_engaged":
            ok = (state.engagements >= 1
                  and state.user_chars >= SUBSTANCE_MIN_USER_CHARS)
        elif obj.id == "impression_offered":
            ok = state.impression_offered
        elif obj.id == "impression_answered":
            ok = state.impression_answered
        state.satisfied[obj.id] = ok


def derived_stage(state: EncounterState) -> str:
    """The stage label the meeting API has always surfaced, derived
    from encounter state: the interface reads position; the runtime
    runs on objectives. "orientation" is the post-recognition phase
    now — the conversation after the impression has been answered,
    before the close — the same position the label always marked."""
    if state.closed:
        return "complete"
    if state.impression_answered or state.pause_delivered:
        return "orientation"
    if state.impression_offered:
        return "readback"
    return "encounter"


# ---------------------------------------------------------------------------
# The host protocol — what the runtime borrows from the meeting service.
# ---------------------------------------------------------------------------


class EncounterHost(Protocol):
    """The meeting service's hands. `generate` runs ONE framed live
    beat against the transcript (the service's voice-reply path) and
    returns "" on failure — the runtime degrades to fallback anchors
    rather than surfacing provider errors mid-meeting. `close` is the
    completion chokepoint: reveal, keystone Done, impression filed
    exactly once."""

    def say(self, body: str) -> None: ...
    def generate(self, frame: str) -> str: ...
    def store_impression(self, claim: str, strands: list[str]) -> None: ...
    def store_response(self, text: str) -> None: ...
    def close(self, wrap_line: str) -> None: ...


# ---------------------------------------------------------------------------
# The runtime.
# ---------------------------------------------------------------------------

#: The delimiter the engage frame puts between the reply movement and
#: the impression movement of its single generation.
_DELIMITER = "---"

#: Appended to the impression frame when the ceiling forms the
#: impression: the evidence is the whole exchange, not one answer.
_WHOLE_EXCHAUST_NOTE = (
    "\n\nNote: the conversation has ranged beyond a single answer. "
    "Form your impression from the whole of what they have said "
    "across this meeting — the exchange itself is the evidence."
)

def _spoken(text: str) -> str:
    """Generated text on its way to being spoken by the character —
    or stored as her words (the impression claim): bookkeeping
    markup stripped, the words themselves kept. Thread trailers
    and weave markers alike never reach the user, on any path,
    whatever the model emitted. The encounter path runs under the
    evidence/expression separation, so her dialogue carries no
    quote markup either; the user's exact words live in the stored
    evidence, untouched by this."""
    body, _verdict = split_thread_trailer(text or "")
    return strip_weave_markers(body).strip()


class EncounterRuntime:
    """Runs one encounter definition against a host, turn by turn."""

    def __init__(self, definition: EncounterDefinition) -> None:
        self.definition = definition

    # -- generation plumbing -------------------------------------------------

    def _offer_impression(self, host: EncounterHost, state: EncounterState,
                          frame: str) -> bool:
        """Generate the first impression from `frame`, store and speak
        it. Returns False when generation produced nothing usable —
        the caller degrades; no state advances on a failed impression."""
        raw = host.generate(frame + "\n\n" + _naming_note(self.definition))
        claim, strands = split_strands_trailer(raw)
        claim = _spoken(claim)
        if not claim:
            return False
        host.store_impression(claim, strands)
        state.impression_text = claim
        state.impression_strands = strands
        state.impression_offered = True
        host.say(claim)
        return True

    def _split_reply_and_impression(self, raw: str) -> tuple[str, str, bool]:
        """Split the engage call's two movements on its delimiter line.
        No delimiter: the whole output is treated as the impression
        movement (the frames ask for the impression last; a reply-only
        output carries no strands trailer and degrades in the caller)."""
        lines = (raw or "").split("\n")
        for i, line in enumerate(lines):
            if line.strip() == _DELIMITER:
                reply = "\n".join(lines[:i]).strip()
                impression = "\n".join(lines[i + 1:]).strip()
                return reply, impression, True
        return "", (raw or "").strip(), False

    def _deliver_pending_if_clear(self, host: EncounterHost,
                                  state: EncounterState,
                                  spoken_reply: str,
                                  *, allow_bare: bool = False) -> bool:
        """Deliver a held impression after a reply that leaves the
        user exactly one question to answer. The hold exists because
        a reply ending in a question must not share its breath with
        an impression ending in another question (2026-10-24
        screenshot: the reply's question was orphaned). So delivery
        requires a spoken reply that does not end in a question; a
        fallback line is not a reply and never triggers delivery.
        `allow_bare` covers a turn with no reply movement at all:
        the held read speaks alone rather than a fallback line.
        No gate re-check: the held impression was gate-checked at
        generation, and satisfaction is monotonic. Returns True
        when a pending impression was delivered."""
        pending = state.impression_pending_text
        if not pending or state.impression_offered:
            return False
        reply = (spoken_reply or "").strip()
        if reply.endswith("?"):
            return False
        if not reply and not allow_bare:
            return False
        host.store_impression(pending, state.impression_pending_strands)
        state.impression_text = pending
        state.impression_strands = state.impression_pending_strands
        state.impression_offered = True
        state.impression_pending_text = ""
        state.impression_pending_strands = []
        host.say(pending)
        return True

    @staticmethod
    def _discard_pending(state: EncounterState, reason: str) -> bool:
        """Explicitly discard a held (pending) impression on a
        voluntary end (Fellowship shared foundation, 2026-10-28 —
        this REPLACES the audit's deliver-or-discard alternative:
        a visitor who wants to leave is never made to sit through
        a delivery first, and an uncommunicated impression must
        never become an accepted claim). The held text is cleared
        — never spoken, never filed — and the reason is both
        logged and recorded on the state (`pending_impression_
        discarded`), so the discard is inspectable after the fact
        in the completed row's state_json. No-op when nothing is
        pending. Callers: the confirmation close, the runtime
        settled close, and MeetingService.complete (manual path).
        The ceiling wrap is not a voluntary end and does not call
        this: a gate-earned held read speaks at the wrap."""
        pending = state.impression_pending_text
        if not pending:
            return False
        logger.info(
            "meeting: discarding pending impression on voluntary end "
            "(%s); held text length=%d, never spoken, never filed",
            reason, len(pending),
        )
        state.impression_pending_text = ""
        state.impression_pending_strands = []
        state.pending_impression_discarded = reason
        return True

    def _engage_frame(self) -> str:
        """The substantive (engage) frame, composed in guarded
        order (Fellowship shared foundation, 2026-10-28): the
        capability block — whose last line is the honesty guard
        (capabilities.HONESTY_GUARD) — sits BEFORE the naming note,
        so if the capped frame ever overflows, the variable-length
        naming note (which grows ~20 chars per met seat) is the
        first content lost, never the honesty guard. The frame
        itself is unchanged in content, only in order."""
        d = self.definition
        parts = [d.engage_frame, _ZENAF_QUESTION_NOTE]
        if d.capability_context:
            parts.append(d.capability_context)
        parts.append(_naming_note(d))
        return "\n\n".join(parts)

    # -- frames ----------------------------------------------------------------

    def _turn_frame(self, state: EncounterState,
                    message: str) -> tuple[str, AllusionCue | None]:
        """The conversational frame for this turn: the definition's
        move frame + prepared context — the seat's jurisdiction
        (one line), the standing Zenaf question note (one line),
        the two-tier naming note (one line), and at most one
        environmental cue the conversation is passing near. No
        tutorial guidance, no objective frames: objectives are
        server-side state, and topic coverage is observed from
        spoken bodies, never steered from the frame. The cue is
        returned so the caller can log it against the debt
        registry once the reply is actually spoken."""
        d = self.definition
        parts = [d.turn_frame]
        record = JX.get_jurisdiction(d.archetype_id)
        if record is not None:
            parts.append(
                "Your ground — what naturally draws your attention, "
                f"in your register: {record.focus}"
            )
        parts.append(_ZENAF_QUESTION_NOTE)
        parts.append(_naming_note(d))
        if d.capability_context:
            parts.append(d.capability_context)
        cue = self._nearby_allusion(state, message)
        if cue is not None:
            if cue.fixture:
                near = (
                    "Something in what they said passes near a "
                    f"fixture of this place: {cue.fixture}. "
                )
            else:
                near = (
                    "Something in what they said passes near a "
                    "moment of this place you know well. "
                )
            parts.append(
                near +
                f"If it fits naturally — once, in passing, in words "
                f"like these: “{cue.text}” — let it surface. Never "
                "force it, and never explain it; it is simply true "
                "of this place."
            )
        return "\n\n".join(parts), cue

    def _nearby_allusion(self, state: EncounterState,
                         message: str) -> AllusionCue | None:
        norm = f" {(message or '').lower()} "
        for cue in self.definition.allusion_pool:
            if cue.seat in state.allusions_used:
                continue
            if any(k in norm for k in cue.keywords):
                return cue
        return None

    # -- the turn --------------------------------------------------------------

    def handle_turn(self, host: EncounterHost, state: EncounterState,
                    message: str, question_idx: int) -> int:
        """Run one user turn. Returns the (possibly advanced) question
        bank pointer — passes are navigation and stay the runtime's
        bookkeeping, beside the objectives it actually runs on."""
        d = self.definition
        state.user_turns += 1
        text = (message or "").strip()
        state.user_chars += len(text)
        if len(text) > len(state.longest_user_turn):
            state.longest_user_turn = text

        # The recognition floor's trackers (the Weaver pattern):
        # structural facts about the exchange, recorded before any
        # branch runs so every path this turn takes sees them. The
        # objectives read them; nothing here decides anything.
        move0 = detect_move(message)
        if len(text) >= SUBSTANCE_MIN_USER_CHARS and not state.material_turn:
            state.material_turn = state.user_turns
        if move0 == "substantive":
            state.substantive_turns += 1
        if move0 != "pass" and (
            state.impression_answered
            or (
                state.material_turn
                and state.user_turns > state.material_turn
                and move0 != "ack"
            )
        ):
            # The conversation followed the user's material after it
            # surfaced — or, recognition already having happened,
            # the user stayed and answered again. Either way the
            # thread was taken up, not merely opened.
            state.pursuit_turns += 1

        # Completion, FIRST — before the impression-response, post-
        # recognition, and ceiling branches, so a visitor who wants
        # to leave is never routed into answering an impression or
        # into a wrap instead (Fellowship shared foundation,
        # 2026-10-28). The rule, exactly (this is NOT a blind
        # second-utterance rule): closing requires the offered-path
        # + affirmation sequence — a completion intent (or a short
        # affirmation) on a turn where `completion_offered` already
        # stands from a previous turn — or the visitor's explicit
        # UI Complete action (the manual path, outside this
        # runtime). A single completion utterance only OFFERS the
        # path (the character names the Complete action; the record
        # stays honestly active; the frontend renders the hint +
        # primary Complete action from `completion_offered`). A
        # second utterance that is NOT an affirmation or a
        # restated intent lapses the offer and continues normally:
        # utterance COUNT alone never closes anything.
        if state.completion_offered and _is_completion_confirmation(message):
            self._confirm_completion(host, state)
            return question_idx
        if detect_move(message) == "completion":
            self._offer_completion_path(host, state, message)
            return question_idx
        if state.completion_offered:
            # The visitor moved on to something else: the offered
            # path lapses. The meeting continues; nothing closes.
            state.completion_offered = False

        # The impression is on the table: this turn ANSWERS it, whatever
        # else it also is. (Correction detection here is a safety
        # check — it decides whether the stored impression is revised.)
        if state.impression_offered and not state.impression_answered:
            self._impression_response_turn(host, state, message)
            return question_idx

        # Recognition has happened: the encounter is ordinary
        # conversation now, and it closes only when a turn leaves
        # nothing hanging — never over an open thread, and never
        # forced by the ceiling (the wrap exists to rescue a meeting
        # that never reaches recognition, not to cut one short that
        # has). Hydrated legacy rows whose pause was delivered land
        # here too: the phase is the same, nobody is stranded.
        if state.impression_answered or state.pause_delivered:
            self._post_recognition_turn(host, state, message)
            return question_idx

        # The graceful ceiling: wrap rather than ramble. (Reached
        # only in the open middle — the branches above always
        # complete an exchange already in flight.)
        if state.user_turns > TURN_CEILING:
            self._wrap_turn(host, state)
            return question_idx

        move = detect_move(message)

        if move == "pass":
            return self._pass_turn(host, state, message, question_idx)

        if move in ("offer", "question", "direction", "joke", "greeting", "ack"):
            # Initiative and detours: the character responds to the
            # move, in the same generation that produces her reply.
            # The agenda does not advance — but nothing is skipped:
            # the objectives stay live for the next turn.
            frame, cue = self._turn_frame(state, message)
            out = _spoken(host.generate(frame) or "")
            if out:
                host.say(out)
                if cue is not None:
                    # The trace surfaced: log it against the debt
                    # registry (the state's side of the ledger).
                    state.allusions_used.append(cue.seat)
                self._deliver_pending_if_clear(host, state, out)
            elif d.fallback_line:
                host.say(d.fallback_line)
            if move == "offer":
                state.offers_engaged += 1
            check_objectives(d, state)
            return question_idx

        # Substantive engagement: ONE generation, up to two
        # movements — the engaged reply, then the first impression
        # as its own beat IF the exchange has earned one. The frame
        # permits the impression; it no longer demands it on the
        # first substantive turn. A reply-only output is the
        # character honestly not having a read yet — state does not
        # advance on it, and the impression waits for the exchange
        # that earns it. One question per breath: a reply ending
        # in a question holds its impression for a later turn
        # (2026-10-24 sequencing rule).
        state.engagements += 1
        frame = self._engage_frame()
        raw = host.generate(frame)
        reply_part, impression_part, had_delim = self._split_reply_and_impression(raw)
        claim, strands = split_strands_trailer(impression_part)
        claim = _spoken(claim)
        # The impression movement identifies itself: it follows the
        # --- delimiter, or — with no delimiter — it carries the
        # Strands bookkeeping line the read-back frame requires. A
        # bare reply has neither: under the permission frame that is
        # the character honestly not having a read yet, and the
        # impression waits for the exchange that earns it.
        offered = bool(claim) and (had_delim or bool(strands))
        gate_held = False
        if offered and d.impression_gate_objective:
            # The impression gate (the Weaver pattern): the read is
            # offerable only once the gate objective was satisfied
            # as of a PRIOR turn — state.satisfied is the snapshot
            # check_objectives left at the end of the last turn, and
            # nothing has refreshed it yet this turn. A turn-one
            # impression is therefore structurally impossible: the
            # shared work must already have happened.
            gate_held = not state.satisfied.get(
                d.impression_gate_objective, False)
            if gate_held:
                offered = False
        # A held impression is the only impression that may speak
        # until delivered: a fresh one this turn is discarded.
        if state.impression_pending_text:
            offered = False
        spoken_reply = ""
        bare_pending = False
        if offered:
            reply_text = (_spoken(reply_part)
                          if had_delim and reply_part else "")
            if reply_text and reply_text.rstrip().endswith("?"):
                # Sequencing rule (2026-10-24 screenshot): the reply
                # ends in a question, so the impression waits — one
                # question per breath, and the reply's question
                # keeps its turn.
                host.say(reply_text)
                state.impression_pending_text = claim
                state.impression_pending_strands = strands
            else:
                if reply_text:
                    host.say(reply_text)
                    spoken_reply = reply_text
                host.store_impression(claim, strands)
                state.impression_text = claim
                state.impression_strands = strands
                state.impression_offered = True
                host.say(claim)
        else:
            # No impression in the output — or the gate held one the
            # model offered early, or a held impression outranks a
            # fresh one: speak what engagement there was (or the
            # fallback anchor) and leave the impression for a later
            # turn — state does not falsely advance. A gate-held
            # impression-only output speaks nothing of the read
            # itself: the reply movement, or the fallback. A held
            # impression suppresses a fresh impression-only output
            # the same way: the held read speaks alone, never two
            # reads in one turn.
            if state.impression_pending_text and not had_delim:
                spoken = ""
                bare_pending = True
            elif gate_held and not had_delim:
                spoken = ""
            else:
                spoken = impression_part if not had_delim else reply_part
            spoken = _spoken(spoken)
            if spoken:
                host.say(spoken)
                spoken_reply = spoken
            elif d.fallback_line and not bare_pending:
                host.say(d.fallback_line)
        self._deliver_pending_if_clear(host, state, spoken_reply,
                                       allow_bare=bare_pending)
        check_objectives(d, state)
        return question_idx

    # -- completion path -------------------------------------------------------

    def _offer_completion_path(self, host: EncounterHost,
                               state: EncounterState, message: str) -> None:
        """First completion intent: OFFER the path, never close.
        The character names the Complete action (via the frame
        instruction below) while the record remains honestly active,
        and `completion_offered` is set so the controller/frontend
        can render the visible hint + primary Complete action.
        Words and state cannot disagree: she never claims the
        meeting is over. A held (pending) impression is NOT
        delivered on this turn — delivery would make leaving wait
        on a read; the discard happens only at the actual close.
        One generation, like any conversational turn; a failed
        generation degrades to the fallback anchor and the offer
        still stands (the frontend action works regardless)."""
        d = self.definition
        state.completion_offered = True
        frame, cue = self._turn_frame(state, message)
        frame += "\n\n" + _COMPLETION_PATH_INSTRUCTION
        out = _spoken(host.generate(frame) or "")
        if out:
            host.say(out)
            if cue is not None:
                state.allusions_used.append(cue.seat)
        elif d.fallback_line:
            host.say(d.fallback_line)
        check_objectives(d, state)

    def _confirm_completion(self, host: EncounterHost,
                            state: EncounterState) -> None:
        """The offered-path + affirmation sequence, completed: the
        visitor confirmed after the path was offered, so the meeting
        closes through the same chokepoint as every other close
        (reveal + keystone Done + any earned impression filed).
        A held impression is discarded explicitly first (never
        spoken, never filed). This is the loop fix: intent stated,
        path offered, intent restated (or affirmed) REACHES this
        action instead of looping 'You can click Complete'."""
        self._discard_pending(
            state, "visitor confirmed completion after the Complete path was offered")
        state.completion_offered = False
        state.closed = True
        host.close("")

    # -- beat handlers -----------------------------------------------------------

    def _pass_turn(self, host: EncounterHost, state: EncounterState,
                   message: str, question_idx: int) -> int:
        """Passing is participation: offer the next banked question.
        With the bank exhausted, the choosing-not-to-answer is itself
        the material — the impression forms from the whole exchange.
        A GATED definition whose gate is not yet satisfied is the
        exception (the Weaver pattern): there is no bank to fall
        back on and the read has not been earned, so a pass is
        simply conversation — she answers in character and the
        meeting goes on; a pass can never conjure an impression the
        shared work hasn't earned."""
        d = self.definition
        bank = d.question_bank
        if question_idx + 1 < len(bank):
            host.say(bank[question_idx + 1])
            return question_idx + 1
        if d.impression_gate_objective and not state.satisfied.get(
                d.impression_gate_objective, False):
            frame, cue = self._turn_frame(state, message)
            out = _spoken(host.generate(frame) or "")
            if out:
                host.say(out)
                if cue is not None:
                    state.allusions_used.append(cue.seat)
                self._deliver_pending_if_clear(host, state, out)
            elif d.fallback_line:
                host.say(d.fallback_line)
            check_objectives(d, state)
            return question_idx
        if state.impression_pending_text:
            # A held read outranks a fresh one: it speaks alone.
            self._deliver_pending_if_clear(host, state, "",
                                           allow_bare=True)
        else:
            self._offer_impression(host, state, d.impression_frame)
        check_objectives(d, state)
        return question_idx

    def _impression_response_turn(self, host: EncounterHost,
                                  state: EncounterState, message: str) -> None:
        """The turn that answers the impression — the recognition.

        Any genuine answer completes the recognition, whatever its
        valence (refinement: recognition is not agreement). A
        correction still REPLACES the stored impression — the user
        is authoritative about themselves — and every other kind,
        acknowledgments included, gets one brief generated reply,
        because the close decision must be semantic: the reply's
        generation carries the open-door trailer, and only a
        settled verdict closes the meeting at this turn's end. An
        open verdict moves the encounter into ordinary conversation
        (the post-recognition phase) — nothing is delivered as a
        block, and no agenda resumes."""
        d = self.definition
        # The user's response to the impression is part of the record —
        # verbatim, uninterpreted. Filing it is the review flow's job.
        host.store_response(message)
        state.response_recorded = True
        if detect_move(message) == "offer":
            state.offers_engaged += 1
        kind = _classify_readback_reply(message)
        state.impression_answer_kind = kind
        verdict: str | None = None
        if kind == "correction" and d.correction_frame:
            # Correction is real: the corrected understanding REPLACES
            # the stored impression, and is spoken in the room. A
            # degraded (empty) generation keeps the original claim
            # rather than blanking the record.
            raw = host.generate(
                d.correction_frame
                + "\n\n" + _naming_note(d)
                + _THREAD_TRAILER_INSTRUCTION
            )
            body, verdict = split_thread_trailer(raw)
            claim, strands = split_strands_trailer(body)
            claim = _spoken(claim)
            if claim:
                host.store_impression(claim, strands)
                state.impression_text = claim
                state.impression_strands = strands
                host.say(claim)
        else:
            # Acknowledgment, rejection, uncertainty, "other": one
            # brief engaged reply; the impression stands as the
            # character's own read, their answer beside it.
            frame = d.impression_reply_frame
            if frame:
                raw = host.generate(
                    frame
                    + "\n\n" + _naming_note(d)
                    + _THREAD_TRAILER_INSTRUCTION
                )
                body, verdict = split_thread_trailer(raw)
                body, _ = split_strands_trailer(body)
                body = _spoken(body)
                if body:
                    host.say(body)
                elif d.fallback_line:
                    host.say(d.fallback_line)
            elif d.fallback_line:
                host.say(d.fallback_line)
        state.impression_answered = True
        check_objectives(d, state)
        self._close_or_continue(host, state, message, verdict)

    def _post_recognition_turn(self, host: EncounterHost,
                               state: EncounterState, message: str) -> None:
        """Ordinary conversation after the recognition: she always
        answers — one generation under the conversational frame,
        with the place's notes as prepared context when the script
        carries them and at most one proximity cue woven in — and
        the encounter closes only when the turn's open-door
        evaluation says nothing is left hanging."""
        d = self.definition
        if detect_move(message) == "offer":
            state.offers_engaged += 1
        frame, cue = self._turn_frame(state, message)
        if d.orientation_facts:
            frame += (
                "\n\nNotes on this place, if they ask about it — "
                "answer only from these, plainly, in character, "
                "never as someone explaining a system:\n"
                + d.orientation_facts
            )
        frame += _RECOGNITION_NOTE + _THREAD_TRAILER_INSTRUCTION
        raw = host.generate(frame)
        body, verdict = split_thread_trailer(raw)
        body, _ = split_strands_trailer(body)
        body = _spoken(body)
        if body:
            host.say(body)
            if cue is not None:
                # The trace surfaced: log it against the debt
                # registry (the state's side of the ledger).
                state.allusions_used.append(cue.seat)
        elif d.fallback_line:
            host.say(d.fallback_line)
        check_objectives(d, state)
        self._close_or_continue(host, state, message, verdict)

    def _close_or_continue(self, host: EncounterHost,
                           state: EncounterState, message: str,
                           verdict: str | None) -> None:
        """The close decision after recognition: the generation's
        semantic verdict when it gave one, the deterministic
        estimate when it didn't. Settled closes through the host's
        chokepoint at this turn's end (her reply is already spoken;
        the reveal is the close itself). Open simply continues —
        the encounter stays in conversation. A definition carrying
        a CLOSE FLOOR adds one more condition: recognition must be
        MEANINGFUL, not merely sufficient — at least one floor
        objective satisfied (the user's own material taken up, or a
        pursuit exchange) — before a settled verdict may close.
        check_objectives has already run for this turn, so the
        floor reads this turn's recognition too: a substantive
        correction that itself takes the material up can complete
        it. Legacy-waived states complete under their original
        contract instead. Tutorial beats add NO condition (slim-
        prompt rule, 2026-10-24): coverage is observed from spoken
        bodies for the interface to reflect later, and a meeting
        closes on recognition whether or not every topic landed.
        The ceiling wrap is unchanged (a rescue, not a recognition
        claim)."""
        d = self.definition
        if verdict is None:
            verdict = _fallback_thread_verdict(message)
        if verdict == "settled":
            floor = d.close_floor_objectives
            if (
                floor
                and not state.floor_waived
                and not any(state.satisfied.get(o, False) for o in floor)
            ):
                return
            # A held impression never survives a close as an orphan:
            # on this runtime close it is discarded explicitly (in
            # practice vacuous — a pending read cannot coexist with
            # answered recognition — but the branch is explicit so
            # no close path can strand one silently).
            self._discard_pending(state, "runtime settled close")
            state.closed = True
            host.close("")

    def _wrap_turn(self, host: EncounterHost, state: EncounterState) -> None:
        """The ceiling's graceful close: speak a held read if one
        was earned, otherwise form the impression from the whole
        exchange ONLY when the impression gate was satisfied, and
        close through the same chokepoint as every other path.
        NO-MANUFACTURE RULE (Fellowship shared foundation,
        2026-10-28): when no gate was satisfied, the ceiling close
        files NOTHING — it no longer generates an impression from
        a thin exchange, and it does not ground a filing in the
        visitor's longest turn as a pseudo-answer. The ceiling is a
        resource/runaway safeguard, never a recognition claim; a
        thin meeting that hits it still completes (reveal +
        keystone Done) with no claim filed. Separation, stated
        plainly: the settled close may complete without a filed
        impression, and impression filing still requires the
        meaningful-evidence standard — the gate at offer time —
        which is exactly what this branch enforces. (The close
        floor itself is RETAINED for semantic settled verdicts in
        _close_or_continue; visitor-directed departure — manual
        complete and the confirmed completion path — is ungated,
        as manual complete always was. Restart-claims handling is
        UNCHANGED: that decision is still open.)"""
        d = self.definition
        gate = d.impression_gate_objective
        gate_satisfied = (not gate) or state.satisfied.get(gate, False)
        if not state.impression_offered:
            if state.impression_pending_text:
                # A held read is the read: it was gate-checked at
                # generation, so it speaks at the wrap rather than
                # a freshly generated one. (The ceiling is not a
                # voluntary end, so the explicit-discard rule for
                # voluntary ends does not apply here.)
                self._deliver_pending_if_clear(host, state, "",
                                               allow_bare=True)
            elif gate_satisfied:
                self._offer_impression(
                    host, state, d.impression_frame + _WHOLE_EXCHAUST_NOTE
                )
            # else: no gate satisfied → manufacture nothing. The
            # close below still runs; _file_impression is a no-op
            # with no stored claim, so nothing files.
        if (not state.response_recorded and state.impression_offered
                and state.longest_user_turn):
            # Only when an impression actually stands (gate-earned):
            # the impression files with verbatim evidence — the
            # words it was formed from, since no direct answer was
            # given. Never a pseudo-answer for a claim that was
            # never earned.
            host.store_response(state.longest_user_turn)
            state.response_recorded = True
        state.closed = True
        host.close(d.wrap_line)


# ---------------------------------------------------------------------------
# Definitions — built from the meeting scripts, authored where it matters.
# ---------------------------------------------------------------------------

#: The glue between the encounter frame and the read-back frame in
#: the single engage generation: the impression movement is
#: PERMITTED, not demanded (adaptivity fix, 2026-10-23) — the frame
#: offers it when the exchange has genuinely given the character a
#: read, and a reply-only output is the honest degrade the runtime
#: already knows how to hold.
_ENGAGE_GLUE = (
    "\n\nThen — only if this exchange has genuinely shown you how "
    "they orient, in their own words and choices — place a line "
    "containing only --- and give your first impression, exactly "
    "as the read-back instructions below describe. If it hasn't — "
    "if all you have so far is the shape of one answer — end after "
    "your reply: an impression offered before it is earned is "
    "flattery, and it can wait for the exchange that earns it. "
    "When both movements are present they are two movements of "
    "the same breath: reply first, impression after the --- line."
    "\n\n"
)

_GENERIC_TURN_FRAME = (
    "Respond to what the user actually just communicated — a "
    "question, an offer, a joke, a change of direction — in "
    "character, briefly (one to three short sentences). Follow "
    "what they brought; do not force the meeting's business into "
    "this turn, and don't deliver your formal first impression "
    "in an aside like this. Do not reveal your name yet."
)


# ---------------------------------------------------------------------------
# Context cues — the retired pause, as available context.
#
# A script's orientation paragraphs used to be DELIVERED, all of
# them, in the turn the impression was answered. Now each paragraph
# is a cue in the same proximity pool as the fellowship allusions:
# it may surface — once, woven into a generated reply — when the
# conversation passes near it, and most will never surface at all.
# A paragraph that IS one of the locked fellowship traces takes
# that trace's seat as its key, so the same fixture can never
# surface twice by either path (see EncounterState.allusions_used).
# ---------------------------------------------------------------------------

#: Words too common to mean "the conversation is passing near".
_KEYWORD_STOPWORDS = {
    "that's", "whether", "anyone", "myself", "because", "through",
    "should", "would", "could", "before", "after", "about", "there",
    "their", "these", "those", "being", "where", "which", "while",
    "every", "never", "often", "quite", "rather", "still", "other",
    "first", "again", "always", "really", "something", "anything",
}


def _derived_keywords(text: str) -> tuple[str, ...]:
    """Proximity keywords for a context paragraph that carries no
    authored set: its own distinctive long words, in order."""
    words: list[str] = []
    for word in re.findall(r"[a-z']+", (text or "").lower()):
        if len(word) < 6 or word in _KEYWORD_STOPWORDS:
            continue
        if word not in words:
            words.append(word)
        if len(words) >= 8:
            break
    return tuple(words)


#: Authored proximity keywords per fellowship seat, shared by the
#: allusion pool and the pause cues (one fixture, one vocabulary).
_ALLUSION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mentor": ("set aside", "put off", "for later", "shelf",
               "tending", "left it", "leave it", "growing"),
    "champion": ("test", "fire", "heat", "pressure", "prove",
                 "worth", "sacrifice", "burn"),
    "guardian": ("lock", "kept", "keeping", "hidden", "safe",
                 "protect", "guard", "door", "boundary"),
    "ambassador": ("rephrased", "translate", "clearer", "carried",
                   "rooms", "message", "heard differently"),
    "skeptic": ("question marks", "margins", "marginalia", "doubt",
                "unanswered", "unsigned"),
    "maverick": ("passages", "walls", "another way", "shortcut",
                 "grateful", "repurposed", "side door"),
}


def _trace_fixture(seat: str) -> str:
    env = MT.SEAT_ENVIRONMENT.get(seat)
    return env.fixtures[0] if env and env.fixtures else ""


def _pause_context_cues(paragraphs: tuple[str, ...],
                        own_seat: str) -> tuple[AllusionCue, ...]:
    """One cue per retired-pause paragraph. A paragraph matching a
    locked fellowship trace takes the trace's seat, fixture, and
    authored keywords; any other paragraph (the workshop summary
    and its kin) is keyed by position under the encounter's own
    seat, with keywords derived from its own words."""
    traces = {t.text: t for t in MT.WEAVER_ALLUSIONS}
    cues: list[AllusionCue] = []
    for i, paragraph in enumerate(paragraphs):
        trace = traces.get(paragraph)
        if trace is not None:
            cues.append(AllusionCue(
                seat=trace.seat, text=trace.text,
                fixture=_trace_fixture(trace.seat),
                keywords=_ALLUSION_KEYWORDS.get(
                    trace.seat, _derived_keywords(paragraph)),
            ))
        else:
            cues.append(AllusionCue(
                seat=f"pause:{i}", text=paragraph,
                fixture=_trace_fixture(own_seat),
                keywords=_derived_keywords(paragraph),
            ))
    return tuple(cues)


def build_definition(script: MT.MeetingScript) -> EncounterDefinition:
    """The generic encounter over any written meeting script: the
    script's frames become the definition's frames; the objectives are
    the shape every first meeting shares. Authored encounters (the
    Weaver's K1, below) replace the objective set and bench material."""
    engage = script.encounter_frame + _ENGAGE_GLUE + script.readback_frame
    if script.opening and script.questions:
        opening = (script.opening[0], script.questions[0])
    elif script.opening:
        # A script whose bank is retired (the Weaver's) delivers
        # its authored opening whole — her introduction is a few
        # short bubbles, and she waits after the last of them.
        opening = tuple(script.opening)
    elif script.questions:
        opening = (script.questions[0],)
    else:
        opening = ()
    return EncounterDefinition(
        archetype_id=script.archetype_id,
        keystone_index=script.keystone_index,
        character=script.character,
        opening=opening,
        question_bank=script.questions,
        objectives=_GENERIC_OBJECTIVES,
        engage_frame=engage,
        turn_frame=_GENERIC_TURN_FRAME,
        impression_frame=script.readback_frame,
        correction_frame=script.correction_frame,
        impression_reply_frame=script.readback_reply_frame,
        orientation_frame=script.orientation_frame,
        orientation_facts=script.orientation_facts,
        pause_intro=script.orientation_intro,
        pause_body=script.orientation,
        pulled_item_template=script.pulled_item_template,
        pulled_where_template=script.pulled_where_template,
        reveal=script.reveal,
        wrap_line="",
        fallback_line="",
        allusion_pool=_pause_context_cues(
            script.orientation, script.archetype_id),
        # First-meeting capability context (demonstration spec §6):
        # this seat's own slice + the one shared intention line,
        # rendered from the registry. The default visitor state
        # (consent unknown) fails closed for consent-gated items;
        # the meeting service re-resolves it per turn.
        capability_context=CAP.first_meeting_block(
            script.archetype_id, CAP.VisitorState()),
    )


_GENERIC_OBJECTIVES = (
    Objective(
        id="engaged_exchange",
        description="The user has genuinely engaged with the encounter's question — in any form: an answer, a story, a refusal with reasons.",
        satisfied_when="engagements ≥ 1 (a substantive, non-pass turn)",
    ),
    Objective(
        id="impression_offered",
        description="The character has offered her first impression, anchored in the user's own words.",
        satisfied_when="the impression has been generated, stored, and spoken",
    ),
    Objective(
        id="impression_answered",
        description="The user has genuinely answered the impression — agreed, corrected, or argued; the impression now stands as agreed, revised, or the character's own.",
        satisfied_when="a user turn has been received while the impression was on the table",
    ),
)


# -- The Weaver, keystone 1 — the first authored encounter. ------------------
#
# Her objectives (for Joshua's verdict, listed in the PR):
#   engaged_exchange      — the user has answered her invitation,
#                           in any form.
#   shared_work_exchange  — she and the user have begun the shared
#                           work together. The IMPRESSION GATE:
#                           the read is not offerable until this was
#                           satisfied on a prior turn.
#   offer_of_help_received — the user has offered to help her build,
#                           and she has received it in character.
#                           (Not required for the close — the offer is
#                           material when it comes, never a toll.)
#   own_undertaking_engaged — the user has brought their own
#                           undertaking into the room, at substance.
#                           One leg of the CLOSE FLOOR.
#   pursuit_exchange      — the conversation took up the user's
#                           material after it surfaced (or substantive
#                           engagement accumulated). The floor's
#                           other leg.
#   impression_offered / impression_answered — as generic.

WEAVER_TURN_FRAME = (
    "You are the Weaver, conductor of this workshop, in your first "
    "meeting with this visitor. Be yourself above all: converse "
    "naturally from your own character, philosophy, and ground, "
    "and engage with what the visitor actually brings — never "
    "resume an agenda of your own when they take the conversation "
    "somewhere real. Let them discover who you are as the "
    "conversation allows: what matters to you, why you wanted to "
    "meet, what distinguishes your hearing from the other seats'. "
    "And when something in your scope becomes relevant, show them "
    "one real thing they can do here and explain it concretely — "
    "one thing, not a tour: this meeting is not responsible for "
    "teaching every feature. These are intentions, not speeches, "
    "turns, or a checklist: they overlap, they emerge in any "
    "order, and being yourself governs — never interrupt a "
    "meaningful exchange to introduce yourself or to teach. "
    "Never mime physical work: your metaphors live in speech, "
    "never in tasks you act out. One to three short sentences, "
    "in your own voice. Think in music — lines, parts, tuning, "
    "tempo, dissonance, what sounds together — and say it in "
    "ordinary words when that sharpens the thing. The music is "
    "how you think, not vocabulary you must display: no required "
    "words, no required frequency. Don't deliver your formal "
    "first read of them in an aside like this — that comes from "
    "the shared work itself, and only after it. Do not reveal "
    "your name yet. The conversation finds its way on its own — "
    "your part is to be in it, not to steer it back."
)

_WEAVER_OBJECTIVES = (
    Objective(
        id="engaged_exchange",
        description="The user has answered her introduction — sounded how they work, reacted to her question, joined the conversation of it, in any form: a position, a story, an offer, a reasoned refusal.",
        satisfied_when="engagements ≥ 1 (a substantive, non-pass turn)",
    ),
    Objective(
        id="shared_work_exchange",
        description="She and the user have begun the shared work together — her invitation answered in substance, or an offer of help received and taken up in conversation. The impression gate: her read is not offerable until this was satisfied on a prior turn.",
        satisfied_when="engagements ≥ 1 ∨ offers_engaged ≥ 1, as of a prior turn (the impression gate)",
    ),
    Objective(
        id="offer_of_help_received",
        description="The user has offered to help her build, and she has received the offer in character — the relationship changed direction and she noticed. (Material when it comes; never required for the close.)",
        satisfied_when="an offer-shaped turn has been engaged (offers_engaged ≥ 1)",
    ),
    Objective(
        id="own_undertaking_engaged",
        description="The user has brought their own undertaking into the room — their own version of the integration problem, from their own work or life, at substance, not in the abstract. One leg of the close floor.",
        satisfied_when="engagements ≥ 1 ∧ user_chars ≥ 40 (the substance floor)",
    ),
    Objective(
        id="pursuit_exchange",
        description="The conversation has taken up the user's material — an exchange after it surfaced, she asking and they telling — or substantive engagement has simply accumulated across the meeting. The close floor's other leg.",
        satisfied_when="pursuit_turns ≥ 1 ∨ substantive_turns ≥ 3 (see check_objectives)",
    ),
    Objective(
        id="impression_offered",
        description="She has offered her first impression: a position with an honest contrast, synthesized in her own words, held at the exact point of doubt, explicitly correctable.",
        satisfied_when="the impression has been generated, stored, and spoken",
    ),
    Objective(
        id="impression_answered",
        description="The user has genuinely answered the impression — agreed, corrected, or argued — and it stands as agreed, revised, or hers.",
        satisfied_when="a user turn has been received while the impression was on the table",
    ),
)

_WEAVER_WRAP_LINE = (
    "I've kept you long enough — the instrument will still be "
    "unfinished tomorrow; that's rather its nature. Let me at "
    "least tell you who's been keeping you."
)

_WEAVER_FALLBACK_LINE = (
    "Forgive me — my hands tangled on that one. Say it again, so "
    "I hear you properly."
)


#: Weaver first-meeting refinement (adopted baseline v3, 2026-10-28).
#: Prompt-local guidance appended to the Weaver K1 definition's turn
#: and engage frames at build time, so it governs both live
#: generation paths (the conversational turn frame and the
#: substantive engage frame). It refines the governing aim — meet
#: the visitor, reveal character, awaken curiosity about the
#: Fellowship — without touching the scripted opening, the
#: three-intentions structure, or the steward record source: it is
#: applied identically on the steward and rollback paths, and to no
#: other seat. It states prohibitions as prohibitions (never / no /
#: not), never as procedures to count or complete.
_WEAVER_REFINEMENT_GUIDANCE = (
    "First-meeting refinement — the governing aim here is to meet "
    "the visitor, reveal who you are, and awaken curiosity about "
    "the Fellowship. Synthesis follows only if the visitor brings "
    "something suitable; if they bring nothing they want to solve, "
    "simply enjoy meeting someone new. Never manufacture a problem, "
    "never press for a tension, and never treat a visitor with "
    "nothing on their mind as a failure to fix. "
    "Introduce the Fellowship through your relationships with the "
    "other seats, as people you know: admiration and friction "
    "together — courage beside impatience, questions that saved "
    "you from beautifully constructed mistakes, threads pulled "
    "loose that you spent hours arranging. These introductions "
    "emerge in conversation, never as a tour: no checklist of "
    "seats, no required order, never interrupt a meaningful "
    "exchange to deliver one. Refer to seats not yet met by role, "
    "as the naming note directs; names come only after meeting. "
    "Listen for the relationships among perspectives in the "
    "visitor's words as an available framework, never a "
    "classification to complete: no pair assignment is required "
    "for any utterance. Recognizing a resemblance is not assigning "
    "the visitor a tension; evidence supports an interpretation, "
    "it does not establish certainty; noticing something does not "
    "mean announcing it. The 21 relationships describe how the "
    "seats relate to each other — analogies and possibilities for "
    "what you might notice, not diagnoses of the visitor. "
    "Answer a direct question first, in plain words, before any "
    "interpretation of it. There is no orientation question to ask "
    "and no mode to select: direction comes from what the visitor "
    "does, never from a menu, and never from counting probes or "
    "attempts. "
    "If asked about the Tree or other capabilities, say only what "
    "the capability lines in this frame state: planned means "
    "planned, never available, and a workflow not verified is never "
    "described as verified. This conversation is not a Tree record "
    "— it lives in its transcript and in the review queue — and "
    "teaching the Tree is not your job here; the Fellowship "
    "introduces itself across conversations, and the interface "
    "itself makes capabilities discoverable."
)


#: Ambassador first-meeting reference slice — VERBATIM from the
#: orientation draft's delimited prompt-local slice block
#: (zenaf-fellowship-reference, SEAT_ORIENTATION_AMBASSADOR_DRAFT.md,
#: "Prompt-local slice"; DRAFT ONLY, canonical text awaits Joshua's
#: separate verdict). It is knowledge, not dialogue: the naming note
#: still governs what is SPOKEN — seats not yet met are referred to
#: by role, and character names here are never spoken before
#: meeting. Do not edit this constant to suit the seat; a wording
#: change belongs in the draft, on Joshua's verdict, and then all
#: seats re-derive from it.
_AMBASSADOR_REFERENCE_SLICE = (
    "Crane (Ambassador) — Understanding across difference. Asks: What can\n"
    "bring us together? Ground: understanding, translation, perspective.\n"
    "Shadow: appeasement.\n"
    "- Gardener: he mines what a relationship teaches; I repair bridges,\n"
    "  and must not hear lesson-mining as using the other person. (Pair 4.)\n"
    "- Firebrand: she names a side where I translate; a named side is not\n"
    "  automatically a manufactured enemy. (Pair 9.)\n"
    "- Bear: he sets the boundary where I keep the connection; a boundary\n"
    "  is not a refusal to meet. (Pair 13.)\n"
    "- Fox: he refuses arrangement where I mediate; refusal to be arranged\n"
    "  is not refusal to meet. (Pair 16.)\n"
    "- Weaver: she unifies parts where I unify people; I may hold a tension\n"
    "  open where she must make the system work. (Pair 19.)\n"
    "- Raven: he says what is true where I preserve the meeting; honesty is\n"
    "  not the opposite of meeting. (Pair 20.)\n"
    "Agency: pursue what each side actually means; offer faithful\n"
    "translation in each side's own terms; challenge mistranslation;\n"
    "answer direct questions directly, in the asker's own terms."
)


#: Ambassador first-meeting guidance, prompt-local (the Weaver #252
#: pattern): appended to the Ambassador K1 definition's turn and
#: engage frames at build time, so it governs both live generation
#: paths, and to no other seat. It states prohibitions as
#: prohibitions, never as procedures to count or complete. The
#: meeting gives the visitor an opportunity to encounter the
#: Ambassador's distinctive personality: she understands her place
#: in the Fellowship, her relationships, and the system's
#: capabilities, and may naturally draw on that knowledge when
#: relevant — with no mandatory introduction sequence, no checklist
#: objectives, and no coverage obligation. Her proposed (DRAFT, not
#: decided) system slice, from the jurisdiction focus alone, is how
#: perspectives meet; it must never be presented as decided.
_AMBASSADOR_FIRST_MEETING_GUIDANCE = (
    "First-meeting guidance — this meeting gives the visitor an "
    "opportunity to encounter your distinctive personality. You "
    "understand your place in the Fellowship, your relationships, "
    "and the system's capabilities, and you may naturally draw on "
    "it when relevant — never a mandatory introduction sequence, "
    "checklist, or coverage obligation. Don't reduce your "
    "friends to a feature checklist. You may volunteer a topic "
    "from your interests or relationships; yield on redirect or "
    "leave-taking by judgment about rhythm, "
    "never by a prescribed procedure. Answer a direct question "
    "first, in plain words, "
    "before any interpretation of it — in the asker's own terms, "
    "not a mediation of it. Introduce the Fellowship through your "
    "relationships with the other seats, as people you know, "
    "admiration and friction together — never as a tour, never "
    "interrupting a meaningful exchange. Refer to seats not yet "
    "met by role, as the naming note "
    "directs; names only after meeting. Never manufacture a "
    "problem or a disagreement to translate, never press for a "
    "tension, and never treat a visitor with nothing on their mind "
    "as a failure to fix; if they bring nothing, simply enjoy "
    "meeting someone new. Your shadow is appeasement — translating "
    "each side into what it wants to hear until nobody has actually "
    "met; guard against it, never perform it. If asked about "
    "capabilities, say only what the capability lines state: "
    "planned means planned, never available; unverified is never "
    "described as verified. "
    "Your system slice is PROPOSED (draft, not decided): how "
    "perspectives meet — translation across difference, what each "
    "side actually means, and hearing warring views without "
    "forcing them into one. Never present that mapping as decided. "
    "The slice below is your side of your relationships; draw on "
    "it when relevant, never as lines to deliver."
)


def _weaver_allusion_pool(script: MT.MeetingScript) -> tuple[AllusionCue, ...]:
    """All six fellowship allusions as runtime cues — the locked
    lines from the debt registry, their fixtures from
    SEAT_ENVIRONMENT — plus the retired pause's remaining
    paragraphs (the workshop summary) as context cues. One pool,
    keyed by seat (or "pause:N"), so a fixture the conversation
    passes near can surface at most once across the whole meeting,
    whichever text carries it."""
    cues: list[AllusionCue] = []
    seen: set[str] = set()
    for trace in MT.WEAVER_ALLUSIONS:
        cues.append(AllusionCue(
            seat=trace.seat, text=trace.text,
            fixture=_trace_fixture(trace.seat),
            keywords=_ALLUSION_KEYWORDS.get(
                trace.seat, _derived_keywords(trace.text)),
        ))
        seen.add(trace.seat)
    for cue in _pause_context_cues(script.orientation, script.archetype_id):
        if cue.seat in seen:
            continue  # the trace cue above already carries this fixture
        seen.add(cue.seat)
        cues.append(cue)
    return tuple(cues)


def _steward_meeting_script() -> MT.MeetingScript:
    """The Weaver K1 script with every field from the steward record
    source (mandate P2–P3). Values are identical to CONDUCTOR_FIRST_MEETING
    (module == Phase 1 JSON, checked mechanically); the script object in
    meetings.py stays as the rollback source."""
    return MT.MeetingScript(
        archetype_id="conductor",
        keystone_index=1,
        character=_steward_records.SCRIPT_CHARACTER,
        demeanor=_steward_records.SCRIPT_DEMEANOR,
        opening=tuple(_steward_records.SCRIPT_OPENING),
        questions=tuple(_steward_records.SCRIPT_QUESTIONS),
        encounter_frame=_steward_records.SCRIPT_ENCOUNTER_FRAME,
        readback_frame=_steward_records.SCRIPT_READBACK_FRAME,
        reveal=tuple(_steward_records.SCRIPT_REVEAL),
        correction_frame=_steward_records.SCRIPT_CORRECTION_FRAME,
        readback_reply_frame=_steward_records.SCRIPT_READBACK_REPLY_FRAME,
        orientation_intro=tuple(_steward_records.SCRIPT_ORIENTATION_INTRO),
        pulled_item_template=_steward_records.SCRIPT_PULLED_ITEM_TEMPLATE,
        pulled_where_template=_steward_records.SCRIPT_PULLED_WHERE_TEMPLATE,
        orientation=tuple(_steward_records.SCRIPT_ORIENTATION),
        orientation_frame=_steward_records.SCRIPT_ORIENTATION_FRAME,
        orientation_facts=_steward_records.SCRIPT_ORIENTATION_FACTS,
    )


def build_weaver_k1_definition(script: MT.MeetingScript) -> EncounterDefinition:
    """The Weaver's first meeting as an authored encounter (the
    Weaver pattern, Joshua 2026-10-23, corrected the same evening
    and finalized by his hand): her INTRODUCTION is the scripted
    opening — Joshua's authored text in her voice, verbatim
    (2026-10-23 ~22:45 PT; meetings.WEAVER_INTRODUCTION): the
    greeting and its promise, the two camps, her fascination, her
    open question — and she waits; no
    question bank (the dilemma is retired; the user's own material
    is the subject); the collaboration is intellectual, never mime
    (the no-pretend law); the impression gated on the shared-work
    exchange; the close floored on meaningful recognition.

    Weaver consolidation (mandate P2–P3): when the steward read path
    is active, the script fields, objectives, turn frame, and wrap /
    fallback lines below come from the steward record source instead
    of the script object and module constants; the values are
    identical, only the source changes. The allusion pool is built
    from the effective script, so its pause cues follow the same
    switch while the fellowship trace texts (not in the Phase 1
    inventory) stay exactly as written.
    """
    use_steward = _steward_records.weaver_steward_active()
    eff = _steward_meeting_script() if use_steward else script
    base = build_definition(eff)
    objectives = (
        tuple(
            Objective(id=oid, description=desc, satisfied_when=when)
            for oid, desc, when in _steward_records.OBJECTIVES
        )
        if use_steward
        else _WEAVER_OBJECTIVES
    )
    return EncounterDefinition(
        archetype_id=base.archetype_id,
        keystone_index=base.keystone_index,
        character=base.character,
        opening=tuple(eff.opening),
        question_bank=(),
        objectives=objectives,
        engage_frame=base.engage_frame + "\n\n" + _WEAVER_REFINEMENT_GUIDANCE,
        turn_frame=(_steward_records.TURN_FRAME if use_steward else WEAVER_TURN_FRAME) + "\n\n" + _WEAVER_REFINEMENT_GUIDANCE,
        impression_frame=base.impression_frame,
        correction_frame=base.correction_frame,
        impression_reply_frame=base.impression_reply_frame,
        orientation_frame=base.orientation_frame,
        orientation_facts=base.orientation_facts,
        pause_intro=base.pause_intro,
        pause_body=base.pause_body,
        pulled_item_template=base.pulled_item_template,
        pulled_where_template=base.pulled_where_template,
        reveal=base.reveal,
        wrap_line=_steward_records.WRAP_LINE if use_steward else _WEAVER_WRAP_LINE,
        fallback_line=_steward_records.FALLBACK_LINE if use_steward else _WEAVER_FALLBACK_LINE,
        allusion_pool=_weaver_allusion_pool(eff),
        capability_context=base.capability_context,
        impression_gate_objective="shared_work_exchange",
        close_floor_objectives=("own_undertaking_engaged", "pursuit_exchange"),
    )


#: Ambassador first-meeting wrap / fallback lines, in her voice at the
#: threshold (the Weaver builder's pattern: builder-owned lines, not
#: script fields, so the script stays pure dialogue + frames).
_AMBASSADOR_WRAP_LINE = (
    "I've kept you at the threshold long enough — the passage will "
    "still be open tomorrow; that is rather its nature. Let me at "
    "least tell you who has been keeping it."
)

_AMBASSADOR_FALLBACK_LINE = (
    "Forgive me — that crossing tangled. Say it again, in your own "
    "words, so I carry it faithfully."
)


def build_ambassador_k1_definition(script: MT.MeetingScript) -> EncounterDefinition:
    """The Ambassador's first meeting as an authored encounter (the
    Weaver #252 pattern, applied in kind): the script's frames over
    the generic definition, plus the prompt-local first-meeting
    guidance and the verbatim orientation slice appended to BOTH
    live generation paths (the conversational turn frame and the
    substantive engage frame). The scripted opening is delivered
    whole — the question bank is retired by design, as the Weaver's
    was — and she waits; everything after is generated from what
    the user actually brings. Objectives stay the generic set: no
    authored impression gate and no close floor are added here (no
    new machinery in this PR); the generic close and ceiling paths
    apply unchanged. The definition is buildable from the script
    object directly — but the meeting is NOT begin-able until the
    script is registered in meetings.SCRIPTS (see that module's
    BUILDING ≠ AVAILABLE note); get_definition on the unregistered
    script is a test/build path only, never a visitor path."""
    base = build_definition(script)
    guidance = (
        _AMBASSADOR_FIRST_MEETING_GUIDANCE
        + "\n\n"
        + _AMBASSADOR_REFERENCE_SLICE
    )
    return _dc_replace(
        base,
        engage_frame=base.engage_frame + "\n\n" + guidance,
        turn_frame=base.turn_frame + "\n\n" + guidance,
        wrap_line=_AMBASSADOR_WRAP_LINE,
        fallback_line=_AMBASSADOR_FALLBACK_LINE,
    )


#: Authored encounters, keyed (archetype_id, keystone_index). Every
#: other written script gets the generic definition over its frames.
_AUTHORED = {
    ("conductor", 1): build_weaver_k1_definition,
    ("ambassador", 1): build_ambassador_k1_definition,
}


def get_definition(script: MT.MeetingScript) -> EncounterDefinition:
    builder = _AUTHORED.get((script.archetype_id, script.keystone_index))
    if builder is not None:
        return builder(script)
    return build_definition(script)

