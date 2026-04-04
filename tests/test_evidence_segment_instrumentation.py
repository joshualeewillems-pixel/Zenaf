"""Per-segment evidence extraction diagnostics (timing, routing snapshot); no real LLM."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.meeting_evidence_pipeline import (
    MEETING_EVIDENCE_SEGMENT_MAX_CHUNK_FAST_LOCAL,
    MEETING_EVIDENCE_SEGMENT_MIN_MERGE_FAST_LOCAL,
    MEETING_EVIDENCE_SEGMENT_TIMEOUT_FAST_LOCAL_S,
    extract_evidence_rows_all_segments,
    extract_evidence_rows_for_segment,
    resolve_meeting_evidence_extraction_preset,
)


def test_extract_segment_reports_timing_and_sizes():
    snap = {
        "effective_provider": "ollama",
        "effective_model": "qwen:test",
        "routing_context_seam_active": False,
        "execution_policy_override_active": False,
        "ollama_model_override_active": False,
    }

    def fake_llm(**kw: str) -> str:
        return json.dumps(
            {
                "rows": [
                    {
                        "text": "Ship the release tomorrow",
                        "evidence_quote": "We ship it tomorrow",
                        "confidence": 0.6,
                    }
                ]
            }
        )

    rows, rep = extract_evidence_rows_for_segment(
        "  discuss shipping  ",
        "seg-a",
        fake_llm,
        llm_routing_snapshot=snap,
    )
    assert len(rows) == 1
    assert rep["outcome"] == "success"
    assert rep["llm_path_outcome"] == "success"
    assert rep["retried"] is False
    assert rep["deterministic_fallback_used"] is False
    tm = rep["timing_ms"]
    assert tm["total_wall"] is not None and tm["total_wall"] >= 0
    assert tm["prompt_build"] is not None and tm["llm_call"] is not None and tm["parse"] is not None
    assert tm.get("retry") is None
    rs = rep["request_sizes"]
    assert rs["segment_text_chars"] == len("  discuss shipping  ")
    assert rs["prompt_chars"] > 100
    assert rs["prior_context_included"] is False
    assert rep["llm_routing"]["effective_model"] == "qwen:test"


def test_resolve_meeting_evidence_preset_fast_local():
    t, chunk, label, min_merge = resolve_meeting_evidence_extraction_preset("interactive")
    assert label == "fast_local"
    assert chunk == MEETING_EVIDENCE_SEGMENT_MAX_CHUNK_FAST_LOCAL
    assert t == MEETING_EVIDENCE_SEGMENT_TIMEOUT_FAST_LOCAL_S
    assert min_merge == MEETING_EVIDENCE_SEGMENT_MIN_MERGE_FAST_LOCAL


def test_extract_all_segments_includes_routing_snapshot():
    def fake_llm(**kw: str) -> str:
        return json.dumps(
            {
                "rows": [
                    {
                        "text": "Automate the intake flow end-to-end",
                        "evidence_quote": "automate the flow",
                        "confidence": 0.4,
                    }
                ]
            }
        )

    from local_ai.llm.execution_principal import anonymous_account_principal

    principal = anonymous_account_principal()
    rows, diag = extract_evidence_rows_all_segments(
        [("s0", "one segment text here")],
        fake_llm,
        principal=principal,
        seam_routing_active=True,
        timeout=22,
        evidence_extraction_preset="fast_local",
        evidence_segment_max_chunk=2800,
    )
    assert len(rows) >= 1
    assert diag.get("evidence_extraction_preset") == "fast_local"
    assert diag.get("evidence_segment_llm_timeout_s") == 22
    assert diag.get("evidence_segment_max_chunk") == 2800
    assert "evidence_llm_routing_snapshot" in diag
    snap = diag["evidence_llm_routing_snapshot"]
    assert "effective_provider" in snap
    assert "effective_model" in snap
    assert snap.get("routing_context_seam_active") is True
    rep0 = diag["evidence_segment_reports"][0]
    assert "timing_ms" in rep0
    assert rep0.get("llm_routing") is not None
