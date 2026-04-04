"""
Harvest-first pipeline for meeting / transcript extraction (passes 1–2).

Pass 1 — HARVEST: recall-maximal units of work, transcript order, no ontology.
Pass 2 — NORMALIZE: short action+object labels without reducing item count.

Mapping (pass 3+) is owned by meeting_extract ontology prompts + ledger injection.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Callable

from local_ai.vision_execution.harvest_substrate import (
    VALID_HARVEST_CATEGORIES,
    HarvestItem,
    HarvestLedger,
)

logger = logging.getLogger(__name__)

HARVEST_PASS_PROMPT = """You are a requirement harvester for meeting / transcript text.

This is NOT summarization. Do NOT merge, theme, dedupe, prioritize, or map to projects/initiatives.
Your job is RECALL-FIRST: extract every plausible unit of work or explicit ask in CHRONOLOGICAL ORDER.

Rules:
- Read the transcript top-to-bottom. Emit items in that order; ordinal starts at 1 and increases by 1 per item.
- One sentence may contain MULTIPLE asks — split into separate items.
- If unsure whether something is work-relevant, INCLUDE IT (prefer recall over cleanliness).
- Mark hedged / future / "maybe" / "we might" items as speculative: true.
- category_hint (optional): one of deliverable, research, workflow, content, media, integration, monetization, scheduling, dependency, speculative_product, other.
- confidence: number 0.0–1.0 for how clear the ask is (vague phrases can be 0.4–0.6).
- raw_text: verbatim clause or sentence span from the transcript (short but exact).
- label: short copy of raw_text for now (pass 2 will refine to action+object).
- speaker: name or label if obvious from line prefix (e.g. "Jay:"), else null.
- Do NOT drop soft or weird asks. Do NOT output initiatives, projects, or tasks tables — only the items array.

Detection cues (non-exhaustive): can you, could you, I want, we need, let's, it would be good to, look into, explore, review, revisit, build, create, set up, distill, summarize, estimate, integrate, test, run through, figure out, see if, charge, sell, monthly, subscription, make money, referral, should we, need to, have to, want to.

Output ONLY valid JSON:
{
  "items": [
    {
      "ordinal": 1,
      "raw_text": "...",
      "label": "...",
      "speaker": null,
      "category_hint": "research",
      "speculative": false,
      "confidence": 0.85,
      "notes": null
    }
  ]
}

Transcript:
---
{text}
---

JSON only, no markdown fence:
"""

NORMALIZE_PASS_PROMPT = """You normalize requirement ledger labels without removing or merging rows.

Input is JSON items with id, ordinal, raw_text, label, speaker, category_hint, speculative, confidence.
For EACH item (same count as input):
- Set label to a concise "action + object" phrase (no fillers). Do NOT merge rows.
- If label changes meaningfully from raw_text, set normalized_from to the previous label (else null).
- Preserve ordinal, id, raw_text, speaker, category_hint, speculative, confidence, notes.
- Do NOT dedupe. Do NOT drop items. Output length MUST equal input length.

Input:
{items_json}

Output ONLY valid JSON: {{ "items": [ ... ] }} with the same number of objects as input, same id and ordinal each.
JSON only:
"""


def _repair_json_outer(s: str) -> str:
    t = (s or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    t = t.strip()
    if t and not t.startswith("{"):
        i = t.find("{")
        if i != -1:
            t = t[i:]
    if t and not t.rstrip().endswith("}"):
        j = t.rfind("}")
        if j != -1:
            t = t[: j + 1]
    return t


def _parse_harvest_response(raw: str) -> list[dict[str, Any]]:
    t = _repair_json_outer(raw)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            out.append(it)
    return out


def _assign_ids_and_validate(
    rows: list[dict[str, Any]],
    *,
    transcript_id: str,
    source_segment_id: str | None = None,
) -> list[HarvestItem]:
    items: list[HarvestItem] = []
    for i, row in enumerate(rows):
        oid = row.get("id")
        hid = str(oid).strip() if oid else uuid.uuid4().hex[:12]
        ord_raw = row.get("ordinal")
        try:
            ordinal = int(ord_raw) if ord_raw is not None else i + 1
        except (TypeError, ValueError):
            ordinal = i + 1
        raw_text = str(row.get("raw_text") or "").strip()
        label = str(row.get("label") or raw_text).strip()
        sp = row.get("speaker")
        speaker = str(sp).strip() if sp else None
        ch = row.get("category_hint")
        category = None
        if ch is not None and str(ch).strip():
            c = str(ch).strip().lower()
            category = c if c in VALID_HARVEST_CATEGORIES else "other"
        spec = bool(row.get("speculative"))
        conf = row.get("confidence")
        try:
            cf = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            cf = None
        if cf is not None:
            cf = max(0.0, min(1.0, cf))
        notes = row.get("notes")
        notes_s = str(notes).strip() if notes else None
        items.append(
            HarvestItem(
                id=hid,
                ordinal=ordinal,
                label=label,
                raw_text=raw_text or label,
                speaker=speaker,
                source_segment_id=source_segment_id,
                source_turn_index=None,
                category_hint=category,
                speculative=spec,
                confidence=cf,
                normalized_from=None,
                mapped_entity_ids=[],
                notes=notes_s,
            )
        )
    items.sort(key=lambda x: (x.ordinal, x.id))
    return items


def run_harvest_pass(
    text: str,
    *,
    transcript_id: str,
    llm_generate: Callable[..., str],
    task_name: str = "meeting_harvest",
    timeout: int = 90,
    source_segment_id: str | None = None,
) -> HarvestLedger:
    """Pass 1 — harvest only."""
    t = (text or "").strip()
    if not t:
        return HarvestLedger.empty(transcript_id)
    prompt = HARVEST_PASS_PROMPT.replace("{text}", t[:12000])
    try:
        raw = (llm_generate(task=task_name, prompt=prompt, timeout=timeout) or "").strip()
    except Exception as e:
        logger.warning("run_harvest_pass: llm failed: %s", e)
        return HarvestLedger.empty(transcript_id)
    rows = _parse_harvest_response(raw)
    if not rows:
        logger.warning("run_harvest_pass: no items parsed")
        return HarvestLedger.empty(transcript_id)
    items = _assign_ids_and_validate(rows, transcript_id=transcript_id, source_segment_id=source_segment_id)
    return HarvestLedger(
        transcript_id=transcript_id,
        created_at=str(int(time.time() * 1000)),
        items=items,
    )


def run_normalize_pass(
    ledger: HarvestLedger,
    *,
    llm_generate: Callable[..., str],
    task_name: str = "meeting_harvest_normalize",
    timeout: int = 90,
) -> HarvestLedger:
    """Pass 2 — labels only; same item count."""
    if not ledger.items:
        return ledger
    payload = [
        {
            "id": it.id,
            "ordinal": it.ordinal,
            "raw_text": it.raw_text,
            "label": it.label,
            "speaker": it.speaker,
            "category_hint": it.category_hint,
            "speculative": it.speculative,
            "confidence": it.confidence,
            "notes": it.notes,
        }
        for it in ledger.items
    ]
    prompt = NORMALIZE_PASS_PROMPT.replace("{items_json}", json.dumps(payload, ensure_ascii=False))
    try:
        raw = (llm_generate(task=task_name, prompt=prompt, timeout=timeout) or "").strip()
    except Exception as e:
        logger.warning("run_normalize_pass: llm failed: %s", e)
        return ledger
    t = _repair_json_outer(raw)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        return ledger
    if not isinstance(data, dict):
        return ledger
    out_rows = data.get("items")
    if not isinstance(out_rows, list) or len(out_rows) != len(ledger.items):
        logger.warning(
            "run_normalize_pass: length mismatch got=%s expected=%s",
            len(out_rows) if isinstance(out_rows, list) else None,
            len(ledger.items),
        )
        return ledger
    by_id = {it.id: it for it in ledger.items}
    new_items: list[HarvestItem] = []
    for row, prev in zip(out_rows, ledger.items):
        if not isinstance(row, dict):
            new_items.append(prev)
            continue
        rid = str(row.get("id") or "").strip() or prev.id
        base = by_id.get(rid, prev)
        new_label = str(row.get("label") or base.label).strip()
        prev_label = base.label
        normalized_from = None
        if new_label != prev_label and prev_label:
            normalized_from = prev_label
        nf = row.get("normalized_from")
        if nf is not None and str(nf).strip():
            normalized_from = str(nf).strip()
        new_items.append(
            HarvestItem(
                id=base.id,
                ordinal=base.ordinal,
                label=new_label or base.raw_text,
                raw_text=str(row.get("raw_text") or base.raw_text).strip(),
                speaker=base.speaker if row.get("speaker") is None else _opt_speaker(row.get("speaker")),
                source_segment_id=base.source_segment_id,
                source_turn_index=base.source_turn_index,
                category_hint=base.category_hint if row.get("category_hint") is None else _opt_cat(row.get("category_hint")),
                speculative=base.speculative if row.get("speculative") is None else bool(row.get("speculative")),
                confidence=base.confidence if row.get("confidence") is None else _opt_cf(row.get("confidence")),
                normalized_from=normalized_from,
                mapped_entity_ids=list(base.mapped_entity_ids),
                notes=base.notes if row.get("notes") is None else _opt_notes(row.get("notes")),
            )
        )
    return HarvestLedger(
        transcript_id=ledger.transcript_id,
        created_at=ledger.created_at,
        items=new_items,
    )


def _opt_speaker(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _opt_cat(v: Any) -> str | None:
    if v is None:
        return None
    c = str(v).strip().lower()
    return c if c in VALID_HARVEST_CATEGORIES else "other"


def _opt_cf(v: Any) -> float | None:
    try:
        x = float(v)
        return max(0.0, min(1.0, x))
    except (TypeError, ValueError):
        return None


def _opt_notes(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def format_ledger_for_map_prompt(ledger: HarvestLedger) -> str:
    """Compact block injected before ontology mapping."""
    lines = [
        "=== REQUIREMENT LEDGER (authoritative recall; map every id — do not drop rows) ===",
        "Each line: [id] (ordinal) label | raw: … | category | speculative",
    ]
    for it in ledger.items:
        sp = f" | speaker={it.speaker}" if it.speaker else ""
        spec = " speculative" if it.speculative else ""
        cat = f" | {it.category_hint}" if it.category_hint else ""
        conf = f" | conf={it.confidence}" if it.confidence is not None else ""
        lines.append(
            f"[{it.id}] ({it.ordinal}) {it.label[:500]}{sp}{cat}{spec}{conf}\n"
            f"    raw: {it.raw_text[:800]}"
        )
    lines.append("=== END LEDGER ===")
    return "\n".join(lines)


LEDGER_MODE_PREFIX = """WHEN A REQUIREMENT LEDGER appears below, it takes precedence over conflicting instructions in this prompt:
- Do NOT merge or theme-compress distinct ledger rows into generic buckets for this mapping pass.
- Do NOT drop vague or speculative ledger rows — represent them as tasks or ideas.
- Full ledger coverage via harvestItemIds on output entities is mandatory.
"""

LEDGER_MAP_RULES = """

LEDGER-AWARE MAPPING (mandatory when a REQUIREMENT LEDGER is present above):
- The ledger is the recall substrate. Your job in THIS pass is to MAP ledger rows into ideas, initiatives, projects, tasks, signals, assets, and people — NOT to re-harvest or compress the transcript into themes.
- Do NOT merge multiple ledger rows into one entity unless they are verbatim duplicates of the same ask (rare). Prefer one entity per distinct ledger row when unsure.
- Every ledger id MUST appear in at least one output object's \"harvestItemIds\" array. If an ask does not fit a bucket, attach it to the closest task or idea and still list the id.
- Include optional \"harvestItemIds\": [\"...\"] on ideas, initiatives, projects, tasks, signals (and assets/people when applicable) listing which ledger row ids are grounded in that entity.
- You may still fill summary/insights from the notes, but they must not replace or hide ledger coverage.
"""


def build_full_harvest_ledger(
    notes_clean: str,
    *,
    meeting_id: str,
    llm_generate: Callable[..., str],
    skip_harvest: bool = False,
    source_segment_id: str | None = None,
) -> HarvestLedger:
    """Passes 1–2 only."""
    if skip_harvest or not (notes_clean or "").strip():
        return HarvestLedger.empty(meeting_id)
    h1 = run_harvest_pass(
        notes_clean,
        transcript_id=meeting_id,
        llm_generate=llm_generate,
        task_name="meeting_harvest",
        source_segment_id=source_segment_id,
    )
    if not h1.items:
        return h1
    return run_normalize_pass(h1, llm_generate=llm_generate, task_name="meeting_harvest_normalize")
