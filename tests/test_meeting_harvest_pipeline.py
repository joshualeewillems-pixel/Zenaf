from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ai.vision_execution.meeting_harvest import (
    build_full_harvest_ledger,
    format_ledger_for_map_prompt,
    run_harvest_pass,
    run_normalize_pass,
)


def _mk_gen(outputs: list[str]):
    state = {"i": 0}

    def _gen(*, task: str, prompt: str, timeout: int) -> str:
        i = state["i"]
        state["i"] += 1
        if i >= len(outputs):
            return outputs[-1] if outputs else ""
        return outputs[i]

    return _gen


def test_harvest_preserves_split_items_and_order():
    raw = json.dumps(
        {
            "items": [
                {
                    "ordinal": 1,
                    "raw_text": "Build drip sequence for onboarding.",
                    "label": "build drip sequence",
                    "category_hint": "content",
                    "speculative": False,
                    "confidence": 0.88,
                },
                {
                    "ordinal": 2,
                    "raw_text": "Create visuals for practitioner sales deck.",
                    "label": "create visuals",
                    "category_hint": "media",
                    "speculative": False,
                    "confidence": 0.84,
                },
                {
                    "ordinal": 3,
                    "raw_text": "Test a monthly referral subscription idea.",
                    "label": "test referral subscription",
                    "category_hint": "monetization",
                    "speculative": True,
                    "confidence": 0.55,
                },
            ]
        }
    )
    ledger = run_harvest_pass(
        "Build drip + visuals + monthly referral model",
        transcript_id="tx-1",
        llm_generate=_mk_gen([raw]),
    )
    assert [it.ordinal for it in ledger.items] == [1, 2, 3]
    assert ledger.items[2].speculative is True
    assert ledger.items[2].category_hint == "monetization"


def test_normalize_keeps_item_count_and_ids_without_dedupe():
    p1 = json.dumps(
        {
            "items": [
                {"id": "a1", "ordinal": 1, "raw_text": "could you look into summit topics", "label": "look into summit topics"},
                {"id": "a2", "ordinal": 2, "raw_text": "could you look into summit sponsor list", "label": "look into summit sponsor list"},
            ]
        }
    )
    p2 = json.dumps(
        {
            "items": [
                {
                    "id": "a1",
                    "ordinal": 1,
                    "raw_text": "could you look into summit topics",
                    "label": "Review AI summit topics",
                    "normalized_from": "look into summit topics",
                },
                {
                    "id": "a2",
                    "ordinal": 2,
                    "raw_text": "could you look into summit sponsor list",
                    "label": "Review summit sponsor list",
                    "normalized_from": "look into summit sponsor list",
                },
            ]
        }
    )
    ledger = build_full_harvest_ledger(
        "s",
        meeting_id="tx-2",
        llm_generate=_mk_gen([p1, p2]),
    )
    assert len(ledger.items) == 2
    assert [it.id for it in ledger.items] == ["a1", "a2"]
    assert ledger.items[0].normalized_from == "look into summit topics"
    assert ledger.items[1].normalized_from == "look into summit sponsor list"


def test_normalize_fallback_when_length_mismatch():
    p1 = json.dumps({"items": [{"id": "a1", "ordinal": 1, "raw_text": "we should test onboarding drip", "label": "test onboarding drip"}]})
    p2 = json.dumps({"items": []})  # invalid normalize output (count mismatch)
    ledger = build_full_harvest_ledger(
        "notes",
        meeting_id="tx-3",
        llm_generate=_mk_gen([p1, p2]),
    )
    assert len(ledger.items) == 1
    assert ledger.items[0].label == "test onboarding drip"


def test_ledger_prompt_format_includes_ids_and_raw_text():
    p1 = json.dumps(
        {
            "items": [
                {"id": "x1", "ordinal": 1, "raw_text": "figure out if referral can be monthly", "label": "figure out monthly referral", "speculative": True}
            ]
        }
    )
    ledger = run_harvest_pass("notes", transcript_id="tx-4", llm_generate=_mk_gen([p1]))
    block = format_ledger_for_map_prompt(ledger)
    assert "[x1] (1)" in block
    assert "raw: figure out if referral can be monthly" in block
    assert "speculative" in block

