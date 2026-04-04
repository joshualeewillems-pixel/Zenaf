"""
Compact, human-readable extraction formation summaries for diagnostics and test/nightly logs.

Builds on provenance emitted under ``_diagnostics["evidence"]`` (see ``meeting_evidence_pipeline``).
Does not alter product extraction payloads.
"""

from __future__ import annotations

from typing import Any

from local_ai.vision_execution.meeting_evidence_pipeline import (
    SOURCE_STAGE_CLAUSE_RECOVERY,
    SOURCE_STAGE_COVER_PHRASE,
    SOURCE_STAGE_LEXICAL_TRANSCRIPT,
    SOURCE_STAGE_LITERAL_ANCHOR,
    SOURCE_STAGE_MODEL,
    SOURCE_STAGE_SEGMENT_SUMMARY,
)


def _n(d: dict[str, Any], key: str) -> int:
    v = d.get(key)
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def build_formation_summary_from_evidence_diag(ev_diag: dict[str, Any] | None) -> dict[str, Any]:
    """
    Derive a short story from the evidence diagnostics block (including optional ``reducer``).

    Returns JSON-serializable dict with ``one_line``, ``text``, ``structured``, and ``signals``.
    """
    if not ev_diag or not isinstance(ev_diag, dict):
        return {
            "one_line": "no_evidence_diagnostics",
            "text": "No evidence diagnostics block present.",
            "structured": {},
            "signals": ["missing_evidence_diag"],
        }

    src = ev_diag.get("source_stage_counts") or {}
    if not isinstance(src, dict):
        src = {}

    def sc(stage: str) -> int:
        v = src.get(stage)
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    n_model = sc(SOURCE_STAGE_MODEL)
    n_cover = sc(SOURCE_STAGE_COVER_PHRASE)
    n_lex = sc(SOURCE_STAGE_LEXICAL_TRANSCRIPT)
    n_clause = sc(SOURCE_STAGE_CLAUSE_RECOVERY)
    n_synth = sc(SOURCE_STAGE_SEGMENT_SUMMARY)
    n_literal = sc(SOURCE_STAGE_LITERAL_ANCHOR)
    n_lexical_total = n_cover + n_lex

    total_rows = _n(ev_diag, "evidence_row_count")
    seg_total = _n(ev_diag, "evidence_segments_total")
    seg_failed = _n(ev_diag, "evidence_segments_failed")

    red = ev_diag.get("reducer") or {}
    if not isinstance(red, dict):
        red = {}
    promos = red.get("promotions") or []
    if not isinstance(promos, list):
        promos = []

    promo_by_kind: dict[str, int] = {}
    for p in promos:
        if not isinstance(p, dict):
            continue
        k = str(p.get("promotionKind") or "unknown")
        promo_by_kind[k] = promo_by_kind.get(k, 0) + 1

    cac = red.get("counts_after_clustering") or {}
    cap = red.get("counts_after_promotion") or {}
    if not isinstance(cac, dict):
        cac = {}
    if not isinstance(cap, dict):
        cap = {}

    signals: list[str] = []
    notes: list[str] = []

    if seg_total > 0 and seg_failed > 0:
        signals.append("segment_model_partial_failure")
        notes.append(
            f"{seg_failed}/{seg_total} segment LLM calls failed or returned unusable JSON "
            "(see evidence_segment_reports / evidence_failed_segment_ids)."
        )
    if total_rows == 0:
        signals.append("no_evidence_rows")
        notes.append("Zero evidence rows after all fallbacks.")
    elif n_model == 0 and n_literal == 0:
        signals.append("no_model_rows")
        notes.append("No model-sourced rows; structure built from cover/lexical/clause/summary paths only.")
    elif n_model == 0 and n_literal > 0:
        signals.append("literal_anchor_primary")
        notes.append("Pass 0 literal anchors only (context entity matches in chunk text; segment LLM skipped or merged).")

    if len(promos) >= 3:
        signals.append("heavy_reducer_promotion")
        notes.append(f"Heavy reducer promotion ({len(promos)} slots); themes/projects uplifted from ideas/tasks.")
    elif len(promos) > 0:
        signals.append("reducer_promotion_used")
        notes.append(f"Reducer filled {len(promos)} initiative/project slot(s) from ideas or tasks.")

    if (
        _n(cap, "initiatives") > _n(cac, "initiatives")
        and promo_by_kind.get("idea_to_initiative", 0) > 0
    ):
        signals.append("initiatives_promoted_from_ideas")
    if _n(cap, "projects") > _n(cac, "projects") and promo_by_kind.get("task_to_project", 0) > 0:
        signals.append("projects_promoted_from_tasks")
    if promo_by_kind.get("idea_to_project", 0) > 0:
        signals.append("projects_promoted_from_ideas")

    if n_lexical_total > 0 and n_model == 0 and total_rows > 0:
        signals.append("lexical_recovery_primary")
    if n_clause > 0:
        signals.append("clause_recovery_used")

    # Gap hints: had row volume but clustering left a bucket empty before promotion
    if (
        total_rows >= 5
        and _n(cac, "projects") == 0
        and _n(cap, "projects") == 0
        and _n(cac, "tasks") > 0
    ):
        signals.append("projects_empty_despite_tasks")
        notes.append(
            "Projects still empty after reducer; tasks were clustered but not promoted (length/heuristics)."
        )

    structured: dict[str, Any] = {
        "evidence_row_total": total_rows,
        "rows_by_source_stage": {
            "model": n_model,
            "literal_anchor": n_literal,
            "cover_phrase": n_cover,
            "lexical_transcript": n_lex,
            "lexical_pattern_total": n_lexical_total,
            "clause_recovery": n_clause,
            "segment_summary": n_synth,
        },
        "segments_total": seg_total,
        "segments_failed": seg_failed,
        "reducer_promotion_total": len(promos),
        "reducer_promotions_by_kind": dict(sorted(promo_by_kind.items())),
        "counts_after_clustering": {k: _n(cac, k) for k in sorted(cac.keys())} if cac else {},
        "counts_after_promotion": {k: _n(cap, k) for k in sorted(cap.keys())} if cap else {},
    }

    pk = structured["reducer_promotions_by_kind"]
    promo_part = ",".join(f"{k}×{v}" for k, v in pk.items()) if pk else "none"

    one_line = (
        f"rows={total_rows} "
        f"model={n_model} lit={n_literal} cover={n_cover} lex={n_lex} clause={n_clause} seg_sum={n_synth} | "
        f"seg_fail={seg_failed}/{seg_total if seg_total else 0} | "
        f"promos={len(promos)}({promo_part})"
    )

    lines = [
        f"Evidence rows: total={total_rows}",
        f"  • model (LLM per segment): {n_model}",
        f"  • literal anchor (context match): {n_literal}",
        f"  • cover phrase: {n_cover}",
        f"  • transcript lexical: {n_lex}",
        f"  • clause recovery: {n_clause}",
        f"  • segment-summary bridge: {n_synth}",
    ]
    if seg_total > 0:
        lines.append(f"Segments: {seg_failed} failed of {seg_total} (LLM/parse partial success path).")
    lines.append(f"Reducer promotions: {len(promos)} total ({promo_part})")
    if cac:
        bk = ["initiatives", "projects", "tasks", "ideas", "assets", "peopleReferences", "signals"]
        lines.append("After clustering: " + " ".join(f"{k}={_n(cac, k)}" for k in bk))
    if cap:
        lines.append(
            "  after promotion: "
            + " ".join(
                f"{k}={_n(cap, k)}"
                for k in ["initiatives", "projects", "tasks", "ideas", "assets", "peopleReferences", "signals"]
            )
        )
    if notes:
        lines.append("Interpretation:")
        for n in notes:
            lines.append(f"  — {n}")

    text = "\n".join(lines)

    return {
        "one_line": one_line,
        "text": text,
        "structured": structured,
        "signals": signals,
    }


def format_formation_summary_for_assertion(diagnostics: dict[str, Any] | None) -> str:
    """Short block to append to pytest assertion messages when ``_diagnostics`` is present."""
    if not diagnostics or not isinstance(diagnostics, dict):
        return ""
    fs = diagnostics.get("formation_summary")
    if isinstance(fs, dict) and fs.get("text"):
        return "\n\n--- formation_summary ---\n" + str(fs.get("text")) + "\n" + str(fs.get("one_line", ""))
    ev = diagnostics.get("evidence")
    if isinstance(ev, dict):
        built = build_formation_summary_from_evidence_diag(ev)
        return "\n\n--- formation_summary ---\n" + built.get("text", "") + "\n" + built.get("one_line", "")
    return ""
