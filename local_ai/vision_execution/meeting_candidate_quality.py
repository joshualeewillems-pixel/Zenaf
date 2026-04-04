"""
Post-filters extraction candidate text before API / review.

Interactive (fast_local) uses stricter gates; default still drops obvious noise
(vague intent, meta-transcript, non-committal questions).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from local_ai.vision_execution.meeting_proposition import title_is_propositional

if TYPE_CHECKING:
    from local_ai.vision_execution.meeting_evidence_pipeline import ExtractionCandidate

_VAGUE_FUTURE_RE = re.compile(
    r"\b("
    r"i'?ll\s+(think|come\s+up|figure\s+out|see\s+what|try\s+to\s+think)|"
    r"come\s+up\s+with\s+(some\s+)?ideas?|"
    r"think\s+of\s+a\s+word|"
    r"probably\s+maybe|"
    r"kind\s+of\s+overwhelmed"
    r")\b",
    re.I,
)

_META_TRANSCRIPT_RE = re.compile(
    r"\b("
    r"don'?t\s+know\s+if\s+you\s+can\s+read|"
    r"can\s+you\s+see\s+this|"
    r"summary\s+ai|"
    r"transcript\s+of\s+the|"
    r"created\s+on\s+.{0,40}\s+by\s+summary"
    r")\b",
    re.I,
)

_ACK_HEAVY_RE = re.compile(
    r"^(yeah|yep|ok|okay|right|sure|thanks|thank\s+you|uh+|um+)\b[.!?,:\s].{0,100}$",
    re.I,
)

_SUBSTANTIVE_CUE_RE = re.compile(
    r"\b("
    r"we\s+will|we'?ll|we\s+are\s+going\s+to|we\s+must|we\s+need\s+to|we\s+have\s+to|"
    r"decided|decision|agreed|approve|approval|"
    r"action\s+item|deadline|by\s+(monday|friday|tuesday|wednesday|thursday|saturday|sunday|"
    r"next\s+week|tomorrow|eod|end\s+of\s+day)|"
    r"ship|launch|migrate|rebuild|integrate|budget|hire|deploy|dashboard|"
    r"deliver|complete|schedule|assign|owner|blocker|risk|milestone|"
    r"next\s+step|follow\s*[- ]?up|"
    r"automate|automation|workflow|intake"
    r")\b",
    re.I,
)

_QUESTION_COMMIT_RE = re.compile(
    r"\b("
    r"should\s+we\s+(ship|go|approve|delay|commit)|"
    r"can\s+we\s+commit|"
    r"who\s+owns|"
    r"what('?s|\s+is)\s+the\s+deadline|"
    r"ready\s+to\s+sign|"
    r"sign\s+off\s+on"
    r")\b",
    re.I,
)

# Clause recovery: durable speech only (stricter than lexical heuristics).
_CLAUSE_DURABILITY_RE = re.compile(
    r"\b("
    r"we\s+will|we'?ll|we\s+must|we\s+need\s+to|decided|decision|agreed|"
    r"action\s+item|deadline|ship|launch|migrate|rebuild|budget|hire|deploy|"
    r"deliver|complete|schedule|approve|owner|blocker|milestone|next\s+step|"
    r"automate|automation|workflow|intake"
    r")\b",
    re.I,
)


def is_vague_future_or_meta_chatter(text: str) -> bool:
    low = (text or "").lower()
    return bool(_VAGUE_FUTURE_RE.search(low) or _META_TRANSCRIPT_RE.search(low))


def clause_sentence_passes_strict_gate(sentence: str) -> bool:
    """Used by substantive clause recovery when strict=True."""
    s = (sentence or "").strip()
    if len(s) < 72 or len(s) > 380:
        return False
    if s.rstrip().endswith("?"):
        return False
    low = s.lower()
    if is_vague_future_or_meta_chatter(s):
        return False
    if _ACK_HEAVY_RE.match(s):
        return False
    if re.match(r"^speaker\s+[a-z0-9]", s, re.I):
        return False
    wc = len(s.split())
    if _CLAUSE_DURABILITY_RE.search(low):
        return wc >= 6 and len(s) >= 52
    return wc >= 14 and len(s) >= 105


def candidate_text_passes_api_quality(text: str, *, interactive: bool) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    wc = len(t.split())

    if is_vague_future_or_meta_chatter(t):
        return False
    if _ACK_HEAVY_RE.match(t):
        return False

    stripped = t.rstrip()
    if stripped.endswith("?"):
        if not _QUESTION_COMMIT_RE.search(low) and (interactive or len(t) < 120):
            return False

    if interactive:
        if len(t) < 32 and wc < 6:
            return False
        if re.match(r"^(and\s+)?(yeah|um|uh|like|so|well)\b[,.\s]", low) and not _SUBSTANTIVE_CUE_RE.search(low):
            return False
        if not _SUBSTANTIVE_CUE_RE.search(low) and wc < 9 and len(t) < 88:
            return False
        if len(re.findall(r"\byou know\b", low)) >= 2 and len(t) < 160:
            return False
    else:
        if len(t) < 22 and wc < 5:
            return False
        if not _SUBSTANTIVE_CUE_RE.search(low) and len(t) < 40 and wc < 8:
            return False

    return True


def filter_extraction_candidates_by_text_quality(
    candidates: list[ExtractionCandidate], *, interactive: bool
) -> list[ExtractionCandidate]:
    """
    Drop non-propositional titles for every source (model, lexical fallback).
    Literal/workspace anchor path does not emit candidates; any legacy literal row still passes
    the same proposition + quality bar as model rows.
    """
    out: list[ExtractionCandidate] = []
    for c in candidates:
        if not title_is_propositional(c.text):
            continue
        if candidate_text_passes_api_quality(c.text, interactive=interactive):
            out.append(c)
    return out
