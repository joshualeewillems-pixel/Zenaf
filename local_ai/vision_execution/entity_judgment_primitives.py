"""
Shared decision primitives for Vision Execution entity judgment flows.

Used by placement / presort heuristics and extraction canonization overlap logic.
Not coupled to intake JudgmentRecord or persistence.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Literal, Mapping

# --- Confidence / bounds ---


def clamp01(x: Any, *, default_when_invalid: float = 0.5) -> float:
    """Clamp to [0, 1]. Invalid values use ``default_when_invalid`` (placement/presort: 0.5; node transform: 0.55)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default_when_invalid
    return max(0.0, min(1.0, v))


# --- Sequence (difflib) similarity ---


def sequence_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def compute_similarity(query_text: str, target_text: str) -> float:
    """Pairwise sequence similarity (same contract as placement/presort heuristics)."""
    return sequence_similarity(query_text, target_text)


# --- Workspace catalog: best row by title (and optional row text context) ---

_LINK_KIND_KEYS: tuple[tuple[str, str], ...] = (
    ("idea", "ideas"),
    ("initiative", "initiatives"),
    ("project", "projects"),
    ("task", "tasks"),
)


def _row_extra_text_for_context(kind: str, row: dict[str, Any]) -> str:
    if kind == "initiative":
        return str(row.get("brief") or row.get("description") or "")[:160].lower()
    if kind in ("project", "task"):
        return str(row.get("brief") or row.get("description") or "")[:160].lower()
    if kind == "idea":
        return str(row.get("summary") or row.get("description") or "")[:160].lower()
    return ""


def select_best_catalog_row_match(
    query_blob_lower: str,
    existing: Mapping[str, Any] | None,
    *,
    max_entities_per_kind: int,
    include_row_text_context: bool,
) -> tuple[float, tuple[str, str, str] | None]:
    """
    Scan ideas/initiatives/projects/tasks. ``query_blob_lower`` must already be lowercased.

    When ``include_row_text_context`` is False, matches candidate_placement_suggest title-only heuristic.
    When True, matches candidate_presort_triage ``_best_catalog_row`` (title + optional brief/summary).
    """
    blob = query_blob_lower
    if not blob.strip():
        return 0.0, None
    best_ratio = 0.0
    best: tuple[str, str, str] | None = None
    for kind, key in _LINK_KIND_KEYS:
        rows = list((existing or {}).get(key) or [])
        for row in rows[:max_entities_per_kind]:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or "").strip()
            tit = str(row.get("title") or row.get("name") or "").strip()
            if not eid or not tit:
                continue
            tit_l = tit.lower()
            r = sequence_similarity(blob, tit_l)
            if include_row_text_context:
                extra = _row_extra_text_for_context(kind, row)
                if extra.strip():
                    r = max(r, sequence_similarity(blob, f"{tit_l} {extra}".strip()))
            if r > best_ratio:
                best_ratio = r
                best = (kind, eid, tit)
    return best_ratio, best


def select_best_match(
    query_blob_lower: str,
    existing: Mapping[str, Any] | None,
    *,
    max_entities_per_kind: int,
    include_row_text_context: bool,
) -> tuple[float, tuple[str, str, str] | None]:
    """Alias for :func:`select_best_catalog_row_match` (shared VE naming)."""
    return select_best_catalog_row_match(
        query_blob_lower,
        existing,
        max_entities_per_kind=max_entities_per_kind,
        include_row_text_context=include_row_text_context,
    )


def select_best_idea_title_sequence_match(
    title: str,
    ideas: list[Any] | None,
    *,
    max_entities: int,
) -> tuple[float, tuple[str, str] | None]:
    """
    Compare candidate title to catalog idea titles only (presort idea near-duplicate path).
    Returns (best_ratio, (idea_id, idea_title)) or (0.0, None).
    """
    tl = (title or "").strip().lower()
    if len(tl) < 5:
        return 0.0, None
    best_r = 0.0
    best: tuple[str, str] | None = None
    for row in list(ideas or [])[:max_entities]:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("id") or "").strip()
        it = str(row.get("title") or "").strip()
        if not eid or not it:
            continue
        r = sequence_similarity(tl, it.lower())
        if r > best_r:
            best_r = r
            best = (eid, it)
    return best_r, best


# --- Heuristic confidence helpers (fixed formulas; do not change without golden tests) ---


def placement_heuristic_confidence_from_ratio(best_ratio: float) -> float:
    return round(min(0.85, 0.45 + best_ratio * 0.4), 2)


def placement_heuristic_target_confidence(best_ratio: float) -> float:
    return round(best_ratio, 2)


def presort_confidence_for_catalog_existing(ratio: float) -> float:
    return round(min(0.92, 0.42 + ratio * 0.48), 2)


def presort_confidence_for_new_weak_overlap(ratio: float) -> float:
    return round(0.52 + min(0.2, ratio * 0.25), 2)


def presort_confidence_for_idea_title_duplicate(best_r: float) -> float:
    return round(min(0.9, 0.5 + best_r * 0.38), 2)


# --- Coarse type default (heuristic paths) ---


def infer_entity_type_for_heuristic_new() -> Literal["idea"]:
    """Default coarse type when heuristics commit to ``new`` without LLM type (historical behavior)."""
    return "idea"


# --- Novelty (threshold compare only; thresholds stay at call sites) ---


def compute_novelty(best_similarity: float, *, existing_match_threshold: float) -> bool:
    """
    Return True if the candidate is treated as novel relative to catalog similarity.

    ``existing_match_threshold`` is the minimum similarity to call a match (e.g. 0.35 placement).
    """
    return best_similarity < existing_match_threshold


# --- Jaccard / word overlap on titles (extraction canonization) ---


def normalize_title_for_match(title: str) -> str:
    """Lowercase, collapse whitespace, remove punctuation for similarity."""
    if not title:
        return ""
    s = re.sub(r"[^\w\s]", " ", title.lower())
    s = " ".join(s.split())
    return s


def title_word_set_for_overlap(s: str) -> set[str]:
    return set(normalize_title_for_match(s).split()) - {"a", "an", "the", "and", "or", "of", "for", "in", "on"}


def jaccard_word_similarity(a: str, b: str) -> float:
    """Jaccard-like overlap of word sets; 0..1 (extraction_canonization ``_title_similarity``)."""
    wa, wb = title_word_set_for_overlap(a), title_word_set_for_overlap(b)
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)
