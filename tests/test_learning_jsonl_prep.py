"""Offline LearningRecord JSONL dedupe + summary (learning_jsonl_prep)."""

from __future__ import annotations

import json
from pathlib import Path

from local_ai.delegation.learning_jsonl_prep import (
    build_summary,
    dedupe_last_line_wins,
    format_summary_text,
    is_learning_record_row,
    resolve_input_paths,
    run_prep,
)


def _row(rid: str, ts: int, **kw):
    base = {
        "record_id": rid,
        "ts_ms": ts,
        "action_intent": "a",
        "surface": "s",
        "delegation_tier": "general",
        "provider_used": "p",
        "model_used": "m",
        "validation_passed": True,
        "validation_error": None,
        "input_snapshot_redacted": "",
        "compiled_prompt_sha256_prefix": "",
        "compiled_prompt_char_len": 0,
        "model_output_redacted": "",
        "delegation_path": None,
        "externalization_mapping_active": False,
        "capture_mode": "full",
    }
    base.update(kw)
    return base


def test_is_learning_record_row():
    assert is_learning_record_row(_row("x", 1))
    assert not is_learning_record_row({})
    assert not is_learning_record_row({"record_id": "", "ts_ms": 1})


def test_dedupe_last_line_wins(tmp_path: Path):
    f1 = tmp_path / "a.jsonl"
    f1.write_text(
        json.dumps(_row("a", 10, user_outcome=None)) + "\n" + json.dumps(_row("a", 20, user_outcome="applied")) + "\n",
        encoding="utf-8",
    )
    deduped, st = dedupe_last_line_wins([f1])
    assert st.distinct_record_ids == 1
    assert st.record_ids_with_multiple_lines == 1
    assert deduped["a"]["user_outcome"] == "applied"


def test_corrupt_line_skipped(tmp_path: Path):
    f = tmp_path / "x.jsonl"
    f.write_text("not json\n" + json.dumps(_row("z", 5)) + "\n", encoding="utf-8")
    deduped, st = dedupe_last_line_wins([f])
    assert st.lines_corrupt >= 1
    assert "z" in deduped


def test_multi_file_order_cli(tmp_path: Path):
    f1 = tmp_path / "1.jsonl"
    f2 = tmp_path / "2.jsonl"
    f1.write_text(json.dumps(_row("id", 100, action_intent="first")) + "\n", encoding="utf-8")
    f2.write_text(json.dumps(_row("id", 50, action_intent="second")) + "\n", encoding="utf-8")
    deduped, _st = dedupe_last_line_wins([f1, f2])
    assert deduped["id"]["action_intent"] == "second"
    deduped2, _ = dedupe_last_line_wins([f2, f1])
    assert deduped2["id"]["action_intent"] == "first"


def test_build_summary_validation_counts():
    rows = {
        "1": _row("1", 1, validation_passed=True),
        "2": _row("2", 2, validation_passed=False),
        "3": _row("3", 3, validation_passed=None),
    }
    s = build_summary(rows)
    assert s["validation"]["passed_true"] == 1
    assert s["validation"]["passed_false"] == 1
    assert s["validation"]["passed_other_or_missing"] == 1


def test_run_prep_writes_files(tmp_path: Path):
    f = tmp_path / "in.jsonl"
    f.write_text(json.dumps(_row("r1", 99, surface="idea")) + "\n", encoding="utf-8")
    out = tmp_path / "clean.jsonl"
    sj = tmp_path / "sum.json"
    run_prep([str(f)], out_jsonl=out, summary_json=sj, sort_files="none")
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    summ = json.loads(sj.read_text(encoding="utf-8"))
    assert summ["dedupe"]["distinct_record_ids"] == 1
    assert summ["summary"]["surface_counts"]["idea"] == 1


def test_resolve_input_paths_glob(tmp_path: Path):
    (tmp_path / "a.jsonl").write_text("{}\n", encoding="utf-8")
    paths = resolve_input_paths([str(tmp_path / "*.jsonl")], sort="path")
    assert len(paths) == 1


def test_format_summary_text_contains_sections():
    from local_ai.delegation.learning_jsonl_prep import DedupeStats

    d = {"x": _row("x", 1, action_intent="ai", surface="sv")}
    summ = build_summary(d)
    dst = DedupeStats(1, 1, 0, 0, 1, 1, 0)
    txt = format_summary_text(dst, summ)
    assert "action_intent" in txt
    assert "validation" in txt
