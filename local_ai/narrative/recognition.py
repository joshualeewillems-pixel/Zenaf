"""Narrative Steward — recognition: the missing caller (Gate B).

The Steward's interpretive machinery was built and never invoked:
``discovery`` finds thread pairs and is called nowhere; the lens
canon (``lenses.py``) carries observable fit signals and cautions
and nothing proposes a fitting; ``correspondence`` accepts explicit
evidence refs from a caller that did not exist. This module is that
caller — one recognition pass with four outlets, all writing
proposals through the store's existing transitions and nothing
else:

- **Outlet A — progressions.** One thread's evidence, ordered, is
  tested by deterministic gates (G1–G4 below) and, only when every
  gate passes, by at most one generation through the injected
  ``generate_fn`` seam (derivation's idiom). A surviving candidate
  is proposed as a ``ThreadReading`` (author ``steward``, status
  ``proposed``, progression ``unknown`` — no lens named, no
  position claimed) whose structured payload is the sequence
  itself: steps that observe, one labelled development claim, both
  rival explanations, any contradiction the record carries, and a
  coverage note.
- **Outlet B — fittings.** Deterministic, generation-free: a canon
  lens is proposed when at least two of its fit signals match
  distinct evidence points (F1). Competing lenses are proposed
  together, unranked — the canon carries no scores and neither
  does this module. Durable rejection is the store's own rule
  (``set_fitting``, Phase 4 T2): recognition never passes
  ``reopen_of``; a refused fitting surfaces here as abstention
  (F2).
- **Outlet C — correspondences.** Deterministic tension detection
  (C1: two threads sharing an entity ref whose change records
  stand in opposition, paired with discovery's rarity arithmetic).
  Generation for this outlet has its OWN switch
  (``ZENAF_RECOGNITION_CORRESPONDENCE_GEN``, default off): with it
  off, detection runs and records its result in the result object
  — and generates nothing, proposes nothing. With it on, at most
  one generation per pass proposes the structure, and recognition
  validates substantive limitations before the call (C2);
  ``propose_correspondence`` re-enforces its own abstentions.
- **Outlet D — card sections (Story-First Phase 1B).** A thread's
  structural abstraction: a reading whose payload carries the
  personal card's sections — ``structure`` (roles, relationships,
  conflicts, reversals, sacrifices, consequences, changes over
  time; every entry citing its evidence refs), ``distinctions``
  (what the narrative is not), and ``tags`` — alongside the
  existing tensions, open questions, and milestones. A
  deterministic pre-filter runs first (S1 multiplicity, S2
  detectable structural material, S3 dedup against the thread's
  own card readings): card-shaped structure is detectable in the
  evidence without any model call, and when the pre-filter fails
  nothing is generated. Generation has its OWN switch
  (``ZENAF_RECOGNITION_CARD_SECTIONS_GEN``, default off) on the
  correspondence precedent: with it off, the pre-filter runs and
  records its result — and generates nothing, proposes nothing.
  The reading lands through ``propose_reading`` at ``proposed``
  standing, seat-less, like all derivation: a card's structure is
  an interpretation, never a fact about the visitor, and no
  verdict path is touched.

Assessment is pure: :func:`assess_thread`, :func:`assess_pairs`,
and :func:`assess_card_sections` write nothing and return a
result object. Only :func:`propose_all` writes, and only through
``propose_reading``, ``set_fitting``, and
``propose_correspondence``. Abstention is the default at every
outlet and writes nothing: a pass that proposes nothing is a
complete, successful pass.

Boundaries, inherited and re-stated so they are checkable here:

- Consent and eligibility are not re-implemented. The pass runs
  inside the sweep's existing consent gate (see ``sweep.py``);
  evidence considered is only evidence already attached to threads
  in the store — already consent-gated, tier-E, and
  eligibility-filtered at derivation time. When an erasure
  tombstone stands, recognition additionally excludes evidence
  rows at or before the boundary from every window and every
  generation input (fail closed, the conservative reader-side
  complement to D2's write-time funnels).
- No generation backend is resolved here. ``generate_fn`` is
  injected; when it is None, generation-dependent steps abstain.
  This module imports no generation machinery, no conversation
  path (reply/service/encounter/meeting), no signals store, and
  no review/intake filing path — derivation's separation.
- Evidence text is prompt context, never stored (derivation's
  rule); the store's rows carry a note, an entity ref, and a
  timestamp, and the generation input is assembled from exactly
  those — a row with no words renders as a record with no words.
- Ordering is the store's evidence order: rows attach under one
  lock in the order their origin records were derived, and
  ``evidence_for`` returns them in that order. Derivative
  timestamps (a reading's, a proposal's) never order a sequence.

Switches (read per call, so tests flip them with ``setenv``):

- ``ZENAF_RECOGNITION`` — master switch for the pass, default OFF.
  Off ⇒ the sweep behaves exactly as it did before this module.
- ``ZENAF_RECOGNITION_CORRESPONDENCE_GEN`` — Outlet C generation
  only, default OFF, independent of the progression path.
- ``ZENAF_RECOGNITION_CARD_SECTIONS_GEN`` — Outlet D generation
  only, default OFF, independent of every other outlet: enabling
  it enables neither progression nor correspondence generation.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .correspondence import propose_correspondence
from .derivation import (
    correspondence_signature_from_fields,
    fitting_signature_from_keys,
)
from .discovery import _live_threads, _thread_ref_map
from .lenses import LENSES, NarrativeLens, get_lens
from .models import ThreadChange, ThreadEvidence
from .store import NarrativeStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — the gates, as data
# ---------------------------------------------------------------------------

#: Threads the recognition pass surveys: ongoing stories. Nascent
#: threads are proposals themselves; finished threads are closed.
PASS_THREAD_STATUSES: tuple[str, ...] = ("active", "dormant")

#: Whole-record bound: the thread's most recent evidence rows, plus
#: ALL its change records. The bound is stated in every candidate's
#: coverage note, never silently applied.
MAX_EVIDENCE_WINDOW = 40

#: G1 — multiplicity and separation.
MIN_PROGRESSION_POINTS = 3
MIN_PROGRESSION_DAYS = 2

#: Change kinds that count as intervening movement for G2. A
#: verdict on thread evidence reaches the store as one of these
#: (the Phase 3 detectors record claim verdicts as extended /
#: contradicted changes), so the verdict branch of G2 reads the
#: same rows.
_MOVEMENT_KINDS: tuple[str, ...] = ("milestone", "extended")
_MOVEMENT_STATUSES: tuple[str, ...] = ("proposed", "confirmed")

#: Caps per pass per user (enforced by run_recognition_pass's
#: budgeted wrappers; a single assess call generates at most once).
MAX_PROGRESSION_GENERATIONS_PER_PASS = 2
MAX_CORRESPONDENCE_GENERATIONS_PER_PASS = 1
MAX_CARD_SECTION_GENERATIONS_PER_PASS = 1

#: F1 — a lens needs this many fit signals, each matched to a
#: DISTINCT evidence point.
MIN_FIT_SIGNALS = 2

#: C2 — limitations shorter than this are not substantive.
MIN_LIMITATIONS_CHARS = 20

#: The reading-payload kind marking a progression candidate.
PROGRESSION_READING_KIND = "progression_candidate"

#: The reading-payload kind marking a card-section candidate
#: (Outlet D). The card view surfaces the payload's ``structure``
#: / ``distinctions`` / ``tags`` keys; the kind marker is what the
#: S3 dedup scans for.
CARD_SECTIONS_READING_KIND = "card_sections"

#: S1 — multiplicity and separation for a card abstraction (the
#: G1 values, independently tunable: one mention is not a
#: structure, and a structure spans more than a day).
MIN_CARD_SECTION_POINTS = 3
MIN_CARD_SECTION_DAYS = 2

#: The structure block's fields (design Rev 2, Step 2): the shape
#: of a narrative, each field a list of evidence-cited entries.
STRUCTURE_FIELDS: tuple[str, ...] = (
    "roles",
    "relationships",
    "conflicts",
    "reversals",
    "sacrifices",
    "consequences",
    "changes_over_time",
)

#: Change kinds that are themselves structural material for S2 —
#: recorded movement of any shape (an extension, a contradiction,
#: a milestone, a reopening) is a change over time in the record.
_STRUCTURAL_CHANGE_KINDS: tuple[str, ...] = (
    "extended",
    "contradicted",
    "milestone",
    "reopened",
)

#: Opposed change shapes for C1: one thread's movement against the
#: other's reversal or reopening.
_OPPOSED_PAIRS: tuple[tuple[str, str], ...] = (
    ("extended", "contradicted"),
    ("milestone", "reopened"),
)

#: Coverage-note omission classes that always hold of a candidate:
#: the record it did NOT rest on, stated so the silence is
#: inspectable (proposal §3).
_STANDING_OMISSIONS: tuple[str, ...] = (
    "dramatization-tier material (inadmissible as evidence by type)",
    "pre-consent activity never derived",
    "claims excluded post-erasure (Option B)",
)


# ---------------------------------------------------------------------------
# Switches
# ---------------------------------------------------------------------------


def _switch_enabled(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes", "on")


def recognition_enabled() -> bool:
    """Master switch for the recognition pass (default OFF).

    The Slice A switch idiom (``candidates.py``), with the default
    inverted per the Gate B brief: unset means off, so the sweep
    behaves exactly as today until the switch is deliberately set.
    """
    return _switch_enabled("ZENAF_RECOGNITION")


def correspondence_generation_enabled() -> bool:
    """Outlet C's OWN generation switch (default OFF).

    Independent of the progression path by design: enabling
    progression generation never enables correspondence
    generation. Live enablement is a separate founder decision
    with its own spending boundary.
    """
    return _switch_enabled("ZENAF_RECOGNITION_CORRESPONDENCE_GEN")


def card_sections_generation_enabled() -> bool:
    """Outlet D's OWN generation switch (default OFF).

    Independent of every other outlet by design, on the
    correspondence precedent: enabling progression or
    correspondence generation never enables card-section
    generation, and live enablement is a separate founder
    decision with its own spending boundary.
    """
    return _switch_enabled("ZENAF_RECOGNITION_CARD_SECTIONS_GEN")


# ---------------------------------------------------------------------------
# Result types — assessment returns objects, never rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProgressionCandidate:
    """One validated progression for one thread, ready to propose."""

    thread_id: str
    #: The ThreadReading payload (proposal §4 schema, plus the
    #: sequence signature G4 dedupes on).
    reading: dict
    #: Thread-evidence row ids the reading cites, in step order.
    evidence_refs: tuple[str, ...]
    gate_trace: tuple[str, ...] = ()


@dataclass(frozen=True)
class FittingCandidate:
    """One lens proposed for one thread, with its matched signals."""

    thread_id: str
    lens_id: str
    evidence_refs: tuple[str, ...]
    #: (fit signal text, evidence row id) — the matched signals
    #: travel with the candidate so the review surface can show
    #: WHY this lens was suggested; the lens's cautions and source
    #: note ride along verbatim from the canon.
    matched_signals: tuple[tuple[str, str], ...]
    cautions: tuple[str, ...] = ()
    source_note: str = ""


@dataclass(frozen=True)
class CorrespondenceDetection:
    """One deterministic tension pair (Outlet C, pre-generation).

    A detection is not a candidate: it becomes one only when
    generation (behind its own switch) produces a validated
    structure for it. Detections are reported even when generation
    is off, so the deterministic half of the outlet is inspectable.
    """

    thread_a_id: str
    thread_b_id: str
    shared_entity_refs: tuple[str, ...]
    opposed_kinds: tuple[str, str]
    score: float
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class CorrespondenceCandidate:
    """One validated correspondence structure, ready to propose."""

    thread_ids: tuple[str, str]
    evidence_refs: tuple[str, ...]
    structural_tension: str
    proposed_relationship: str
    limitations: str
    candidate_metaphor: str | None = None
    mapping: dict | None = None


@dataclass(frozen=True)
class CardSectionCandidate:
    """One validated card abstraction for one thread (Outlet D).

    ``reading`` is the ThreadReading payload: the card sections
    (``structure`` / ``distinctions`` / ``tags``) alongside the
    existing tensions, open questions, and milestones, plus the
    kind marker, the sections signature S3 dedupes on, and the
    coverage note.
    """

    thread_id: str
    reading: dict
    #: Thread-evidence row ids the structure entries cite, in
    #: window order — the reading's evidence refs.
    evidence_refs: tuple[str, ...]
    gate_trace: tuple[str, ...] = ()


@dataclass
class RecognitionResult:
    """The outcome of one assessment or pass. Never a stored row."""

    candidates: list = field(default_factory=list)
    detections: list[CorrespondenceDetection] = field(default_factory=list)
    threads_examined: int = 0
    pairs_examined: int = 0
    generation_calls: int = 0
    #: Gate traces and abstention reasons, in order. A run that
    #: proposes nothing still explains itself.
    notes: list[str] = field(default_factory=list)

    @property
    def abstained(self) -> bool:
        """True when the assessment produced nothing proposable."""
        return not self.candidates

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": len(self.candidates),
            "detections": len(self.detections),
            "threads_examined": self.threads_examined,
            "pairs_examined": self.pairs_examined,
            "generation_calls": self.generation_calls,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Deterministic text matching (relevance.py idiom — local copies, so
# recognition stays readable without the derivation pipeline)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z][a-z0-9']+")
_MIN_TOKEN_LEN = 4
_TOKEN_COHESION_MIN = 2

_STOPWORDS = frozenset(
    {
        "about", "above", "across", "after", "again", "against", "also",
        "among", "another", "around", "because", "been", "before",
        "being", "below", "between", "both", "came", "come", "does",
        "doing", "done", "down", "each", "even", "ever", "every",
        "from", "have", "having", "here", "into", "just", "like",
        "made", "make", "many", "more", "most", "much", "must",
        "never", "only", "other", "ought", "over", "same", "such",
        "than", "that", "their", "them", "then", "there", "these",
        "they", "this", "those", "through", "under", "upon",
        "very", "want", "well", "were", "what", "when", "where",
        "which", "while", "will", "with", "within", "would",
        "your", "yours",
    }
)


def _stem(token: str) -> str:
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


# ---------------------------------------------------------------------------
# Window assembly — the whole-record bound, barrier-aware
# ---------------------------------------------------------------------------


def _barrier_cutoff(store: NarrativeStore, user_id: str) -> str | None:
    """The user's erasure boundary (ISO), or None when none stands."""
    try:
        tombstone = store.get_erasure_tombstone(user_id)
    except Exception:
        logger.exception("recognition: tombstone read failed; failing closed")
        return "9999"  # fail closed: everything is at-or-before this
    if not tombstone:
        return None
    return str(tombstone.get("erased_at") or "") or None


def _thread_window(
    store: NarrativeStore, user_id: str, thread_id: str, cutoff: str | None
) -> tuple[list[ThreadEvidence], list[ThreadChange], int]:
    """(window rows in order, changes, rows excluded by the barrier).

    The window is the thread's most recent ``MAX_EVIDENCE_WINDOW``
    evidence rows, in the store's evidence order. Changes are the
    thread's full change record (the bound covers evidence rows;
    changes are few and all are read).
    """
    rows = store.evidence_for(user_id, thread_id)
    excluded = 0
    if cutoff is not None:
        kept = [r for r in rows if (r.created_at or "") > cutoff]
        excluded = len(rows) - len(kept)
        rows = kept
    window = rows[-MAX_EVIDENCE_WINDOW:]
    changes = store.changes_for(user_id, thread_id)
    return window, changes, excluded


def _coverage_note(
    window: list[ThreadEvidence], *, truncated: bool, barrier_excluded: int
) -> dict:
    omitted = list(_STANDING_OMISSIONS)
    if truncated:
        omitted.append(
            f"evidence older than the {MAX_EVIDENCE_WINDOW}-row window"
        )
    if barrier_excluded:
        omitted.append("evidence at or before the erasure boundary")
    return {
        "evidence_examined": len(window),
        "span": [
            window[0].created_at if window else "",
            window[-1].created_at if window else "",
        ],
        "omitted_classes": omitted,
    }


def progression_signature(thread_id: str, rows: list[ThreadEvidence]) -> str:
    """Content-addressed signature of one sequence (G4).

    Mirrors derivation's signature grammar (sorted evidence keys),
    namespaced by its own ``progression:`` prefix. Consulted under
    the store's existing content-addressed dismissal regime (kind
    ``extension`` — the thread-scoped regime; DISMISSAL_KINDS is
    fixed store vocabulary and the prefix keeps this namespace
    disjoint from derivation's own signatures).
    """
    keys = sorted(f"{r.ref_kind}:{r.ref_id}" for r in rows)
    return f"progression:{thread_id}:" + "|".join(keys)


def card_sections_signature(
    thread_id: str, rows: list[ThreadEvidence]
) -> str:
    """Content-addressed signature of one evidence window (S3).

    Same grammar as :func:`progression_signature`, namespaced by
    its own ``card_sections:`` prefix so the two kinds' dedup
    namespaces stay disjoint. New evidence changes the signature
    and re-opens eligibility.
    """
    keys = sorted(f"{r.ref_kind}:{r.ref_id}" for r in rows)
    return f"card_sections:{thread_id}:" + "|".join(keys)


# ---------------------------------------------------------------------------
# Outlet B — fitting matching (deterministic, generation-free)
# ---------------------------------------------------------------------------


def _point_surface(row: ThreadEvidence) -> set[str]:
    """The matchable text of one evidence point: its note, its
    entity identity, and its ref identity. (The thread's title is
    NOT an evidence point and never matches a signal.)"""
    parts = [row.note or "", row.entity_ref or "", row.ref_id or ""]
    return _tokens(" ".join(parts))


def _match_lens(
    lens: NarrativeLens, window: list[ThreadEvidence]
) -> list[tuple[str, str]] | None:
    """Match a lens's fit signals to distinct evidence points.

    A signal matches a point when they share at least
    ``_TOKEN_COHESION_MIN`` distinctive tokens (relevance's bar).
    Greedy in signal order, each point serving at most one signal
    for this lens. Returns [(signal, row id)] when at least
    ``MIN_FIT_SIGNALS`` signals matched, else None.
    """
    surfaces = [_point_surface(row) for row in window]
    used: set[int] = set()
    matched: list[tuple[str, str]] = []
    for signal in lens.fit_signals:
        signal_tokens = _tokens(signal)
        if not signal_tokens:
            continue
        for idx, surface in enumerate(surfaces):
            if idx in used:
                continue
            if len(signal_tokens & surface) >= _TOKEN_COHESION_MIN:
                matched.append((signal, window[idx].id))
                used.add(idx)
                break
    if len(matched) >= MIN_FIT_SIGNALS:
        return matched
    return None


def _assess_fittings(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    window: list[ThreadEvidence],
    result: RecognitionResult,
) -> None:
    """Outlet B for one thread: append fitting candidates.

    Dedupe is deterministic and mirrors the store: a lens already
    proposed/offered/accepted on the same evidence set is not
    re-proposed, and a lens+evidence set matching a REJECTED
    fitting is skipped here (F2 — the store would refuse it; the
    assessment surfaces the refusal as abstention instead).
    """
    if not window:
        return
    existing = store.fittings_for(user_id, thread_id)
    for lens in LENSES:
        matched = _match_lens(lens, window)
        if matched is None:
            continue
        evidence_ids = tuple(row_id for _, row_id in matched)
        evidence_set = set(evidence_ids)
        skip = False
        for fitting in existing:
            if fitting.lens_id != lens.id:
                continue
            if set(fitting.evidence_refs or []) != evidence_set:
                continue
            # Same lens, same evidence: any standing status means
            # this exact proposal already exists in some decided
            # or pending form — proposed/offered/accepted would
            # duplicate; rejected is F2's durable refusal.
            skip = True
            if fitting.status == "rejected":
                result.notes.append(
                    f"fitting {lens.id} on {thread_id}: rejected on "
                    "this evidence — durable (F2), not re-proposed"
                )
            break
        if skip:
            continue
        result.candidates.append(
            FittingCandidate(
                thread_id=thread_id,
                lens_id=lens.id,
                evidence_refs=evidence_ids,
                matched_signals=tuple(matched),
                cautions=tuple(lens.cautions),
                source_note=lens.source_note,
            )
        )


# ---------------------------------------------------------------------------
# Outlet A — progression assessment (gated, at most one generation)
# ---------------------------------------------------------------------------

_PROGRESSION_PROMPT = """\
You are the Narrative Steward's slow-path analyst. You do NOT speak
to the user and you are not any council voice. Below is one thread's
evidence in chronological order. Propose, in plain system language,
whether these records form a progression — one story developing
over time — and exactly what developed.

Evidence (chronological):
{evidence}

Intervening movements recorded on the thread: {movements}
{contradiction_block}
If these records do NOT form a progression (a theme merely
recurring, or unrelated records), reply with exactly:
NONE

Otherwise reply with exactly one JSON object and nothing else:
{{"steps": [{{"evidence_refs": ["<evidence row id>", ...],
"observation": "what the record shows at this point"}}],
"development_claim": "the proposed development, stated as
interpretation", "rivals": {{"recurrence": "why this might be a
theme returning, addressed honestly", "coincidence": "why these
might be unrelated, addressed honestly"}}, "contradiction":
{{"evidence_refs": ["<evidence row id>", ...], "note": "how the
contradiction bears on the sequence"}} or null}}

Rules: at least three steps, in chronological order; every step
cites evidence row ids from the list above and nothing else;
observations state only what the record shows — the interpretation
lives in development_claim alone; chronology is not causation;
never invent facts, people, or events. Keep every string short.
"""


def _render_evidence(rows: list[ThreadEvidence]) -> str:
    lines = []
    for i, row in enumerate(rows, 1):
        text = (row.note or "").strip()
        if not text:
            text = "(record with no words)"
        about = f" about {row.entity_ref}" if row.entity_ref else ""
        lines.append(
            f"{i}. [{row.id}] ({row.ref_kind}:{row.ref_id}, "
            f"{row.created_at}){about} {text[:600]}"
        )
    return "\n".join(lines)


def _parse_progression(
    raw: str | None,
    *,
    window: list[ThreadEvidence],
    flagged_contradiction_refs: set[str],
) -> dict | None:
    """Parse + validate a progression generation, or None = discard.

    Deterministic validation (proposal §2 step 4): every step cites
    at least one ref from the input set; steps are in chronological
    order (each step's refs lie strictly after the previous step's);
    at least three steps; the development claim stands apart from
    the observations; both rivals are addressed; a G3-flagged
    contradiction is cited (in the contradiction field AND in a
    step) and addressed. Any failure discards the whole candidate —
    no partial proposal is ever written.
    """
    text = (raw or "").strip()
    if not text or text.upper() == "NONE" or text.upper().startswith("NONE\n"):
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    positions = {row.id: idx for idx, row in enumerate(window)}
    steps_in = data.get("steps")
    if not isinstance(steps_in, list) or len(steps_in) < MIN_PROGRESSION_POINTS:
        return None
    steps: list[dict] = []
    cited: list[str] = []
    last_max = -1
    for step in steps_in:
        if not isinstance(step, dict):
            return None
        refs = step.get("evidence_refs")
        observation = step.get("observation")
        if (
            not isinstance(refs, list)
            or not refs
            or not all(isinstance(r, str) for r in refs)
            or not isinstance(observation, str)
            or not observation.strip()
        ):
            return None
        if any(r not in positions for r in refs):
            return None  # citation outside the input set
        step_positions = [positions[r] for r in refs]
        if min(step_positions) <= last_max:
            return None  # out of chronological order
        last_max = max(step_positions)
        steps.append(
            {"evidence_refs": list(refs), "observation": observation.strip()}
        )
        cited.extend(refs)
    claim = data.get("development_claim")
    if not isinstance(claim, str) or not claim.strip():
        return None
    rivals = data.get("rivals")
    if not isinstance(rivals, dict):
        return None
    recurrence = rivals.get("recurrence")
    coincidence = rivals.get("coincidence")
    if not (
        isinstance(recurrence, str)
        and recurrence.strip()
        and isinstance(coincidence, str)
        and coincidence.strip()
    ):
        return None
    contradiction = data.get("contradiction")
    if flagged_contradiction_refs:
        if not isinstance(contradiction, dict):
            return None
        contra_refs = contradiction.get("evidence_refs")
        note = contradiction.get("note")
        if (
            not isinstance(contra_refs, list)
            or not all(isinstance(r, str) for r in contra_refs)
            or not flagged_contradiction_refs.issubset(set(contra_refs))
            or not isinstance(note, str)
            or not note.strip()
        ):
            return None
        if not flagged_contradiction_refs.intersection(cited):
            return None  # the contradiction must appear as a step
        contradiction = {
            "evidence_refs": list(contra_refs),
            "note": note.strip(),
        }
    elif contradiction is not None:
        if not isinstance(contradiction, dict):
            return None
        contra_refs = contradiction.get("evidence_refs")
        if (
            not isinstance(contra_refs, list)
            or any(r not in positions for r in contra_refs)
        ):
            return None
        contradiction = {
            "evidence_refs": list(contra_refs),
            "note": str(contradiction.get("note") or "").strip(),
        }
    out: dict[str, Any] = {
        "kind": PROGRESSION_READING_KIND,
        "steps": steps,
        "development_claim": claim.strip(),
        "rivals": {
            "recurrence": recurrence.strip(),
            "coincidence": coincidence.strip(),
        },
    }
    if contradiction is not None:
        out["contradiction"] = contradiction
    out["_cited_refs"] = cited
    return out


def _assess_progression(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    window: list[ThreadEvidence],
    changes: list[ThreadChange],
    *,
    generate_fn: Callable | None,
    truncated: bool,
    barrier_excluded: int,
    result: RecognitionResult,
) -> None:
    """Outlet A for one thread: gates G1–G4, then ≤1 generation."""
    trace: list[str] = []
    positions = {row.id: idx for idx, row in enumerate(window)}

    # G1 — multiplicity and separation.
    days = {(row.created_at or "")[:10] for row in window}
    if len(window) < MIN_PROGRESSION_POINTS or len(days) < MIN_PROGRESSION_DAYS:
        result.notes.append(
            f"progression on {thread_id}: G1 abstain "
            f"({len(window)} points across {len(days)} day(s))"
        )
        return
    trace.append(
        f"G1 pass ({len(window)} points across {len(days)} days)"
    )

    # G2 — intervening typed movement.
    movement = [
        change
        for change in changes
        if change.kind in _MOVEMENT_KINDS
        and change.status in _MOVEMENT_STATUSES
        and any(
            positions.get(ref, -1) > 0 for ref in (change.evidence_refs or [])
        )
    ]
    if not movement:
        result.notes.append(
            f"progression on {thread_id}: G2 abstain "
            "(no intervening movement — recurrence is not progression)"
        )
        return
    trace.append(
        "G2 pass (movement: "
        + ", ".join(sorted({c.kind for c in movement}))
        + ")"
    )

    # G3 — contradiction screen: a confirmed contradicted change
    # touching the window flags its evidence; the flag travels into
    # the generation input and validation (§2 step 4).
    flagged: set[str] = set()
    for change in changes:
        if change.kind == "contradicted" and change.status == "confirmed":
            flagged.update(
                ref for ref in (change.evidence_refs or []) if ref in positions
            )
    if flagged:
        trace.append(
            f"G3 flagged contradiction on {len(flagged)} evidence row(s)"
        )

    # G4 — dismissal memory + prior progression readings. A
    # sequence already proposed, standing, or rejected on this
    # window is not proposed again; new evidence changes the
    # signature and re-opens eligibility.
    signature = progression_signature(thread_id, window)
    window_ids = {row.id for row in window}
    try:
        if store.is_dismissed(
            user_id, kind="extension", signature=signature
        ):
            result.notes.append(
                f"progression on {thread_id}: G4 abstain (dismissed)"
            )
            return
    except ValueError:
        pass  # unknown kind regimes never block assessment
    for reading in store.readings_for(user_id, thread_id):
        payload = reading.reading or {}
        if payload.get("kind") != PROGRESSION_READING_KIND:
            continue
        if payload.get("sequence_signature") == signature:
            result.notes.append(
                f"progression on {thread_id}: G4 abstain "
                f"(sequence already {reading.status})"
            )
            return
        if reading.status == "rejected" and window_ids.issubset(
            set(reading.evidence_refs or [])
        ):
            result.notes.append(
                f"progression on {thread_id}: G4 abstain "
                "(rejected on this evidence)"
            )
            return
    trace.append("G4 pass")

    if generate_fn is None:
        result.notes.append(
            f"progression on {thread_id}: gates pass, no generation "
            "injected — no candidate"
        )
        return

    movements_text = ", ".join(
        f"{c.kind} (citing {', '.join(c.evidence_refs or [])})"
        for c in movement
    )
    contradiction_block = ""
    if flagged:
        contradiction_block = (
            "\nContradiction on record: a confirmed change marks "
            "this evidence contradicted: "
            + ", ".join(sorted(flagged))
            + ". A candidate that ignores it will be discarded.\n"
        )
    prompt = _PROGRESSION_PROMPT.format(
        evidence=_render_evidence(window),
        movements=movements_text,
        contradiction_block=contradiction_block,
    )
    try:
        raw = generate_fn(
            prompt,
            provider_id="meta",
            user_id=user_id or None,
            operation="narrative-recognition",
            timeout=60,
        )
    except Exception:
        logger.exception(
            "recognition: progression generation failed for %s", thread_id
        )
        result.notes.append(
            f"progression on {thread_id}: generation failed — no candidate"
        )
        return
    result.generation_calls += 1
    parsed = _parse_progression(
        raw, window=window, flagged_contradiction_refs=flagged
    )
    if parsed is None:
        result.notes.append(
            f"progression on {thread_id}: generation declined or "
            "failed validation — no candidate"
        )
        return
    cited = parsed.pop("_cited_refs")
    parsed["sequence_signature"] = signature
    parsed["coverage"] = _coverage_note(
        window, truncated=truncated, barrier_excluded=barrier_excluded
    )
    ordered_refs = tuple(sorted(set(cited), key=positions.__getitem__))
    result.candidates.append(
        ProgressionCandidate(
            thread_id=thread_id,
            reading=parsed,
            evidence_refs=ordered_refs,
            gate_trace=tuple(trace),
        )
    )


def assess_thread(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    *,
    generate_fn: Callable | None = None,
) -> RecognitionResult:
    """Assess one thread (Outlets B + A). Writes nothing.

    Fittings are assessed first (deterministic, free); the
    progression outlet runs its gates and generates at most once.
    The result carries every candidate plus the gate traces that
    explain any abstention.
    """
    result = RecognitionResult(threads_examined=1)
    thread = store.get_thread(user_id, thread_id)
    if thread is None:
        result.notes.append(f"thread {thread_id}: not found — abstain")
        return result
    cutoff = _barrier_cutoff(store, user_id)
    total_rows = len(store.evidence_for(user_id, thread_id))
    window, changes, barrier_excluded = _thread_window(
        store, user_id, thread_id, cutoff
    )
    truncated = (total_rows - barrier_excluded) > MAX_EVIDENCE_WINDOW
    _assess_fittings(store, user_id, thread_id, window, result)
    _assess_progression(
        store,
        user_id,
        thread_id,
        window,
        changes,
        generate_fn=generate_fn,
        truncated=truncated,
        barrier_excluded=barrier_excluded,
        result=result,
    )
    return result


# ---------------------------------------------------------------------------
# Outlet C — correspondence detection + bounded generation
# ---------------------------------------------------------------------------

_CORRESPONDENCE_PROMPT = """\
You are the Narrative Steward's slow-path analyst. You do NOT speak
to the user and you are not any council voice. Two of the user's
threads share an entity, and their recorded movements stand in
opposition. Propose, in plain system language, the STRUCTURE of
that tension — a correspondence the user may find illuminating —
or decline.

Thread A evidence:
{evidence_a}

Thread B evidence:
{evidence_b}

Opposed movements: {opposed}

If the shared entity does not establish a meaningful tension
between these observations, reply with exactly:
NONE

Otherwise reply with exactly one JSON object and nothing else:
{{"structural_tension": "the shape of the tension, stated plainly",
"proposed_relationship": "how the two observations relate",
"candidate_metaphor": "an optional illustrative metaphor, or null",
"mapping": {{"<element>": "<what it parallels>"}},
"limitations": "where the analogy breaks down — required, and
substantive: a framing without a breakdown imposes meaning"}}

Rules: cite no evidence beyond what is shown; invent no facts,
people, or events; the metaphor is illustrative only and is never
evidence for the relationship. Keep every string short.
"""


def _opposed_kinds(
    kinds_a: set[str], kinds_b: set[str]
) -> tuple[str, str] | None:
    """The opposed change shape between two threads, or None."""
    for kind_x, kind_y in _OPPOSED_PAIRS:
        if kind_x in kinds_a and kind_y in kinds_b:
            return (kind_x, kind_y)
        if kind_y in kinds_a and kind_x in kinds_b:
            return (kind_y, kind_x)
    return None


def _live_change_kinds(
    store: NarrativeStore, user_id: str, thread_id: str
) -> set[str]:
    """Change kinds standing on a thread (proposed or confirmed —
    a dismissed change is not a movement the record stands by)."""
    return {
        change.kind
        for change in store.changes_for(user_id, thread_id)
        if change.status in _MOVEMENT_STATUSES
    }


def _parse_correspondence(raw: str | None) -> dict | None:
    """Parse + validate a correspondence generation, or None.

    C2 lives here: limitations must be present and substantive
    before ``propose_correspondence`` is ever called (that module
    re-enforces the same abstention on its own side).
    """
    text = (raw or "").strip()
    if not text or text.upper() == "NONE" or text.upper().startswith("NONE\n"):
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    tension = data.get("structural_tension")
    relationship = data.get("proposed_relationship")
    limitations = data.get("limitations")
    if not (isinstance(tension, str) and tension.strip()):
        return None
    if not (isinstance(relationship, str) and relationship.strip()):
        return None
    if not (
        isinstance(limitations, str)
        and len(limitations.strip()) >= MIN_LIMITATIONS_CHARS
    ):
        return None
    metaphor = data.get("candidate_metaphor")
    if metaphor is not None and not isinstance(metaphor, str):
        return None
    mapping = data.get("mapping")
    if mapping is not None and not isinstance(mapping, dict):
        return None
    return {
        "structural_tension": tension.strip(),
        "proposed_relationship": relationship.strip(),
        "candidate_metaphor": (metaphor or "").strip() or None,
        "mapping": mapping,
        "limitations": limitations.strip(),
    }


def assess_pairs(
    store: NarrativeStore,
    user_id: str,
    *,
    generate_fn: Callable | None = None,
) -> RecognitionResult:
    """Assess thread pairs for correspondences (Outlet C).

    Deterministic detection always runs (C1); detections are
    reported on the result. Generation happens only when the
    outlet's own switch is on and a ``generate_fn`` is injected,
    and only for the single strongest detection (rarity score,
    discovery's arithmetic). Writes nothing.
    """
    result = RecognitionResult()
    threads = _live_threads(store, user_id)
    result.threads_examined = len(threads)
    ref_maps = {
        thread.id: _thread_ref_map(store, user_id, thread.id)
        for thread in threads
    }
    ref_thread_count: dict[str, int] = {}
    for mapping in ref_maps.values():
        for ref in mapping:
            ref_thread_count[ref] = ref_thread_count.get(ref, 0) + 1
    kinds_by_thread = {
        thread.id: _live_change_kinds(store, user_id, thread.id)
        for thread in threads
    }
    existing = store.correspondences_for(user_id)
    detections: list[CorrespondenceDetection] = []
    for i, thread_a in enumerate(threads):
        for thread_b in threads[i + 1 :]:
            result.pairs_examined += 1
            shared = sorted(
                set(ref_maps[thread_a.id]) & set(ref_maps[thread_b.id])
            )
            if not shared:
                continue
            opposed = _opposed_kinds(
                kinds_by_thread[thread_a.id], kinds_by_thread[thread_b.id]
            )
            if opposed is None:
                continue
            evidence_refs: list[str] = []
            for ref in shared:
                for thread in (thread_a, thread_b):
                    row = ref_maps[thread.id][ref][0]
                    if row.id not in evidence_refs:
                        evidence_refs.append(row.id)
            # Idempotency / durable rejection: the same pair on the
            # same evidence already has its correspondence, in
            # whatever decided or pending form; identical content
            # is not proposed twice.
            already = any(
                set(corr.thread_ids or []) == {thread_a.id, thread_b.id}
                and set(corr.evidence_refs or []) == set(evidence_refs)
                for corr in existing
            )
            if already:
                continue
            score = sum(2.0 / ref_thread_count[ref] for ref in shared)
            detections.append(
                CorrespondenceDetection(
                    thread_a_id=thread_a.id,
                    thread_b_id=thread_b.id,
                    shared_entity_refs=tuple(shared),
                    opposed_kinds=opposed,
                    score=score,
                    evidence_refs=tuple(evidence_refs),
                )
            )
    detections.sort(key=lambda d: (-d.score, d.thread_a_id, d.thread_b_id))
    result.detections = detections
    if not detections:
        result.notes.append("correspondence: no tension pair — abstain")
        return result
    if not correspondence_generation_enabled():
        result.notes.append(
            "correspondence: detection recorded; generation switch "
            "off — nothing generated, nothing proposed"
        )
        return result
    if generate_fn is None:
        result.notes.append(
            "correspondence: detection recorded; no generation "
            "injected — nothing proposed"
        )
        return result
    detection = detections[0]
    rows_a = store.evidence_for(user_id, detection.thread_a_id)
    rows_b = store.evidence_for(user_id, detection.thread_b_id)
    wanted = set(detection.evidence_refs)
    prompt = _CORRESPONDENCE_PROMPT.format(
        evidence_a=_render_evidence(
            [r for r in rows_a if r.id in wanted] or rows_a[:5]
        ),
        evidence_b=_render_evidence(
            [r for r in rows_b if r.id in wanted] or rows_b[:5]
        ),
        opposed=(
            f"{detection.opposed_kinds[0]} on one thread against "
            f"{detection.opposed_kinds[1]} on the other, over "
            + ", ".join(detection.shared_entity_refs)
        ),
    )
    try:
        raw = generate_fn(
            prompt,
            provider_id="meta",
            user_id=user_id or None,
            operation="narrative-recognition",
            timeout=60,
        )
    except Exception:
        logger.exception("recognition: correspondence generation failed")
        result.notes.append(
            "correspondence: generation failed — no candidate"
        )
        return result
    result.generation_calls += 1
    parsed = _parse_correspondence(raw)
    if parsed is None:
        result.notes.append(
            "correspondence: generation declined or failed "
            "validation (C2) — no candidate"
        )
        return result
    result.candidates.append(
        CorrespondenceCandidate(
            thread_ids=(detection.thread_a_id, detection.thread_b_id),
            evidence_refs=detection.evidence_refs,
            structural_tension=parsed["structural_tension"],
            proposed_relationship=parsed["proposed_relationship"],
            limitations=parsed["limitations"],
            candidate_metaphor=parsed["candidate_metaphor"],
            mapping=parsed["mapping"],
        )
    )
    return result


# ---------------------------------------------------------------------------
# Outlet D — card sections (Story-First Phase 1B)
# ---------------------------------------------------------------------------

_CARD_SECTIONS_PROMPT = """\
You are the Narrative Steward's slow-path analyst. You do NOT speak
to the user and you are not any council voice. Below is one thread's
evidence in chronological order. Abstract, in plain system language,
the STRUCTURE of the narrative these records form — the sections of
the personal card the Steward keeps of this story — or decline.

Evidence (chronological):
{evidence}

Movements recorded on the thread: {movements}

If these records do not yet form a structure worth abstracting
(a single note, or a theme with no shape), reply with exactly:
NONE

Otherwise reply with exactly one JSON object and nothing else:
{{"structure": {{"roles": [{{"text": "who or what fills a role in
this story", "evidence_refs": ["<evidence row id>", ...]}}],
"relationships": [{{"text": "...", "evidence_refs": [...]}}],
"conflicts": [{{"text": "...", "evidence_refs": [...]}}],
"reversals": [{{"text": "...", "evidence_refs": [...]}}],
"sacrifices": [{{"text": "...", "evidence_refs": [...]}}],
"consequences": [{{"text": "...", "evidence_refs": [...]}}],
"changes_over_time": [{{"text": "...", "evidence_refs": [...]}}]}},
"distinctions": ["what this narrative is NOT, on this evidence"],
"tags": ["short structural tag", "..."],
"tensions": ["..."], "open_questions": ["..."],
"milestones": ["..."]}}

Rules: every structure entry cites evidence row ids from the list
above and nothing else; a structure field with no supported entry
is an empty list — never invent an entry to fill a field;
distinctions state readings the evidence does not support,
comparisons that would mislead, or boundaries the user has
stated — at least one, addressed honestly; tags derive from the
structure alone; the structure is an interpretation of the story,
never a fact about the user; never invent facts, people, or
events. Keep every string short.
"""


def _string_list(value: Any) -> list[str] | None:
    """A list of non-empty strings, normalized, or None."""
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        out.append(item.strip())
    return out


def _parse_card_sections(
    raw: str | None,
    *,
    window: list[ThreadEvidence],
) -> dict | None:
    """Parse + validate a card-section generation, or None.

    Deterministic validation, mirroring the progression parser:
    every structure entry cites at least one ref from the input
    set; at least one structure entry exists across the block's
    fields; distinctions are present and addressed (at least
    one); tags derive and are present; the existing reading
    fields are string lists when present. Any failure discards
    the whole candidate — no partial card is ever written.
    """
    text = (raw or "").strip()
    if not text or text.upper() == "NONE" or text.upper().startswith("NONE\n"):
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    positions = {row.id: idx for idx, row in enumerate(window)}

    structure_in = data.get("structure")
    if not isinstance(structure_in, dict):
        return None
    if any(key not in STRUCTURE_FIELDS for key in structure_in):
        return None  # a field outside the block's shape
    structure: dict[str, list[dict]] = {}
    cited: list[str] = []
    entries = 0
    for field_name in STRUCTURE_FIELDS:
        raw_entries = structure_in.get(field_name) or []
        if not isinstance(raw_entries, list):
            return None
        cleaned: list[dict] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                return None
            entry_text = entry.get("text")
            refs = entry.get("evidence_refs")
            if (
                not isinstance(entry_text, str)
                or not entry_text.strip()
                or not isinstance(refs, list)
                or not refs
                or not all(isinstance(r, str) for r in refs)
            ):
                return None
            if any(r not in positions for r in refs):
                return None  # citation outside the input set
            cleaned.append(
                {
                    "text": entry_text.strip(),
                    "evidence_refs": list(refs),
                }
            )
            cited.extend(refs)
            entries += 1
        structure[field_name] = cleaned
    if entries == 0:
        return None  # a structure block with no entries is no card

    distinctions = _string_list(data.get("distinctions"))
    if not distinctions:
        return None  # the section must be addressed, honestly
    tags = _string_list(data.get("tags"))
    if not tags:
        return None  # tags derive from the structure; none, no card

    out: dict[str, Any] = {
        "kind": CARD_SECTIONS_READING_KIND,
        "structure": structure,
        "distinctions": distinctions,
        "tags": tags,
    }
    for key in ("tensions", "open_questions", "milestones"):
        value = data.get(key)
        if value is None:
            out[key] = []
            continue
        cleaned_list = _string_list(value)
        if cleaned_list is None:
            return None
        out[key] = cleaned_list
    out["_cited_refs"] = cited
    return out


def assess_card_sections(
    store: NarrativeStore,
    user_id: str,
    thread_id: str,
    *,
    generate_fn: Callable | None = None,
) -> RecognitionResult:
    """Assess one thread for a card abstraction (Outlet D).

    The deterministic pre-filter runs first and always (S1–S3):
    card-shaped structure is detectable in the evidence without
    any model call, and a failed gate abstains before generation
    is even considered. Generation happens only when the outlet's
    own switch is on and a ``generate_fn`` is injected, and at
    most once. Writes nothing.
    """
    result = RecognitionResult(threads_examined=1)
    thread = store.get_thread(user_id, thread_id)
    if thread is None:
        result.notes.append(f"thread {thread_id}: not found — abstain")
        return result
    cutoff = _barrier_cutoff(store, user_id)
    total_rows = len(store.evidence_for(user_id, thread_id))
    window, changes, barrier_excluded = _thread_window(
        store, user_id, thread_id, cutoff
    )
    truncated = (total_rows - barrier_excluded) > MAX_EVIDENCE_WINDOW
    trace: list[str] = []

    # S1 — multiplicity and separation (G1's shape): one mention
    # is not a structure, and a structure spans more than a day.
    days = {(row.created_at or "")[:10] for row in window}
    if (
        len(window) < MIN_CARD_SECTION_POINTS
        or len(days) < MIN_CARD_SECTION_DAYS
    ):
        result.notes.append(
            f"card sections on {thread_id}: S1 abstain "
            f"({len(window)} points across {len(days)} day(s))"
        )
        return result
    trace.append(
        f"S1 pass ({len(window)} points across {len(days)} days)"
    )

    # S2 — detectable structural material, no model call: either
    # more than one subject stands in the record (relationships
    # and roles need relata) or the thread carries recorded
    # movement (a change over time is itself structural).
    entity_refs = {row.entity_ref for row in window if row.entity_ref}
    structural_changes = [
        change
        for change in changes
        if change.kind in _STRUCTURAL_CHANGE_KINDS
        and change.status in _MOVEMENT_STATUSES
    ]
    if len(entity_refs) < 2 and not structural_changes:
        result.notes.append(
            f"card sections on {thread_id}: S2 abstain "
            "(single subject, no recorded movement — no structure "
            "detectable in the record)"
        )
        return result
    trace.append(
        "S2 pass ("
        + (
            f"{len(entity_refs)} subjects"
            if len(entity_refs) >= 2
            else "recorded movement: "
            + ", ".join(sorted({c.kind for c in structural_changes}))
        )
        + ")"
    )

    # S3 — dedup against the thread's own card readings (G4's
    # reading-based discipline; the store's dismissal vocabulary
    # has no card kind and this outlet adds none): a card already
    # standing on this exact evidence is not re-proposed, and a
    # card the visitor rejected on evidence covering this window
    # is durably refused. New evidence changes the signature and
    # re-opens eligibility.
    signature = card_sections_signature(thread_id, window)
    window_ids = {row.id for row in window}
    for reading in store.readings_for(user_id, thread_id):
        payload = reading.reading or {}
        if payload.get("kind") != CARD_SECTIONS_READING_KIND:
            continue
        if (
            payload.get("sections_signature") == signature
            and reading.status in ("proposed", "accepted")
        ):
            result.notes.append(
                f"card sections on {thread_id}: S3 abstain "
                f"(card already {reading.status} on this evidence)"
            )
            return result
        if reading.status == "rejected" and (
            payload.get("sections_signature") == signature
            or window_ids.issubset(set(reading.evidence_refs or []))
        ):
            result.notes.append(
                f"card sections on {thread_id}: S3 abstain "
                "(rejected on this evidence)"
            )
            return result
    trace.append("S3 pass")

    if not card_sections_generation_enabled():
        result.notes.append(
            f"card sections on {thread_id}: pre-filter passed; "
            "generation switch off — nothing generated, "
            "nothing proposed"
        )
        return result
    if generate_fn is None:
        result.notes.append(
            f"card sections on {thread_id}: pre-filter passed; "
            "no generation injected — no candidate"
        )
        return result

    movements_text = (
        ", ".join(
            f"{c.kind} (citing {', '.join(c.evidence_refs or [])})"
            for c in structural_changes
        )
        or "none recorded"
    )
    prompt = _CARD_SECTIONS_PROMPT.format(
        evidence=_render_evidence(window),
        movements=movements_text,
    )
    try:
        raw = generate_fn(
            prompt,
            provider_id="meta",
            user_id=user_id or None,
            operation="narrative-recognition",
            timeout=60,
        )
    except Exception:
        logger.exception(
            "recognition: card-section generation failed for %s",
            thread_id,
        )
        result.notes.append(
            f"card sections on {thread_id}: generation failed — "
            "no candidate"
        )
        return result
    result.generation_calls += 1
    parsed = _parse_card_sections(raw, window=window)
    if parsed is None:
        result.notes.append(
            f"card sections on {thread_id}: generation declined "
            "or failed validation — no candidate"
        )
        return result
    cited = parsed.pop("_cited_refs")
    parsed["sections_signature"] = signature
    parsed["coverage"] = _coverage_note(
        window, truncated=truncated, barrier_excluded=barrier_excluded
    )
    positions = {row.id: idx for idx, row in enumerate(window)}
    ordered_refs = tuple(sorted(set(cited), key=positions.__getitem__))
    result.candidates.append(
        CardSectionCandidate(
            thread_id=thread_id,
            reading=parsed,
            evidence_refs=ordered_refs,
            gate_trace=tuple(trace),
        )
    )
    return result


# ---------------------------------------------------------------------------
# Proposal — the only writer, through existing transitions only
# ---------------------------------------------------------------------------


def _evidence_keys_for(
    store: NarrativeStore,
    user_id: str,
    thread_ids: tuple[str, ...] | list[str],
    row_ids: tuple[str, ...] | list[str],
) -> list[str]:
    """Content keys ("<kind>:<id>") for cited evidence row ids,
    resolved over the given threads — the grounds half of a
    dismissal signature, addressed by ref so rebuilt rows (new
    row ids, same refs) key identically. Unresolvable ids are
    absent, never invented."""
    wanted = set(row_ids)
    keys_by_row_id: dict[str, str] = {}
    for thread_id in thread_ids:
        for row in store.evidence_for(user_id, thread_id):
            if row.id in wanted:
                keys_by_row_id[row.id] = (
                    f"{row.ref_kind}:{row.ref_id}"
                )
    return [keys_by_row_id[r] for r in row_ids if r in keys_by_row_id]


def _is_dismissed(
    store: NarrativeStore, user_id: str, *, kind: str, signature: str
) -> bool:
    """Consult dismissal memory, failure-isolated.

    A failed check is logged and treated as not dismissed — the
    same direction the review side's dismissal write fails
    (PR #440): the memory layer never breaks the primary act.
    The decided proposal's terminal status is the first layer;
    this check is the second, against re-proposal.
    """
    try:
        return store.is_dismissed(user_id, kind=kind, signature=signature)
    except Exception:
        logger.exception(
            "recognition: dismissal check failed for %s; "
            "proposing without it",
            kind,
        )
        return False


def propose_all(
    store: NarrativeStore, user_id: str, result: RecognitionResult
) -> list[str]:
    """Write a result's candidates as proposals. Returns their ids.

    Each candidate goes through exactly one existing transition —
    ``propose_reading`` for progressions and card sections,
    ``set_fitting`` (status proposed, proposed_by steward) for
    fittings, ``propose_correspondence`` for correspondences. A
    store refusal (e.g. F2's durable-rejection raise) is logged
    and skipped: a refused proposal leaves no row and never fails
    the pass.

    Dismissal memory is consulted HERE — at the final
    proposal-write, per candidate, immediately before its write
    (Consultation 1 disposition, 2026-11-25) — for the two kinds
    that carry it: fittings and correspondences. A rejection
    recorded while this pass was still assessing therefore gates
    the equivalent candidate in this same pass. The check lives
    only on this autonomous path: the shared writers
    (``set_fitting``, ``propose_correspondence``) consult no
    dismissal state, so a visitor-initiated proposal is never
    barred by it.
    """
    written: list[str] = []
    for candidate in result.candidates:
        try:
            if isinstance(candidate, ProgressionCandidate):
                reading = store.propose_reading(
                    user_id,
                    candidate.thread_id,
                    author="steward",
                    reading=candidate.reading,
                    evidence_refs=list(candidate.evidence_refs),
                )
                written.append(reading.id)
            elif isinstance(candidate, CardSectionCandidate):
                reading = store.propose_reading(
                    user_id,
                    candidate.thread_id,
                    author="steward",
                    reading=candidate.reading,
                    evidence_refs=list(candidate.evidence_refs),
                )
                written.append(reading.id)
            elif isinstance(candidate, FittingCandidate):
                signature = fitting_signature_from_keys(
                    candidate.thread_id,
                    candidate.lens_id,
                    _evidence_keys_for(
                        store,
                        user_id,
                        (candidate.thread_id,),
                        candidate.evidence_refs,
                    ),
                )
                if _is_dismissed(
                    store, user_id, kind="fitting", signature=signature
                ):
                    logger.info(
                        "recognition: fitting proposal dismissed "
                        "by verdict memory; skipped"
                    )
                    continue
                fitting = store.set_fitting(
                    user_id,
                    candidate.thread_id,
                    lens_id=candidate.lens_id,
                    evidence_refs=list(candidate.evidence_refs),
                    proposed_by="steward",
                    status="proposed",
                )
                written.append(fitting.id)
            elif isinstance(candidate, CorrespondenceCandidate):
                signature = correspondence_signature_from_fields(
                    candidate.thread_ids,
                    candidate.proposed_relationship,
                    candidate.mapping,
                    _evidence_keys_for(
                        store,
                        user_id,
                        candidate.thread_ids,
                        candidate.evidence_refs,
                    ),
                )
                if _is_dismissed(
                    store,
                    user_id,
                    kind="correspondence",
                    signature=signature,
                ):
                    logger.info(
                        "recognition: correspondence proposal "
                        "dismissed by verdict memory; skipped"
                    )
                    continue
                outcome = propose_correspondence(
                    store,
                    user_id,
                    evidence_refs=list(candidate.evidence_refs),
                    structural_tension=candidate.structural_tension,
                    proposed_relationship=candidate.proposed_relationship,
                    candidate_metaphor=candidate.candidate_metaphor,
                    mapping=candidate.mapping,
                    limitations=candidate.limitations,
                )
                if outcome.correspondence is not None:
                    written.append(outcome.correspondence.id)
                else:
                    logger.info(
                        "recognition: correspondence abstained at "
                        "write time: %s",
                        outcome.abstention_reason,
                    )
        except ValueError:
            logger.exception(
                "recognition: proposal refused by the store; skipped"
            )
    return written


# ---------------------------------------------------------------------------
# The pass — what the sweep calls
# ---------------------------------------------------------------------------


class _CallBudget:
    """A generate_fn wrapper enforcing a per-pass call cap.

    Past the cap the wrapper declines (``NONE``) without calling
    the wrapped function — budget exhaustion reads exactly like a
    generator decline downstream: no candidate, no row.
    """

    def __init__(self, fn: Callable | None, limit: int) -> None:
        self._fn = fn
        self._limit = limit
        self.used = 0

    def __call__(self, prompt: str, **kwargs: Any) -> str:
        if self._fn is None or self.used >= self._limit:
            return "NONE"
        self.used += 1
        return self._fn(prompt, **kwargs)


def run_recognition_pass(
    store: NarrativeStore,
    user_id: str,
    *,
    generate_fn: Callable | None = None,
) -> RecognitionResult:
    """One recognition pass for one user: assess + propose.

    Gated on the master switch (the sweep also gates; this is the
    second lock on the same door). Per-thread failures are logged
    and swallowed — a failed proposal can never break the sweep
    operation that produced the evidence (derivation's control
    invariant). Generation is budgeted per pass: progressions ≤
    ``MAX_PROGRESSION_GENERATIONS_PER_PASS``, correspondences ≤
    ``MAX_CORRESPONDENCE_GENERATIONS_PER_PASS``, card sections ≤
    ``MAX_CARD_SECTION_GENERATIONS_PER_PASS`` (and Outlets C and
    D additionally require their own switches, inside their
    assess functions).
    """
    merged = RecognitionResult()
    if not recognition_enabled():
        merged.notes.append("recognition switch off — pass skipped")
        return merged
    progression_budget = _CallBudget(
        generate_fn, MAX_PROGRESSION_GENERATIONS_PER_PASS
    )
    correspondence_budget = _CallBudget(
        generate_fn, MAX_CORRESPONDENCE_GENERATIONS_PER_PASS
    )
    card_budget = _CallBudget(
        generate_fn, MAX_CARD_SECTION_GENERATIONS_PER_PASS
    )
    threads = [
        thread
        for thread in store.threads_for(user_id, limit=None)
        if thread.status in PASS_THREAD_STATUSES
    ]
    for thread in threads:
        try:
            result = assess_thread(
                store,
                user_id,
                thread.id,
                generate_fn=(
                    progression_budget if generate_fn is not None else None
                ),
            )
            propose_all(store, user_id, result)
            merged.candidates.extend(result.candidates)
            merged.notes.extend(result.notes)
            merged.threads_examined += 1
        except Exception:
            logger.exception(
                "recognition: thread %s failed; pass continues",
                thread.id,
            )
        try:
            card_result = assess_card_sections(
                store,
                user_id,
                thread.id,
                generate_fn=(
                    card_budget if generate_fn is not None else None
                ),
            )
            propose_all(store, user_id, card_result)
            merged.candidates.extend(card_result.candidates)
            merged.notes.extend(card_result.notes)
        except Exception:
            logger.exception(
                "recognition: card sections for thread %s failed; "
                "pass continues",
                thread.id,
            )
    try:
        pair_result = assess_pairs(
            store,
            user_id,
            generate_fn=(
                correspondence_budget if generate_fn is not None else None
            ),
        )
        propose_all(store, user_id, pair_result)
        merged.candidates.extend(pair_result.candidates)
        merged.detections.extend(pair_result.detections)
        merged.pairs_examined += pair_result.pairs_examined
        merged.notes.extend(pair_result.notes)
    except Exception:
        logger.exception("recognition: pair assessment failed")
    merged.generation_calls = (
        progression_budget.used
        + correspondence_budget.used
        + card_budget.used
    )
    return merged
