"""
Proposition discipline for meeting extraction: titles must be actionable claims, not literals.

Deterministic helpers for prompts, post-filters, and anchor/role hints (no ML).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

AnchorRole = Literal["system_tool", "marketing_acquisition", "product_philosophy", "operations", "general"]

_STOP = frozenset(
    """
    the a an and or for to of in on at by with from as is are was were be been being
    have has had do does did will would could should may might must this that these those
    it its we our you your they their um uh like so well yeah okay ok right just really
    very some any all not no but if then about into out up down over
    """.split()
)

# Recurring transcript / product tokens worth grouping (not valid as standalone row titles).
_ANCHOR_SEED_MIN_LEN = 3
_ANCHOR_TOKEN_MIN_LEN = 4


def infer_anchor_role(text: str) -> AnchorRole:
    """Minimal keyword routing so unrelated items are not merged downstream."""
    low = (text or "").lower()
    # Product/philosophy before generic ``platform`` / ``system`` hits.
    if re.search(
        r"\b(living\s+from\s+the\s+heart|philosophy|vision|mission|brand|values|"
        r"patient\s+experience|care\s+model|strategy|roadmap|modular|productize)\b",
        low,
    ):
        return "product_philosophy"
    if re.search(
        r"\b(marketing|newsletter|email\s+drip|outreach|craigslist|cold\s+call|landing\s+page|"
        r"conversion|funnel|acquisition|ads?|seo|campaign|sign[- ]?up|lead)\b",
        low,
    ):
        return "marketing_acquisition"
    if re.search(
        r"\b(jane|emr|ehr|dashboard|api|integration|wordpress|workflow|automation|"
        r"software|system|platform|tool|app|database|server|voice|telemarketing|ai\s+call)\b",
        low,
    ):
        return "system_tool"
    if re.search(
        r"\b(clinic|operations|staffing|scheduling|billing|onboarding|intake|"
        r"prototype|internal|50/50|collaboration|hourly|capacity)\b",
        low,
    ):
        return "operations"
    return "general"


def title_is_propositional(title: str, *, source_stage: str | None = None) -> bool:
    """
    Hard gate: reject single-token labels, ALL-CAPS shout, raw diarized lines, transcript junk.
    Literal anchors use the same bar (they should already be expanded to full headlines).
    """
    _ = source_stage
    t = (title or "").strip()
    if not t:
        return False
    low = t.lower()
    wc = len(t.split())

    if re.match(r"^speaker\s+[a-z0-9]", low):
        return False
    if re.match(r"^(transcript of|meeting notes|created on)\b", low):
        return False
    if wc <= 1:
        return False
    if t.isupper() and len(t) <= 14 and " " not in t:
        return False
    if re.fullmatch(r"[A-Z]{2,15}", t.strip()):
        return False

    # Propositions are phrases, not bare entity names: need length or word count.
    if wc >= 4 and len(t) >= 18:
        return True
    if wc == 3 and len(t) >= 30:
        return True
    return False


def build_anchor_hints_block(segment_text: str, *, max_anchors: int = 10) -> str:
    """
    Frequency-based anchors (meaningful tokens) + heuristic role tags for the segment LLM.
    Extraction should group rows around these, never emit a row whose title is only an anchor.
    """
    raw = (segment_text or "").lower()
    raw = re.sub(r"speaker\s+[a-z0-9]+\s*(\([^)]+\))?\s*:?", " ", raw, flags=re.I)
    raw = re.sub(r"https?://\S+", " ", raw)
    tokens = re.findall(r"[a-z][a-z0-9_-]{2,}", raw)
    filtered = [
        x
        for x in tokens
        if len(x) >= _ANCHOR_TOKEN_MIN_LEN and x not in _STOP and not x.isdigit()
    ]
    if not filtered:
        return ""
    counts = Counter(filtered)
    top = [w for w, _ in counts.most_common(max_anchors * 2)]
    lines: list[str] = []
    seen: set[str] = set()
    for w in top:
        if w in seen:
            continue
        seen.add(w)
        role = infer_anchor_role(w)
        lines.append(f"  - {w} [{role}] (≈{counts[w]} mentions)")
        if len(lines) >= max_anchors:
            break
    if not lines:
        return ""
    return (
        "Recurring anchors in this segment (use to scope propositions; never output a row whose "
        "title is only one of these tokens):\n" + "\n".join(lines) + "\n\n"
    )


def strip_transcript_header(text: str) -> str:
    """Remove common Summary AI / boilerplate headers before extraction."""
    lines = (text or "").split("\n")
    out: list[str] = []
    skipping = True
    for i, line in enumerate(lines):
        s = line.strip()
        low = s.lower()
        if skipping:
            if low.startswith("transcript of") or low.startswith("created on ") or low.startswith("http"):
                continue
            if s == "---" or s == "—":
                skipping = False
                continue
            if i < 8 and re.match(r"^speaker\s+[a-z0-9]+\s*\(", low):
                skipping = False
                out.append(line)
                continue
            if len(s) < 2:
                continue
            skipping = False
        out.append(line)
    return "\n".join(out).strip()


def normalize_speaker_timestamp_lines(text: str) -> str:
    """
    Fold ``Speaker A (mm:ss)``-only lines into following content; strip orphan timestamps.
    """
    lines = (text or "").split("\n")
    out: list[str] = []
    i = 0
    pat_only = re.compile(r"^speaker\s+([a-z0-9]+)\s*\(\s*\d{1,2}:\d{2}(?::\d{2})?\s*\)\s*$", re.I)
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if pat_only.match(s):
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out).strip()
