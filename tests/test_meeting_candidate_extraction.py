"""Observation-only meeting candidates: parse shape, hard empty, fallback gating (no real LLM)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.meeting_candidate_quality import candidate_text_passes_api_quality
from local_ai.vision_execution.meeting_evidence_pipeline import (
    effective_confidence,
    extract_candidate_rows_all_segments,
    extract_candidate_rows_for_segment,
    normalize_confidence_label,
    parse_candidate_segment_llm_json,
    public_source_stage_for_internal,
    SOURCE_STAGE_CLAUSE_RECOVERY,
    SOURCE_STAGE_LITERAL_ANCHOR,
    SOURCE_STAGE_MODEL,
)
from local_ai.vision_execution.meeting_literal_anchors import literal_anchor_candidates_for_chunk


def test_parse_hard_empty_rows_is_success_meta():
    raw = json.dumps({"rows": []})
    rows, meta = parse_candidate_segment_llm_json(raw)
    assert rows == []
    assert meta.get("decode_ok") is True
    assert meta.get("hard_empty") is True
    assert meta.get("reason") == "ok"


def test_effective_confidence_caps():
    assert effective_confidence(0.9, "model") == 0.9
    assert effective_confidence(0.9, "clause") == 0.4
    assert effective_confidence(0.9, "lexical") == 0.3


def test_normalize_confidence_label_thresholds():
    assert normalize_confidence_label(0.76) == "high"
    assert normalize_confidence_label(0.55) == "medium"
    assert normalize_confidence_label(0.3) == "low"


def test_public_source_stage_mapping():
    assert public_source_stage_for_internal(SOURCE_STAGE_MODEL) == "model"
    assert public_source_stage_for_internal(SOURCE_STAGE_CLAUSE_RECOVERY) == "clause"
    assert public_source_stage_for_internal(SOURCE_STAGE_LITERAL_ANCHOR) == "literal"


def test_literal_anchor_exact_substring_never_skips_llm_meta():
    ctx = {"initiatives": [{"id": "i1", "title": "Patient Intake Refresh"}]}
    notes = "We discussed Patient Intake Refresh timelines today."
    cands, meta = literal_anchor_candidates_for_chunk(notes, ctx)
    assert meta["skip_llm"] is False
    assert meta["exact_hits"] == 1
    assert cands == []
    assert meta.get("literal_review_promotion_disabled") is True
    assert meta.get("promoted_literal_count") == 0
    g = meta.get("grounding_only_anchors") or []
    assert len(g) >= 1
    assert any("Patient Intake Refresh" in (x.get("label") or "") for x in g)


def test_workspace_hint_literal_anchor_without_ve_context():
    packet = {"domainHints": ["Healing Haven Clinic"]}
    notes = "We met at Healing Haven Clinic about onboarding."
    cands, meta = literal_anchor_candidates_for_chunk(notes, None, workspace_packet=packet)
    assert meta["skip_llm"] is False
    assert cands == []
    assert meta.get("promoted_literal_count") == 0
    g = meta.get("grounding_only_anchors") or []
    assert len(g) >= 1
    row = next(x for x in g if "Healing Haven Clinic" in (x.get("label") or ""))
    assert row.get("workspaceMirror") is True
    pm = row.get("possibleMatches") or []
    assert pm and pm[0].get("type") == "workspace_hint"


def test_literal_anchor_bare_name_is_grounding_only_not_review():
    packet = {"domainHints": ["Healing Haven", "BEST"]}
    notes = "Healing Haven.\n\nBEST\n\nThanks everyone."
    cands, meta = literal_anchor_candidates_for_chunk(notes, None, workspace_packet=packet)
    assert cands == []
    assert meta.get("grounding_only_count", 0) >= 1


def test_literal_anchor_action_cues_still_no_review_candidates():
    packet = {"domainHints": ["Jane"]}
    notes = "Next week we need Jane integrated into the clinic dashboard for intake."
    cands, meta = literal_anchor_candidates_for_chunk(notes, None, workspace_packet=packet)
    assert cands == []
    assert meta.get("promoted_literal_count") == 0
    g = meta.get("grounding_only_anchors") or []
    jane = next(x for x in g if (x.get("label") or "") == "Jane")
    assert jane.get("neighborHasActionCues") is True


def test_literal_grounding_preserves_speaker_in_evidence_not_as_title():
    packet = {"domainHints": ["Healing Haven"]}
    notes = "Speaker B (03:31) ... the Healing Haven website needs to be rebuilt."
    cands, meta = literal_anchor_candidates_for_chunk(notes, None, workspace_packet=packet)
    assert cands == []
    g = meta.get("grounding_only_anchors") or []
    row = next(x for x in g if "Healing Haven" in (x.get("label") or ""))
    eq = row.get("evidenceQuote") or ""
    assert "Speaker" in eq or "03:31" in eq


def test_literal_grounding_neighbor_window_for_needs_to_be_line():
    packet = {"domainHints": ["Healing Haven"]}
    notes = (
        "And so, yeah, so something that's, that's, that's up, that the Healing Haven website "
        "needs to be rebuilt. Okay."
    )
    cands, meta = literal_anchor_candidates_for_chunk(notes, None, workspace_packet=packet)
    assert cands == []
    g = meta.get("grounding_only_anchors") or []
    row = next(x for x in g if "Healing Haven" in (x.get("label") or ""))
    preview = (row.get("neighborWindowPreview") or "").lower()
    assert "needs to be" in preview or "rebuilt" in preview


def test_workspace_hint_skips_generic_meetings_and_cache_junk_hints():
    packet = {
        "domainHints": [
            "meetings",
            "www-main-desktop-watch-page-skeleton",
            "Healing Haven Clinic",
        ]
    }
    notes = "We had several meetings today. Visit Healing Haven Clinic for intake."
    cands, meta = literal_anchor_candidates_for_chunk(notes, None, workspace_packet=packet)
    assert meta["skip_llm"] is False
    assert cands == []
    labels = {x.get("label") for x in (meta.get("grounding_only_anchors") or [])}
    assert "Healing Haven Clinic" in labels
    assert "meetings" not in labels


def test_literal_anchor_caps_at_three():
    ctx = {
        "initiatives": [
            {"id": f"i{i}", "title": f"Initiative Alpha {i}"}
            for i in range(5)
        ]
    }
    notes = " ".join(f"Initiative Alpha {i} discussed. " for i in range(5))
    cands, meta = literal_anchor_candidates_for_chunk(notes, ctx)
    assert cands == []
    assert meta.get("anchors_capped") is True
    assert meta.get("raw_anchor_count") == 5
    assert meta.get("grounding_only_count") == 5


def test_literal_anchor_flags_generic_low_value():
    ctx = {"initiatives": [{"id": "i1", "title": "video"}]}
    notes = "We talked about video in the call."
    _cands, meta = literal_anchor_candidates_for_chunk(notes, ctx)
    assert meta.get("low_value_literal_anchor") is True


def test_literal_anchor_near_exact_does_not_skip_llm_without_exact():
    ctx = {"tasks": [{"id": "t1", "title": "Ship dashboard export"}]}
    notes = (
        "Speaker A: please ship the dashboard export before Friday.\n"
        "Speaker B: agreed."
    )
    cands, meta = literal_anchor_candidates_for_chunk(notes, ctx)
    assert meta["exact_hits"] == 0
    assert meta["skip_llm"] is False
    assert cands == []
    g = meta.get("grounding_only_anchors") or []
    assert any((x.get("possibleMatches") or [{}])[0].get("id") == "t1" for x in g)


def test_segment_skips_deterministic_fallback_when_model_returns_rows():
    def fake_llm(**kw: str) -> str:
        return json.dumps(
            {"rows": [{"text": "We will ship the dashboard Friday", "confidence": 0.72}]}
        )

    cands, rep = extract_candidate_rows_for_segment("Speaker A: we ship Friday", "seg-0", fake_llm)
    assert len(cands) == 1
    assert rep.get("deterministic_fallback_used") is False
    assert rep.get("llm_path_outcome") == "success"


def test_document_level_fallback_suppressed_when_any_segment_has_model_rows():
    calls: list[str] = []

    def fake_llm(**kw: str) -> str:
        calls.append(kw.get("prompt", "") or "")
        return json.dumps({"rows": [{"text": "Decided to migrate the CRM next quarter", "confidence": 0.8}]})

    full_notes = (
        "Speaker A: conversation covers onboarding, automation, and patient intake.\n"
        "Speaker B: we should probably think about dashboards.\n"
    )
    cands, diag = extract_candidate_rows_all_segments(
        [("seg-0000", "Speaker A: we will migrate the CRM next quarter.")],
        fake_llm,
        full_notes=full_notes,
    )
    assert diag.get("any_segment_valid_model_rows") is True
    assert len(cands) >= 1
    rep_ids = [r.get("segment_id") for r in diag.get("evidence_segment_reports", [])]
    assert "cover-supplement" not in rep_ids
    assert "transcript-supplement" not in rep_ids
    assert "clause-recovery" not in rep_ids


def test_quality_gate_rejects_noisy_examples():
    assert not candidate_text_passes_api_quality(
        "And also, yeah. I'll think of a word for it.", interactive=True
    )
    assert not candidate_text_passes_api_quality(
        "I don't know if you can read this.", interactive=True
    )
    assert not candidate_text_passes_api_quality("Yeah, I'll come up with some ideas.", interactive=True)
    assert candidate_text_passes_api_quality(
        "We will ship the patient dashboard by next Friday.", interactive=True
    )


def test_fast_local_skips_deterministic_fallback_on_llm_error():
    def fake_llm(**kw: str) -> str:
        raise RuntimeError("unavailable")

    cands, diag = extract_candidate_rows_all_segments(
        [("seg-0", "Speaker A: we need to ship the intake fix by Friday.")],
        fake_llm,
        evidence_extraction_preset="fast_local",
    )
    assert cands == []
    assert diag.get("interactive_lexical_fallback") is False


def test_fast_local_stops_after_consecutive_barren_segments():
    """Empty LLM rows should not force scanning every internal segment (tail latency)."""

    def fake_llm(**kw: str) -> str:
        return json.dumps({"rows": []})

    segs = [(f"seg-{i:04d}", f"paragraph {i} text " * 12) for i in range(6)]
    cands, diag = extract_candidate_rows_all_segments(
        segs,
        fake_llm,
        evidence_extraction_preset="fast_local",
    )
    assert cands == []
    assert diag.get("evidence_internal_segments_processed") == 3
    assert diag.get("interactive_stop_reason") == "consecutive_barren"
    assert (diag.get("evidence_llm_ms_total") or 0) >= 0


def test_fast_local_post_filter_drops_vague_model_row():
    def fake_llm(**kw: str) -> str:
        return json.dumps(
            {"rows": [{"text": "Yeah, I'll come up with some ideas.", "confidence": 0.88}]}
        )

    cands, _diag = extract_candidate_rows_all_segments(
        [("seg-0", "Speaker A: brainstorming")],
        fake_llm,
        evidence_extraction_preset="fast_local",
    )
    assert cands == []
