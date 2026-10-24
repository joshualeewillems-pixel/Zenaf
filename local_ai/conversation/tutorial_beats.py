"""Tutorial beats: the per-seat teaching checklist for first meetings.

Ratified 2026-10-24 (doctrine, "Tutorial beats: tension gradient +
three-turn fallback"; amended 2026-10-24, Joshua, amendments A-F):
a seat's first meeting must leave the user knowing what that seat is
FOR — taught by use, in the conversation itself. Each seat carries
three beats — its terrain (which parts of Zenaf are its charge),
the user's involvement (what the user does with it), and why-meet
(why the seat wanted the meeting at all). Together the seven
checklists tile the system: after all seven meetings, the user knows
what Zenaf does — or at least what it aims to do. No gaps, no
overlaps: growth, action, protection, travel, checking, exits,
integration — one slice per seat.

Coverage is SEMANTIC, not scripted (amendment A): a beat is covered
when the visitor has come to understand something, not when the
character emitted a line, a metaphor, or a prescribed explanation.
Each beat is therefore defined as FACETS — the two or three
understandings the beat consists of — and a facet is satisfied only
by a CONNECTED mention in a single spoken turn: the turn's body must
hit at least one term from EVERY one of the facet's term sets. A
facet with one set is a topic the turn must name; a facet with two
sets is a functionality the turn must connect — the place AND what
you can do with it, in the same turn. Facets accumulate across the
character's spoken turns over the whole meeting (different facets
may land on different turns, in any order, whenever they naturally
relate), and only the character's own speech counts — never the
visitor's words, never a bookkeeping trailer.

This check is a CONSERVATIVE PROXY, not proof of understanding
(amendment A, stated plainly so no one mistakes it for more): it
is deterministic string matching, and it can require the
ingredients of an explanation without certifying that the
explanation landed. What it does block, by construction:

- disconnected keyword mentions: a place named in one turn and a
  capability word in another, never joined, satisfy nothing — a
  facet's sets must co-occur in ONE turn's body;
- superficial explanations: naming a place without any capability
  language ("the council exists") satisfies no functionality facet;
- inaccurate capability claims: a facet's capability terms are the
  seat's APPROVED vocabulary, drawn from its user-experience
  jurisdiction (amendment F) — an invented capability shares no
  terms with the approved set and satisfies nothing. (A real
  capability belonging to another seat's primary slice is a
  legitimate explanation through this seat's own jurisdiction; it
  simply does not satisfy this seat's facets unless it matches
  their terms.)
- markers and isolated vocabulary: ``[[beat:<id>]]`` trailers are
  stripped as a backstop and are NEVER an input to coverage, and no
  single word certifies a beat. Depth judgment stays with the user
  at the review surface, like every other claim in the system.

Mechanism (the runtime in encounter.py consumes this module):

- Natural segue first: the beats ride the conversational frame as
  standing hopes, never a bolted-on lecture block.
- Tension gradient: steering pressure grows with the turns. Early
  turns mostly follow; as the meeting runs, the frame steers more
  toward uncovered facets. This is frame instruction only — no new
  LLM call, no per-turn classifier.
- Per-character patience: the fallback threshold is tempo, part of
  register, so it lives with the seat, never a global. After that
  many exchanges with facets still uncovered, the frame instructs
  an honest pivot: the character OWNS the direction change, in its
  own words — an honest transition is REQUIRED, prescribed wording
  is NOT (amendment B). The pivot addresses uncovered substance
  without reciting the checklist: the frame names the uncovered
  facets' substance, never a script to deliver.
- Close gating (corrected 2026-10-24, Joshua): a meeting closes
  only when recognition conditions are met AND every beat is
  COVERED — covered meaning every facet of the beat was satisfied
  by connected mentions in spoken turns. The pivot is a redirection
  mechanism only: it steers toward uncovered facets, and after a
  pivot the steering stays at maximum until the facets are covered.
  A pivot NEVER satisfies the gate on its own. The ceiling wrap
  bypasses the gate by design (a rescue, not a close).
- Overarching requirement (Joshua): tutorial coverage serves the
  conversation, never dominates it. The visitor should leave
  understanding the seat's purpose and the relevant Zenaf
  functionality, while still feeling that they met a character
  rather than completed a lesson. The guidance text carries that
  line in every tier, and the mechanism is built to honor it:
  facets land whenever they naturally relate, and a meeting that
  has not taught stays open rather than forcing a lesson.

This module is pure data + pure functions. It imports nothing from
the encounter runtime, so it can never create a cycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Facet:
    """One understanding a beat consists of. `substance` is the
    short phrase the frame hands the character for uncovered facets
    — content to address, never a script to recite. `term_sets`
    are the term groups a single spoken turn must hit, one term
    from EVERY set, for the facet to count: one set = a topic the
    turn names; two or more sets = a functionality the turn
    connects (place AND capability, same turn). Terms are matched
    case-insensitively with word boundaries."""

    name: str
    substance: str
    term_sets: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class TutorialBeat:
    """One thing a first meeting must teach. `teaching` is plain
    substance for the frame — the character renders it in its own
    voice; the frame never scripts its words. `facets` are the
    beat's required understandings (see Facet): every facet must
    be satisfied by connected mentions in spoken turns before the
    beat counts as covered."""

    id: str
    kind: str  # "terrain" | "involvement" | "why_meet"
    title: str
    teaching: str
    facets: tuple[Facet, ...] = ()


def _facet(name: str, substance: str,
           *term_sets: tuple[str, ...]) -> Facet:
    return Facet(name=name, substance=substance, term_sets=term_sets)


#: Facets per beat, keyed by (seat, kind). Capability terms are the
#: seat's APPROVED vocabulary — drawn from its user-experience
#: jurisdiction (meetings.py SEAT_FEATURE_FOCUS, primary slice) —
#: so an invented capability shares no terms and satisfies nothing.
#: Every beat's teaching text itself satisfies every facet of that
#: beat (pinned by test): facets and teaching cannot drift apart
#: unnoticed. Single words and phrases both allowed.
_BEAT_FACETS: dict[tuple[str, str], tuple[Facet, ...]] = {
    ("conductor", "terrain"): (
        _facet("places", "the council and the tree as places",
               ("council", "tree")),
        _facet("functionality",
               "how the council and the tree work — what you can "
               "show and do with them",
               ("council", "tree"),
               ("hearing together", "sound together", "work",
                "coordinate", "explain", "show")),
    ),
    ("conductor", "involvement"): (
        _facet("doing",
               "bringing what will not sit together, whenever it "
               "needs hearing together",
               ("bring", "brings", "return", "returns"),
               ("sit together", "competing priorities",
                "hearing together", "tension")),
    ),
    ("conductor", "why_meet"): (
        _facet("purpose",
               "every new voice changes what the whole can play",
               ("new voice", "whole orchestra", "in ear")),
    ),
    ("mentor", "terrain"): (
        _facet("topics", "growth over time: snapshots and eras",
               ("snapshots", "eras", "tending", "uploads", "depth")),
        _facet("functionality",
               "how tending and uploads shape a seat over time",
               ("tending", "uploads", "snapshots", "eras"),
               ("shape", "grow", "grown", "accrue", "accrues",
                "explain", "show")),
    ),
    ("mentor", "involvement"): (
        _facet("doing",
               "tending what was set aside, bringing uploads, "
               "returning to see what has grown",
               ("tend", "tends", "bring", "brings", "return",
                "returns"),
               ("uploads", "set aside", "grown")),
    ),
    ("mentor", "why_meet"): (
        _facet("purpose", "nothing grows untended",
               ("untended", "tending", "better shape")),
    ),
    ("champion", "terrain"): (
        _facet("topics",
               "talk into action: projects, tasks, commitments, "
               "follow-through",
               ("follow-through", "commitments", "projects",
                "tasks")),
        _facet("functionality",
               "how conversation becomes projects and kept "
               "commitments",
               ("projects", "tasks", "commitments",
                "follow-through"),
               ("becomes", "made", "kept", "close", "closes",
                "explain", "show")),
    ),
    ("champion", "involvement"): (
        _facet("doing",
               "turning talk into a commitment: picking the hill, "
               "naming the next step",
               ("pick", "picks", "name", "names", "commitment"),
               ("hill", "next step")),
    ),
    ("champion", "why_meet"): (
        _facet("purpose", "words unkept are just weather",
               ("unkept", "weather")),
    ),
    ("guardian", "terrain"): (
        _facet("topics",
               "protection: consent scopes, redaction, what is "
               "never observed",
               ("consent scopes", "redaction", "never observed")),
        _facet("functionality",
               "how consent scopes and redaction keep your data "
               "yours",
               ("consent scopes", "redaction", "data"),
               ("stays", "set", "check", "explain", "show",
                "protect")),
    ),
    ("guardian", "involvement"): (
        _facet("doing",
               "setting consent scopes, checking what is observed, "
               "holding boundaries",
               ("set", "sets", "check", "checks", "hold", "holds"),
               ("consent scopes", "observed", "boundaries")),
    ),
    ("guardian", "why_meet"): (
        _facet("purpose",
               "trust agreed before anything else is built",
               ("trust", "nothing to protect")),
    ),
    ("ambassador", "terrain"): (
        _facet("topics",
               "how a voice travels: rentals, zones, disclosures",
               ("rentals", "zones", "disclosures")),
        _facet("functionality",
               "how rentals, zones, and disclosures carry a voice "
               "faithfully",
               ("rentals", "zones", "disclosures"),
               ("travel", "travels", "represented", "explain",
                "show")),
    ),
    ("ambassador", "involvement"): (
        _facet("doing",
               "choosing how a voice is represented, reading "
               "disclosures, setting zones",
               ("choose", "chooses", "read", "reads", "set",
                "sets", "decide", "decides"),
               ("represented", "disclosures", "zones",
                "elsewhere")),
    ),
    ("ambassador", "why_meet"): (
        _facet("purpose", "a voice carried badly is betrayed",
               ("betrayed", "faithfully")),
    ),
    ("skeptic", "terrain"): (
        _facet("topics",
               "checking the work: review queue, anchored evidence, "
               "blend view",
               ("review queue", "anchored evidence", "blend")),
        _facet("functionality",
               "how the review queue, evidence, and blend let you "
               "check the work",
               ("review queue", "anchored evidence", "blend"),
               ("check", "checking", "contest", "explain", "show",
                "user-sourced")),
    ),
    ("skeptic", "involvement"): (
        _facet("doing",
               "reviewing claims, contesting reads, checking the "
               "blend, leaving things unresolved",
               ("review", "reviews", "contest", "contests",
                "check", "checks"),
               ("claims", "blend", "unresolved")),
    ),
    ("skeptic", "why_meet"): (
        _facet("purpose",
               "nothing believed on its say-so, including this "
               "system",
               ("say-so", "check its work")),
    ),
    ("maverick", "terrain"): (
        _facet("topics",
               "exits and keys: imports, exports, own key, "
               "reshaping",
               ("own key", "importing", "exports", "reshaping")),
        _facet("functionality",
               "how imports, exports, and reshaping move your "
               "history in and out",
               ("exports", "own key", "importing"),
               ("renaming", "reshaping", "bring", "take",
                "explain", "show")),
    ),
    ("maverick", "involvement"): (
        _facet("doing",
               "importing history, bringing your own key, "
               "reshaping seats, taking everything when leaving",
               ("import", "imports", "bring", "brings", "reshape",
                "reshapes", "take", "takes"),
               ("own key", "history", "everything", "leave")),
    ),
    ("maverick", "why_meet"): (
        _facet("purpose",
               "there is always another way — including out",
               ("another way", "has to be this way")),
    ),
}


def _beat(seat: str, kind: str, title: str, teaching: str) -> TutorialBeat:
    return TutorialBeat(id=f"{seat}:{kind}", kind=kind, title=title,
                        teaching=teaching,
                        facets=_BEAT_FACETS[(seat, kind)])


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

#: Detection heuristic for a delivered pivot, NOT a required
#: utterance: the frame requires an honest transition in the
#: character's own words and never quotes a sentence to say, so a
#: pivot phrased differently is still a pivot — it simply is not
#: detected as one, and guidance stays at the pivot tier. The
#: marker exists so the runtime can tell a delivered pivot from a
#: merely steered turn for steering purposes only; it is never a
#: gate condition.
PIVOT_SET_ASIDE_MARKER = "set that aside"

#: Bookkeeping trailer a generated reply may still carry for a beat
#: it taught: ``[[beat:<beat-id>]]`` on its own line. Trailers are
#: stripped before anything is spoken and are NEVER an input to
#: coverage — the runtime reads facets from spoken bodies alone.
#: Stripping is unconditional (a trailer trailing a Strands line
#: would otherwise break strand parsing even for definitions
#: without a tutorial gate, since split_strands_trailer reads from
#: the end).
_BEAT_MARKER_RE = re.compile(r"\[\[beat:([^\]]+)\]\]")


def beats_for(archetype_id: str) -> tuple[TutorialBeat, ...]:
    """The seat's checklist; empty for a seat with none defined."""
    return SEAT_TUTORIAL_BEATS.get(archetype_id, ())


def patience_for(archetype_id: str) -> int:
    """The seat's fallback threshold; 0 means no tutorial gate."""
    return SEAT_PATIENCE.get(archetype_id, 0)


def uncovered_facets(
        beats: tuple[TutorialBeat, ...],
        facet_hits: dict[str, set[str]]) -> list[tuple[TutorialBeat, Facet]]:
    """(Beat, facet) pairs not yet satisfied, in checklist order.
    `facet_hits` maps beat id -> satisfied facet names."""
    out: list[tuple[TutorialBeat, Facet]] = []
    for beat in beats:
        hits = facet_hits.get(beat.id, set())
        for facet in beat.facets:
            if facet.name not in hits:
                out.append((beat, facet))
    return out


def uncovered_beats(
        beats: tuple[TutorialBeat, ...],
        facet_hits: dict[str, set[str]]) -> list[TutorialBeat]:
    """Beats with at least one facet still unsatisfied."""
    return [b for b in beats
            if any(f.name not in facet_hits.get(b.id, set())
                   for f in b.facets)]


#: Minimal substance floor for the coverage proxy: a body of fewer
#: than this many words cannot satisfy a facet, however term-rich
#: it looks. A backstop only — co-occurrence does the real work;
#: this exists to block degenerate fragments, not to grade depth.
_MIN_BODY_WORDS = 3


def _term_hit(term: str, body: str) -> bool:
    """Case-insensitive whole-word/phrase match. Word boundaries
    keep "tree" from matching "street" and keep "work" from
    matching "working"."""
    return re.search(r"\b" + re.escape(term.lower()) + r"\b",
                     body.lower()) is not None


def facet_satisfied(facet: Facet, spoken_body: str) -> bool:
    """True when ONE spoken body satisfies the facet: the body
    clears the substance floor AND hits at least one term from
    EVERY term set. A single-set facet is a topic named; a
    multi-set facet is a functionality connected — place and
    capability in the same turn, never scattered across turns.
    Deterministic string matching only: no model call, no fuzzy
    matching, no embeddings. This is a conservative proxy, not
    proof of understanding: it requires the ingredients of an
    explanation, it cannot certify that the explanation landed."""
    body = spoken_body or ""
    if len(body.split()) < _MIN_BODY_WORDS:
        return False
    return all(
        any(_term_hit(term, body) for term in term_set)
        for term_set in facet.term_sets
    )


def satisfied_facets(beat: TutorialBeat, spoken_body: str,
                     already: set[str]) -> set[str]:
    """The beat's satisfied facet names after this spoken body:
    `already` plus every facet this body newly satisfies. Facets
    accumulate across turns; a facet once satisfied stays
    satisfied."""
    hits = set(already)
    for facet in beat.facets:
        if facet.name not in hits and facet_satisfied(facet,
                                                      spoken_body):
            hits.add(facet.name)
    return hits


def beat_covered(beat: TutorialBeat, satisfied: set[str]) -> bool:
    """True when every facet of the beat is satisfied."""
    return all(f.name in satisfied for f in beat.facets)


def strip_beat_markers(text: str) -> str:
    """Remove beat trailers from text about to be spoken or stored
    as the character's words. Bookkeeping never reaches the user,
    and trailers never feed coverage."""
    return _BEAT_MARKER_RE.sub("", text or "")


def pivot_delivered_in(spoken: str) -> bool:
    """True when a spoken reply owns its direction change with the
    explicit set-aside marker — the pivot, not a steered turn.
    Detection heuristic only (see PIVOT_SET_ASIDE_MARKER)."""
    return PIVOT_SET_ASIDE_MARKER in (spoken or "").lower()


#: The overarching requirement, carried in every non-empty guidance
#: return: coverage serves the conversation, never dominates it.
_SERVE_LINE = (
    "The teaching serves this conversation, never dominates it: "
    "the visitor should leave having met a character, not "
    "completed a lesson."
)


def tutorial_guidance(beats: tuple[TutorialBeat, ...],
                      facet_hits: dict[str, set[str]],
                      user_turns: int,
                      patience: int,
                      pivot_delivered: bool) -> str:
    """Frame instruction for this turn's steering pressure. "" when
    there is nothing to teach (no beats, or all facets covered).
    The pivot does NOT empty the guidance: after a pivot, steering
    stays at maximum until the facets are covered — the pivot
    redirects, it does not satisfy. Otherwise one of four tiers,
    scaling with turn count against the seat's patience:

    - light (early): follow the conversation; the facets may
      surface when the conversation passes near them.
    - gentle (past half patience): look for a natural opening to
      steer toward the uncovered facets — a segue, not a lecture.
    - pivot (at patience): own the change of direction EXPLICITLY,
      in your own words — an honest transition is required,
      prescribed wording is not — and address the uncovered facets'
      substance, never by reciting a checklist.
    - post-pivot (pivot delivered, facets still uncovered): the
      thread is already set aside — address what is still untaught
      directly, in your own voice. No re-set-aside, no relaxation.

    The frame names uncovered facets' substance for the character
    to address; it never hands it a script. No marker instruction:
    trailers are not part of coverage, so the frame does not ask
    for them.
    """
    if not beats or patience <= 0:
        return ""
    uncovered = uncovered_facets(beats, facet_hits)
    if not uncovered:
        return ""
    substance = "; ".join(
        f"{beat.title}: {facet.substance}"
        for beat, facet in uncovered
    )
    if pivot_delivered:
        return (
            "The thread is already set aside to make room for this "
            "teaching — now address what is still untaught, "
            f"directly, in your own voice: {substance} "
            "No re-set-aside, no relaxation. "
            + _SERVE_LINE
        )
    if user_turns >= patience:
        return (
            "Now: the conversation has run long enough that the "
            "teaching cannot wait for a perfect opening. Own the "
            "change of direction explicitly, in your own words — "
            "name that you are setting the current thread aside "
            "to say what you came to say; never fake a natural "
            "segue here — and then address what is still "
            f"untaught: {substance} "
            + _SERVE_LINE
        )
    if user_turns * 2 >= patience:
        return (
            "The conversation has run several turns; look for a "
            "natural opening to steer toward what is still "
            f"untaught — {substance} — a segue, not a lecture, and "
            "only when the opening is real. "
            + _SERVE_LINE
        )
    return (
        "Follow what they brought; the teaching will find its "
        "moment. These are still to find their moment in the "
        f"conversation: {substance} Let them surface when the "
        "conversation passes near them. "
        + _SERVE_LINE
    )
