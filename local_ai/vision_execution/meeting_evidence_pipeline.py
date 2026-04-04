"""
Evidence-first meeting extraction: LLM emits small atomic rows per segment;
Python clusters and maps them to initiatives / projects / tasks / etc.

Harvest + normalize LLM passes are not used on the critical path; a synthetic
harvest ledger can be built from evidence rows for the existing UI/API surface.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from local_ai.llm.execution_principal import ExecutionPrincipal
from local_ai.llm.resolver import describe_meeting_evidence_llm_routing
from local_ai.vision_execution.extraction_canonization import _title_similarity
from local_ai.vision_execution.harvest_substrate import HarvestItem, HarvestLedger, VALID_HARVEST_CATEGORIES
from local_ai.vision_execution.meeting_candidate_quality import (
    filter_extraction_candidates_by_text_quality,
    is_vague_future_or_meta_chatter,
    clause_sentence_passes_strict_gate,
)

logger = logging.getLogger(__name__)

VALID_CLAIM_TYPES = frozenset({"initiative", "project", "task", "idea", "asset", "person", "signal"})
VALID_SIGNAL_KINDS = frozenset({"attention", "risk", "opportunity", "blocker"})

# --- Evidence provenance (diagnostics only; not part of canonized product payload) ---
SOURCE_STAGE_MODEL = "model"
SOURCE_STAGE_COVER_PHRASE = "cover_phrase"
SOURCE_STAGE_LEXICAL_TRANSCRIPT = "lexical_transcript"
SOURCE_STAGE_CLAUSE_RECOVERY = "clause_recovery"
SOURCE_STAGE_SEGMENT_SUMMARY = "segment_summary"
# Pass 0: deterministic match of context entity title/name in chunk text (before any segment LLM).
SOURCE_STAGE_LITERAL_ANCHOR = "literal_anchor"

STRUCTURE_TIER_MODEL_DIRECT = "model_direct"
STRUCTURE_TIER_LEXICAL_RECOVERY = "lexical_recovery"
STRUCTURE_TIER_LITERAL_ANCHOR = "literal_anchor"
STRUCTURE_TIER_SYNTHESIS_SEGMENT = "synthesis_segment"
STRUCTURE_TIER_REDUCER_PROMOTED = "reducer_promoted"

CONFIDENCE_TIER_LLM_EVIDENCE = "llm_evidence"
CONFIDENCE_TIER_DETERMINISTIC_RECOVERY = "deterministic_recovery"
CONFIDENCE_TIER_SYNTHESIS_BRIDGE = "segment_summary_bridge"
CONFIDENCE_TIER_PROMOTED_STRUCTURE = "promoted_structure"

CONFIDENCE_TIER_LITERAL_ANCHOR = "literal_anchor"
CONFIDENCE_TIER_LEGEND: dict[str, str] = {
    CONFIDENCE_TIER_LLM_EVIDENCE: "Per-segment extraction model output (atomic evidence rows).",
    CONFIDENCE_TIER_DETERMINISTIC_RECOVERY: "Cover phrase, transcript lexical heuristics, or clause-split recovery rows.",
    CONFIDENCE_TIER_LITERAL_ANCHOR: "Verbatim or near-verbatim match to a known entity from extraction context (Pass 0).",
    CONFIDENCE_TIER_SYNTHESIS_BRIDGE: "Rows built deterministically from segment-summary JSON (long-meeting synthesis path).",
    CONFIDENCE_TIER_PROMOTED_STRUCTURE: "Initiative/project slots filled by reducer promotion from ideas or tasks (fallback structure).",
}

# Per-segment evidence LLM: responsiveness (local Ollama iteration). Does not change reducer/heuristics.
MEETING_EVIDENCE_SEGMENT_TIMEOUT_DEFAULT_S = 60
MEETING_EVIDENCE_SEGMENT_MAX_CHUNK_DEFAULT = 4200
MEETING_EVIDENCE_SEGMENT_MIN_MERGE_DEFAULT = 350
# Interactive: fewer segments (larger chunks), shorter LLM wait, no lexical/document recovery.
MEETING_EVIDENCE_SEGMENT_TIMEOUT_FAST_LOCAL_S = 12
MEETING_EVIDENCE_SEGMENT_MAX_CHUNK_FAST_LOCAL = 5200
MEETING_EVIDENCE_SEGMENT_MIN_MERGE_FAST_LOCAL = 900
MEETING_EVIDENCE_ROLLING_PRIOR_FAST_LOCAL = 720
INTERACTIVE_MODEL_CANDIDATES_EARLY_STOP = 18
# Cap internal evidence LLM passes per user chunk (fast_local); avoids long tails on empty transcripts.
INTERACTIVE_MAX_INTERNAL_SEGMENTS = 8
# Stop after N consecutive segment calls that succeeded but yielded zero rows (hard empty / filtered path).
INTERACTIVE_CONSECUTIVE_BARREN_SEGMENTS = 3


def resolve_meeting_evidence_extraction_preset(preset: str | None) -> tuple[int, int, str, int]:
    """
    Map API/runtime preset to
    (llm_timeout_seconds, segment_max_chunk_chars, canonical_label, segment_min_merge_chars).

    ``fast_local``: larger chunks (fewer segment LLM calls), short timeout, strict interactive quality.
    ``exhaustive`` / ``batch`` / ``offline``: default timing and full lexical/document/clause recovery
    (clause recovery uses legacy permissive heuristics).
    """
    p = (preset or "default").strip().lower().replace("-", "_")
    if p in ("fast_local", "fastlocal", "interactive"):
        return (
            MEETING_EVIDENCE_SEGMENT_TIMEOUT_FAST_LOCAL_S,
            MEETING_EVIDENCE_SEGMENT_MAX_CHUNK_FAST_LOCAL,
            "fast_local",
            MEETING_EVIDENCE_SEGMENT_MIN_MERGE_FAST_LOCAL,
        )
    if p in ("exhaustive", "batch", "offline"):
        return (
            MEETING_EVIDENCE_SEGMENT_TIMEOUT_DEFAULT_S,
            MEETING_EVIDENCE_SEGMENT_MAX_CHUNK_DEFAULT,
            "exhaustive",
            MEETING_EVIDENCE_SEGMENT_MIN_MERGE_DEFAULT,
        )
    return (
        MEETING_EVIDENCE_SEGMENT_TIMEOUT_DEFAULT_S,
        MEETING_EVIDENCE_SEGMENT_MAX_CHUNK_DEFAULT,
        "default",
        MEETING_EVIDENCE_SEGMENT_MIN_MERGE_DEFAULT,
    )

_VALID_SOURCE_STAGES = frozenset(
    {
        SOURCE_STAGE_MODEL,
        SOURCE_STAGE_COVER_PHRASE,
        SOURCE_STAGE_LEXICAL_TRANSCRIPT,
        SOURCE_STAGE_CLAUSE_RECOVERY,
        SOURCE_STAGE_SEGMENT_SUMMARY,
        SOURCE_STAGE_LITERAL_ANCHOR,
    }
)

# Public API / review: reliability buckets (caps in effective_confidence).
PUBLIC_SOURCE_MODEL = "model"
PUBLIC_SOURCE_CLAUSE = "clause"
PUBLIC_SOURCE_LEXICAL = "lexical"
PUBLIC_SOURCE_LITERAL = "literal"


def public_source_stage_for_internal(internal: str) -> str:
    if internal == SOURCE_STAGE_MODEL:
        return PUBLIC_SOURCE_MODEL
    if internal == SOURCE_STAGE_CLAUSE_RECOVERY:
        return PUBLIC_SOURCE_CLAUSE
    if internal == SOURCE_STAGE_SEGMENT_SUMMARY:
        return PUBLIC_SOURCE_MODEL
    if internal == SOURCE_STAGE_LITERAL_ANCHOR:
        return PUBLIC_SOURCE_LITERAL
    return PUBLIC_SOURCE_LEXICAL


def effective_confidence(raw: float, public_stage: str) -> float:
    x = max(0.0, min(1.0, float(raw)))
    if public_stage == PUBLIC_SOURCE_CLAUSE:
        return min(x, 0.4)
    if public_stage == PUBLIC_SOURCE_LEXICAL:
        return min(x, 0.3)
    if public_stage == PUBLIC_SOURCE_LITERAL:
        return min(x, 0.88)
    return x


def normalize_confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _structure_tier_for_source_stage(stage: str) -> str:
    if stage == SOURCE_STAGE_MODEL:
        return STRUCTURE_TIER_MODEL_DIRECT
    if stage == SOURCE_STAGE_SEGMENT_SUMMARY:
        return STRUCTURE_TIER_SYNTHESIS_SEGMENT
    if stage == SOURCE_STAGE_LITERAL_ANCHOR:
        return STRUCTURE_TIER_LITERAL_ANCHOR
    return STRUCTURE_TIER_LEXICAL_RECOVERY


def _row_confidence_tier(structure_tier: str) -> str:
    if structure_tier == STRUCTURE_TIER_MODEL_DIRECT:
        return CONFIDENCE_TIER_LLM_EVIDENCE
    if structure_tier == STRUCTURE_TIER_SYNTHESIS_SEGMENT:
        return CONFIDENCE_TIER_SYNTHESIS_BRIDGE
    if structure_tier == STRUCTURE_TIER_LITERAL_ANCHOR:
        return CONFIDENCE_TIER_LITERAL_ANCHOR
    return CONFIDENCE_TIER_DETERMINISTIC_RECOVERY


def _source_category_for_row(stage: str) -> str:
    """High-level bucket for evidence rows: model vs deterministic transcript recovery vs synthesis bridge."""
    if stage == SOURCE_STAGE_MODEL:
        return "model"
    if stage == SOURCE_STAGE_SEGMENT_SUMMARY:
        return "synthesis_segment"
    if stage == SOURCE_STAGE_LITERAL_ANCHOR:
        return "literal_anchor"
    return "lexical_recovery"


# Grounded fallbacks only: every row's evidence_quote must be a substring of the segment text.
_COVER_PHRASE_RE = re.compile(
    r"(?:the\s+)?conversation\s+covers\s+(.+?)(?:\.(?:\s|$)|$)",
    re.IGNORECASE | re.DOTALL,
)
_SIMPLE_COVER_RE = re.compile(r"covers\s+(.+?)(?:\.(?:\s|$)|$)", re.IGNORECASE | re.DOTALL)
# Cover comma-chunks that look like a named work surface (tooling) or a multi-word proper noun (org/program).
_TECH_SURFACE_IN_CHUNK_RE = re.compile(
    r"\b(systems?|automation|infrastructure|integration|platform|software|tool|toolchain|database|api|dashboard|portal)\b",
    re.IGNORECASE,
)
_PROPER_NOUN_PAIR_IN_CHUNK_RE = re.compile(r"[A-Z][a-zA-Z]*\s+[A-Z][a-zA-Z]*")


def text_has_conversation_cover(t: str) -> bool:
    s = (t or "").strip()
    if len(s) < 30:
        return False
    return bool(_COVER_PHRASE_RE.search(s) or _SIMPLE_COVER_RE.search(s))


def cover_phrase_evidence_rows(text: str, segment_id: str) -> list[EvidenceRow]:
    """Structured rows from 'conversation covers …' sentences (verbatim chunks only)."""
    t = (text or "").strip()
    if len(t) < 20:
        return []
    out: list[EvidenceRow] = []
    m = _COVER_PHRASE_RE.search(t) or _SIMPLE_COVER_RE.search(t)
    if not m:
        return []
    body = (m.group(1) or "").strip()
    body = re.sub(r"\s+", " ", body)
    parts = body.split(",")
    quote_full = (m.group(0) or body)[:800]
    for p in parts:
        chunk = re.sub(r"\s+", " ", p).strip(" \t.;:-")
        if chunk.lower().startswith("and "):
            chunk = chunk[4:].strip()
        if len(chunk) < 10 or len(chunk) > 220:
            continue
        out.append(
            EvidenceRow(
                id=uuid.uuid4().hex[:12],
                segment_id=segment_id,
                claim_type="initiative",
                label=chunk[:500],
                details="",
                owner_hint=None,
                time_hint=None,
                evidence_quote=quote_full,
                signal_kind=None,
                confidence=0.45,
                source_stage=SOURCE_STAGE_COVER_PHRASE,
            )
        )
        out.append(
            EvidenceRow(
                id=uuid.uuid4().hex[:12],
                segment_id=segment_id,
                claim_type="project",
                label=chunk[:500],
                details="",
                owner_hint=None,
                time_hint=None,
                evidence_quote=quote_full,
                signal_kind=None,
                confidence=0.44,
                source_stage=SOURCE_STAGE_COVER_PHRASE,
            )
        )
        # Named surface / tooling / org-style phrase: extra asset row (same verbatim chunk, lower confidence).
        if _TECH_SURFACE_IN_CHUNK_RE.search(chunk) or _PROPER_NOUN_PAIR_IN_CHUNK_RE.search(chunk):
            out.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=segment_id,
                    claim_type="asset",
                    label=chunk[:500],
                    details="",
                    owner_hint=None,
                    time_hint=None,
                    evidence_quote=quote_full,
                    signal_kind=None,
                    confidence=0.36,
                    source_stage=SOURCE_STAGE_COVER_PHRASE,
                )
            )
    # Optional signal rows when the summary sentence names recurring operational themes (verbatim words only).
    blo = body.lower()
    if "follow-up" in blo or "follow up" in blo:
        out.append(
            EvidenceRow(
                id=uuid.uuid4().hex[:12],
                segment_id=segment_id,
                claim_type="signal",
                label="follow-up",
                details="",
                owner_hint=None,
                time_hint=None,
                evidence_quote=quote_full,
                signal_kind="attention",
                confidence=0.4,
                source_stage=SOURCE_STAGE_COVER_PHRASE,
            )
        )
    if "onboarding" in blo:
        out.append(
            EvidenceRow(
                id=uuid.uuid4().hex[:12],
                segment_id=segment_id,
                claim_type="signal",
                label="onboarding",
                details="",
                owner_hint=None,
                time_hint=None,
                evidence_quote=quote_full,
                signal_kind="attention",
                confidence=0.39,
                source_stage=SOURCE_STAGE_COVER_PHRASE,
            )
        )
    if re.search(r"\bpatient\b", body, re.I):
        out.append(
            EvidenceRow(
                id=uuid.uuid4().hex[:12],
                segment_id=segment_id,
                claim_type="signal",
                label="patient",
                details="",
                owner_hint=None,
                time_hint=None,
                evidence_quote=quote_full,
                signal_kind="attention",
                confidence=0.38,
                source_stage=SOURCE_STAGE_COVER_PHRASE,
            )
        )
    if "automation" in blo or "automate" in blo:
        out.append(
            EvidenceRow(
                id=uuid.uuid4().hex[:12],
                segment_id=segment_id,
                claim_type="signal",
                label="automation",
                details="",
                owner_hint=None,
                time_hint=None,
                evidence_quote=quote_full,
                signal_kind="opportunity",
                confidence=0.4,
                source_stage=SOURCE_STAGE_COVER_PHRASE,
            )
        )
    return out


def substantive_clause_recovery_rows(
    text: str,
    segment_id: str = "clause-recovery",
    *,
    max_rows: int = 8,
    strict: bool = True,
) -> list[EvidenceRow]:
    """
    Emit a few verbatim ``idea`` rows from substantive sentences (last resort, low confidence).

    Used when extraction produced no rows at all, or (for diarized transcripts) no initiative/project
    rows so theme buckets would otherwise stay empty after fallbacks.

    ``strict=True`` (default): only durable action/decision-shaped clauses; skips questions,
    vague future intent, and conversational fragments.

    Bounded and domain-neutral: skips short backchannels and bare speaker labels.
    """
    t = (text or "").strip()
    if len(t) < 80:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|\n+", t)
    backchannel = re.compile(
        r"^(yeah|yep|ok|okay|right|sure|thanks|thank you|mm[- ]?hmm|uh+)\b[.!?,:\s]*$",
        re.IGNORECASE,
    )
    out: list[EvidenceRow] = []
    for ch in chunks:
        s = ch.strip()
        if strict:
            if not clause_sentence_passes_strict_gate(s):
                continue
        else:
            if len(s) < 45 or len(s) > 420:
                continue
            if backchannel.match(s):
                continue
            if re.match(r"^speaker\s+[a-z0-9]", s, re.I):
                continue
            if is_vague_future_or_meta_chatter(s):
                continue
            if re.match(r"^(transcript of|meeting notes|recording|audio transcript|strategy session)\b", s, re.I):
                continue
            if re.search(r"\(excerpt\)\s*$", s, re.I) and len(s) <= 160:
                continue
            if len(re.findall(r"[a-zA-Z]{2,}", s)) < 6:
                continue
        lab = s if len(s) <= 200 else s[:197] + "…"
        out.append(
            EvidenceRow(
                id=uuid.uuid4().hex[:12],
                segment_id=segment_id,
                claim_type="idea",
                label=lab,
                details="",
                owner_hint=None,
                time_hint=None,
                evidence_quote=s[:800],
                signal_kind=None,
                confidence=0.32,
                source_stage=SOURCE_STAGE_CLAUSE_RECOVERY,
            )
        )
        if len(out) >= max_rows:
            break
    return out


def evidence_rows_to_public_dicts(rows: list[EvidenceRow]) -> list[dict[str, Any]]:
    """Stable JSON shape for diagnostics / clients (camelCase mirrors API style)."""
    return [
        {
            "id": r.id,
            "segmentId": r.segment_id,
            "type": r.claim_type,
            "label": r.label,
            "details": r.details or None,
            "ownerHint": r.owner_hint,
            "timeHint": r.time_hint,
            "evidenceQuote": r.evidence_quote,
            "signalKind": r.signal_kind,
            "confidence": r.confidence,
            "sourceStage": r.source_stage,
            "sourceCategory": _source_category_for_row(r.source_stage),
            "structureTier": r.structure_tier,
            "confidenceTier": _row_confidence_tier(r.structure_tier),
        }
        for r in rows
    ]


def merge_supplement_evidence_rows(
    existing: list[EvidenceRow],
    supplement: list[EvidenceRow],
    *,
    sim_threshold: float = 0.72,
) -> list[EvidenceRow]:
    """Append supplement rows that are not near-duplicates of existing (same claim_type)."""
    merged = list(existing)
    for s in supplement:
        dup = False
        for e in existing:
            if s.claim_type != e.claim_type:
                continue
            if _title_similarity(s.label, e.label) >= sim_threshold:
                dup = True
                break
        if not dup:
            merged.append(s)
    return merged


# Domain-general transcript cues (any vertical). Each row must quote a line or clause from the source.
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*•]+|\d+[\).\s])\s+(.{10,500})\s*$")
_COMMITMENT_CUE_RE = re.compile(
    r"\b(we need to|we have to|we should|we must|we will|we want to|we're going to|we are going to|"
    r"i will|i'll|i need to|action item|follow\s*[- ]?up|next step|todo:|"
    r"please\s+(send|review|update|complete|confirm))\b",
    re.IGNORECASE,
)
_FRICTION_CUE_RE = re.compile(
    r"\b(don't know|do not know|not sure|unclear|unsure|concern(ed)?|worried|"
    r"risk|blocker|stuck|bottleneck|ambigu|problem is|issue is)\w*\b",
    re.IGNORECASE,
)
# Tangible artifact named in speech (slides, media, leave-behinds) — not org-specific.
_DELIVERABLE_MENTION_RE = re.compile(
    r"\b(handout|handouts|worksheet|dashboard|portal|slide\s*deck|deck|artifact|artifacts|"
    r"newsletter|little\s+video|\ba\s+video\b|\bvideo\b|\bvideos\b)\b",
    re.IGNORECASE,
)
_SPEAKER_LINE_RE = re.compile(
    r"^(speaker\s+[a-z0-9]+)\s*(?:\(\s*\d{1,2}:\d{2}\s*\))?\s*[:\-]?\s*(.*)$",
    re.IGNORECASE,
)


def _line_without_speaker_prefix(line: str) -> tuple[str, str | None]:
    """Return (content, speaker_label) for 'Speaker A: ...' diarized lines."""
    m = _SPEAKER_LINE_RE.match(line.strip())
    if m:
        return m.group(2).strip(), m.group(1).strip()
    # Timestamp-prefixed "Name (12:34)" optional — strip leading parenthetical time
    tsm = re.match(r"^([^(]{1,40})\(\s*\d{1,2}:\d{2}\s*\)\s*(.*)$", line.strip())
    if tsm and len(tsm.group(2).strip()) > 5:
        return tsm.group(2).strip(), tsm.group(1).strip()
    return line.strip(), None


def lexical_transcript_evidence_rows(segment_text: str, segment_id: str) -> list[EvidenceRow]:
    """
    Line-level rows from diarized or plain transcripts without a meta 'covers …' sentence.

    Heuristics (bounded, explainable):
    - Bullet / numbered lines → task (common across meeting styles).
    - Commitment / obligation phrasing → task.
    - Uncertainty, risk, or friction phrasing → signal (attention).
    - Standalone ``Given Familyname`` two-token line → person (filters out obvious non-names).
    """
    t = (segment_text or "").strip()
    if len(t) < 20:
        return []
    out: list[EvidenceRow] = []
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]

    for ln in lines:
        ll = ln.lower()
        if re.match(r"^speaker\s+[a-z0-9]+\s*$", ll):
            continue
        core, spk = _line_without_speaker_prefix(ln)
        cl = core.lower()
        if len(core) < 12:
            continue

        mb = _BULLET_LINE_RE.match(ln)
        if mb:
            payload = mb.group(1).strip()
            if len(payload) >= 10:
                out.append(
                    EvidenceRow(
                        id=uuid.uuid4().hex[:12],
                        segment_id=segment_id,
                        claim_type="task",
                        label=payload[:200],
                        details="",
                        owner_hint=spk,
                        time_hint=None,
                        evidence_quote=ln[:800],
                        signal_kind=None,
                        confidence=0.48,
                        source_stage=SOURCE_STAGE_LEXICAL_TRANSCRIPT,
                    )
                )
            continue

        if _COMMITMENT_CUE_RE.search(cl) and len(core) >= 18:
            lab = core if len(core) <= 180 else core[:177] + "…"
            out.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=segment_id,
                    claim_type="task",
                    label=lab,
                    details="",
                    owner_hint=spk,
                    time_hint=None,
                    evidence_quote=ln[:800],
                    signal_kind=None,
                    confidence=0.46,
                    source_stage=SOURCE_STAGE_LEXICAL_TRANSCRIPT,
                )
            )
            continue

        if _FRICTION_CUE_RE.search(cl) and len(core) >= 22:
            lab = core if len(core) <= 160 else core[:157] + "…"
            out.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=segment_id,
                    claim_type="signal",
                    label=lab,
                    details="",
                    owner_hint=spk,
                    time_hint=None,
                    evidence_quote=ln[:800],
                    signal_kind="attention",
                    confidence=0.42,
                    source_stage=SOURCE_STAGE_LEXICAL_TRANSCRIPT,
                )
            )
            continue

        if (re.search(r"\bemail\b", cl) and re.search(r"\bdrip\b", cl)) and len(core) >= 18:
            lab = core if len(core) <= 200 else core[:197] + "…"
            out.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=segment_id,
                    claim_type="asset",
                    label=lab,
                    details="",
                    owner_hint=spk,
                    time_hint=None,
                    evidence_quote=ln[:800],
                    signal_kind=None,
                    confidence=0.41,
                    source_stage=SOURCE_STAGE_LEXICAL_TRANSCRIPT,
                )
            )
            continue

        if _DELIVERABLE_MENTION_RE.search(cl) and len(core) >= 22:
            lab = core if len(core) <= 200 else core[:197] + "…"
            out.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=segment_id,
                    claim_type="asset",
                    label=lab,
                    details="",
                    owner_hint=spk,
                    time_hint=None,
                    evidence_quote=ln[:800],
                    signal_kind=None,
                    confidence=0.43,
                    source_stage=SOURCE_STAGE_LEXICAL_TRANSCRIPT,
                )
            )
            continue

    for ln in lines:
        if re.match(r"^speaker\s+[a-z0-9]", ln, re.I):
            continue
        if re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+\s*\.?\s*$", ln) and len(ln) <= 36:
            w1, w2 = ln.replace(".", "").split()[:2]
            if w1.lower() in {"evening", "good", "right", "sure", "speaker"}:
                continue
            out.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=segment_id,
                    claim_type="person",
                    label=f"{w1} {w2}",
                    details="",
                    owner_hint=None,
                    time_hint=None,
                    evidence_quote=ln[:800],
                    signal_kind=None,
                    confidence=0.5,
                    source_stage=SOURCE_STAGE_LEXICAL_TRANSCRIPT,
                )
            )

    dedup: dict[tuple[str, str, str], EvidenceRow] = {}
    for r in out:
        key = (r.claim_type, r.label.lower(), r.evidence_quote[:120])
        dedup[key] = r
    return list(dedup.values())


def deterministic_fallback_rows(segment_text: str, segment_id: str) -> list[EvidenceRow]:
    """When a segment model call fails: cover sentence rows, else transcript heuristics."""
    t = (segment_text or "").strip()
    if len(t) < 20:
        return []
    cov = cover_phrase_evidence_rows(t, segment_id)
    if cov:
        return cov
    return lexical_transcript_evidence_rows(t, segment_id)


EVIDENCE_SEGMENT_PROMPT = """You extract **propositional** meeting observations from ONE segment (notes or transcript).

Each row is a **candidate idea / initiative / task / strategy** phrased as a clear, actionable claim — NOT a literal fragment, label, product name alone, or raw transcript line.

SEGMENT GROUNDING (hard):
- Use **only** information **explicitly present in THIS segment** (the transcript block below, after ``Segment (id=...)``).
- Do **not** infer from other parts of the meeting, from “overall” meeting themes, or from generic industry knowledge unless the segment itself states it.
- Optional **Prior context** (if present) is **reference-only** to resolve a pronoun or vague phrase **that appears in this segment** — do **not** emit rows whose sole support is prior text; every row must be anchored in this segment.

DRIFT GUARD (hard):
- If you cannot tie a proposition to **specific wording or a clear paraphrase of what was said in this segment**, **do not output it**.
- **Never** copy, echo, or lightly rephrase **any example line from these instructions** (including placeholder patterns below) as your ``text`` or ``summary``. Examples show **shape only**.

PROPOSITION RULES (hard):
- ``text`` (title) MUST be a short normalized proposition: at least **4 words** and **18+ characters**, or **3 words** and **30+ characters** if the phrase is already dense (e.g. proper-noun heavy).
- NEVER output: single-word titles, ALL-CAPS shout tokens, bare tool/system names without a verb phrase, speaker labels, timestamps, or lines copied verbatim as the title.
- ``summary``: 1–4 **clean sentences** explaining the claim in plain English. No "Speaker A", no "(00:00)", no bullets, no filler ("yeah", "you know"). Paraphrase; do not paste oral filler.
- ``evidence_quote``: **verbatim** short snippet from **this segment** (only field that may keep transcript formatting).

Group related threads **only when they co-occur in this segment**. One row per distinct proposition that is supported here.

STYLE EXAMPLES — **abstract templates only** (replace bracketed parts with **words that actually appear or are clearly implied in this segment**; do not output the brackets or these dummy phrases literally):
- text: "<Imperative verb> <object or deliverable> for <entity or workstream named in segment>"
  summary: "<Constraint, goal, or rationale stated in segment; no facts not spoken here.>"
- text: "<Decide or execute> <scoped action> before <timeframe or milestone from segment>"
  summary: "<Who said what and why, grounded in segment.>"
- text: "<Integrate or connect> <system A> with <system B> for <stated purpose>"
  summary: "<Integration context from segment only.>"

DO NOT extract vague or non-committal chat:
- hedges with no commitment ("I'll talk to her about that", "we should probably", "yeah that makes sense", "maybe we can") unless the segment records a **concrete** decision or next step.

ONLY extract rows with commitment-level substance **in this segment**. Do not invent context.

HARD EMPTY:
- If there are NO valid propositions, return exactly: {{"rows": []}}

Output ONLY valid JSON (no markdown fence):
{{
  "rows": [
    {{
      "text": "Short normalized proposition title (meets word/length rules)",
      "summary": "Clean explanation without transcript formatting.",
      "evidence_quote": "verbatim snippet from the segment",
      "confidence": 0.7
    }}
  ]
}}

confidence: number 0.0–1.0.

{anchor_hints_block}{workspace_mirror_block}{prior_block}Segment (id={segment_id}):
---
{segment_text}
---
JSON only:"""


MEETING_POLISH_PROMPT = """You polish meeting metadata from structured bullets already extracted (do not invent new entities).

Return ONLY valid JSON:
{{
  "summary": {{ "text": "one concise paragraph describing the meeting focus", "confidence": "high"|"medium"|"low" }},
  "insights": [
    {{ "statement": "a tension, open question, or unresolved thread", "sourceQuote": "short supporting phrase or null", "confidence": "high"|"medium"|"low" }}
  ]
}}

Rules:
- insights: 0–8 items; focus on tensions, ambiguities, unresolved decisions — not repeating the entity list.
- Do not add initiatives, projects, tasks, people, or assets not implied below.

Bullets:
{bullets}

JSON only:"""


def segment_notes_for_evidence(notes: str, *, max_chunk: int = 4200, min_merge: int = 350) -> list[tuple[str, str]]:
    """
    Deterministic segmentation: paragraph boundaries first, then line groups.
    Returns (segment_id, text) with stable ids seg-0000, seg-0001, ...
    """
    text = (notes or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    if not paras:
        return []
    segments: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for p in paras:
        plen = len(p) + (2 if buf else 0)
        if buf and buf_len + plen > max_chunk and buf_len >= min_merge:
            segments.append("\n\n".join(buf))
            buf = [p]
            buf_len = len(p)
            continue
        if len(p) > max_chunk:
            if buf:
                segments.append("\n\n".join(buf))
                buf = []
                buf_len = 0
            for piece in _split_oversized_paragraph(p, max_chunk):
                segments.append(piece)
            continue
        buf.append(p)
        buf_len += plen
    if buf:
        segments.append("\n\n".join(buf))
    out: list[tuple[str, str]] = []
    for i, seg in enumerate(segments):
        if seg.strip():
            out.append((f"seg-{i:04d}", seg.strip()))
    return out if out else [("seg-0000", text)]


def _split_oversized_paragraph(p: str, max_chunk: int) -> list[str]:
    lines = p.split("\n")
    parts: list[str] = []
    buf: list[str] = []
    n = 0
    for line in lines:
        line = line.rstrip()
        add = len(line) + (1 if buf else 0)
        if buf and n + add > max_chunk:
            parts.append("\n".join(buf))
            buf = [line]
            n = len(line)
        else:
            buf.append(line)
            n += add
    if buf:
        parts.append("\n".join(buf))
    return [x.strip() for x in parts if x.strip()]


def _repair_json_outer(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    t = t.strip()
    # Top-level JSON array (some models omit the ``rows`` wrapper).
    if t.startswith("["):
        if not t.rstrip().endswith("]"):
            j = t.rfind("]")
            if j != -1:
                t = t[: j + 1]
        return t
    if t and not t.startswith("{"):
        i = t.find("{")
        if i != -1:
            t = t[i:]
    if t and not t.rstrip().endswith("}"):
        j = t.rfind("}")
        if j != -1:
            t = t[: j + 1]
    return t


def _json_loads_lenient(s: str) -> Any | None:
    """Parse JSON; repair common LLM mistakes (trailing commas) before giving up."""
    t = (s or "").strip()
    if not t:
        return None
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    t2 = re.sub(r",\s*}", "}", t)
    t2 = re.sub(r",\s*]", "]", t2)
    if t2 != t:
        try:
            return json.loads(t2)
        except json.JSONDecodeError:
            pass
    return None


def _coerce_evidence_row_dicts(data: Any) -> list[dict[str, Any]]:
    """
    Normalize alternate model shapes to a list of row dicts (same keys as schema).

    Handles: top-level array, ``rows``, nested ``data``/``result`` wrappers, single-row root object.
    """
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    if isinstance(rows, list):
        out = [r for r in rows if isinstance(r, dict)]
        if out:
            return out
    for key in ("data", "result", "items", "evidence", "claims", "extracted_rows", "output"):
        v = data.get(key)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict):
            inner = v.get("rows")
            if isinstance(inner, list):
                got = [r for r in inner if isinstance(r, dict)]
                if got:
                    return got
            nested = _coerce_evidence_row_dicts(v)
            if nested:
                return nested
    if data.get("claim_type") or data.get("type") or data.get("label"):
        return [data]
    return []


def _coerce_candidate_rows_from_parsed(data: Any) -> list[dict[str, Any]]:
    """Rows with non-empty ``text`` (observation-only segment schema)."""
    if data is None:
        return []
    if isinstance(data, list):
        if data and all(isinstance(x, dict) and str(x.get("text") or "").strip() for x in data):
            return [x for x in data if isinstance(x, dict)]
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    if isinstance(rows, list) and rows:
        if all(isinstance(r, dict) for r in rows) and not rows:
            return []
        if all(isinstance(r, dict) and str(r.get("text") or "").strip() for r in rows):
            return [r for r in rows if isinstance(r, dict)]
    return []


def parse_candidate_segment_llm_json(raw: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta: dict[str, Any] = {"decode_ok": False}
    t = _repair_json_outer(raw)
    data = _json_loads_lenient(t)
    if data is None:
        meta["reason"] = "json_decode_error"
        return [], meta
    meta["decode_ok"] = True
    if isinstance(data, dict):
        rows_key = data.get("rows")
        if isinstance(rows_key, list) and len(rows_key) == 0:
            meta["reason"] = "ok"
            meta["parsed_row_count"] = 0
            meta["hard_empty"] = True
            return [], meta
    rows = _coerce_candidate_rows_from_parsed(data)
    if rows:
        meta["reason"] = "ok"
        meta["parsed_row_count"] = len(rows)
        return rows, meta
    meta["reason"] = "zero_rows_after_coerce"
    meta["root_type"] = type(data).__name__
    return [], meta


def parse_evidence_llm_json(raw: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Parse segment extraction JSON with shape recovery.

    Returns (row_dicts, meta). meta includes decode_ok, reason, and optional diagnostics.
    """
    meta: dict[str, Any] = {"decode_ok": False}
    t = _repair_json_outer(raw)
    data = _json_loads_lenient(t)
    if data is None:
        meta["reason"] = "json_decode_error"
        return [], meta
    meta["decode_ok"] = True
    rows = _coerce_evidence_row_dicts(data)
    if rows:
        meta["reason"] = "ok"
        meta["parsed_row_count"] = len(rows)
        return rows, meta
    meta["reason"] = "zero_rows_after_coerce"
    meta["root_type"] = type(data).__name__
    return [], meta


def _parse_evidence_json(raw: str) -> list[dict[str, Any]]:
    """Backward-compatible: row list only (no meta)."""
    rows, _ = parse_evidence_llm_json(raw)
    return rows


def _norm_claim_type(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in VALID_CLAIM_TYPES else None


def _norm_signal_kind(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in VALID_SIGNAL_KINDS else None


def _opt_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        return max(0.0, min(1.0, x))
    except (TypeError, ValueError):
        return None


@dataclass
class EvidenceRow:
    id: str
    segment_id: str
    claim_type: str
    label: str
    details: str
    owner_hint: str | None
    time_hint: str | None
    evidence_quote: str
    signal_kind: str | None
    confidence: float | None
    source_stage: str = SOURCE_STAGE_MODEL
    structure_tier: str = ""

    def __post_init__(self) -> None:
        if self.structure_tier:
            return
        object.__setattr__(self, "structure_tier", _structure_tier_for_source_stage(self.source_stage))


@dataclass
class ExtractionCandidate:
    """Flat observation for UI typing; no extract-time entity classification."""

    id: str
    segment_id: str
    text: str
    evidence_quote: str
    confidence_raw: float
    internal_source_stage: str
    possible_matches: list[dict[str, Any]] | None = None
    """API row ``kind``; default ``candidate``. ``promoted_literal`` is legacy only (Pass 0 no longer promotes anchors)."""
    api_kind: str | None = None
    """Paraphrase for review UI when ``text`` is a normalized title (e.g. promoted literals)."""
    summary_text: str | None = None
    """Heuristic theme bucket for merge gating (system_tool, marketing_acquisition, …)."""
    anchor_role: str | None = None
    proposed_type: str | None = None  # external path: project|task|initiative|decision|research|signal|observation


VALID_PROPOSED_TYPES = frozenset(
    {"project", "task", "initiative", "decision", "research", "signal", "observation"}
)


def _norm_proposed_type(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower().replace("-", "_")
    return s if s in VALID_PROPOSED_TYPES else None


def extraction_candidate_provenance_summary(candidates: list[ExtractionCandidate]) -> dict[str, Any]:
    if not candidates:
        return {"source_stage_counts": {}, "structure_tier_counts": {}}
    return {
        "source_stage_counts": dict(Counter(c.internal_source_stage for c in candidates)),
        "structure_tier_counts": dict(
            Counter(_structure_tier_for_source_stage(c.internal_source_stage) for c in candidates)
        ),
    }


def extraction_candidate_from_llm_row(d: dict[str, Any], *, segment_id: str) -> ExtractionCandidate | None:
    from local_ai.vision_execution.meeting_proposition import infer_anchor_role, title_is_propositional

    text = str(d.get("text") or "").strip()
    if len(text) < 4:
        return None
    if not title_is_propositional(text):
        return None
    eq = str(d.get("evidence_quote") or d.get("evidenceQuote") or "").strip()
    if not eq:
        eq = text[:800]
    cr = _opt_float(d.get("confidence"))
    if cr is None:
        cr = 0.55
    summary_raw = str(d.get("summary") or d.get("paraphrase") or "").strip()
    summary_text = summary_raw[:2000] if summary_raw else None
    role = infer_anchor_role(text + " " + (summary_raw or ""))
    ptype = _norm_proposed_type(d.get("proposed_type") or d.get("proposedType"))
    return ExtractionCandidate(
        id=uuid.uuid4().hex[:12],
        segment_id=segment_id,
        text=text[:2000],
        evidence_quote=eq[:2000],
        confidence_raw=cr,
        internal_source_stage=SOURCE_STAGE_MODEL,
        possible_matches=None,
        summary_text=summary_text,
        anchor_role=role,
        proposed_type=ptype,
    )


def extraction_candidate_from_evidence_row(r: EvidenceRow) -> ExtractionCandidate:
    from local_ai.vision_execution.meeting_proposition import infer_anchor_role

    label = (r.label or "").strip()[:2000]
    eq = (r.evidence_quote or label)[:2000]
    cr = r.confidence if r.confidence is not None else 0.35
    return ExtractionCandidate(
        id=r.id,
        segment_id=r.segment_id,
        text=label,
        evidence_quote=eq,
        confidence_raw=cr,
        internal_source_stage=r.source_stage,
        possible_matches=None,
        summary_text=None,
        anchor_role=infer_anchor_role(label),
        proposed_type=None,
    )


def _evidence_row_from_candidate(c: ExtractionCandidate) -> EvidenceRow:
    return EvidenceRow(
        id=c.id,
        segment_id=c.segment_id,
        claim_type="idea",
        label=c.text,
        details="",
        owner_hint=None,
        time_hint=None,
        evidence_quote=c.evidence_quote,
        signal_kind=None,
        confidence=c.confidence_raw,
        source_stage=c.internal_source_stage,
    )


def merge_supplement_candidates(
    existing: list[ExtractionCandidate],
    supplement: list[ExtractionCandidate],
    *,
    sim_threshold: float = 0.72,
) -> list[ExtractionCandidate]:
    merged = list(existing)
    for s in supplement:
        dup = any(_title_similarity(s.text, e.text) >= sim_threshold for e in existing)
        if not dup:
            merged.append(s)
    return merged


def dedupe_candidates_ordered(candidates: list[ExtractionCandidate], *, sim_threshold: float = 0.72) -> list[ExtractionCandidate]:
    out: list[ExtractionCandidate] = []
    for c in candidates:
        if any(_title_similarity(c.text, o.text) >= sim_threshold for o in out):
            continue
        out.append(c)
    return out


def extraction_candidate_to_api_dict(c: ExtractionCandidate) -> dict[str, Any]:
    pub = public_source_stage_for_internal(c.internal_source_stage)
    eff = effective_confidence(c.confidence_raw, pub)
    label = normalize_confidence_label(eff)
    row: dict[str, Any] = {
        "id": c.id,
        "kind": (c.api_kind or "candidate").strip() or "candidate",
        "text": c.text,
        "confidence": eff,
        "confidenceLabel": label,
        "sourceStage": pub,
        "segmentId": c.segment_id,
        "sourceExcerpt": c.evidence_quote if c.evidence_quote else None,
    }
    st = (c.summary_text or "").strip()
    if st:
        row["summary"] = st[:2000]
    if c.anchor_role:
        row["anchorRole"] = c.anchor_role
    if c.proposed_type:
        row["proposedType"] = c.proposed_type
    if c.possible_matches:
        row["possibleMatches"] = c.possible_matches
    return row


def attach_possible_matches_to_candidates(
    candidates: list[ExtractionCandidate],
    context: dict[str, Any] | None,
) -> None:
    """Soft hints only; does not set existing*MatchId on any entity payload."""
    if not context or not isinstance(context, dict) or not candidates:
        return

    def collect_matches(text: str) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        for lst, typ, key in (
            (context.get("initiatives") or [], "initiative", "title"),
            (context.get("projects") or [], "project", "title"),
            (context.get("tasks") or [], "task", "title"),
        ):
            if not isinstance(lst, list):
                continue
            for ent in lst:
                if not isinstance(ent, dict):
                    continue
                tid = ent.get("id")
                title = str(ent.get(key) or "").strip()
                if not tid or not title:
                    continue
                sc = _title_similarity(text, title)
                if sc >= 0.42:
                    matches.append({"id": str(tid), "type": typ, "similarity": round(float(sc), 3)})
        matches.sort(key=lambda m: float(m.get("similarity") or 0.0), reverse=True)
        return matches[:5]

    for c in candidates:
        if c.possible_matches:
            continue
        pm = collect_matches(c.text)
        c.possible_matches = pm if pm else None


def candidates_to_harvest_ledger(meeting_id: str, candidates: list[ExtractionCandidate]) -> HarvestLedger:
    created_at = str(int(time.time() * 1000))
    if not candidates:
        return HarvestLedger.empty(meeting_id)
    items: list[HarvestItem] = []
    sorted_c = sorted(candidates, key=lambda x: (x.segment_id, x.id))
    for i, c in enumerate(sorted_c):
        pub = public_source_stage_for_internal(c.internal_source_stage)
        eff = effective_confidence(c.confidence_raw, pub)
        items.append(
            HarvestItem(
                id=c.id,
                ordinal=i + 1,
                label=c.text[:2000],
                raw_text=c.evidence_quote[:2000],
                speaker=None,
                source_segment_id=c.segment_id,
                source_turn_index=None,
                category_hint="other",
                speculative=eff < 0.45,
                confidence=eff,
                normalized_from=None,
                mapped_entity_ids=[],
                notes=None,
            )
        )
    return HarvestLedger(transcript_id=meeting_id, created_at=created_at, items=items)


def build_deterministic_summary_from_candidates(api_candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    texts = [
        str(x.get("text") or "").strip()
        for x in api_candidates
        if isinstance(x, dict) and str(x.get("text") or "").strip()
    ]
    if not texts:
        return None
    bundle = "; ".join(texts[:12])
    return {"text": ("Observations: " + bundle)[:2000], "confidence": "medium"}


def evidence_row_provenance_summary(rows: list[EvidenceRow]) -> dict[str, Any]:
    """Aggregate counts for diagnostics (no row text)."""
    if not rows:
        return {"source_stage_counts": {}, "structure_tier_counts": {}}
    return {
        "source_stage_counts": dict(Counter(r.source_stage for r in rows)),
        "structure_tier_counts": dict(Counter(r.structure_tier for r in rows)),
    }


def _row_from_dict(
    d: dict[str, Any],
    *,
    segment_id: str,
    row_id: str,
) -> EvidenceRow | None:
    ct = _norm_claim_type(d.get("claim_type")) or _norm_claim_type(d.get("type"))
    if not ct:
        return None
    label = str(d.get("label") or "").strip()
    if not label:
        return None
    details = str(d.get("details") or "").strip()
    eq = str(d.get("evidence_quote") or d.get("evidence_span") or d.get("quote") or "").strip()
    if not eq:
        eq = label[:500]
    sk = _norm_signal_kind(d.get("signal_kind")) if ct == "signal" else None
    if ct == "signal" and not sk:
        sk = "attention"
    oh = d.get("owner_hint")
    owner = str(oh).strip() if oh is not None and str(oh).strip() else None
    th = d.get("time_hint")
    time_h = str(th).strip() if th is not None and str(th).strip() else None
    raw_stage = d.get("source_stage") or d.get("sourceStage")
    ss = str(raw_stage).strip() if raw_stage is not None else ""
    source_stage = ss if ss in _VALID_SOURCE_STAGES else SOURCE_STAGE_MODEL
    return EvidenceRow(
        id=row_id,
        segment_id=segment_id,
        claim_type=ct,
        label=label,
        details=details,
        owner_hint=owner,
        time_hint=time_h,
        evidence_quote=eq[:2000],
        signal_kind=sk,
        confidence=_opt_float(d.get("confidence")),
        source_stage=source_stage,
    )


def _evidence_segment_instrumentation_attach_routing(
    rep: dict[str, Any],
    llm_routing_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    if llm_routing_snapshot is not None:
        rep["llm_routing"] = dict(llm_routing_snapshot)
    return rep


def _log_meeting_evidence_segment_extract(rep: dict[str, Any], *, segment_id: str, row_count: int) -> None:
    rt = rep.get("llm_routing") or {}
    tm = rep.get("timing_ms") or {}
    rs = rep.get("request_sizes") or {}
    logger.info(
        "[meeting-evidence-segment] seg=%s rows=%s outcome=%s llm_path=%s llm_ms=%s parse_ms=%s "
        "total_ms=%s prompt_chars=%s seg_chars=%s prior=%s provider=%s model=%s seam=%s "
        "policy_ovr=%s ollama_ovr=%s det_fb=%s fb_ms=%s",
        segment_id,
        row_count,
        rep.get("outcome"),
        rep.get("llm_path_outcome"),
        tm.get("llm_call"),
        tm.get("parse"),
        tm.get("total_wall"),
        rs.get("prompt_chars"),
        rs.get("segment_text_chars"),
        rs.get("prior_context_included"),
        rt.get("effective_provider"),
        rt.get("effective_model"),
        rt.get("routing_context_seam_active"),
        rt.get("execution_policy_override_active"),
        rt.get("ollama_model_override_active"),
        rep.get("deterministic_fallback_used"),
        tm.get("deterministic_fallback"),
    )


def extract_candidate_rows_for_segment(
    segment_text: str,
    segment_id: str,
    llm_generate: Callable[..., str],
    *,
    prior_block: str = "",
    workspace_mirror_block: str = "",
    task_name: str = "meeting_evidence_segment",
    timeout: int = MEETING_EVIDENCE_SEGMENT_TIMEOUT_DEFAULT_S,
    llm_routing_snapshot: dict[str, Any] | None = None,
) -> tuple[list[ExtractionCandidate], dict[str, Any]]:
    """
    One LLM call per segment — observation-only JSON (text + confidence).

    Explicit ``{{"rows":[]}}`` is **success** (hard empty). On LLM/parse failure returns ([], report).
    """
    t_wall0 = time.perf_counter()

    def _finalize(rep: dict[str, Any]) -> dict[str, Any]:
        tm = rep.setdefault("timing_ms", {})
        if tm.get("total_wall") is None:
            tm["total_wall"] = (time.perf_counter() - t_wall0) * 1000
        return _evidence_segment_instrumentation_attach_routing(rep, llm_routing_snapshot)

    seg_src = segment_text or ""
    st = seg_src.strip()
    seg_chars_full = len(seg_src)
    if not st:
        rep_empty: dict[str, Any] = {
            "segment_id": segment_id,
            "error": "empty_segment",
            "skipped": True,
            "outcome": "skipped_empty_segment",
            "llm_path_outcome": "skipped_empty_segment",
            "retried": False,
            "deterministic_fallback_used": False,
            "timing_ms": {
                "prompt_build": None,
                "llm_call": None,
                "parse": None,
                "retry": None,
                "deterministic_fallback": None,
                "total_wall": (time.perf_counter() - t_wall0) * 1000,
            },
            "request_sizes": {
                "segment_text_chars": seg_chars_full,
                "segment_in_prompt_chars": 0,
                "segment_text_capped": False,
                "prompt_chars": 0,
                "prior_context_included": False,
            },
        }
        return [], _finalize(rep_empty)

    prior = (prior_block or "").strip()
    prior_included = bool(prior)
    t_pb0 = time.perf_counter()
    prior_fmt = (
        "Prior context (reference only — resolve pronouns/vague mentions that appear in THIS segment; "
        "do not extract rows whose support is only in prior text):\n"
        + prior
        + "\n\n"
    ) if prior else ""
    wm = (workspace_mirror_block or "").strip()
    wm_fmt = (
        "Workspace mirror (local tree orientation; non-authoritative, not stored in VE):\n" + wm + "\n\n"
    ) if wm else ""
    from local_ai.vision_execution.meeting_proposition import build_anchor_hints_block

    anchor_hints = build_anchor_hints_block(st)
    anchor_fmt = anchor_hints if anchor_hints else ""
    capped = st[:12000]
    prompt = EVIDENCE_SEGMENT_PROMPT.format(
        segment_id=segment_id,
        segment_text=capped,
        anchor_hints_block=anchor_fmt,
        workspace_mirror_block=wm_fmt,
        prior_block=prior_fmt,
    )
    prompt_build_ms = (time.perf_counter() - t_pb0) * 1000

    request_sizes: dict[str, Any] = {
        "segment_text_chars": seg_chars_full,
        "segment_in_prompt_chars": len(capped),
        "segment_text_capped": len(capped) < len(st),
        "prompt_chars": len(prompt),
        "prior_context_included": prior_included,
    }

    timing_ms: dict[str, Any] = {
        "prompt_build": prompt_build_ms,
        "llm_call": None,
        "parse": None,
        "retry": None,
        "deterministic_fallback": None,
        "total_wall": None,
    }

    try:
        t_llm0 = time.perf_counter()
        raw = (llm_generate(task=task_name, prompt=prompt, timeout=timeout) or "").strip()
        timing_ms["llm_call"] = (time.perf_counter() - t_llm0) * 1000
    except Exception as e:
        timing_ms["total_wall"] = (time.perf_counter() - t_wall0) * 1000
        logger.warning("extract_evidence_rows_for_segment: llm failed seg=%s: %s", segment_id, e)
        return [], _finalize(
            {
                "segment_id": segment_id,
                "error": "llm_failed",
                "message": str(e),
                "outcome": "llm_failed",
                "llm_path_outcome": "llm_failed",
                "retried": False,
                "deterministic_fallback_used": False,
                "timing_ms": dict(timing_ms),
                "request_sizes": request_sizes,
                "raw_response_chars": 0,
                "parsed_json_row_count": 0,
                "proposition_kept_row_count": 0,
                "dropped_at_proposition_gate": 0,
            }
        )

    sample = (raw[:400] + ("..." if len(raw) > 400 else "")).replace("\r", "")
    t_parse0 = time.perf_counter()
    rows_raw, parse_meta = parse_candidate_segment_llm_json(raw)
    timing_ms["parse"] = (time.perf_counter() - t_parse0) * 1000
    timing_ms["total_wall"] = (time.perf_counter() - t_wall0) * 1000
    raw_response_chars = len(raw)

    base_diag = {
        "segment_id": segment_id,
        "timing_ms": dict(timing_ms),
        "request_sizes": request_sizes,
        "raw_response_chars": raw_response_chars,
        "retried": False,
        "deterministic_fallback_used": False,
    }

    if not rows_raw:
        reason = parse_meta.get("reason", "unknown")
        if not parse_meta.get("decode_ok"):
            oc = "parse_failed"
            logger.warning(
                "extract_candidate_rows_for_segment: json decode failed seg=%s reason=%s sample=%s",
                segment_id,
                reason,
                sample[:200],
            )
            return [], _finalize(
                {
                    **base_diag,
                    "error": "parse_failed",
                    "parse_meta": parse_meta,
                    "raw_sample": sample,
                    "outcome": oc,
                    "llm_path_outcome": oc,
                }
            )
        if parse_meta.get("hard_empty"):
            return [], _finalize(
                {
                    **base_diag,
                    "segment_id": segment_id,
                    "row_count": 0,
                    "parse_meta": parse_meta,
                    "outcome": "success",
                    "llm_path_outcome": "success",
                    "hard_empty": True,
                    "parsed_json_row_count": 0,
                    "proposition_kept_row_count": 0,
                    "dropped_at_proposition_gate": 0,
                }
            )
        oc = "empty_rows"
        logger.warning(
            "extract_candidate_rows_for_segment: empty rows after JSON seg=%s reason=%s root_type=%s sample=%s",
            segment_id,
            reason,
            parse_meta.get("root_type"),
            sample[:200],
        )
        return [], _finalize(
            {
                **base_diag,
                "error": "empty_rows",
                "parse_meta": parse_meta,
                "raw_sample": sample,
                "outcome": oc,
                "llm_path_outcome": oc,
            }
        )
    out: list[ExtractionCandidate] = []
    for d in rows_raw:
        c = extraction_candidate_from_llm_row(d, segment_id=segment_id)
        if c:
            out.append(c)
    if not out:
        oc = "no_valid_rows"
        logger.warning(
            "extract_candidate_rows_for_segment: no valid rows after schema check seg=%s parsed=%s sample=%s",
            segment_id,
            len(rows_raw),
            sample[:200],
        )
        return [], _finalize(
            {
                **base_diag,
                "error": "no_valid_rows",
                "parse_meta": parse_meta,
                "parsed_row_count": len(rows_raw),
                "parsed_json_row_count": len(rows_raw),
                "proposition_kept_row_count": 0,
                "dropped_at_proposition_gate": len(rows_raw),
                "raw_sample": sample,
                "outcome": oc,
                "llm_path_outcome": oc,
            }
        )
    return out, _finalize(
        {
            **base_diag,
            "segment_id": segment_id,
            "row_count": len(out),
            "parse_meta": parse_meta,
            "outcome": "success",
            "llm_path_outcome": "success",
            "parsed_json_row_count": len(rows_raw),
            "proposition_kept_row_count": len(out),
            "dropped_at_proposition_gate": len(rows_raw) - len(out),
        }
    )


def _build_evidence_extraction_trace_summary(
    *,
    evidence_extraction_preset: str,
    timeout: int,
    evidence_segment_max_chunk: int | None,
    is_interactive: bool,
    segments_planned: int,
    internal_segments_processed: int,
    segment_reports: list[dict[str, Any]],
    pre_dedupe_row_count: int,
    post_dedupe_row_count: int,
    pre_filter_row_count: int,
    post_filter_row_count: int,
) -> dict[str, Any]:
    """
    Temporary operator diagnostics for extract path verification (preset, timeouts, per-segment rows).
    """
    per_segment: list[dict[str, Any]] = []
    llm_failed_segment_count = 0
    llm_failed_timeout_hint_count = 0
    hard_empty_segment_count = 0
    for r in segment_reports:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("segment_id") or "")
        err = r.get("error")
        msg_l = str(r.get("message") or "").lower()
        if err == "llm_failed":
            llm_failed_segment_count += 1
            if "timeout" in msg_l or "timed out" in msg_l:
                llm_failed_timeout_hint_count += 1
        if r.get("hard_empty"):
            hard_empty_segment_count += 1
        emitted = r.get("rows_emitted_to_pipeline")
        if emitted is None:
            emitted = int(r.get("row_count") or 0)
        else:
            emitted = int(emitted)
        per_segment.append(
            {
                "segment_id": sid,
                "llm_path_outcome": r.get("llm_path_outcome") or r.get("outcome"),
                "rows_returned": emitted,
                "parsed_json_rows": r.get("parsed_json_row_count"),
                "dropped_at_proposition_gate": r.get("dropped_at_proposition_gate"),
                "hard_empty": bool(r.get("hard_empty")),
                "llm_failed": err == "llm_failed",
                "recovered_by": r.get("recovered_by"),
            }
        )
    return {
        "preset": evidence_extraction_preset,
        "timeout_s": timeout,
        "max_chunk": evidence_segment_max_chunk,
        "interactive": is_interactive,
        "segments_planned": segments_planned,
        "segments_completed": internal_segments_processed,
        "per_segment": per_segment,
        "llm_failed_segment_count": llm_failed_segment_count,
        "llm_failed_timeout_hint_count": llm_failed_timeout_hint_count,
        "hard_empty_segment_count": hard_empty_segment_count,
        "rows_pre_dedupe": pre_dedupe_row_count,
        "rows_post_dedupe": post_dedupe_row_count,
        "dedupe_dropped_total": max(0, pre_dedupe_row_count - post_dedupe_row_count),
        "rows_pre_quality_filter": pre_filter_row_count,
        "rows_post_quality_filter": post_filter_row_count,
        "quality_filter_dropped_total": max(0, pre_filter_row_count - post_filter_row_count),
        "note": "Per-segment drops count proposition gate only; dedupe/quality are document-level after merge.",
    }


def extract_evidence_rows_for_segment(
    segment_text: str,
    segment_id: str,
    llm_generate: Callable[..., str],
    *,
    prior_block: str = "",
    task_name: str = "meeting_evidence_segment",
    timeout: int = MEETING_EVIDENCE_SEGMENT_TIMEOUT_DEFAULT_S,
    llm_routing_snapshot: dict[str, Any] | None = None,
) -> tuple[list[EvidenceRow], dict[str, Any]]:
    """Compatibility: same segment LLM path as candidates, mapped to single-bucket evidence rows."""
    cands, rep = extract_candidate_rows_for_segment(
        segment_text,
        segment_id,
        llm_generate,
        prior_block=prior_block,
        workspace_mirror_block="",
        task_name=task_name,
        timeout=timeout,
        llm_routing_snapshot=llm_routing_snapshot,
    )
    return [_evidence_row_from_candidate(c) for c in cands], rep


def extract_candidate_rows_all_segments(
    segments: list[tuple[str, str]],
    llm_generate: Callable[..., str],
    *,
    task_name: str = "meeting_evidence_segment",
    timeout: int = MEETING_EVIDENCE_SEGMENT_TIMEOUT_DEFAULT_S,
    rolling_prior_max_chars: int = 2800,
    full_notes: str = "",
    principal: ExecutionPrincipal | None = None,
    seam_routing_active: bool = False,
    evidence_extraction_preset: str = "default",
    evidence_segment_max_chunk: int | None = None,
    workspace_mirror_block: str = "",
) -> tuple[list[ExtractionCandidate], dict[str, Any]]:
    """
    Per-segment candidate extraction with rolling prior.

    Fallback gating: if a segment's model path returns at least one valid row (not deterministic
    fallback), clause/lexical fallbacks are skipped for that segment. After all segments, if **any**
    segment had valid model rows, document-level cover / lexical / clause recovery on ``full_notes``
    is skipped entirely.

    ``fast_local``: no per-segment lexical/cover fallback, no document-level supplements, stricter
    post-filter; prefer empty over noisy rows.
    """
    is_interactive = evidence_extraction_preset == "fast_local"
    clause_strict = evidence_extraction_preset != "exhaustive"
    all_cands: list[ExtractionCandidate] = []
    segment_reports: list[dict[str, Any]] = []
    prior_bits: list[str] = []
    any_valid_model_segment = False
    interactive_early_stop = False
    interactive_stop_reason: str | None = None
    consecutive_barren = 0
    internal_segments_processed = 0
    routing_snap: dict[str, Any] | None = None
    if principal is not None:
        routing_snap = describe_meeting_evidence_llm_routing(
            principal,
            seam_routing_active=seam_routing_active,
        )
    wm_full = (workspace_mirror_block or "").strip()
    for seg_i, (seg_id, seg_text) in enumerate(segments):
        if is_interactive and internal_segments_processed >= INTERACTIVE_MAX_INTERNAL_SEGMENTS:
            interactive_stop_reason = interactive_stop_reason or "max_segments"
            break
        prior_block = ""
        if prior_bits:
            prior_block = "Recently extracted observations (for reference): " + "; ".join(prior_bits[-25:])[
                :rolling_prior_max_chars
            ]
        seg_wm = wm_full if seg_i == 0 else ""
        cands, rep = extract_candidate_rows_for_segment(
            seg_text,
            seg_id,
            llm_generate,
            prior_block=prior_block,
            workspace_mirror_block=seg_wm,
            task_name=task_name,
            timeout=timeout,
            llm_routing_snapshot=routing_snap,
        )
        valid_model_here = (
            rep.get("llm_path_outcome") == "success"
            and not rep.get("deterministic_fallback_used")
            and bool(cands)
        )
        if valid_model_here:
            any_valid_model_segment = True

        if not cands and rep.get("error") and not is_interactive:
            t_fb0 = time.perf_counter()
            fb_rows = deterministic_fallback_rows(seg_text, seg_id)
            fb_ms = (time.perf_counter() - t_fb0) * 1000
            rep = dict(rep)
            tm_fb = dict(rep.get("timing_ms") or {})
            tm_fb["deterministic_fallback"] = fb_ms
            rep["timing_ms"] = tm_fb
            if fb_rows:
                cands = [extraction_candidate_from_evidence_row(r) for r in fb_rows]
                rep = {
                    **rep,
                    "recovered_by": "deterministic_fallback",
                    "fallback_row_count": len(fb_rows),
                    "deterministic_fallback_used": True,
                    "outcome": "success",
                }
        rep = dict(rep)
        rep["rows_emitted_to_pipeline"] = len(cands)
        _log_meeting_evidence_segment_extract(rep, segment_id=seg_id, row_count=len(cands))
        segment_reports.append(rep)
        internal_segments_processed += 1
        all_cands.extend(cands)
        for c in cands:
            prior_bits.append(c.text[:120])
        if is_interactive:
            if rep.get("llm_path_outcome") == "success" and not cands:
                consecutive_barren += 1
                if consecutive_barren >= INTERACTIVE_CONSECUTIVE_BARREN_SEGMENTS:
                    interactive_stop_reason = interactive_stop_reason or "consecutive_barren"
                    break
            else:
                consecutive_barren = 0
            n_model = sum(1 for c in all_cands if c.internal_source_stage == SOURCE_STAGE_MODEL)
            if n_model >= INTERACTIVE_MODEL_CANDIDATES_EARLY_STOP:
                interactive_early_stop = True
                interactive_stop_reason = interactive_stop_reason or "early_model_count"
                break
    failed = [r for r in segment_reports if r.get("error") and not r.get("skipped")]
    fn = (full_notes or "").strip()

    if not is_interactive and not any_valid_model_segment and fn and text_has_conversation_cover(fn):
        extra_rows = cover_phrase_evidence_rows(fn, "cover-supplement")
        if extra_rows:
            extra = [extraction_candidate_from_evidence_row(r) for r in extra_rows]
            n_before = len(all_cands)
            all_cands = merge_supplement_candidates(all_cands, extra)
            if len(all_cands) > n_before:
                n_add = len(all_cands) - n_before
                segment_reports.append(
                    {
                        "segment_id": "cover-supplement",
                        "recovered_by": "cover_phrase_supplement",
                        "row_count": n_add,
                        "rows_emitted_to_pipeline": n_add,
                    }
                )

    sparse_doc = len(all_cands) < 3
    if (
        not is_interactive
        and not any_valid_model_segment
        and fn
        and sparse_doc
        and re.search(r"speaker\s+[a-z0-9]", fn, re.I)
    ):
        extra2_rows = lexical_transcript_evidence_rows(fn, "transcript-supplement")
        if extra2_rows:
            extra2 = [extraction_candidate_from_evidence_row(r) for r in extra2_rows]
            n_before = len(all_cands)
            all_cands = merge_supplement_candidates(all_cands, extra2)
            if len(all_cands) > n_before:
                n_add2 = len(all_cands) - n_before
                segment_reports.append(
                    {
                        "segment_id": "transcript-supplement",
                        "recovered_by": "lexical_transcript_supplement",
                        "row_count": n_add2,
                        "rows_emitted_to_pipeline": n_add2,
                    }
                )

    is_transcript = bool(fn and re.search(r"speaker\s+[a-z0-9]", fn, re.I))
    if not is_interactive and not any_valid_model_segment and fn and len(fn) >= 120:
        # Flat candidates have no extract-time initiative/project typing; approximate old "sparse transcript" rule.
        need_clause_recovery = (not all_cands) or (is_transcript and len(all_cands) < 3)
        if need_clause_recovery:
            rec = substantive_clause_recovery_rows(fn, strict=clause_strict)
            if rec:
                rec_c = [extraction_candidate_from_evidence_row(r) for r in rec]
                if not all_cands:
                    all_cands = rec_c
                    segment_reports.append(
                        {
                            "segment_id": "clause-recovery",
                            "recovered_by": "substantive_clause_recovery",
                            "row_count": len(rec_c),
                            "rows_emitted_to_pipeline": len(rec_c),
                        }
                    )
                else:
                    n_before = len(all_cands)
                    all_cands = merge_supplement_candidates(all_cands, rec_c)
                    if len(all_cands) > n_before:
                        n_add3 = len(all_cands) - n_before
                        segment_reports.append(
                            {
                                "segment_id": "clause-recovery",
                                "recovered_by": "substantive_clause_recovery_supplement",
                                "row_count": n_add3,
                                "rows_emitted_to_pipeline": n_add3,
                            }
                        )

    t_post0 = time.perf_counter()
    pre_dedupe_n = len(all_cands)
    all_cands = dedupe_candidates_ordered(all_cands, sim_threshold=0.72)
    post_dedupe_n = len(all_cands)
    pre_filter_n = len(all_cands)
    all_cands = filter_extraction_candidates_by_text_quality(all_cands, interactive=is_interactive)
    post_filter_n = len(all_cands)
    evidence_post_process_ms = (time.perf_counter() - t_post0) * 1000.0

    llm_ms_total = 0.0
    for r in segment_reports:
        tm = r.get("timing_ms") or {}
        v = tm.get("llm_call")
        if isinstance(v, (int, float)):
            llm_ms_total += float(v)

    trace_summary = _build_evidence_extraction_trace_summary(
        evidence_extraction_preset=evidence_extraction_preset,
        timeout=timeout,
        evidence_segment_max_chunk=evidence_segment_max_chunk,
        is_interactive=is_interactive,
        segments_planned=len(segments),
        internal_segments_processed=internal_segments_processed,
        segment_reports=segment_reports,
        pre_dedupe_row_count=pre_dedupe_n,
        post_dedupe_row_count=post_dedupe_n,
        pre_filter_row_count=pre_filter_n,
        post_filter_row_count=post_filter_n,
    )
    trace_summary["final_candidate_count"] = post_filter_n
    logger.info("[evidence-extract-trace] %s", json.dumps(trace_summary, default=str))

    diag: dict[str, Any] = {
        "evidence_segments_total": len(segments),
        "evidence_segments_failed": len(failed),
        "evidence_segment_reports": segment_reports,
        "evidence_row_count": len(all_cands),
        "candidate_observation_only": True,
        "any_segment_valid_model_rows": any_valid_model_segment,
        **extraction_candidate_provenance_summary(all_cands),
        "confidence_tier_legend": CONFIDENCE_TIER_LEGEND,
        "evidence_extraction_preset": evidence_extraction_preset,
        "evidence_segment_llm_timeout_s": timeout,
        "interactive_lexical_fallback": not is_interactive,
        "interactive_document_supplements": not is_interactive,
        "interactive_early_stop_triggered": interactive_early_stop,
        "interactive_stop_reason": interactive_stop_reason,
        "evidence_internal_segments_processed": internal_segments_processed,
        "evidence_llm_ms_total": round(llm_ms_total, 2),
        "evidence_post_process_ms": round(evidence_post_process_ms, 2),
        "evidence_extraction_trace_summary": trace_summary,
    }
    if evidence_segment_max_chunk is not None:
        diag["evidence_segment_max_chunk"] = evidence_segment_max_chunk
    if routing_snap is not None:
        diag["evidence_llm_routing_snapshot"] = routing_snap
    _ev_public = [extraction_candidate_to_api_dict(c) for c in all_cands]
    _max_diag_rows = 400
    if len(_ev_public) > _max_diag_rows:
        diag["evidence_rows"] = _ev_public[:_max_diag_rows]
        diag["evidence_rows_truncated"] = True
        diag["evidence_rows_omitted_count"] = len(_ev_public) - _max_diag_rows
    else:
        diag["evidence_rows"] = _ev_public
        diag["evidence_rows_truncated"] = False
    if failed:
        diag["evidence_failed_segment_ids"] = [f.get("segment_id") for f in failed if f.get("segment_id")]
    return all_cands, diag


def extract_evidence_rows_all_segments(
    segments: list[tuple[str, str]],
    llm_generate: Callable[..., str],
    *,
    task_name: str = "meeting_evidence_segment",
    timeout: int = MEETING_EVIDENCE_SEGMENT_TIMEOUT_DEFAULT_S,
    rolling_prior_max_chars: int = 2800,
    full_notes: str = "",
    principal: ExecutionPrincipal | None = None,
    seam_routing_active: bool = False,
    evidence_extraction_preset: str = "default",
    evidence_segment_max_chunk: int | None = None,
) -> tuple[list[EvidenceRow], dict[str, Any]]:
    """Delegates to observation-only candidate extraction; maps each candidate to a synthetic idea-shaped row."""
    cands, diag = extract_candidate_rows_all_segments(
        segments,
        llm_generate,
        task_name=task_name,
        timeout=timeout,
        rolling_prior_max_chars=rolling_prior_max_chars,
        full_notes=full_notes,
        principal=principal,
        seam_routing_active=seam_routing_active,
        evidence_extraction_preset=evidence_extraction_preset,
        evidence_segment_max_chunk=evidence_segment_max_chunk,
    )
    return [_evidence_row_from_candidate(c) for c in cands], diag


def _label_cluster_key(label: str) -> str:
    """Alphanumeric tokens only — merges near-duplicate labels that fuzzy similarity misses."""
    s = re.sub(r"[^a-z0-9]+", " ", (label or "").lower())
    return " ".join(s.split())


def _cluster_indices_by_claim_type(rows: list[EvidenceRow], sim_threshold: float = 0.48) -> list[list[int]]:
    n = len(rows)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if rows[i].claim_type != rows[j].claim_type:
                continue
            ki = _label_cluster_key(rows[i].label)
            kj = _label_cluster_key(rows[j].label)
            same_norm = bool(ki) and ki == kj and len(ki) >= 4
            if _title_similarity(rows[i].label, rows[j].label) >= sim_threshold or same_norm:
                union(i, j)
    buckets: dict[int, list[int]] = {}
    for i in range(n):
        r = find(i)
        buckets.setdefault(r, []).append(i)
    return list(buckets.values())


def _float_to_conf(cf: float | None) -> str | None:
    if cf is None:
        return "medium"
    if cf >= 0.82:
        return "high"
    if cf >= 0.55:
        return "medium"
    return "low"


def _best_quote(cluster: list[EvidenceRow]) -> str | None:
    for r in sorted(cluster, key=lambda x: (x.confidence or 0.0), reverse=True):
        if r.evidence_quote.strip():
            return r.evidence_quote.strip()[:800]
    return None


def _merge_confidence(cluster: list[EvidenceRow]) -> str | None:
    scores = [r.confidence for r in cluster if r.confidence is not None]
    if not scores:
        return "medium"
    mx = max(scores)
    return _float_to_conf(mx)


def _pick_representative_label(cluster: list[EvidenceRow]) -> str:
    """Prefer longest substantive label within cluster (often most specific)."""
    return max(cluster, key=lambda r: (len(r.label), r.confidence or 0.0)).label.strip()


def _cluster_source_stage_summary(cluster: list[EvidenceRow]) -> dict[str, Any]:
    """How the clustered evidence rows were produced (for direct bucket entries)."""
    ctr = Counter(r.source_stage for r in cluster)
    primary = ctr.most_common(1)[0][0] if ctr else SOURCE_STAGE_MODEL
    return {
        "primarySourceStage": primary,
        "sourceStageCounts": dict(ctr),
        "primarySourceCategory": _source_category_for_row(primary),
        "primaryStructureTier": _structure_tier_for_source_stage(primary),
        "primaryConfidenceTier": _row_confidence_tier(_structure_tier_for_source_stage(primary)),
    }


def reduce_evidence_clusters_to_raw_extraction(
    rows: list[EvidenceRow],
    *,
    meeting_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Build the legacy typed shape expected by canonize_extraction / API (before canonization).

    Does **not** promote ideas into initiatives/projects or tasks into projects; clustering only.

    Returns ``(raw_extraction, reducer_diagnostics)``. Diagnostics are for
    ``return_diagnostics`` / logging only — not merged into the canonized product payload.
    """
    promotions: list[dict[str, Any]] = []
    direct_provenance: list[dict[str, Any]] = []

    if not rows:
        empty = {
            "summary": None,
            "insights": [],
            "ideas": [],
            "initiatives": [],
            "projects": [],
            "tasks": [],
            "assets": [],
            "peopleReferences": [],
            "signals": [],
            "meeting_id": meeting_id,
        }
        return empty, {
            "promotions": [],
            "direct_entity_provenance": [],
            "counts_after_clustering": {},
            "counts_after_promotion": {},
            "confidence_tier_legend": CONFIDENCE_TIER_LEGEND,
        }
    clusters = _cluster_indices_by_claim_type(rows)
    ideas: list[dict[str, Any]] = []
    initiatives: list[dict[str, Any]] = []
    projects: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    people: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    for idxs in clusters:
        cluster = [rows[i] for i in idxs]
        ct = cluster[0].claim_type
        label = _pick_representative_label(cluster)
        hid = sorted({r.id for r in cluster})
        excerpt = _best_quote(cluster)
        conf = _merge_confidence(cluster)
        details = " ".join({r.details for r in cluster if r.details})[:1500] or None
        owner = next((r.owner_hint for r in cluster if r.owner_hint), None)
        seg0 = cluster[0].segment_id
        if ct == "idea":
            ideas.append({
                "title": label,
                "summary": details or label,
                "description": details or "",
                "status": "Captured",
                "confidence": conf,
                "sourceExcerpt": excerpt,
                "harvestItemIds": hid,
                "segmentId": seg0,
                "segmentTitle": None,
            })
            direct_provenance.append(
                {"bucket": "ideas", "title": label, "formation": "direct_cluster", **_cluster_source_stage_summary(cluster)}
            )
        elif ct == "initiative":
            initiatives.append({
                "title": label,
                "brief": details or "",
                "status": "Draft",
                "ownerName": owner,
                "notes": "",
                "confidence": conf,
                "sourceExcerpt": excerpt,
                "existingInitiativeMatchId": None,
                "matchConfidence": None,
                "harvestItemIds": hid,
                "segmentId": seg0,
                "segmentTitle": None,
            })
            direct_provenance.append(
                {
                    "bucket": "initiatives",
                    "title": label,
                    "formation": "direct_cluster",
                    **_cluster_source_stage_summary(cluster),
                }
            )
        elif ct == "project":
            projects.append({
                "title": label,
                "brief": details or "",
                "status": "Draft",
                "initiativeTitle": None,
                "confidence": conf,
                "sourceExcerpt": excerpt,
                "existingInitiativeMatchId": None,
                "existingProjectMatchId": None,
                "matchConfidence": None,
                "harvestItemIds": hid,
                "segmentId": seg0,
                "segmentTitle": None,
            })
            direct_provenance.append(
                {"bucket": "projects", "title": label, "formation": "direct_cluster", **_cluster_source_stage_summary(cluster)}
            )
        elif ct == "task":
            tasks.append({
                "title": label,
                "description": details or "",
                "status": "Todo",
                "assigneeName": owner,
                "notes": "",
                "confidence": conf,
                "sourceExcerpt": excerpt,
                "existingProjectMatchId": None,
                "existingTaskMatchId": None,
                "existingPersonMatchId": None,
                "matchConfidence": None,
                "harvestItemIds": hid,
                "segmentId": seg0,
                "segmentTitle": None,
            })
            direct_provenance.append(
                {"bucket": "tasks", "title": label, "formation": "direct_cluster", **_cluster_source_stage_summary(cluster)}
            )
        elif ct == "asset":
            ak = _infer_asset_kind(label + " " + (details or ""))
            assets.append({
                "name": label,
                "kind": ak,
                "description": details,
                "confidence": conf,
                "sourceExcerpt": excerpt,
                "harvestItemIds": hid,
                "segmentId": seg0,
                "segmentTitle": None,
            })
            direct_provenance.append(
                {"bucket": "assets", "title": label, "formation": "direct_cluster", **_cluster_source_stage_summary(cluster)}
            )
        elif ct == "person":
            name, role = _split_person_label(label)
            people.append({
                "name": name,
                "role": role,
                "context": details,
                "confidence": conf,
                "sourceExcerpt": excerpt,
                "existingPersonMatchId": None,
                "matchConfidence": None,
                "harvestItemIds": hid,
                "segmentId": seg0,
                "segmentTitle": None,
            })
            direct_provenance.append(
                {"bucket": "peopleReferences", "title": name, "formation": "direct_cluster", **_cluster_source_stage_summary(cluster)}
            )
        elif ct == "signal":
            sk = cluster[0].signal_kind or "attention"
            for r in cluster:
                if r.signal_kind:
                    sk = r.signal_kind
                    break
            signals.append({
                "kind": sk,
                "label": label,
                "detail": details,
                "confidence": conf,
                "sourceExcerpt": excerpt,
                "harvestItemIds": hid,
                "segmentId": seg0,
                "segmentTitle": None,
            })
            direct_provenance.append(
                {"bucket": "signals", "title": label, "formation": "direct_cluster", **_cluster_source_stage_summary(cluster)}
            )
    counts_after_clustering = {
        "ideas": len(ideas),
        "initiatives": len(initiatives),
        "projects": len(projects),
        "tasks": len(tasks),
        "assets": len(assets),
        "peopleReferences": len(people),
        "signals": len(signals),
    }
    counts_after_promotion = dict(counts_after_clustering)
    _max_dp = 300
    raw_out = {
        "summary": None,
        "insights": [],
        "ideas": ideas,
        "initiatives": initiatives,
        "projects": projects,
        "tasks": tasks,
        "assets": assets,
        "peopleReferences": people,
        "signals": signals,
        "meeting_id": meeting_id,
    }
    reducer_diag: dict[str, Any] = {
        "promotions": promotions,
        "promotion_count": len(promotions),
        "direct_entity_provenance": direct_provenance[:_max_dp],
        "direct_entity_provenance_truncated": len(direct_provenance) > _max_dp,
        "direct_entity_provenance_omitted_count": max(0, len(direct_provenance) - _max_dp),
        "counts_after_clustering": counts_after_clustering,
        "counts_after_promotion": counts_after_promotion,
        "confidence_tier_legend": CONFIDENCE_TIER_LEGEND,
    }
    return raw_out, reducer_diag


def _infer_asset_kind(text: str) -> str:
    t = text.lower()
    if any(x in t for x in ("crm", "jane", "epic", "salesforce", "hubspot", "platform", "api", "integration", "dashboard", "radar")):
        return "system"
    if any(x in t for x in ("doc", "pdf", "template", "letter", "deck", "slides", "form", "survey")):
        return "document"
    if "video" in t or "meditation" in t or "audio" in t:
        return "media"
    return "other"


def _split_person_label(label: str) -> tuple[str, str | None]:
    if " - " in label:
        a, b = label.split(" - ", 1)
        a, b = a.strip(), b.strip()
        if a and b:
            return a, b
    return label.strip(), None


def evidence_rows_to_harvest_ledger(meeting_id: str, rows: list[EvidenceRow]) -> HarvestLedger:
    """Synthetic ledger for harvest UI — derived from evidence rows (no separate harvest LLM)."""
    created_at = str(int(time.time() * 1000))
    if not rows:
        return HarvestLedger.empty(meeting_id)
    items: list[HarvestItem] = []
    for i, r in enumerate(sorted(rows, key=lambda x: (x.segment_id, x.id))):
        cat = "other"
        if r.claim_type == "task":
            cat = "deliverable"
        elif r.claim_type == "initiative":
            cat = "workflow"
        elif r.claim_type == "project":
            cat = "workflow"
        elif r.claim_type == "idea":
            cat = "speculative_product"
        elif r.claim_type == "asset":
            cat = "integration"
        elif r.claim_type == "person":
            cat = "dependency"
        elif r.claim_type == "signal":
            cat = "dependency"
        if cat not in VALID_HARVEST_CATEGORIES:
            cat = "other"
        items.append(
            HarvestItem(
                id=r.id,
                ordinal=i + 1,
                label=r.label[:2000],
                raw_text=(r.evidence_quote or r.label)[:2000],
                speaker=None,
                source_segment_id=r.segment_id,
                source_turn_index=None,
                category_hint=cat,
                speculative=(r.confidence or 0.5) < 0.45,
                confidence=r.confidence,
                normalized_from=None,
                mapped_entity_ids=[],
                notes=(r.details[:500] if r.details else None),
            )
        )
    return HarvestLedger(transcript_id=meeting_id, created_at=created_at, items=items)


def _deterministic_summary_bullets(ext: dict[str, Any]) -> str:
    lines: list[str] = []
    cands = ext.get("candidates") or []
    if isinstance(cands, list) and cands:
        for it in cands[:24]:
            if isinstance(it, dict) and (it.get("text") or "").strip():
                lines.append(f"Candidate: {it['text']}")
        if lines:
            return "\n".join(lines)
    for it in (ext.get("initiatives") or [])[:12]:
        if isinstance(it, dict) and it.get("title"):
            lines.append(f"Initiative: {it['title']}")
    for it in (ext.get("projects") or [])[:15]:
        if isinstance(it, dict) and it.get("title"):
            lines.append(f"Project: {it['title']}")
    for it in (ext.get("signals") or [])[:10]:
        if isinstance(it, dict):
            lines.append(f"Signal ({it.get('kind')}): {it.get('label')}")
    for it in (ext.get("tasks") or [])[:10]:
        if isinstance(it, dict) and it.get("title"):
            lines.append(f"Task: {it['title']}")
    return "\n".join(lines) if lines else "(no structured items)"


def build_deterministic_summary(ext: dict[str, Any]) -> dict[str, Any] | None:
    inits = [i.get("title") for i in (ext.get("initiatives") or []) if isinstance(i, dict) and i.get("title")]
    projs = [p.get("title") for p in (ext.get("projects") or []) if isinstance(p, dict) and p.get("title")]
    if not inits and not projs:
        return None
    parts = []
    if inits:
        parts.append("Main themes: " + ", ".join(inits[:8]) + ".")
    if projs:
        parts.append("Workstreams mentioned: " + ", ".join(projs[:10]) + ".")
    text = " ".join(parts).strip()
    return {"text": text[:2000], "confidence": "medium"}


def run_optional_meeting_polish(
    llm_generate: Callable[..., str],
    ext: dict[str, Any],
    *,
    task_name: str = "meeting_extract_polish",
    timeout: int = 50,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    Optional LLM pass: replaces ``summary`` and ``insights`` only (prompt forbids new initiatives/tasks/etc.).

    Gated by ``extract_meeting`` / ``extract_meeting_synthesis`` (``include_meeting_polish``);
    not invoked on ``fast_local`` preset.
    """
    bullets = _deterministic_summary_bullets(ext)
    if len(bullets) > 6000:
        bullets = bullets[:6000]
    prompt = MEETING_POLISH_PROMPT.format(bullets=bullets)
    diag: dict[str, Any] = {}
    try:
        raw = (llm_generate(task=task_name, prompt=prompt, timeout=timeout) or "").strip()
    except Exception as e:
        diag["polish_error"] = "llm_failed"
        diag["polish_message"] = str(e)
        logger.warning("run_optional_meeting_polish: failed: %s", e)
        return None, diag
    t = _repair_json_outer(raw)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        diag["polish_error"] = "parse_failed"
        diag["polish_raw_sample"] = raw[:600]
        return None, diag
    if not isinstance(data, dict):
        diag["polish_error"] = "invalid_shape"
        return None, diag
    return data, diag


def apply_context_entity_links(raw: dict[str, Any], context: dict[str, Any] | None) -> None:
    """Mutates raw extraction dict to set existing*MatchId when titles match context entities."""
    if not context or not isinstance(context, dict):
        return

    def best_match(title: str, candidates: list[dict[str, Any]]) -> tuple[str | None, float]:
        best_id = None
        best_sc = 0.0
        for c in candidates:
            if not isinstance(c, dict):
                continue
            tid = c.get("id")
            if not tid:
                continue
            t2 = str(c.get("title") or c.get("name") or "").strip()
            if not t2:
                continue
            sc = _title_similarity(title, t2)
            if sc > best_sc:
                best_sc = sc
                best_id = str(tid).strip()
        if best_sc >= 0.52 and best_id:
            return best_id, best_sc
        return None, best_sc

    for key, lst_key, id_field, title_key in (
        ("initiatives", "initiatives", "existingInitiativeMatchId", "title"),
        ("projects", "projects", "existingProjectMatchId", "title"),
        ("tasks", "tasks", "existingTaskMatchId", "title"),
        ("assets", "assets", "existingAssetMatchId", "name"),
        ("people", "peopleReferences", "existingPersonMatchId", "name"),
    ):
        items = raw.get(lst_key)
        ctx_items = context.get(key)
        if not isinstance(items, list) or not isinstance(ctx_items, list):
            continue
        ctx_list = [c for c in ctx_items if isinstance(c, dict)]
        for it in items:
            if not isinstance(it, dict):
                continue
            title = str(it.get(title_key) or it.get("title") or it.get("name") or "").strip()
            if not title:
                continue
            mid, sc = best_match(title, ctx_list)
            if mid:
                it[id_field] = mid
                it["matchConfidence"] = round(sc, 3)


def summaries_to_evidence_rows(segment_summaries: list[dict[str, Any]]) -> list[EvidenceRow]:
    """
    Deterministic bridge: segment-summary JSON -> evidence rows (no LLM).
    Used by extract_meeting_synthesis instead of a monolithic synthesis model call.
    """
    rows: list[EvidenceRow] = []
    for i, s in enumerate(segment_summaries):
        if not isinstance(s, dict):
            continue
        sid = str(s.get("segmentId") or s.get("segment_id") or f"seg-{i:04d}")
        topic = str(s.get("topic") or "").strip()
        brief = str(s.get("briefSummary") or s.get("brief_summary") or "").strip()
        if topic:
            rows.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=sid,
                    claim_type="initiative",
                    label=topic[:500],
                    details=brief[:1500] if brief else "",
                    owner_hint=None,
                    time_hint=None,
                    evidence_quote=(brief or topic)[:800],
                    signal_kind=None,
                    confidence=0.65,
                    source_stage=SOURCE_STAGE_SEGMENT_SUMMARY,
                )
            )
        elif brief:
            rows.append(
                EvidenceRow(
                    id=uuid.uuid4().hex[:12],
                    segment_id=sid,
                    claim_type="initiative",
                    label=brief[:120] + ("…" if len(brief) > 120 else ""),
                    details=brief[:1500],
                    owner_hint=None,
                    time_hint=None,
                    evidence_quote=brief[:800],
                    signal_kind=None,
                    confidence=0.5,
                    source_stage=SOURCE_STAGE_SEGMENT_SUMMARY,
                )
            )
        tasks = s.get("candidateTasks") or s.get("candidate_tasks") or []
        if isinstance(tasks, list):
            for t in tasks:
                ts = str(t).strip() if not isinstance(t, dict) else str(t.get("title") or t.get("text") or "").strip()
                if not ts or ts.lower().startswith("speaker "):
                    continue
                rows.append(
                    EvidenceRow(
                        id=uuid.uuid4().hex[:12],
                        segment_id=sid,
                        claim_type="task",
                        label=ts[:500],
                        details="",
                        owner_hint=None,
                        time_hint=None,
                        evidence_quote=ts[:800],
                        signal_kind=None,
                        confidence=0.62,
                        source_stage=SOURCE_STAGE_SEGMENT_SUMMARY,
                    )
                )
        entities = s.get("candidateEntities") or s.get("candidate_entities") or []
        if isinstance(entities, list):
            for e in entities:
                es = str(e).strip() if not isinstance(e, dict) else str(e.get("name") or e.get("title") or "").strip()
                if not es or re.match(r"^speaker\s+[a-z0-9]", es, re.I):
                    continue
                ct = "project"
                if re.match(r"^[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?\s+-\s+.+", es):
                    ct = "person"
                rows.append(
                    EvidenceRow(
                        id=uuid.uuid4().hex[:12],
                        segment_id=sid,
                        claim_type=ct,
                        label=es[:500],
                        details="",
                        owner_hint=None,
                        time_hint=None,
                        evidence_quote=es[:800],
                        signal_kind=None,
                        confidence=0.58,
                        source_stage=SOURCE_STAGE_SEGMENT_SUMMARY,
                    )
                )
        sigs = s.get("candidateSignals") or s.get("candidate_signals") or []
        if isinstance(sigs, list):
            for sg in sigs:
                if not isinstance(sg, dict):
                    continue
                kind = str(sg.get("kind") or "attention").strip().lower()
                if kind not in VALID_SIGNAL_KINDS:
                    kind = "attention"
                lab = str(sg.get("label") or sg.get("detail") or kind).strip() or kind
                det = str(sg.get("detail") or "").strip() or None
                quote = (lab + (" — " + det if det else ""))[:800]
                rows.append(
                    EvidenceRow(
                        id=uuid.uuid4().hex[:12],
                        segment_id=sid,
                        claim_type="signal",
                        label=lab[:500],
                        details=det or "",
                        owner_hint=None,
                        time_hint=None,
                        evidence_quote=quote,
                        signal_kind=kind,
                        confidence=0.6,
                        source_stage=SOURCE_STAGE_SEGMENT_SUMMARY,
                    )
                )
    return rows
