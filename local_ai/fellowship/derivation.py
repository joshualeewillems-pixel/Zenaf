"""Observation derivation — the slow path (Fellowship Runtime P1).

Derivation turns an event (events.py) into zero or more observations
(observations.py): a seat's attributable reading of shared evidence.
It runs in two steps, and the split is the cost law (doctrine §2/§3 +
the 2026-10-23 rulings):

  1. Deterministic pre-filter — pure arithmetic, no model. An event
     is scored against every seat's jurisdiction (the P0 registry:
     focus/periphery text, matched as keywords) and, when the event
     references an entity with strand weightings (entity_strands.py),
     against every seat's strand-weight vector. Seats that clear the
     bar are *candidates*. An event in nobody's focus or periphery
     produces zero model calls and zero observations — the fellowship
     is generally listening, not generally generating.
  2. Interpretation — one LLM call per candidate seat, through the
     codebase's usual injectable ``generate_fn`` seam. The seat reads
     the event's evidence in its own register and either offers one
     short observation or declines (``NONE``) — precision over
     coverage, the house honesty rule. A seat that declines leaves no
     row: an observation exists only when a character actually has a
     reading.

Two-speed law: nothing here runs on a reply path. Emitters schedule
derivation through the installed pipeline (background daemon thread,
the demo_routes precedent); ``install_default_pipeline`` is called at
app assembly (api/main.py). Without an installed pipeline, events are
still recorded and derivation simply doesn't run — callers who need
it synchronously (tests, tools) call ``derive_observations``
directly. Every failure inside derivation — per-seat or whole-event —
is logged and swallowed: a failed observation can never break the
operation that produced the event.

Control invariants: derivation writes ONLY to the observations store.
It imports nothing from the review/intake filing paths and nothing
from the signals store; an observation becomes training material only
through the user's own later verdicts, in later phases.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from local_ai.council.archetypes import get_archetype, stock_archetype_ids
from local_ai.council.jurisdictions import get_jurisdiction
from local_ai.fellowship.events import FellowshipEvent
from local_ai.fellowship.observations import Observation, ObservationStore

logger = logging.getLogger(__name__)

GenerateFn = Callable[..., str]

#: Character names (Joshua's naming authority) for prompt voice.
_CHARACTER_NAMES: dict[str, str] = {
    "mentor": "Gardener",
    "champion": "Firebrand",
    "guardian": "Bear",
    "maverick": "Fox",
    "ambassador": "Crane",
    "conductor": "Weaver",
    "skeptic": "Raven",
}

# ---------------------------------------------------------------------------
# Deterministic pre-filter
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset[str] = frozenset(
    """
    about above after again against all and any are as at be because been
    before being below between both but by can could did do does doing down
    during each few for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just like me
    more most my no nor not now of off on once only or other our ours out
    over own s same she should so some such t than that the their theirs
    them themselves then there these they this those through to too under
    until up very was we were what when where which while who whom why will
    with would you your yours yourself one ones thing things way ways get
    gets got make made makes also much many would could may might must
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9']+")
_MIN_TOKEN_LEN = 4
#: A term appearing in at least this many seats' corpora discriminates
#: nothing and is dropped from every corpus.
_DF_DROP = 4
#: Candidate thresholds (see candidate_seats).
_FOCUS_HIT_POINTS = 2
_STRAND_ALIGNMENT_MIN = 0.30
_CANDIDATE_MIN_SCORE = 3


def _stem(token: str) -> str:
    """Naive suffix stem so 'fits'/'fitting' meet the corpus's 'fit'."""
    t = token.rstrip("'")
    for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
        if t.endswith(suffix) and len(t) - len(suffix) >= 3:
            return t[: -len(suffix)]
    return t


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _TOKEN_RE.findall((text or "").lower()):
        if len(raw) < _MIN_TOKEN_LEN or raw in _STOPWORDS:
            continue
        out.add(_stem(raw))
    return out


@dataclass(frozen=True)
class _SeatCorpus:
    focus_terms: frozenset[str]
    periphery_terms: frozenset[str]


_CORPORA: dict[str, _SeatCorpus] | None = None
_CORPORA_LOCK = threading.Lock()


def _seat_corpora() -> dict[str, _SeatCorpus]:
    """Per-seat keyword corpora built once from the P0 registry.

    Terms in >= _DF_DROP seats' combined corpora are dropped (they
    discriminate nothing). A seat's focus terms exclude its periphery
    terms so a term scores at its strongest level only.
    """
    global _CORPORA
    if _CORPORA is not None:
        return _CORPORA
    with _CORPORA_LOCK:
        if _CORPORA is not None:
            return _CORPORA
        raw: dict[str, tuple[set[str], set[str]]] = {}
        doc_freq: dict[str, int] = {}
        for seat in stock_archetype_ids():
            record = get_jurisdiction(seat)
            if record is None:
                continue
            focus = _tokens(record.focus)
            periphery: set[str] = set()
            for entry in record.periphery:
                periphery |= _tokens(entry)
            raw[seat] = (focus, periphery)
            for term in focus | periphery:
                doc_freq[term] = doc_freq.get(term, 0) + 1
        corpora: dict[str, _SeatCorpus] = {}
        for seat, (focus, periphery) in raw.items():
            focus = {t for t in focus if doc_freq.get(t, 0) < _DF_DROP}
            periphery = {
                t for t in periphery - focus if doc_freq.get(t, 0) < _DF_DROP
            }
            corpora[seat] = _SeatCorpus(frozenset(focus), frozenset(periphery))
        _CORPORA = corpora
        return _CORPORA


@dataclass
class CandidateMatch:
    """One seat's pre-filter result for an event — the *reasons* are
    kept so a derived observation stays inspectable."""

    seat: str
    score: int
    focus_terms: list[str] = field(default_factory=list)
    periphery_terms: list[str] = field(default_factory=list)
    strand_alignment: float = 0.0

    def reasons(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "focus_terms": list(self.focus_terms),
            "periphery_terms": list(self.periphery_terms),
            "strand_alignment": round(self.strand_alignment, 4),
        }


def _event_text(event: FellowshipEvent) -> str:
    parts = [event.summary or "", event.evidence_text or ""]
    for value in (event.payload or {}).values():
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts)


def _entity_strand_weights(event: FellowshipEvent) -> dict[str, float] | None:
    """The event entity's strand weightings, if it has any.

    Honest unknown: entities never weighed return None and the strand
    signal simply doesn't contribute (entity_strands' own rule).
    """
    entity_type = (event.entity_type or "").strip().lower()
    if entity_type not in ("person", "project", "task", "asset", "job"):
        return None
    if not event.entity_id or not event.user_id:
        return None
    try:
        from local_ai.entity_strands import get_entity_strands

        weighting = get_entity_strands(event.user_id, entity_type, event.entity_id)
        return weighting.strand_weights
    except Exception:
        logger.exception("fellowship: strand lookup failed for %s", event.id)
        return None


def _strand_alignment(
    entity_weights: dict[str, float], seat_weights: dict[str, float] | None
) -> float:
    """Cosine alignment between an entity's strand vector and a seat's."""
    if not seat_weights:
        return 0.0
    dot = sum(entity_weights.get(k, 0.0) * seat_weights.get(k, 0.0) for k in entity_weights)
    norm_e = math.sqrt(sum(v * v for v in entity_weights.values()))
    norm_s = math.sqrt(sum(v * v for v in seat_weights.values()))
    if norm_e <= 0 or norm_s <= 0:
        return 0.0
    return dot / (norm_e * norm_s)


def candidate_seats(event: FellowshipEvent) -> list[CandidateMatch]:
    """Deterministic: which seats should even consider this event?

    A seat is a candidate when its focus genuinely engages the event:
    at least two distinct focus-term hits, or one focus hit with a
    total score (focus weighs double; periphery hits and a strong
    strand alignment add) at or over the higher bar. A lone generic
    focus word is never enough — one keyword is not an
    observation-worthy event. Strand alignment can strengthen a
    candidacy but cannot create one: attention comes from
    jurisdiction first, strands second.
    """
    corpora = _seat_corpora()
    event_terms = _tokens(_event_text(event))
    entity_weights = _entity_strand_weights(event)
    matches: list[CandidateMatch] = []
    for seat in stock_archetype_ids():
        corpus = corpora.get(seat)
        if corpus is None:
            continue
        focus_hits = sorted(event_terms & corpus.focus_terms)
        periphery_hits = sorted(event_terms & corpus.periphery_terms)
        arch = get_archetype(seat)
        alignment = (
            _strand_alignment(entity_weights, arch.strand_weights if arch else None)
            if entity_weights
            else 0.0
        )
        score = _FOCUS_HIT_POINTS * len(focus_hits) + len(periphery_hits)
        if alignment >= _STRAND_ALIGNMENT_MIN and (focus_hits or periphery_hits):
            score += 1
        if focus_hits and (len(focus_hits) >= 2 or score >= _CANDIDATE_MIN_SCORE + 1):
            matches.append(
                CandidateMatch(
                    seat=seat,
                    score=score,
                    focus_terms=focus_hits,
                    periphery_terms=periphery_hits,
                    strand_alignment=alignment,
                )
            )
    matches.sort(key=lambda m: (-m.score, m.seat))
    return matches


# ---------------------------------------------------------------------------
# Interpretation (LLM, candidate seats only)
# ---------------------------------------------------------------------------

_OBSERVATION_PROMPT = """\
You are the {character}, one of seven council voices in Zenaf, reading
something that just happened in the user's world. Your jurisdiction —
what naturally draws your attention: {focus}
Your register: diction — {diction}; metaphor family — {metaphors}.

Event: {summary}
Evidence (the user's own words / the record, verbatim):
\"\"\"{evidence}\"\"\"

If this genuinely touches your jurisdiction, write ONE observation:
1-2 sentences, in your register, an attributable reading of what this
suggests — grounded only in the evidence above, keeping the
interpretive jump small and falsifiable. Do not paraphrase the
evidence as your observation; say what it means from your ground.
If it does not genuinely touch your jurisdiction, reply with exactly:
NONE
"""

_EVENT_KIND_CONTEXT: dict[str, str] = {
    "conversation_turn": "The user said this in conversation with one of the council voices.",
    "claim_decided": "The user ruled on a claim the system had made about them (their review verdict).",
    "task_completed": "A task in the user's work was completed.",
    "meeting_completed": "The user completed a first meeting with one of the council voices.",
    "decision_recorded": "A decision about the user's work was recorded.",
}


def _character_name(seat: str) -> str:
    if seat in _CHARACTER_NAMES:
        return _CHARACTER_NAMES[seat]
    arch = get_archetype(seat)
    return arch.display_name if arch else seat


def _interpret(
    event: FellowshipEvent,
    seat: str,
    gen: GenerateFn,
) -> str | None:
    """One seat's reading of the event, or None when it declines/fails."""
    record = get_jurisdiction(seat)
    if record is None:
        return None
    summary = event.summary or _EVENT_KIND_CONTEXT.get(event.kind, event.kind)
    context = _EVENT_KIND_CONTEXT.get(event.kind, "")
    if context and context not in summary:
        summary = f"{summary} ({context})" if summary else context
    prompt = _OBSERVATION_PROMPT.format(
        character=_character_name(seat),
        focus=record.focus,
        diction=record.register.diction,
        metaphors=record.register.metaphor_family,
        summary=summary[:600],
        evidence=(event.evidence_text or "(no verbatim words — the event is the record itself)")[:1200],
    )
    raw = gen(
        prompt,
        provider_id="meta",
        user_id=event.user_id or None,
        operation="fellowship-observation",
        timeout=60,
    )
    text = (raw or "").strip()
    if not text or text.upper() == "NONE" or text.upper().startswith("NONE\n"):
        return None
    return text[:600]


def derive_observations(
    event: FellowshipEvent,
    store: ObservationStore,
    generate_fn: GenerateFn | None = None,
) -> list[Observation]:
    """Derive and persist observations for one event. Never raises.

    No candidate seats → no LLM call at all. Each candidate seat's
    generation is independently guarded: one seat's failure costs its
    own observation, never the event's other seats or the caller.
    """
    try:
        matches = candidate_seats(event)
    except Exception:
        logger.exception("fellowship: pre-filter failed for event %s", event.id)
        return []
    if not matches:
        return []
    gen = generate_fn
    if gen is None:
        from local_ai.agent_intake.llm_keys import generate as _gen

        gen = _gen
    derived: list[Observation] = []
    for match in matches:
        try:
            interpretation = _interpret(event, match.seat, gen)
            if not interpretation:
                continue
            if (event.evidence_text or "").strip():
                evidence, evidence_kind = event.evidence_text, "quote"
            else:
                evidence = f"{event.entity_type}:{event.entity_id}"
                evidence_kind = "entity_ref"
            obs = store.add(
                user_id=event.user_id,
                seat=match.seat,
                event_ref=event.id,
                event_kind=event.kind,
                evidence=evidence,
                evidence_kind=evidence_kind,
                interpretation=interpretation,
                derivation={
                    "prefilter": match.reasons(),
                    "operation": "fellowship-observation",
                },
            )
            derived.append(obs)
        except Exception:
            logger.exception(
                "fellowship: derivation failed for seat %s on event %s",
                match.seat,
                event.id,
            )
    return derived


# ---------------------------------------------------------------------------
# Background pipeline (installed at app assembly)
# ---------------------------------------------------------------------------


class DerivationPipeline:
    """Schedules derivation off the caller's path.

    The default scheduler spawns a daemon thread (the api demo_routes
    precedent); tests and tools may inject a synchronous scheduler
    (``lambda fn: fn()``) for determinism. ``generate_fn`` and
    ``store`` are injectable for the same reason. Scheduling itself
    never raises.
    """

    def __init__(
        self,
        store: ObservationStore | None = None,
        generate_fn: GenerateFn | None = None,
        scheduler: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._store = store
        self._generate_fn = generate_fn
        self._scheduler = scheduler or self._thread_scheduler

    @staticmethod
    def _thread_scheduler(fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, name="fellowship-derivation", daemon=True).start()

    @property
    def store(self) -> ObservationStore:
        if self._store is None:
            self._store = ObservationStore()
        return self._store

    def schedule(self, event: FellowshipEvent) -> None:
        try:
            self._scheduler(lambda: self._run(event))
        except Exception:
            logger.exception("fellowship: could not schedule derivation for %s", event.id)

    def _run(self, event: FellowshipEvent) -> None:
        try:
            derive_observations(event, self.store, generate_fn=self._generate_fn)
        except Exception:
            logger.exception("fellowship: derivation run failed for %s", event.id)


_PIPELINE: DerivationPipeline | None = None
_PIPELINE_LOCK = threading.Lock()


def install_default_pipeline(
    store: ObservationStore | None = None,
    generate_fn: GenerateFn | None = None,
    scheduler: Callable[[Callable[[], None]], None] | None = None,
) -> DerivationPipeline:
    """Install the process-wide derivation pipeline (app assembly).

    Idempotent-ish: re-installing replaces the pipeline (tests use
    this to install a synchronous one; production installs once).
    """
    global _PIPELINE
    with _PIPELINE_LOCK:
        _PIPELINE = DerivationPipeline(
            store=store, generate_fn=generate_fn, scheduler=scheduler
        )
        return _PIPELINE


def get_pipeline() -> DerivationPipeline | None:
    """The installed pipeline, or None when derivation is not wired."""
    return _PIPELINE
