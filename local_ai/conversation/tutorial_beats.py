"""Tutorial beats: the per-seat teaching checklist for first meetings.

Ratified 2026-10-24 (doctrine, "Tutorial beats: tension gradient +
three-turn fallback"): a seat's first meeting must leave the user
knowing what that seat is FOR — taught by use, in the conversation
itself. Each seat carries three beats — its terrain (which parts of
Zenaf are its charge), the user's involvement (what the user does
with it), and why-meet (why the seat wanted the meeting at all).
Together the seven checklists tile the system: after all seven
meetings, the user knows what Zenaf does — or at least what it aims
to do. No gaps, no overlaps: growth, action, protection, travel,
checking, exits, integration — one slice per seat.

Mechanism (the runtime in encounter.py consumes this module):

- Natural segue first: the beats ride the conversational frame as
  standing hopes, never a bolted-on lecture block.
- Tension gradient: steering pressure grows with the turns. Early
  turns mostly follow; as the meeting runs, the frame steers more
  toward uncovered beats. This is frame instruction only — no new
  LLM call, no per-turn classifier. Beat recognition rides the
  generation call the meeting already makes, via bookkeeping
  trailers (``[[beat:<id>]]``), stripped before anything is spoken
  — the same pattern as the thread trailers.
- Per-character patience: the fallback threshold is tempo, part of
  register, so it lives with the seat, never a global. After that
  many exchanges with beats still uncovered, the frame instructs an
  honest pivot — "let's set that aside for now, why I wanted to
  talk was…" — which OWNS the direction change instead of faking
  a natural segue.
- Close gating (corrected 2026-10-24, Joshua): a meeting closes
  only when recognition conditions are met AND every beat is
  COVERED — covered meaning the beat's essential information was
  actually communicated in a spoken turn. The pivot is a
  redirection mechanism only: it steers toward uncovered beats,
  and after a pivot the steering stays at maximum until the beats
  are covered. A pivot NEVER satisfies the gate on its own; a
  pivot response can satisfy it only by covering beats with
  content, under the same coverage rule as any other turn. The
  ceiling wrap bypasses the gate by design (a rescue, not a close).

- Content guard (same correction): a ``[[beat:<id>]]`` trailer is
  the generating model's own claim, so a claim alone never counts.
  Coverage requires the trailer AND content: the stripped spoken
  body must hit one of the beat's content anchors — distinctive
  topical terms for that beat, never the beat id, never generic
  words an empty announcement could hit ("let me cover my
  terrain" matches nothing; "my ground is the council and the
  tree" matches). The check runs on the body AFTER trailer
  stripping, so trailer text can never self-satisfy. Anchors block
  announcement-only and generic claims; they do not grade
  explanatory depth — that judgment stays with the user at the
  review surface, like every other claim in the system.

This module is pure data + pure functions. It imports nothing from
the encounter runtime, so it can never create a cycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TutorialBeat:
    """One thing a first meeting must teach. `teaching` is plain
    substance for the frame — the character renders it in its own
    voice; the frame never scripts its words. `anchors` are the
    beat's content anchors for the coverage guard (see
    beat_content_covered): distinctive topical terms the spoken
    body must contain before a claimed beat counts as covered."""

    id: str
    kind: str  # "terrain" | "involvement" | "why_meet"
    title: str
    teaching: str
    anchors: tuple[str, ...] = ()


#: Content anchors per beat, keyed by (seat, kind). Chosen so an
#: empty announcement ("let me cover my terrain", "my terrain is
#: important to me") matches NOTHING, while a body that actually
#: explains the beat matches: the anchors are the beat's own
#: topical vocabulary — council, tree, rentals, zones, redaction —
#: never the beat id, never generic words. Every beat's teaching
#: text itself passes its own anchors (pinned by test). Single
#: words and phrases both allowed; matching is case-insensitive
#: with word boundaries, on the stripped spoken body.
_BEAT_ANCHORS: dict[tuple[str, str], tuple[str, ...]] = {
    ("conductor", "terrain"): ("council", "tree", "hearing together"),
    ("conductor", "involvement"): (
        "competing priorities", "sit together", "hearing together"),
    ("conductor", "why_meet"): ("new voice", "in ear", "whole orchestra"),
    ("mentor", "terrain"): ("snapshots", "eras", "tending", "uploads"),
    ("mentor", "involvement"): ("set aside", "uploads", "grown"),
    ("mentor", "why_meet"): ("untended", "tending", "better shape"),
    ("champion", "terrain"): ("follow-through", "commitments", "projects"),
    ("champion", "involvement"): ("hill", "next step", "commitment"),
    ("champion", "why_meet"): ("unkept", "weather"),
    ("guardian", "terrain"): ("consent scopes", "redaction", "never observed"),
    ("guardian", "involvement"): ("consent scopes", "boundaries", "observed"),
    ("guardian", "why_meet"): ("trust", "nothing to protect"),
    ("ambassador", "terrain"): ("rentals", "zones", "disclosures"),
    ("ambassador", "involvement"): ("represented", "travel", "elsewhere"),
    ("ambassador", "why_meet"): ("betrayed", "faithfully"),
    ("skeptic", "terrain"): ("review queue", "anchored evidence", "blend"),
    ("skeptic", "involvement"): ("contests", "unresolved", "claims"),
    ("skeptic", "why_meet"): ("say-so", "check its work"),
    ("maverick", "terrain"): ("own key", "importing", "exports", "reshaping"),
    ("maverick", "involvement"): ("own key", "reshapes", "takes everything"),
    ("maverick", "why_meet"): ("another way", "has to be this way"),
}


def _beat(seat: str, kind: str, title: str, teaching: str) -> TutorialBeat:
    return TutorialBeat(id=f"{seat}:{kind}", kind=kind, title=title,
                        teaching=teaching,
                        anchors=_BEAT_ANCHORS[(seat, kind)])


#: The seven checklists, keyed by archetype id. Derived from each
#: seat's SEAT_FEATURE_FOCUS slice (meetings.py) and jurisdiction
#: (jurisdictions.py). The Weaver's beats are the ones whose absence
#: the 2026-10-24 playtest exposed; the other six are defined now so
#: the mechanism generalizes the day their encounters are built.
SEAT_TUTORIAL_BEATS: dict[str, tuple[TutorialBeat, ...]] = {
    "conductor": (
        _beat(
            "conductor", "terrain", "Her terrain",
            "Your ground is the council and the tree — anywhere "
            "parts of a life need hearing together. When voices, "
            "plans, or decisions pull in different directions, "
            "that is where you work.",
        ),
        _beat(
            "conductor", "involvement", "What the visitor does",
            "The visitor brings you the things that will not sit "
            "together — competing priorities, decisions, voices "
            "in tension — whenever they need hearing together, "
            "and returns whenever something new needs hearing.",
        ),
        _beat(
            "conductor", "why_meet", "Why you wanted to meet",
            "Every new voice changes what the whole orchestra can "
            "play, and you keep the whole of it in ear, not one "
            "instrument at a time. You wanted to meet so that "
            "this new voice could be heard as part of the whole.",
        ),
    ),
    "mentor": (
        _beat(
            "mentor", "terrain", "His terrain",
            "Growth over time is his ground: how depth accrues, "
            "how tending and uploads shape a seat, how signals "
            "fade unless they recur, how snapshots and eras mark "
            "what you have become.",
        ),
        _beat(
            "mentor", "involvement", "What the visitor does",
            "The visitor tends what they set aside, brings uploads "
            "for the seats to learn from, and returns to see what "
            "has grown in their absence.",
        ),
        _beat(
            "mentor", "why_meet", "Why he wanted to meet",
            "Nothing grows untended. He wanted to meet so the "
            "tending could begin — so what you set aside would "
            "be in better shape when you return to it.",
        ),
    ),
    "champion": (
        _beat(
            "champion", "terrain", "Her terrain",
            "Talk into action is her ground: how conversation "
            "becomes projects and tasks, how commitments are made "
            "and kept, how the follow-through loop closes.",
        ),
        _beat(
            "champion", "involvement", "What the visitor does",
            "The visitor turns talk into a commitment — picks the "
            "hill, names the next step, and lets her hold them "
            "to it.",
        ),
        _beat(
            "champion", "why_meet", "Why she wanted to meet",
            "Words unkept are just weather. She wanted to meet so "
            "that something you said could become something you "
            "did.",
        ),
    ),
    "guardian": (
        _beat(
            "guardian", "terrain", "His terrain",
            "Protection is his ground: consent scopes, what is "
            "never observed, redaction, and the rule that the "
            "user's data stays the user's.",
        ),
        _beat(
            "guardian", "involvement", "What the visitor does",
            "The visitor sets consent scopes, checks what is "
            "observed and what is not, and holds boundaries — "
            "including against the system itself.",
        ),
        _beat(
            "guardian", "why_meet", "Why he wanted to meet",
            "Trust is agreed before anything else is built. He "
            "wanted to meet so the boundaries could be set while "
            "there was still nothing to protect.",
        ),
    ),
    "ambassador": (
        _beat(
            "ambassador", "terrain", "Her terrain",
            "How a voice travels is her ground: echo rentals, "
            "zones, listing disclosures — 'trained on X, running "
            "on Y' — and being represented in other people's "
            "councils.",
        ),
        _beat(
            "ambassador", "involvement", "What the visitor does",
            "The visitor chooses how their voice is represented, "
            "reads the disclosures, sets the zones it may travel "
            "in, and decides what it may say elsewhere.",
        ),
        _beat(
            "ambassador", "why_meet", "Why she wanted to meet",
            "A voice carried badly is a voice betrayed. She "
            "wanted to meet so that, when your voice travels, it "
            "travels faithfully.",
        ),
    ),
    "skeptic": (
        _beat(
            "skeptic", "terrain", "His terrain",
            "Checking the work is his ground: the review queue, "
            "anchored evidence, contesting a read, recurrence "
            "patterns across turns, and the blend view — what is "
            "user-sourced and what is base fill.",
        ),
        _beat(
            "skeptic", "involvement", "What the visitor does",
            "The visitor reviews claims, contests reads that do "
            "not hold, checks the blend, and leaves unresolved "
            "whatever deserves to stay unresolved.",
        ),
        _beat(
            "skeptic", "why_meet", "Why he wanted to meet",
            "Nothing should be believed on its say-so — including "
            "this system. He wanted to meet so you would know, "
            "from the start, where to check its work.",
        ),
    ),
    "maverick": (
        _beat(
            "maverick", "terrain", "Her terrain",
            "Exits and keys are her ground: importing "
            "conversation exports, bring-your-own key, exporting "
            "everything, renaming and reshaping seats.",
        ),
        _beat(
            "maverick", "involvement", "What the visitor does",
            "The visitor imports their history, brings their own "
            "key, reshapes seats to fit, and takes everything "
            "with them whenever they choose to leave.",
        ),
        _beat(
            "maverick", "why_meet", "Why she wanted to meet",
            "Who says it has to be this way? She wanted to meet "
            "so you would know, from the start, that there is "
            "always another way — including out.",
        ),
    ),
}

#: Patience per seat (exchanges before the honest pivot fires).
#: Ratified 2026-10-24: Firebrand 2, Crane 7, Weaver 5, Gardener 6,
#: Bear 4, Raven 6, Fox 3. Keyed by archetype id: champion is the
#: Firebrand, ambassador the Crane, conductor the Weaver, mentor
#: the Gardener, guardian the Bear, skeptic the Raven, maverick
#: the Fox. Patience is tempo, part of register — it lives with
#: the seat, never a global.
SEAT_PATIENCE: dict[str, int] = {
    "champion": 2,
    "ambassador": 7,
    "conductor": 5,
    "mentor": 6,
    "guardian": 4,
    "skeptic": 6,
    "maverick": 3,
}

#: The explicit set-aside marker: the pivot line must contain it,
#: so a pivot can never pass as a natural segue — and so the
#: runtime can tell a delivered pivot from a merely steered turn.
PIVOT_SET_ASIDE_MARKER = "set that aside"

#: Bookkeeping trailer a generated reply may carry for each beat it
#: taught: ``[[beat:<beat-id>]]`` on its own line, stripped before
#: anything is spoken (encounter._spoken). Unknown ids never
#: satisfy anything — the runtime validates against the
#: definition's beats.
_BEAT_MARKER_RE = re.compile(r"\[\[beat:([^\]]+)\]\]")


def beats_for(archetype_id: str) -> tuple[TutorialBeat, ...]:
    """The seat's checklist; empty for a seat with none defined."""
    return SEAT_TUTORIAL_BEATS.get(archetype_id, ())


def patience_for(archetype_id: str) -> int:
    """The seat's fallback threshold; 0 means no tutorial gate."""
    return SEAT_PATIENCE.get(archetype_id, 0)


def uncovered_beats(beats: tuple[TutorialBeat, ...],
                    covered: set[str]) -> list[TutorialBeat]:
    """Beats not yet marked covered, in checklist order."""
    return [b for b in beats if b.id not in covered]


def all_beats_covered(beats: tuple[TutorialBeat, ...],
                      covered: set[str]) -> bool:
    """True when every beat on the checklist is covered (and the
    checklist is non-empty — an empty checklist never satisfies a
    gate on its own)."""
    return bool(beats) and all(b.id in covered for b in beats)


#: Minimal substance floor for the content guard: a body of fewer
#: than this many words cannot cover a beat, however anchor-rich
#: it looks. A backstop only — the anchors do the real work; this
#: exists to block degenerate fragments, not to grade depth.
_MIN_BODY_WORDS = 3


def _anchor_hit(anchor: str, body: str) -> bool:
    """Case-insensitive whole-word/phrase match. Word boundaries
    keep "tree" from matching "street" and keep the pivot's "set
    that aside" from matching the mentor's "set aside" anchor."""
    return re.search(r"\b" + re.escape(anchor.lower()) + r"\b",
                     body.lower()) is not None


def beat_content_covered(beat: TutorialBeat, spoken_body: str) -> bool:
    """True when a stripped spoken body actually communicates the
    beat: it hits at least one of the beat's content anchors and
    clears the substance floor. `spoken_body` must already be
    trailer-stripped — trailer text can never self-satisfy, and
    the beat id itself is never an anchor. Deterministic string
    matching only: no model call, no fuzzy matching, no
    embeddings. A claim without content (announcement-only, or a
    generic mention with no anchor) returns False."""
    body = spoken_body or ""
    if len(body.split()) < _MIN_BODY_WORDS:
        return False
    return any(_anchor_hit(a, body) for a in beat.anchors)


def extract_beat_markers(raw: str) -> list[str]:
    """Beat ids a generated reply claims to have taught, in order.
    Validation against the definition's beats happens in the
    runtime — this function only reads the trailers."""
    return _BEAT_MARKER_RE.findall(raw or "")


def strip_beat_markers(text: str) -> str:
    """Remove beat trailers from text about to be spoken or stored
    as the character's words. Bookkeeping never reaches the user."""
    return _BEAT_MARKER_RE.sub("", text or "")


def pivot_delivered_in(spoken: str) -> bool:
    """True when a spoken reply owns its direction change with the
    explicit set-aside marker — the pivot, not a steered turn."""
    return PIVOT_SET_ASIDE_MARKER in (spoken or "").lower()


def _marker_instruction(beats: tuple[TutorialBeat, ...]) -> str:
    ids = ", ".join(b.id for b in beats)
    return (
        "Bookkeeping, never spoken: when your reply teaches one of "
        "these — its terrain, what the visitor can do with you, or "
        "why you wanted to meet — end your reply with [[beat:<id>]] "
        "on its own line for each one taught "
        f"(ids: {ids}), before any thread-trailer line. The markers "
        "are stripped before anything is spoken."
    )


def tutorial_guidance(beats: tuple[TutorialBeat, ...],
                      covered: set[str],
                      user_turns: int,
                      patience: int,
                      pivot_delivered: bool) -> str:
    """Frame instruction for this turn's steering pressure. "" when
    there is nothing to teach (no beats, or all covered). The
    pivot does NOT empty the guidance: after a pivot, steering
    stays at maximum until the beats are covered — the pivot
    redirects, it does not satisfy. Otherwise one of four tiers,
    scaling with turn count against the seat's patience:

    - light (early): follow the conversation; the beats may surface
      when the conversation passes near them.
    - gentle (past half patience): look for a natural opening to
      steer toward the uncovered beats — a segue, not a lecture.
    - pivot (at patience): set the thread aside EXPLICITLY with the
      set-aside line and deliver the uncovered beats in your own
      voice. Never fake a natural segue at this tier.
    - post-pivot (pivot delivered, beats still uncovered): the
      thread is already set aside — deliver what is still untaught
      directly, in your own voice. No re-set-aside, no relaxation.
    """
    if not beats or patience <= 0:
        return ""
    uncovered = uncovered_beats(beats, covered)
    if not uncovered:
        return ""
    titles = "; ".join(f"{b.title}: {b.teaching}" for b in uncovered)
    marker = _marker_instruction(beats)
    if pivot_delivered:
        return (
            "The thread is already set aside to make room for this "
            "teaching — now deliver what is still untaught, "
            f"directly, in your own voice: {titles} "
            + marker
        )
    if user_turns >= patience:
        return (
            "Now: the conversation has run long enough that the "
            "teaching cannot wait for a perfect opening. Set the "
            "current thread aside EXPLICITLY — say something like "
            "\"let's set that aside for now, why I wanted to talk "
            "was…\" — and then, in your own voice, say what is "
            f"still untaught: {titles} Own the change of direction; "
            "never fake a natural segue here. "
            + marker
        )
    if user_turns * 2 >= patience:
        return (
            "The conversation has run several turns; look for a "
            "natural opening to steer toward what is still "
            f"untaught — {titles} — a segue, not a lecture, and "
            "only when the opening is real. "
            + marker
        )
    return (
        "Follow what they brought; the teaching will find its "
        "moment. These are still to find their moment in the "
        f"conversation: {titles} Let them surface when the "
        "conversation passes near them. "
        + marker
    )
