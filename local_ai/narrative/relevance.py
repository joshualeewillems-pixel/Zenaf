"""Deterministic relevance assessment (addendum I2).

No model, no generation, no per-request analysis beyond arithmetic:
relevance is decided by three inspectable rules, and every decision
records the exact inputs those rules read (stored via
``NarrativeStore.record_relevance_assessment`` by the caller).

Rules — any one firing makes the candidate relevant:

1. ``shared_entity_ref`` — the candidate shares an entity ref with
   something the receiving branch already attends to, or the
   candidate thread is itself attended.
2. ``focus_term_overlap`` — the candidate text shares at least two
   distinctive tokens with the receiving seat's jurisdiction focus
   + periphery text (seat branches only).
3. ``strand_alignment`` — cosine similarity between the candidate
   strand vector and the receiving seat's archetype strand vector
   meets the seat-alignment bar (seat branches with a vector only).

Bars mirror ``local_ai/narrative/derivation.py`` (token cohesion
minimum 2, token minimum length 4, strand-alignment bar 0.30) so
relevance and derivation candidacy read the same ground. The
helpers here are local copies, not imports of derivation privates:
relevance must stay readable without the derivation pipeline.

A decision of "not relevant" is a complete result, not a failure:
unestablished relevance closes coordination for that preparation,
and the recorded assessment is what a later discrepancy flag
references.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .branches import get_branch

_TOKEN_RE = re.compile(r"[a-z][a-z0-9']+")
_MIN_TOKEN_LEN = 4
_TOKEN_COHESION_MIN = 2
_STRAND_ALIGNMENT_MIN = 0.30

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


def _cosine(a: dict, b: dict) -> float:
    """Cosine similarity with case-insensitive strand keys."""
    norm_a = {str(k).lower(): float(v) for k, v in (a or {}).items()}
    norm_b = {str(k).lower(): float(v) for k, v in (b or {}).items()}
    dot = sum(norm_a.get(k, 0.0) * v for k, v in norm_b.items())
    mag_a = math.sqrt(sum(v * v for v in norm_a.values()))
    mag_b = math.sqrt(sum(v * v for v in norm_b.values()))
    if mag_a <= 0 or mag_b <= 0:
        return 0.0
    return dot / (mag_a * mag_b)


def seat_focus_terms(archetype_id: str) -> frozenset[str]:
    """Focus + periphery tokens for one seat (lazy jurisdiction read)."""
    from local_ai.council.jurisdictions import SEAT_JURISDICTIONS

    record = SEAT_JURISDICTIONS.get(archetype_id)
    if record is None:
        return frozenset()
    return frozenset(
        _tokens(record.focus) | _tokens(" ".join(record.periphery))
    )


def seat_strand_weights(archetype_id: str) -> dict | None:
    """Archetype strand vector for one seat, or None (e.g. dynamic)."""
    from local_ai.council.archetypes import get_archetype

    arch = get_archetype(archetype_id)
    if arch is None or not arch.strand_weights:
        return None
    return dict(arch.strand_weights)


@dataclass(frozen=True)
class RelevanceResult:
    """The outcome of one relevance assessment (unstored).

    ``reasons`` names the rules that fired; ``inputs`` snapshots
    everything those rules read, so the decision can be inspected
    without re-running it. ``coordination.py`` persists this result
    as a ``RelevanceAssessment`` row.
    """

    relevant: bool
    reasons: tuple[str, ...] = ()
    inputs: dict = field(default_factory=dict)


def assess_relevance(
    branch_id: str,
    *,
    candidate_text: str = "",
    candidate_entity_refs: tuple[str, ...] | list[str] = (),
    candidate_strand_weights: dict | None = None,
    candidate_thread_id: str | None = None,
    attended_entity_refs: tuple[str, ...] | list[str] = (),
    attended_thread_ids: tuple[str, ...] | list[str] = (),
) -> RelevanceResult:
    """Decide relevance for one branch, deterministically.

    Raises ``ValueError`` for an unknown branch id: a branch that
    is not in the registry cannot establish relevance, and that is
    a configuration error, not a silent unavailable.
    """
    contract = get_branch(branch_id)
    if contract is None:
        raise ValueError(f"unknown branch: {branch_id!r}")
    reasons: list[str] = []
    candidate_refs = [str(r) for r in candidate_entity_refs]
    attended_refs = [str(r) for r in attended_entity_refs]
    attended_threads = [str(t) for t in attended_thread_ids]
    shared_refs = sorted(set(candidate_refs) & set(attended_refs))
    thread_attended = (
        candidate_thread_id is not None
        and candidate_thread_id in attended_threads
    )
    if shared_refs or thread_attended:
        reasons.append("shared_entity_ref")

    focus_overlap: list[str] = []
    focus_available = False
    if branch_id.startswith("seat:"):
        archetype_id = branch_id[len("seat:"):]
        focus_terms = seat_focus_terms(archetype_id)
        focus_available = True
        focus_overlap = sorted(_tokens(candidate_text) & set(focus_terms))
        if len(focus_overlap) >= _TOKEN_COHESION_MIN:
            reasons.append("focus_term_overlap")

    strand_similarity: float | None = None
    strand_available = False
    if branch_id.startswith("seat:") and candidate_strand_weights:
        archetype_id = branch_id[len("seat:"):]
        branch_weights = seat_strand_weights(archetype_id)
        if branch_weights:
            strand_available = True
            strand_similarity = _cosine(candidate_strand_weights, branch_weights)
            if strand_similarity >= _STRAND_ALIGNMENT_MIN:
                reasons.append("strand_alignment")

    inputs = {
        "branch_id": branch_id,
        "candidate_entity_refs": candidate_refs,
        "attended_entity_refs": attended_refs,
        "candidate_thread_id": candidate_thread_id,
        "attended_thread_ids": attended_threads,
        "shared_entity_refs": shared_refs,
        "thread_attended": thread_attended,
        "focus_terms_available": focus_available,
        "focus_overlap_tokens": focus_overlap,
        "focus_overlap_count": len(focus_overlap),
        "strand_available": strand_available,
        "strand_similarity": strand_similarity,
        "strand_alignment_bar": _STRAND_ALIGNMENT_MIN,
        "token_cohesion_min": _TOKEN_COHESION_MIN,
    }
    return RelevanceResult(
        relevant=bool(reasons), reasons=tuple(reasons), inputs=inputs
    )
