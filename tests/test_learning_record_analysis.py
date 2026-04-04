"""learning_record_analysis: cleaned JSONL evidence reports."""

from __future__ import annotations

import json
from pathlib import Path

from local_ai.delegation.learning_record_analysis import (
    format_analysis_report,
    load_cleaned_jsonl,
    recommend_surfaces_for_tuning,
    run_full_analysis,
    validation_failure_rate_by_action_intent,
)


def _row(**kw):
    base = {
        "record_id": "x",
        "ts_ms": 1,
        "action_intent": "a",
        "surface": "s",
        "delegation_tier": "structured",
        "provider_used": "openai",
        "model_used": "gpt-4",
        "validation_passed": True,
        "validation_error": None,
        "input_snapshot_redacted": "",
        "compiled_prompt_sha256_prefix": "",
        "compiled_prompt_char_len": 0,
        "model_output_redacted": "",
        "delegation_path": None,
        "externalization_mapping_active": False,
        "user_outcome": None,
        "capture_mode": "full",
    }
    base.update(kw)
    return base


def test_validation_failure_rate_by_intent():
    rows = [
        _row(action_intent="i1", validation_passed=False),
        _row(action_intent="i1", validation_passed=False),
        _row(action_intent="i1", validation_passed=True),
        _row(action_intent="i2", validation_passed=None),
    ]
    v = validation_failure_rate_by_action_intent(rows)
    by = {x["action_intent"]: x for x in v}
    assert by["i1"]["failure_rate_among_labeled"] == round(2 / 3, 4)
    assert by["i2"]["failure_rate_among_labeled"] is None


def test_run_full_analysis_provider_buckets(tmp_path: Path):
    rows = []
    for _ in range(10):
        rows.append(_row(action_intent="bad", validation_passed=False, surface="workspace"))
    for _ in range(12):
        rows.append(_row(action_intent="good", validation_passed=True, surface="ideas"))
    a = run_full_analysis(rows, min_volume_surface=3, min_labeled_intent=5)
    assert "bad" in a["high_failure_action_intents"]
    assert a["provider_model_breakdown_high_failure_intents"]["provider_model_counts"]["openai"]["gpt-4"] == 10
    assert a["distillation_readiness"]["narrow_pilot_recommended"] is False  # n=22 < 200


def test_recommend_surfaces_mixed_outcomes():
    rows = []
    for i in range(20):
        rows.append(
            _row(
                surface="hot_surface",
                action_intent="x",
                validation_passed=False if i < 8 else True,
                user_outcome="dismissed" if i % 4 == 0 else ("applied" if i % 4 == 1 else None),
            )
        )
    rec = recommend_surfaces_for_tuning(rows, min_volume=5, top_recommendations=2)
    assert rec[0]["surface"] == "hot_surface"
    assert any("mixed" in x or "failure" in x for r in rec for x in r["rationale"])


def test_load_cleaned_jsonl_roundtrip(tmp_path: Path):
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps(_row(record_id="a", ts_ms=1)) + "\n", encoding="utf-8")
    loaded = load_cleaned_jsonl(p)
    assert len(loaded) == 1
    assert loaded[0]["record_id"] == "a"


def test_format_report_non_empty():
    txt = format_analysis_report(run_full_analysis([_row()], min_volume_surface=1, min_labeled_intent=1))
    assert "Validation failure" in txt
    assert "Distillation" in txt
