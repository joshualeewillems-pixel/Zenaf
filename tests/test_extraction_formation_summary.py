"""Unit tests for compact extraction formation summaries (no LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.extraction_formation_summary import (
    build_formation_summary_from_evidence_diag,
)
from local_ai.vision_execution.meeting_evidence_pipeline import SOURCE_STAGE_MODEL


def test_formation_summary_flags_segment_failure_and_promotions():
    ev = {
        "evidence_row_count": 12,
        "evidence_segments_total": 3,
        "evidence_segments_failed": 1,
        "source_stage_counts": {SOURCE_STAGE_MODEL: 8, "lexical_transcript": 4},
        "reducer": {
            "promotions": [
                {"promotionKind": "idea_to_initiative", "title": "A"},
                {"promotionKind": "task_to_project", "title": "B"},
            ],
            "counts_after_clustering": {"initiatives": 0, "projects": 0, "tasks": 2, "ideas": 3},
            "counts_after_promotion": {"initiatives": 1, "projects": 1, "tasks": 1, "ideas": 1},
        },
    }
    fs = build_formation_summary_from_evidence_diag(ev)
    assert "segment_model_partial_failure" in fs["signals"]
    assert "reducer_promotion_used" in fs["signals"]
    assert fs["structured"]["reducer_promotion_total"] == 2
    assert "model=8" in fs["one_line"]
    assert "seg_fail=1/3" in fs["one_line"]


def test_formation_summary_no_model_rows():
    ev = {
        "evidence_row_count": 5,
        "evidence_segments_total": 1,
        "evidence_segments_failed": 0,
        "source_stage_counts": {"cover_phrase": 3, "lexical_transcript": 2},
        "reducer": {"promotions": [], "counts_after_clustering": {}, "counts_after_promotion": {}},
    }
    fs = build_formation_summary_from_evidence_diag(ev)
    assert "no_model_rows" in fs["signals"]
