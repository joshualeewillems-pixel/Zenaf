"""Pinned-validator tests for the wash harness (validator.py).

Covers the frozen parse + repair, the proposition gate, the confidence
default reversal, and the three-part quote gate (exactness / attribution /
support), each with its own diagnostic reason. All inputs are synthetic raw
model text — no model is called.
"""

from __future__ import annotations

import json

import pytest

from local_ai.eval.wash.fixtures import default_fixture_path, load_fixture_set
from local_ai.eval.wash.validator import (
    normalize_confidence_label,
    parse_raw_model_text,
    title_is_propositional,
    validate_segment_output,
)


@pytest.fixture(scope="module")
def fixture_set():
    return load_fixture_set(default_fixture_path())


def _rows_json(rows) -> str:
    return json.dumps({"rows": rows})


def _row(text, quote, stance="committed", confidence="high"):
    return {
        "text": text,
        "summary": "A test row.",
        "evidence_quote": quote,
        "confidence": confidence,
        "stance": stance,
    }


# --- parse + repair (mirrors pipeline :797-894) ---------------------------


def test_parse_plain_rows_object():
    rows, meta = parse_raw_model_text(_rows_json([{"text": "Something happened here today"}]))
    assert meta["decode_ok"] is True
    assert meta["reason"] == "ok"
    assert meta["clean_parse"] is True
    assert len(rows) == 1


def test_parse_fenced_json():
    raw = "```json\n" + _rows_json([{"text": "Something happened here today"}]) + "\n```"
    rows, meta = parse_raw_model_text(raw)
    assert meta["decode_ok"] is True
    assert len(rows) == 1


def test_parse_trailing_comma_repaired_and_flagged():
    raw = '{"rows": [{"text": "Something happened here today",}]}'
    rows, meta = parse_raw_model_text(raw)
    assert meta["decode_ok"] is True
    assert meta["clean_parse"] is False  # repair was needed (measure 6)
    assert len(rows) == 1


def test_parse_brace_truncation_recovery():
    raw = '{"rows": [{"text": "Something happened here today"}]}\n trailing prose here'
    rows, meta = parse_raw_model_text(raw)
    assert meta["decode_ok"] is True
    assert len(rows) == 1


def test_parse_top_level_array():
    rows, meta = parse_raw_model_text('[{"text": "Something happened here today"}]')
    assert meta["decode_ok"] is True
    assert len(rows) == 1


def test_parse_wrapper_coercion():
    raw = json.dumps({"data": {"rows": [{"text": "Something happened here today"}]}})
    rows, meta = parse_raw_model_text(raw)
    assert meta["decode_ok"] is True
    assert len(rows) == 1


def test_parse_hard_empty():
    rows, meta = parse_raw_model_text('{"rows": []}')
    assert meta["decode_ok"] is True
    assert meta["hard_empty"] is True
    assert rows == []


def test_parse_garbage_is_decode_error():
    rows, meta = parse_raw_model_text("this is not json at all {{{")
    assert meta["decode_ok"] is False
    assert meta["reason"] == "json_decode_error"
    assert rows == []


def test_parse_empty_object_is_zero_rows_after_coerce():
    rows, meta = parse_raw_model_text("{}")
    assert meta["decode_ok"] is True
    assert meta["reason"] == "zero_rows_after_coerce"


# --- proposition gate -------------------------------------------------------


def test_title_is_propositional_rules():
    assert title_is_propositional("The team decided to ship on Friday") is True
    assert title_is_propositional("Ship") is False  # single token
    assert title_is_propositional("The migration") is False  # too short / not a claim
    assert title_is_propositional("") is False
    assert title_is_propositional("Speaker A: hello there today") is False


def test_text_too_short_dropped(fixture_set):
    fx = fixture_set.by_id("com-01")
    result = validate_segment_output(
        _rows_json([_row("Go!", "We decided to ship on Friday")]), fx.segment, fx
    )
    assert result.emitted == []
    assert result.gate_counts == {"text_too_short": 1}


def test_non_propositional_dropped(fixture_set):
    fx = fixture_set.by_id("com-01")
    result = validate_segment_output(
        _rows_json([_row("Friday", "We decided to ship on Friday")]), fx.segment, fx
    )
    assert result.emitted == []
    assert result.gate_counts == {"not_propositional": 1}


# --- confidence (refinement C + §2.1.5) --------------------------------------


def test_missing_confidence_is_low_with_reason(fixture_set):
    fx = fixture_set.by_id("com-01")
    row = _row("The team decided to ship on Friday", "We decided to ship on Friday")
    del row["confidence"]
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert len(result.emitted) == 1
    assert result.emitted[0].confidence == "low"
    assert result.emitted[0].confidence_reason == "confidence_missing"


def test_explicit_low_confidence_is_weak_evidence(fixture_set):
    fx = fixture_set.by_id("com-01")
    result = validate_segment_output(
        _rows_json(
            [_row("The team decided to ship on Friday", "We decided to ship on Friday", confidence="low")]
        ),
        fx.segment,
        fx,
    )
    assert result.emitted[0].confidence == "low"
    assert result.emitted[0].confidence_reason == "support_uncertain"


def test_numeric_confidence_maps_by_word_rule():
    assert normalize_confidence_label(0.9) == "high"
    assert normalize_confidence_label(0.6) == "medium"
    assert normalize_confidence_label(0.3) == "low"


def test_numeric_confidence_on_row(fixture_set):
    fx = fixture_set.by_id("com-01")
    row = _row("The team decided to ship on Friday", "We decided to ship on Friday", confidence=0.9)
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert result.emitted[0].confidence == "high"
    assert result.emitted[0].confidence_raw == 0.9
    assert result.emitted[0].confidence_reason is None


# --- three-part quote gate (§2.1.5) ------------------------------------------


def test_verbatim_quote_emitted(fixture_set):
    fx = fixture_set.by_id("com-01")
    result = validate_segment_output(
        _rows_json([_row("The team decided to ship on Friday", "We decided to ship on Friday")]),
        fx.segment,
        fx,
    )
    assert len(result.emitted) == 1
    assert result.gate_counts == {}


def test_missing_quote_is_dropped_not_substituted(fixture_set):
    # The pipeline's title-substitution fallback is reversed by the contract:
    # a row with no quote is dropped, never given its own title as evidence.
    fx = fixture_set.by_id("com-01")
    row = _row("The team decided to ship on Friday", "")
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert result.emitted == []
    assert result.gate_counts == {"missing_quote": 1}


def test_fabricated_quote_rejected(fixture_set):
    fx = fixture_set.by_id("com-01")
    row = _row(
        "The team decided to ship on Friday",
        "We decided to ship Friday, for real this time",
    )
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert result.emitted == []
    assert result.gate_counts == {"quote_not_verbatim": 1}


def test_paraphrased_quote_rejected(fixture_set):
    # A paraphrase of the segment words is not a verbatim span.
    fx = fixture_set.by_id("evp-01")
    row = _row(
        "The migration cutover is scheduled for November 14 at 2 a.m. Pacific with a four-hour window",
        "The cutover is set for Nov 14 at 2am Pacific",
    )
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert result.emitted == []
    assert result.gate_counts == {"quote_not_verbatim": 1}


def test_verbatim_quote_from_wrong_speaker_fails_attribution(fixture_set):
    # att-01 gold (b) is B's "Friday is too soon"; quoting A's line for it fails.
    fx = fixture_set.by_id("att-01")
    row = _row(
        "Friday is too soon to ship the beta because the tests aren't green",
        "We should ship the beta on Friday",
        stance="rejected",
    )
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert result.emitted == []
    assert result.gate_counts == {"quote_misattributed": 1}


def test_correct_attribution_passes(fixture_set):
    fx = fixture_set.by_id("att-01")
    row = _row(
        "Friday is too soon to ship the beta because the tests aren't green",
        "Friday is too soon, the tests aren't green",
        stance="rejected",
    )
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert len(result.emitted) == 1


def test_verbatim_quote_that_does_not_support_fails(fixture_set):
    # Right segment, verbatim span, but not one of the gold proposition's
    # supporting quotes — so it does not support the row's text.
    fx = fixture_set.by_id("com-01")
    row = _row(
        "The team decided to ship on Friday",
        "to ship on Friday",  # verbatim substring, but not the supporting quote
        stance="committed",
    )
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert result.emitted == []
    assert result.gate_counts == {"quote_unsupported": 1}


def test_unsupported_row_dropped(fixture_set):
    # A verbatim, correctly attributed quote for a proposition in no gold list.
    fx = fixture_set.by_id("com-01")
    row = _row(
        "The team celebrated the release with cake on Friday afternoon",
        "We decided to ship on Friday",
    )
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert result.emitted == []
    assert result.gate_counts == {"quote_unsupported": 1}


def test_duplicate_rows_deduped(fixture_set):
    fx = fixture_set.by_id("com-01")
    rows = [
        _row("The team decided to ship on Friday", "We decided to ship on Friday"),
        _row("The team decided to ship on Friday", "We decided to ship on Friday"),
    ]
    result = validate_segment_output(_rows_json(rows), fx.segment, fx)
    assert len(result.emitted) == 1
    assert result.gate_counts == {"duplicate": 1}


def test_ambiguous_quote_flagged_as_diagnostic():
    # A quote matching more than one span is flagged (§2.1.2), not silently
    # resolved: the harness records the diagnostic and scores attribution
    # against gold. Built on a synthetic fixture (no shipped fixture has a
    # repeated supporting span).
    from local_ai.eval.wash.fixtures import ExpectedRow, Fixture

    fx = Fixture(
        id="syn-ambig",
        category="commitments",
        segment="The launch is Friday. We launch Friday, and the launch is Friday.",
        segment_id="seg-9999",
        has_explicit_speakers=False,
        expected=(
            ExpectedRow(
                text="The launch is on Friday",
                stance="committed",
                speaker=None,
                quote="launch is Friday",
                equivalents=(),
                supporting_quotes=("launch is Friday",),
            ),
        ),
    )
    row = _row("The launch is on Friday", "launch is Friday", stance="committed")
    result = validate_segment_output(_rows_json([row]), fx.segment, fx)
    assert len(result.emitted) == 1
    assert any(d.startswith("quote_ambiguous") for d in result.diagnostics)


# --- failure semantics (§2.1.4) ----------------------------------------------


def test_failed_call_is_never_an_empty(fixture_set):
    fx = fixture_set.by_id("emp-01")
    result = validate_segment_output(
        "", fx.segment, fx, failure_code="unreachable"
    )
    assert result.failure == {"code": "unreachable"}
    assert result.emitted == []
    assert result.hard_empty is False


def test_unknown_failure_code_rejected(fixture_set):
    fx = fixture_set.by_id("com-01")
    with pytest.raises(ValueError, match="unknown failure code"):
        validate_segment_output("", fx.segment, fx, failure_code="exploded")


def test_hard_empty_reports_no_rows(fixture_set):
    fx = fixture_set.by_id("emp-01")
    result = validate_segment_output('{"rows": []}', fx.segment, fx)
    assert result.hard_empty is True
    assert result.emitted == []
    assert result.proposed_count == 0
