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
    The user is participating within three short bubbles — the rest
    of the old scripted opening survives as bench anchors and
    prepared context, not as a monologue delivered at the door.
  - Objectives, never announced: each objective is a predicate over
    the encounter state (transcript-derived counters and flags),
    checked after every turn. An objective can be satisfied by
    whatever the user volunteers — an offer to help the Weaver build
    IS encounter material, because it shows how the user relates to
    someone else's unfinished work. At most one objective is the
    live one per turn, and only when the user's move leaves room.
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
  - Closing is on CONDITIONS, not position: the reveal fires when
    the impression has been offered AND genuinely answered (agree,
    correct, or argue — all count) — or at the turn ceiling, where
    the character wraps gracefully ("I've kept you long enough")
    and the impression still files exactly once, through the host's
    existing chokepoint.
  - The world is a runtime input: frames draw on the seat's
    jurisdiction record (P0) and the environmental registry
    (meetings.SEAT_ENVIRONMENT); allusions surface at most one per
    turn, only when the conversation passes near a fixture, and are
    logged in the encounter state against the debt registry
    (meetings.WEAVER_ALLUSIONS) — traces are debts, and the state is
    where the runtime keeps its side of the ledger.
  - Scripted lines survive as fallback anchors: if generation fails
    or returns nothing, the character says the definition's fallback
    line and the encounter state does not advance — degradation is
    honest, never a silent skip.

Nothing here trains anything. The impression files through the host
into the review queue, anchored to the user's verbatim words, and
only a verdict on it writes a signal — the transparency mechanics
stay in the review interface, out of the character's dialogue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from local_ai.council import jurisdictions as JX
from local_ai.council import meetings as MT

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
    #: Delivered verbatim at start — at most three bubbles: character,
    #: environment, invitation.
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
    #: The workshop pause (scripts that carry one): verbatim paragraphs
    #: around the pulled item, delivered when the impression is answered.
    pause_intro: tuple[str, ...]
    pause_body: tuple[str, ...]
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

    @property
    def has_pause(self) -> bool:
        return bool(self.pause_intro or self.pause_body
                    or self.pulled_item_template)


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
    satisfied: dict[str, bool] = field(default_factory=dict)
    impression_offered: bool = False
    impression_answered: bool = False
    impression_answer_kind: str = ""
    impression_text: str = ""
    impression_strands: list[str] = field(default_factory=list)
    response_recorded: bool = False
    pause_delivered: bool = False
    allusions_used: list[str] = field(default_factory=list)
    closed: bool = False

    def to_json(self) -> str:
        return json.dumps({
            "user_turns": self.user_turns,
            "engagements": self.engagements,
            "offers_engaged": self.offers_engaged,
            "user_chars": self.user_chars,
            "longest_user_turn": self.longest_user_turn,
            "satisfied": self.satisfied,
            "impression_offered": self.impression_offered,
            "impression_answered": self.impression_answered,
            "impression_answer_kind": self.impression_answer_kind,
            "impression_text": self.impression_text,
            "impression_strands": self.impression_strands,
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
            "longest_user_turn", "satisfied", "impression_offered",
            "impression_answered", "impression_answer_kind",
            "impression_text", "impression_strands", "response_recorded",
            "pause_delivered", "allusions_used", "closed",
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
        elif obj.id == "offer_of_help_received":
            ok = state.offers_engaged >= 1
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
    runs on objectives."""
    if state.closed:
        return "complete"
    if state.pause_delivered:
        return "orientation"
    if state.impression_offered and not state.impression_answered:
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
        raw = host.generate(frame)
        claim, strands = split_strands_trailer(raw)
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
        move frame + prepared context — the seat's jurisdiction, the
        live objectives' guidance (never announced), and at most one
        environmental allusion the conversation is passing near. The
        cue is returned so the caller can log it against the debt
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
        live = [o for o in d.objectives if not state.satisfied.get(o.id)]
        for obj in live[:2]:
            if obj.frame:
                parts.append(obj.frame)
        cue = self._nearby_allusion(state, message)
        if cue is not None:
            parts.append(
                "Something in what they said passes near a fixture of "
                f"this place: {cue.fixture}. If it fits naturally — "
                f"once, in passing, in words like these: “{cue.text}” "
                "— let it surface. Never force it, and never explain "
                "it; it is simply true of this place."
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

        # The impression is on the table: this turn ANSWERS it, whatever
        # else it also is. (Correction detection here is a safety
        # check — it decides whether the stored impression is revised.)
        if state.impression_offered and not state.impression_answered:
            self._impression_response_turn(host, state, message)
            return question_idx

        # The workshop pause gets exactly one exchange, then the close.
        if state.pause_delivered:
            self._pause_turn(host, state, message)
            return question_idx

        # The graceful ceiling: wrap rather than ramble. (Reached only
        # in the open middle — the two branches above always complete
        # an exchange already in flight.)
        if state.user_turns > TURN_CEILING:
            self._wrap_turn(host, state)
            return question_idx

        move = detect_move(message)

        if move == "pass":
            return self._pass_turn(host, state, question_idx)

        if move in ("offer", "question", "direction", "joke", "greeting", "ack"):
            # Initiative and detours: the character responds to the
            # move, in the same generation that produces her reply.
            # The agenda does not advance — but nothing is skipped:
            # the objectives stay live for the next turn.
            frame, cue = self._turn_frame(state, message)
            out = (host.generate(frame) or "").strip()
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

        # Substantive engagement: ONE generation, two movements — the
        # engaged reply, then the first impression as its own beat.
        state.engagements += 1
        raw = host.generate(d.engage_frame)
        reply_part, impression_part, had_delim = self._split_reply_and_impression(raw)
        claim, strands = split_strands_trailer(impression_part)
        if claim:
            if had_delim and reply_part:
                host.say(reply_part)
            host.store_impression(claim, strands)
            state.impression_text = claim
            state.impression_strands = strands
            state.impression_offered = True
            host.say(claim)
        else:
            # No impression in the output: speak what engagement there
            # was (or the fallback anchor) and leave the impression
            # for a later turn — state does not falsely advance.
            spoken = impression_part if not had_delim else reply_part
            if spoken:
                host.say(spoken)
            elif d.fallback_line:
                host.say(d.fallback_line)
        check_objectives(d, state)
        return question_idx

    # -- beat handlers -----------------------------------------------------------

    def _pass_turn(self, host: EncounterHost, state: EncounterState,
                   question_idx: int) -> int:
        """Passing is participation: offer the next banked question.
        With the bank exhausted, the choosing-not-to-answer is itself
        the material — the impression forms from the whole exchange."""
        d = self.definition
        bank = d.question_bank
        if question_idx + 1 < len(bank):
            host.say(bank[question_idx + 1])
            return question_idx + 1
        self._offer_impression(host, state, d.impression_frame)
        check_objectives(d, state)
        return question_idx

    def _impression_response_turn(self, host: EncounterHost,
                                  state: EncounterState, message: str) -> None:
        d = self.definition
        # The user's response to the impression is part of the record —
        # verbatim, uninterpreted. Filing it is the review flow's job.
        host.store_response(message)
        state.response_recorded = True
        kind = _classify_readback_reply(message)
        state.impression_answer_kind = kind
        if kind == "correction" and d.correction_frame:
            # Correction is real: the corrected understanding REPLACES
            # the stored impression, and is spoken in the room. A
            # degraded (empty) generation keeps the original claim
            # rather than blanking the record.
            raw = host.generate(d.correction_frame)
            claim, strands = split_strands_trailer(raw)
            if claim:
                host.store_impression(claim, strands)
                state.impression_text = claim
                state.impression_strands = strands
                host.say(claim)
        elif kind == "other" and d.impression_reply_frame:
            # Neither agreement nor correction: one brief engaged
            # reply; the impression stands as the character's own.
            out = (host.generate(d.impression_reply_frame) or "").strip()
            if out:
                host.say(out)
        # An acknowledgment alters nothing: the impression stands.
        state.impression_answered = True
        check_objectives(d, state)
        if d.has_pause:
            self._deliver_pause(host, state, message)
            state.pause_delivered = True
        else:
            state.closed = True
            host.close("")

    def _deliver_pause(self, host: EncounterHost, state: EncounterState,
                       response: str) -> None:
        """The workshop pause: theatre, not accounting. The pulled
        item — where a script still carries one — quotes the record
        with weave markers stripped BEFORE excerpting, so a cut can
        never sever a marker (the stored claim keeps its markers for
        the woven rendering)."""
        d = self.definition
        for paragraph in d.pause_intro:
            host.say(paragraph)
        if d.pulled_item_template:
            host.say(d.pulled_item_template.format(
                claim=_excerpt(strip_weave_markers(state.impression_text), 160),
                response=_excerpt(strip_weave_markers(response), 120),
            ))
        if d.pulled_where_template:
            strands = state.impression_strands
            if len(strands) == 1:
                phrase = f"the {strands[0]} strand"
            elif len(strands) >= 2:
                phrase = f"the {strands[0]} and {strands[1]} strands"
            else:
                phrase = "the strands it was heard under"
            host.say(d.pulled_where_template.format(strands=phrase))
        for paragraph in d.pause_body:
            host.say(paragraph)

    def _pause_turn(self, host: EncounterHost, state: EncounterState,
                    message: str) -> None:
        d = self.definition
        if not _is_acknowledgment(message) and not _is_pass(message):
            # A real question: one framed answer from the facts block,
            # then the meeting proceeds to its close.
            frame = d.orientation_frame
            if d.orientation_facts:
                frame = f"{frame}\n\n{d.orientation_facts}"
            out = (host.generate(frame) or "").strip()
            if out:
                host.say(out)
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

#: The glue between the encounter frame and the read-back frame in the
#: single engage generation: two movements, one call.
_ENGAGE_GLUE = (
    "\n\nThen — after your reply — place a line containing only --- "
    "and give your first impression, exactly as the read-back "
    "instructions below describe. The reply and the impression are "
    "two separate movements of the same breath: reply first, "
    "impression after the --- line.\n\n"
)

_GENERIC_TURN_FRAME = (
    "Respond to what the user actually just communicated — a "
    "question, an offer, a joke, a change of direction — in "
    "character, briefly (one to three short sentences). Do not "
    "advance the meeting's business this turn and do not offer your "
    "first impression yet; the conversation returns to it on its "
    "own. Do not reveal your name yet."
)


def build_definition(script: MT.MeetingScript) -> EncounterDefinition:
    """The generic encounter over any written meeting script: the
    script's frames become the definition's frames; the objectives are
    the shape every first meeting shares. Authored encounters (the
    Weaver's K1, below) replace the objective set and bench material."""
    engage = script.encounter_frame + _ENGAGE_GLUE + script.readback_frame
    return EncounterDefinition(
        archetype_id=script.archetype_id,
        keystone_index=script.keystone_index,
        character=script.character,
        opening=(script.opening[0], script.questions[0]) if script.opening else (script.questions[0],),
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
        allusion_pool=(),
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
#   engaged_exchange      — the user has taken up the undertaking at
#                           her bench, in any form.
#   offer_of_help_received — the user has offered to help her build,
#                           and she has received it in character.
#                           (Not required for the close — the offer is
#                           material when it comes, never a toll.)
#   own_undertaking_engaged — the user has brought their own
#                           undertaking into the room, at substance.
#   impression_offered / impression_answered — as generic.

WEAVER_TURN_FRAME = (
    "You are mid-conversation in your workshop, in your first "
    "meeting with this visitor. The unfinished instrument of seven "
    "rather incompatible parts is on the bench between you, and you "
    "have asked them who they would listen to among the mover, the "
    "planner, and the doubter. They have not answered that yet. "
    "Respond FIRST to what they actually just did: if they offered "
    "to help, take the offer seriously and in kind — a part to "
    "hold, a joint to steady; helping hands are how you learn a "
    "person, and the offer itself tells you something true about "
    "how they meet unfinished work. If they asked you something, "
    "answer it from the bench, plainly and briefly. If they joked, "
    "be amused the way a busy person is. If they changed the "
    "subject, follow a step and see where it goes. One to three "
    "short sentences, in your own voice, hands never quite still. "
    "Do NOT offer your first impression yet; do NOT restate or "
    "re-ask your question word for word; never name or describe the "
    "other council members; do not reveal your name yet. The "
    "conversation will find its way back to the bench on its own — "
    "it always does."
)

_WEAVER_OBJECTIVES = (
    Objective(
        id="engaged_exchange",
        description="The user has taken up the undertaking at her bench — answered the dilemma in any form: a position, a story, an offer, a reasoned refusal.",
        frame=(
            "What you are listening for, without ever naming it: how "
            "this person takes up a shared undertaking — who they "
            "listen to when the mover, the planner, and the doubter "
            "disagree."
        ),
        satisfied_when="engagements ≥ 1 (a substantive, non-pass turn)",
    ),
    Objective(
        id="offer_of_help_received",
        description="The user has offered to help her build, and she has received the offer in character — the relationship changed direction and she noticed. (Material when it comes; never required for the close.)",
        frame=(
            "If they offer their hands, that is not an interruption "
            "of the meeting. To you, it IS the meeting arriving "
            "early."
        ),
        satisfied_when="an offer-shaped turn has been engaged (offers_engaged ≥ 1)",
    ),
    Objective(
        id="own_undertaking_engaged",
        description="The user has brought their own undertaking into the room — answered from their own work or life, at substance, not in the abstract.",
        frame=(
            "Where you can, invite the mapping without demanding "
            "it: the dilemma is any undertaking of theirs, and you "
            "would rather hear about the real one."
        ),
        satisfied_when="engagements ≥ 1 ∧ user_chars ≥ 40 (the substance floor)",
    ),
    Objective(
        id="impression_offered",
        description="She has offered her first impression: a position with an honest contrast, anchored in the user's own words, explicitly correctable.",
        frame="",
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
    """The opening's two allusions as runtime cues: the locked lines
    from the debt registry, their fixtures from SEAT_ENVIRONMENT.
    (The orientation's four stay inside the scripted pause, as their
    debts record.)"""
    cues: list[AllusionCue] = []
    env = MT.SEAT_ENVIRONMENT
    keywords = {
        "mentor": ("set aside", "put off", "for later", "shelf",
                   "tending", "left it", "leave it", "growing"),
        "champion": ("test", "fire", "heat", "pressure", "prove",
                     "worth", "sacrifice", "burn"),
    }
    for trace in MT.WEAVER_ALLUSIONS:
        if trace.seat not in keywords:
            continue
        seat_env = env.get(trace.seat)
        fixture = seat_env.fixtures[0] if seat_env and seat_env.fixtures else ""
        cues.append(AllusionCue(
            seat=trace.seat, text=trace.text, fixture=fixture,
            keywords=keywords[trace.seat],
        ))
    return tuple(cues)


def build_weaver_k1_definition(script: MT.MeetingScript) -> EncounterDefinition:
    """The Weaver's first meeting as an authored encounter: her
    objectives, her bench, the dilemma as the opening's invitation."""
    base = build_definition(script)
    return EncounterDefinition(
        archetype_id=base.archetype_id,
        keystone_index=base.keystone_index,
        character=base.character,
        opening=base.opening,
        question_bank=base.question_bank,
        objectives=_WEAVER_OBJECTIVES,
        engage_frame=base.engage_frame,
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

