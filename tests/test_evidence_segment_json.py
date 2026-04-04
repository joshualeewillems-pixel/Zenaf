"""Segment evidence JSON parsing: shape recovery and empty-row classification (no LLM)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.meeting_evidence_pipeline import (
    _row_from_dict,
    parse_evidence_llm_json,
)


def test_parse_standard_rows():
    raw = json.dumps(
        {
            "rows": [
                {
                    "type": "task",
                    "label": "Ship the report",
                    "evidence_quote": "We need to ship the report by Friday",
                    "confidence": 0.7,
                }
            ]
        }
    )
    rows, meta = parse_evidence_llm_json(raw)
    assert meta.get("decode_ok") and meta.get("reason") == "ok"
    assert len(rows) == 1


def test_parse_top_level_array():
    raw = json.dumps(
        [
            {
                "type": "idea",
                "label": "Explore automation",
                "evidence_quote": "Maybe we automate the handoff",
                "confidence": 0.5,
            }
        ]
    )
    rows, meta = parse_evidence_llm_json(raw)
    assert meta.get("reason") == "ok"
    assert len(rows) == 1


def test_parse_nested_data_rows():
    inner = {
        "rows": [
            {
                "claim_type": "signal",
                "label": "risk",
                "evidence_quote": "We might miss the deadline",
                "signal_kind": "risk",
                "confidence": 0.6,
            }
        ]
    }
    raw = json.dumps({"data": inner})
    rows, meta = parse_evidence_llm_json(raw)
    assert meta.get("reason") == "ok"
    assert len(rows) == 1


def test_parse_trailing_comma():
    raw = '{"rows": [{"type":"task","label":"x","evidence_quote":"do x","confidence":0.5},]}'
    rows, meta = parse_evidence_llm_json(raw)
    assert meta.get("decode_ok")
    assert len(rows) == 1


def test_empty_rows_object_distinct_from_decode_error():
    ok, meta_ok = parse_evidence_llm_json('{"rows": []}')
    assert ok == [] and meta_ok.get("decode_ok") and meta_ok.get("reason") == "zero_rows_after_coerce"
    bad, meta_bad = parse_evidence_llm_json("not json {{{")
    assert bad == [] and not meta_bad.get("decode_ok")


def test_row_from_dict_accepts_recovered_shapes():
    rows, _ = parse_evidence_llm_json(
        json.dumps(
            {
                "rows": [
                    {
                        "type": "task",
                        "label": "T",
                        "evidence_quote": "verbatim T here",
                        "confidence": 0.5,
                    }
                ]
            }
        )
    )
    r = _row_from_dict(rows[0], segment_id="s0", row_id="id1")
    assert r is not None and r.claim_type == "task"
