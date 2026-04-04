"""
One-off diagnostic: run default evidence extraction with per-segment raw JSON capture.

Usage (repo root):
  python tools/meeting_extract_trace_run.py "C:/path/to/Meeting 2.txt"

Prints a structured report to stdout; does not change product code paths except wrapping llm_generate.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SEG_ID_RE = re.compile(r"Segment \(id=([^)]+)\):\s*\n---", re.MULTILINE)


def _segment_id_from_prompt(prompt: str) -> str:
    m = _SEG_ID_RE.search(prompt or "")
    return m.group(1).strip() if m else "unknown"


def _classify_raw_row(d: dict, segment_id: str) -> tuple[str, list[str]]:
    """Reasons why extraction_candidate_from_llm_row would drop; empty list if row becomes a candidate."""
    from local_ai.vision_execution.meeting_evidence_pipeline import (
        extraction_candidate_from_llm_row,
    )
    from local_ai.vision_execution.meeting_proposition import title_is_propositional

    text = str(d.get("text") or "").strip()
    reasons: list[str] = []
    if len(text) < 4:
        reasons.append("schema: text shorter than 4 characters")
        return text, reasons
    if not title_is_propositional(text):
        reasons.append("proposition gate: title_is_propositional(text) is False")
        return text, reasons
    c = extraction_candidate_from_llm_row(d, segment_id=segment_id)
    if c is None:
        reasons.append("unexpected: extraction_candidate_from_llm_row returned None after proposition check")
        return text, reasons
    return text, []


def _why_post_pipeline_drop(text: str, *, interactive: bool) -> str | None:
    from local_ai.vision_execution.meeting_candidate_quality import candidate_text_passes_api_quality
    from local_ai.vision_execution.meeting_proposition import title_is_propositional

    if not title_is_propositional(text):
        return "post-pass: title_is_propositional False"
    if not candidate_text_passes_api_quality(text, interactive=interactive):
        return "post-pass: candidate_text_passes_api_quality False (chatter / vague / low substance heuristics)"
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python tools/meeting_extract_trace_run.py <path-to-transcript.txt>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]).expanduser()
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 2

    notes = path.read_text(encoding="utf-8", errors="replace")

    from local_ai.vision_execution.meeting_extract import _llm_generate, _meeting_execution_principal, preclean_transcript
    from local_ai.vision_execution.meeting_evidence_pipeline import (
        SOURCE_STAGE_MODEL,
        describe_meeting_evidence_llm_routing,
        extract_candidate_rows_all_segments,
        extraction_candidate_from_llm_row,
        parse_candidate_segment_llm_json,
        resolve_meeting_evidence_extraction_preset,
        segment_notes_for_evidence,
    )
    from local_ai.vision_execution.meeting_literal_anchors import literal_anchor_candidates_for_chunk

    notes = preclean_transcript(notes)
    ev_timeout_s, ev_max_chunk, ev_preset_label, ev_min_merge = resolve_meeting_evidence_extraction_preset("default")
    segments = segment_notes_for_evidence(notes, max_chunk=ev_max_chunk, min_merge=ev_min_merge)
    principal = _meeting_execution_principal(None)
    routing_snap = describe_meeting_evidence_llm_routing(principal, seam_routing_active=False)

    trace: list[dict] = []

    def llm_generate(*, task: str | None = None, prompt: str | None = None, timeout: int | None = None) -> str:
        assert prompt is not None
        seg_id = _segment_id_from_prompt(prompt)
        entry: dict = {"segment_id": seg_id, "llm_error": None, "parse_meta": None, "rows_raw": []}
        try:
            raw = (_llm_generate(principal, task=str(task or ""), prompt=prompt, timeout=int(timeout or 60)) or "").strip()
        except Exception as e:
            entry["llm_error"] = repr(e)
            trace.append(entry)
            raise
        rows_raw, parse_meta = parse_candidate_segment_llm_json(raw)
        entry["parse_meta"] = dict(parse_meta)
        entry["rows_raw"] = rows_raw or []
        entry["raw_response_chars"] = len(raw)
        trace.append(entry)
        return raw

    is_interactive = ev_preset_label == "fast_local"
    cands, diag = extract_candidate_rows_all_segments(
        segments,
        llm_generate,
        task_name="meeting_evidence_segment",
        timeout=ev_timeout_s,
        rolling_prior_max_chars=2800,
        full_notes=notes,
        principal=principal,
        seam_routing_active=False,
        evidence_extraction_preset=ev_preset_label,
        evidence_segment_max_chunk=ev_max_chunk,
        workspace_mirror_block="",
    )

    _, lit_meta = literal_anchor_candidates_for_chunk(notes, None, workspace_packet=None)

    def cand_from_row(d: dict, sid: str):
        return extraction_candidate_from_llm_row(d, segment_id=sid) if isinstance(d, dict) else None

    passed_model_cands: list = []
    for t in trace:
        sid = t.get("segment_id") or "unknown"
        for d in t.get("rows_raw") or []:
            c = cand_from_row(d, sid)
            if c:
                passed_model_cands.append(c)

    reports = diag.get("evidence_segment_reports") or []

    print("=== meeting extract trace ===")
    print(json.dumps({"file": str(path), "preset": ev_preset_label, "segment_count": len(segments), "routing": routing_snap}, indent=2))
    print("\n--- literal grounding (background only) ---")
    print(
        json.dumps(
            {
                "raw_anchor_count": lit_meta.get("raw_anchor_count"),
                "grounding_only_count": lit_meta.get("grounding_only_count"),
                "literal_review_promotion_disabled": lit_meta.get("literal_review_promotion_disabled"),
            },
            indent=2,
        )
    )

    print("\n--- 1) Chunks with model-backed segment rows (after proposition gate in extraction_candidate_from_llm_row) ---")
    for t in trace:
        sid = t["segment_id"]
        kept = sum(1 for d in t.get("rows_raw") or [] if cand_from_row(d, sid) is not None)
        if t.get("llm_error"):
            continue
        if kept > 0:
            print(f"  {sid}: {kept} row(s) passed proposition gate from JSON")

    print("\n--- 2) Chunks with empty model JSON or no passing rows ---")
    for i, t in enumerate(trace):
        sid = t["segment_id"]
        if t.get("llm_error"):
            print(f"  {sid}: LLM error — {t['llm_error']}")
            continue
        pm = t.get("parse_meta") or {}
        rows_raw = t.get("rows_raw") or []
        if not pm.get("decode_ok"):
            print(f"  {sid}: parse/decode failed — {pm.get('reason')}")
            continue
        if pm.get("hard_empty") or len(rows_raw) == 0:
            print(f"  {sid}: hard_empty or rows=[] (outcome={pm.get('reason') or 'ok'})")
            continue
        kept = sum(1 for d in rows_raw if cand_from_row(d, sid) is not None)
        if kept == 0:
            print(f"  {sid}: JSON had {len(rows_raw)} row(s) but none passed proposition gate")

    print("\n--- 3–4) Raw model rows dropped at proposition gate (per segment) ---")
    dropped: list[dict] = []
    for t in trace:
        sid = t["segment_id"]
        for d in t.get("rows_raw") or []:
            if not isinstance(d, dict):
                continue
            text, reasons = _classify_raw_row(d, sid)
            if reasons:
                dropped.append({"segment_id": sid, "text": text, "reasons": reasons})
    if not dropped:
        print("  (none)")
    else:
        for item in dropped:
            print(f"  segment={item['segment_id']}")
            print(f"    raw text: {json.dumps(item['text'][:500])}")
            print(f"    why: {'; '.join(item['reasons'])}")

    print("\n--- Model rows lost after JSON (dedupe + quality on full merged stream) ---")
    from local_ai.vision_execution.extraction_canonization import _title_similarity
    from local_ai.vision_execution.meeting_candidate_quality import filter_extraction_candidates_by_text_quality
    from local_ai.vision_execution.meeting_evidence_pipeline import public_source_stage_for_internal

    def best_match(text: str, pool: list):
        best = None
        best_sc = 0.0
        for x in pool:
            sc = _title_similarity(text, x.text)
            if sc > best_sc:
                best_sc = sc
                best = x
        return best, best_sc

    final_pool = list(cands)
    for c in passed_model_cands:
        mate, sc = best_match(c.text, final_pool)
        if mate and sc >= 0.72:
            continue
        q = _why_post_pipeline_drop(c.text, interactive=is_interactive)
        if q:
            print(f"  FILTERED segment={c.segment_id} id={c.id}")
            print(f"    text: {json.dumps(c.text[:400])}")
            print(f"    why: {q}")
        else:
            print(f"  NOT_IN_FINAL segment={c.segment_id} id={c.id}")
            print(f"    text: {json.dumps(c.text[:400])}")
            print(
                "    why: no final candidate within similarity 0.72 — typically dropped earlier in "
                "dedupe_candidates_ordered because a similar row (model or cover/lexical/clause) appeared first "
                "in the merged list, or filtered as part of the combined post-process pass"
            )

    only_model_final = [c for c in cands if c.internal_source_stage == SOURCE_STAGE_MODEL]
    after_filter_model_only = filter_extraction_candidates_by_text_quality(only_model_final, interactive=is_interactive)
    for c in only_model_final:
        if c not in after_filter_model_only:
            w = _why_post_pipeline_drop(c.text, interactive=is_interactive) or "unknown"
            print(f"  FINAL_MODEL_FILTERED segment={c.segment_id}")
            print(f"    text: {json.dumps(c.text[:400])}")
            print(f"    why: {w}")

    print("\n--- Summary counts ---")
    by_stage = {}
    for c in cands:
        by_stage[c.internal_source_stage] = by_stage.get(c.internal_source_stage, 0) + 1
    print(
        json.dumps(
            {
                "final_candidate_count": len(cands),
                "final_rows_by_internal_source_stage": by_stage,
                "final_model_rows_public": sum(
                    1
                    for c in cands
                    if public_source_stage_for_internal(c.internal_source_stage) == "model"
                ),
                "trace_llm_calls": len(trace),
                "json_rows_dropped_at_proposition_gate": len(dropped),
                "json_rows_passing_proposition_gate": len(passed_model_cands),
                "any_segment_valid_model_rows": diag.get("any_segment_valid_model_rows"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
