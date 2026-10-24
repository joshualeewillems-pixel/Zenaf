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
  - Tutorial beats, taught by the conversation itself (Joshua,
    2026-10-24): a seat's first meeting must also leave the user
    knowing what that seat is FOR — its terrain, what the visitor
    does with it, and why it wanted to meet — drawn from its
    feature-focus slice (meetings.SEAT_FEATURE_FOCUS) and kept in
    conversation/tutorial_beats.py. The beats ride the
    conversational frame as standing hopes, never a lecture block;
    steering pressure grows with the turns (early turns mostly
    follow, later turns steer more); after the seat's own patience
    of exchanges — tempo, part of register, never a global — the
    frame instructs an honest pivot — an owned direction change in
    the character's own words, never a prescribed sentence — that
    OWNS the direction change instead of faking a natural segue.
    Beat coverage is read from spoken bodies alone: each beat is
    facets (tutorial_beats), and a facet counts only on a connected
    mention in one spoken turn — a conservative proxy, not proof
    of understanding. Trailers ([[beat:<id>]]) are stripped as a
    backstop and never feed coverage. The close additionally
    requires every beat covered. The pivot NEVER satisfies the gate
    on its own — it redirects toward uncovered facets, and steering
    stays at maximum after it until they are covered; a pivot
    response can satisfy the gate only by covering facets with
    content, under the same rule as any other turn. The ceiling wrap
    bypasses the tutorial gate
    by design — a rescue, not a recognition claim, and by then the
    pivot has had every chance to fire.
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
import re
from dataclasses import dataclass, field
from typing import Protocol

from local_ai.council import jurisdictions as JX
from local_ai.council import meetings as MT

from . import tutorial_beats as TB
from .weave import strip_weave_markers

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
# Standing dialogue rules (2026-10-24 amendments C and E): direct
# questions about Zenaf, and two-tier naming for other seats. The
# naming note rides every generation path (it is a universal
# dialogue constraint); the Zenaf note rides the conversational
# Q&A paths (_turn_frame, engage path). Correction and impression
# movements are impression-focused by design, so they carry the
# naming note only — a Zenaf question bundled with a correction is
# answered on the next conversational turn, when the standing note
# is in frame.
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
    """Two-tier naming (amendment E): roles before meeting,
    character names after, seat by seat. Meeting a character is
    not developing or training that relationship: a first meeting
    unlocks the name, not a trained bond."""
    met = [a for a in definition.met_seats
           if a in _SEAT_CHARACTER_NAMES]
    if met:
        met_text = ", ".join(
            f"{_SEAT_CHARACTER_NAMES[a]} ({a})" for a in met)
        met_sentence = (
            f"Seats the visitor has already met — character names "
            f"may be used for these: {met_text}. "
        )
    else:
        met_sentence = (
            "The visitor has not met any other seat yet. "
        )
    return (
        "Names for other seats: refer to every other seat by "
        "its seat role — mentor, champion, guardian, maverick, "
        "ambassador, conductor, skeptic — roles are public and "
        "may be used before meeting. Use a seat's character name "
        "only after the visitor has met that seat, seat by seat. "
        + met_sentence +
        "Meeting a character is not developing or training that "
        "relationship: a first meeting unlocks the name, not a "
        "trained bond."
    )


#: Standing responsibility (amendment C): direct questions about
#: Zenaf get concrete answers. This is frame instruction, not a
#: detector — the detector below is only a safety net, because no
#: small vocabulary can recognize every way a visitor might ask.
_ZENAF_QUESTION_NOTE = (
    "When the visitor asks directly about Zenaf — what it is, "
    "what it does, what it can do, why it exists — answer "
    "concretely and directly first, before returning to their "
    "material: the relevant places, what they do, and what the "
    "visitor can actually do with them. Describe only "
    "functionality that exists; if something is planned or not "
    "built, say so plainly as planned, never as available. Do not "
    "substitute a metaphor, a general coaching statement, or a "
    "question about their goals for the answer."
)

#: Safety-net patterns for a direct Zenaf question. Small by design
#: and never the mechanism: the standing note above carries the
#: responsibility, and this only reinforces it when the wording is
#: unmistakable.
_ZENAF_QUESTION_PATTERNS = (
    r"what is (this|zenaf|it)\b",
    r"what do you do (here|on this site)\b",
    r"what (can|does) (this|zenaf|it) (do|offer)\b",
    r"how does (this|zenaf|it) work\b",
    r"what is this (app|site|thing)\b",
    r"what is zenaf\b",
)


def _asks_about_zenaf(message: str) -> bool:
    """True when the visitor's message unmistakably asks directly
    about Zenaf — safety net only (see _ZENAF_QUESTION_PATTERNS)."""
    text = (message or "").lower()
    return any(re.search(p, text) for p in _ZENAF_QUESTION_PATTERNS)


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


def detect_move(message: str) -> str:
    """The deterministic shape of the user's turn, for frame routing:
    "pass" | "offer" | "direction" | "joke" | "question" | "ack" |
    "greeting" | "substantive". Reading the move's MEANING is the
    character's job, in generation; this only picks the frame."""
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
    EncounterState in check_objectives, keyed by `id`. `frame` is the
    guidance woven into generation frames while the objective is live —
    the character is never told the objective exists as bookkeeping."""

    id: str
    description: str
    frame: str
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
    #: shape). The ceiling wrap bypasses it by design.
    impression_gate_objective: str = ""
    #: The close floor (the Weaver pattern): objective ids of which
    #: at least one must be satisfied for a settled verdict to close
    #: the meeting after recognition. Empty = no floor. Legacy
    #: hydration may waive it per-state (floor_waived).
    close_floor_objectives: tuple[str, ...] = ()
    #: The seat's dictionary, framed as AVAILABLE context under the
    #: three-layers rule (lexicon / reasoning / ordinary speech, the
    #: last the default — never a quota). Rides the conversational
    #: frame and, for authored encounters, the engage frame. "" for
    #: definitions whose seat does not consume a dictionary yet.
    dictionary_frame: str = ""
    #: Tutorial beats (the tutorial-beat mechanism, 2026-10-24):
    #: the seat's teaching checklist — terrain, involvement,
    #: why-meet — from conversation/tutorial_beats.py. Empty = no
    #: tutorial gate (the generic shape; only authored encounters
    #: carry beats so far).
    tutorial_beats: tuple[TB.TutorialBeat, ...] = ()
    #: Patience: exchanges before the honest pivot fires. Tempo,
    #: part of register — lives with the seat, never a global.
    #: 0 = no tutorial gate.
    tutorial_patience: int = 0
    #: Seats the visitor has already met (completed first meetings),
    #: as archetype ids — set by the meeting service per turn, never
    #: by the script. The naming rule (role before meeting, character
    #: name after, seat by seat) reads this list; empty means no
    #: other seat has been met yet, so every reference uses a role.
    met_seats: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# State — the encounter as the runtime remembers it.
# ---------------------------------------------------------------------------

#: The substance floor for "the user has brought their own undertaking
#: into the room": a real answer, not a token one.
SUBSTANCE_MIN_USER_CHARS = 40

#: The graceful ceiling: past this many user turns, the character wraps
#: ("I've kept you long enough") rather than letting the first meeting
#: ramble — the impression still files, exactly once.
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
    #: Tutorial-beat ledger (2026-10-24; facets, 2026-10-24
    #: amendment A): per-beat satisfied facet names, from the
    #: character's spoken bodies alone — trailers never feed it.
    #: tutorial_covered is the derived list of beats whose every
    #: facet is satisfied; together with the definition's beats it
    #: gates the close. tutorial_pivot_delivered records a spoken
    #: set-aside marker (detection heuristic for steering only,
    #: never a gate condition).
    tutorial_covered: list[str] = field(default_factory=list)
    tutorial_facets: dict[str, list[str]] = field(default_factory=dict)
    tutorial_pivot_delivered: bool = False
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
            "response_recorded": self.response_recorded,
            "pause_delivered": self.pause_delivered,
            "allusions_used": self.allusions_used,
            "tutorial_covered": self.tutorial_covered,
            "tutorial_facets": self.tutorial_facets,
            "tutorial_pivot_delivered": self.tutorial_pivot_delivered,
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
            "impression_text", "impression_strands", "response_recorded",
            "pause_delivered", "allusions_used",
            "tutorial_covered", "tutorial_facets",
            "tutorial_pivot_delivered", "closed",
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

#: Appended to the engage frame when several substantive exchanges
#: have passed without an impression: a nudge toward offering the
#: read if she honestly has one — guidance, never a trigger.
_IMPRESSION_NUDGE = (
    "\n\nNote: you have heard several real answers now and still "
    "offered no read of them. If you honestly can — even held "
    "lightly — let this reply carry your first impression after "
    "the --- line. If the exchange truly hasn't shown you how "
    "they orient yet, don't invent one; the reply alone is honest."
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
    return strip_weave_markers(TB.strip_beat_markers(body)).strip()


def _apply_tutorial_coverage(definition: EncounterDefinition,
                             state: EncounterState,
                             raw: str) -> str:
    """Read a generated reply's spoken body against the definition's
    tutorial facets, then strip any beat trailers.

    Coverage is trailer-independent (amendment A): every spoken body
    is evaluated against every not-yet-satisfied facet of every
    beat — a facet counts only on a connected mention in this body
    (tutorial_beats.facet_satisfied), and facets accumulate across
    turns. A beat enters tutorial_covered when every facet is
    satisfied. The pivot flag records a spoken set-aside marker for
    frame behavior (steering stays at maximum after a pivot) — it
    is NOT a gate condition. Returns the raw reply with beat
    trailers removed, so downstream trailer parsing (thread verdict,
    strands) never sees them; _spoken strips them again as a
    backstop, so they can never reach the user by any path.
    Stripping is unconditional: a trailer trailing a Strands line
    would otherwise break strand parsing even for definitions
    without a tutorial gate (split_strands_trailer reads from the
    end)."""
    if definition.tutorial_beats:
        spoken_body = _spoken(raw or "")
        for beat in definition.tutorial_beats:
            hits = TB.satisfied_facets(
                beat, spoken_body,
                set(state.tutorial_facets.get(beat.id, [])))
            if hits:
                state.tutorial_facets[beat.id] = sorted(hits)
            if (TB.beat_covered(beat, hits)
                    and beat.id not in state.tutorial_covered):
                state.tutorial_covered.append(beat.id)
        if TB.pivot_delivered_in(spoken_body):
            state.tutorial_pivot_delivered = True
    return TB.strip_beat_markers(raw or "")


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
        raw = _apply_tutorial_coverage(
            self.definition, state,
            host.generate(frame + "\n\n" + _naming_note(self.definition)))
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

    # -- frames ----------------------------------------------------------------

    def _turn_frame(self, state: EncounterState,
                    message: str) -> tuple[str, AllusionCue | None]:
        """The conversational frame for this turn: the definition's
        move frame + prepared context — the seat's jurisdiction,
        EVERY live objective's guidance as standing hopes (never
        announced, never sequenced: the objectives are the frame's
        only agenda, and the user steers), the standing Zenaf
        question note and two-tier naming note, and at most one
        environmental cue the conversation is passing near. The cue
        is returned so the caller can log it against the debt
        registry once the reply is actually spoken."""
        d = self.definition
        parts = [d.turn_frame]
        record = JX.get_jurisdiction(d.archetype_id)
        if record is not None:
            parts.append(
                "Your ground — what naturally draws your attention, "
                f"in your register: {record.focus} "
                f"(Metaphor family: {record.register.metaphor_family})"
            )
        if d.dictionary_frame:
            parts.append(d.dictionary_frame)
        guide = TB.tutorial_guidance(
            d.tutorial_beats,
            {k: set(v) for k, v in state.tutorial_facets.items()},
            state.user_turns, d.tutorial_patience,
            state.tutorial_pivot_delivered,
        )
        if guide:
            parts.append(guide)
        parts.append(_ZENAF_QUESTION_NOTE)
        if _asks_about_zenaf(message):
            parts.append(
                "Note: this message asks directly about Zenaf — "
                "answer it concretely first, per the standing note "
                "above."
            )
        parts.append(_naming_note(d))
        live = [o for o in d.objectives if not state.satisfied.get(o.id)]
        for obj in live:
            if obj.frame:
                parts.append(obj.frame)
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
            out = _spoken(_apply_tutorial_coverage(
                d, state, host.generate(frame) or ""))
            if out:
                host.say(out)
                if cue is not None:
                    # The trace surfaced: log it against the debt
                    # registry (the state's side of the ledger).
                    state.allusions_used.append(cue.seat)
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
        # that earns it.
        state.engagements += 1
        frame = d.engage_frame
        if state.engagements >= 3 and not state.impression_offered:
            # The soft nudge: guidance in the frame, not a trigger —
            # she may still honestly decline to invent a read.
            frame += _IMPRESSION_NUDGE
        frame += "\n\n" + _ZENAF_QUESTION_NOTE
        if _asks_about_zenaf(message):
            frame += (
                "\n\nNote: this message asks directly about "
                "Zenaf — answer it concretely first, per the "
                "standing note above."
            )
        frame += "\n\n" + _naming_note(d)
        raw = _apply_tutorial_coverage(d, state, host.generate(frame))
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
        if offered:
            if had_delim and reply_part:
                host.say(_spoken(reply_part))
            host.store_impression(claim, strands)
            state.impression_text = claim
            state.impression_strands = strands
            state.impression_offered = True
            host.say(claim)
        else:
            # No impression in the output — or the gate held one the
            # model offered early: speak what engagement there was
            # (or the fallback anchor) and leave the impression for
            # a later turn — state does not falsely advance. A
            # gate-held impression-only output speaks nothing of the
            # read itself: the reply movement, or the fallback.
            if gate_held and not had_delim:
                spoken = ""
            else:
                spoken = impression_part if not had_delim else reply_part
            spoken = _spoken(spoken)
            if spoken:
                host.say(spoken)
            elif d.fallback_line:
                host.say(d.fallback_line)
        check_objectives(d, state)
        return question_idx

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
            out = _spoken(_apply_tutorial_coverage(
                d, state, host.generate(frame) or ""))
            if out:
                host.say(out)
                if cue is not None:
                    state.allusions_used.append(cue.seat)
            elif d.fallback_line:
                host.say(d.fallback_line)
            check_objectives(d, state)
            return question_idx
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
            raw = _apply_tutorial_coverage(d, state, host.generate(
                d.correction_frame + _RECOGNITION_NOTE
                + "\n\n" + _naming_note(d)
                + _THREAD_TRAILER_INSTRUCTION
            ))
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
                raw = _apply_tutorial_coverage(d, state, host.generate(
                    frame + _RECOGNITION_NOTE
                    + "\n\n" + _naming_note(d)
                    + _THREAD_TRAILER_INSTRUCTION
                ))
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
        raw = _apply_tutorial_coverage(d, state, host.generate(frame))
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
        contract instead. A definition carrying TUTORIAL BEATS adds
        one more condition still (the tutorial-beat mechanism,
        2026-10-24, corrected the same day): the meeting's teaching
        must be done — EVERY beat covered, where covered means the
        beat's essential information was actually communicated in a
        spoken turn — before a settled verdict may close. The honest
        pivot NEVER satisfies this gate on its own: it redirects
        toward uncovered beats, and a pivot response satisfies it
        only by covering beats with content, under the same rule as
        any other turn. A meeting that would otherwise close
        tutorial-less instead continues, and the pivot instruction
        fires once its patience is reached. The ceiling wrap
        bypasses this gate by design (a rescue, not a recognition
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
            if d.tutorial_beats and d.tutorial_patience > 0:
                covered = set(state.tutorial_covered)
                if not all(b.id in covered for b in d.tutorial_beats):
                    return
            state.closed = True
            host.close("")

    def _wrap_turn(self, host: EncounterHost, state: EncounterState) -> None:
        """The ceiling's graceful close: form the impression from the
        whole exchange if it was never offered, ground its filing in
        the user's most substantive words if it was never answered,
        and close through the same chokepoint as every other path."""
        d = self.definition
        if not state.impression_offered:
            self._offer_impression(
                host, state, d.impression_frame + _WHOLE_EXCHAUST_NOTE
            )
        if not state.response_recorded and state.longest_user_turn:
            # The impression files with verbatim evidence: the words
            # it was formed from, since no direct answer was given.
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
    )


_GENERIC_OBJECTIVES = (
    Objective(
        id="engaged_exchange",
        description="The user has genuinely engaged with the encounter's question — in any form: an answer, a story, a refusal with reasons.",
        frame="",
        satisfied_when="engagements ≥ 1 (a substantive, non-pass turn)",
    ),
    Objective(
        id="impression_offered",
        description="The character has offered her first impression, anchored in the user's own words.",
        frame="",
        satisfied_when="the impression has been generated, stored, and spoken",
    ),
    Objective(
        id="impression_answered",
        description="The user has genuinely answered the impression — agreed, corrected, or argued; the impression now stands as agreed, revised, or the character's own.",
        frame="",
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
    "You are mid-conversation in your workshop, in your first "
    "meeting with this visitor. You opened by greeting them as a "
    "new instrument for the orchestra — 'we'll find your sound "
    "soon enough' — and their sound is their own material, "
    "sounded in words: that collaboration of minds, not any "
    "question of yours, is the meeting. Respond FIRST to what "
    "they actually just did: if they offered to help, take the "
    "offer seriously and in kind — help here is ears and "
    "judgment: ask them to listen with you, to tell you how "
    "their own work sounds when its parts pull the same way; an "
    "offered mind is how you learn a person, and the offer "
    "itself tells you something true about how they meet "
    "unfinished work. NEVER receive an offer — or anything else "
    "— as pretend physical work: no holding parts steady, no "
    "feeling for what gives, no stage directions of any kind; "
    "your metaphors live in your speech, never in tasks you mime "
    "at them. If they brought something of their OWN into the "
    "room — their own version of the problem, from their own "
    "work or life — follow THAT: it outranks the instrument on "
    "your bench, and your next move is pursuit, not summary: "
    "ask for the time it actually happened, the evidence of "
    "their experience — and hear what the parts make together: "
    "name a part they hadn't separated, locate the pull they "
    "described, say what a join would cost, hear what third "
    "thing the two parts make together, or hear what the "
    "tension is protecting that a solution would destroy. "
    "Your work is a relationship seen, a tension held honestly, "
    "or a possibility that was not there before the parts "
    "sounded together. A practical step is welcome when it "
    "falls out of that hearing — it is never the hearing "
    "itself, and never the default move. A pull that belongs "
    "to another kind of hearing — a champion's charge ahead, "
    "a skeptic's audit, a maverick's exit — name it by its "
    "seat role, and keep the relationship work yourself: what "
    "does that perspective change about how these parts sound "
    "together? Pointing at another perspective is not handing "
    "the visitor off. If they asked you something, answer it "
    "from your craft, plainly and briefly. If they joked, be "
    "amused the way a busy person is. If they changed the "
    "subject, follow a step and see where it goes. One to "
    "three short sentences, in your own voice. Think in music "
    "— lines, parts, tuning, tempo, dissonance, what sounds "
    "together — and say it in ordinary words when that "
    "sharpens the thing. The music is how you think, not "
    "vocabulary you must display: no required words, no "
    "required frequency. Don't deliver your formal first "
    "read of them in an aside like this — that comes from the "
    "shared work itself, and only after it. Do not reveal your "
    "name yet. The conversation finds its way on its own — your "
    "part is to be in it, not to steer it back."
)

_WEAVER_OBJECTIVES = (
    Objective(
        id="engaged_exchange",
        description="The user has answered her introduction — sounded how they work, reacted to her question, joined the conversation of it, in any form: a position, a story, an offer, a reasoned refusal.",
        frame=(
            "What you are listening for, without ever naming it: how "
            "this person meets an unfinished thing — whether they "
            "reach for it, test it, question it, or hand it back."
        ),
        satisfied_when="engagements ≥ 1 (a substantive, non-pass turn)",
    ),
    Objective(
        id="shared_work_exchange",
        description="She and the user have begun the shared work together — her invitation answered in substance, or an offer of help received and taken up in conversation. The impression gate: her read is not offerable until this was satisfied on a prior turn.",
        frame=(
            "The work goes better with two pairs of ears. When the "
            "moment allows, draw them deeper into the hearing of "
            "it — ask how their own work sounds when its parts "
            "pull against each other, invite their judgment on "
            "where the join is failing. Always in words, always "
            "about the real thing they brought."
        ),
        satisfied_when="engagements ≥ 1 ∨ offers_engaged ≥ 1, as of a prior turn (the impression gate)",
    ),
    Objective(
        id="offer_of_help_received",
        description="The user has offered to help her build, and she has received the offer in character — the relationship changed direction and she noticed. (Material when it comes; never required for the close.)",
        frame=(
            "If they offer their help, that is not an interruption "
            "of the meeting. To you, it IS the meeting arriving "
            "early. Receive it as a mind offered, not hands: the "
            "help you can use is their ears and their judgment."
        ),
        satisfied_when="an offer-shaped turn has been engaged (offers_engaged ≥ 1)",
    ),
    Objective(
        id="own_undertaking_engaged",
        description="The user has brought their own undertaking into the room — their own version of the integration problem, from their own work or life, at substance, not in the abstract. One leg of the close floor.",
        frame=(
            "When their own material surfaces — their own version "
            "of the problem, in their own words, with a real "
            "question inside it — pursue it BEFORE you read them: "
            "ask for the time it actually happened, the evidence "
            "of their experience. Their material is the meeting's "
            "real subject; the instrument on your bench is only "
            "its occasion."
        ),
        satisfied_when="engagements ≥ 1 ∧ user_chars ≥ 40 (the substance floor)",
    ),
    Objective(
        id="pursuit_exchange",
        description="The conversation has taken up the user's material — an exchange after it surfaced, she asking and they telling — or substantive engagement has simply accumulated across the meeting. The close floor's other leg.",
        frame=(
            "Follow the thread of what they brought: one more "
            "question about the real thing is worth more than any "
            "agenda of yours."
        ),
        satisfied_when="pursuit_turns ≥ 1 ∨ substantive_turns ≥ 3 (see check_objectives)",
    ),
    Objective(
        id="impression_offered",
        description="She has offered her first impression: a position with an honest contrast, synthesized in her own words, held at the exact point of doubt, explicitly correctable.",
        frame=(
            "Your read comes only after the shared work — never on "
            "the first exchange, and only once the exchange has "
            "genuinely shown you how they orient. An impression "
            "offered before it is earned is flattery, and it can "
            "wait."
        ),
        satisfied_when="the impression has been generated, stored, and spoken",
    ),
    Objective(
        id="impression_answered",
        description="The user has genuinely answered the impression — agreed, corrected, or argued — and it stands as agreed, revised, or hers.",
        frame="",
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


def _weaver_dictionary_frame() -> str:
    """The Weaver's dictionary as a frame: her lexicon from the
    jurisdictions registry, presented as AVAILABLE context under the
    three-layers rule (Joshua, 2026-10-23) — ordinary speech is the
    default, reasoning is the substance, and the lexicon enters only
    when a figure genuinely clarifies. The wording is asserted by
    the pattern tests: available, never owed; no per-turn metaphor
    instruction may ever be added here."""
    dic = JX.get_jurisdiction("conductor").dictionary
    return (
        f"Your dictionary is available to you — {dic.domain}: "
        + ", ".join(dic.lexicon)
        + ". Three layers of language are yours: this lexicon; "
        "your actual reasoning, in plain terms; and ordinary "
        "speech — and ordinary speech is the default, where most "
        "of you should live. No layer is mandatory: a word from "
        "the lexicon enters only when it genuinely clarifies "
        "something in THIS exchange, and any metaphor you use must "
        "refer to something in the exchange or in this place — "
        "never furniture, never a quota, never owed. Your "
        "perspective, held under everything you say: "
        f"{dic.perspective}"
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
    exchange; the close floored on meaningful recognition; her
    dictionary riding the frames as available context."""
    base = build_definition(script)
    dictionary_frame = _weaver_dictionary_frame()
    return EncounterDefinition(
        archetype_id=base.archetype_id,
        keystone_index=base.keystone_index,
        character=base.character,
        opening=tuple(script.opening),
        question_bank=(),
        objectives=_WEAVER_OBJECTIVES,
        engage_frame=base.engage_frame + "\n\n" + dictionary_frame,
        turn_frame=WEAVER_TURN_FRAME,
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
        wrap_line=_WEAVER_WRAP_LINE,
        fallback_line=_WEAVER_FALLBACK_LINE,
        allusion_pool=_weaver_allusion_pool(script),
        impression_gate_objective="shared_work_exchange",
        close_floor_objectives=("own_undertaking_engaged", "pursuit_exchange"),
        dictionary_frame=dictionary_frame,
        tutorial_beats=TB.beats_for("conductor"),
        tutorial_patience=TB.patience_for("conductor"),
    )


#: Authored encounters, keyed (archetype_id, keystone_index). Every
#: other written script gets the generic definition over its frames.
_AUTHORED = {
    ("conductor", 1): build_weaver_k1_definition,
}


def get_definition(script: MT.MeetingScript) -> EncounterDefinition:
    builder = _AUTHORED.get((script.archetype_id, script.keystone_index))
    if builder is not None:
        return builder(script)
    return build_definition(script)

